"""build_index 的口径回归测试。

索引是 Tier 2 阶段一唯一的检索面：格子分组错 → 候选集错；category 来源错 → 分片选错；
行宽压缩口径错 → 阶段一过滤拿不到判别信号；hash 口径错 → `--check` 永久红或永久绿。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_index as bi  # noqa: E402

CASE_TMPL = """cases:
  - id: {cid}
    title: "{title}"
    category: {cat}
    tags: [{tags}]
    compat:
      - framework: vllm-ascend
        ranges: ["0.23.0"]
    confidence:
      score: 0.6
    symptoms:
      - "{sym}"
"""


class BuildIndexTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "knowledge").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_case(self, rel, cid="TEST-1", cat="interrupt", title="t", tags="a, b", sym="s"):
        p = self.root / "knowledge" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(CASE_TMPL.format(cid=cid, cat=cat, title=title, tags=tags, sym=sym),
                     encoding="utf-8")
        return p

    # ---------------------------------------------------------------- hash 口径
    def test_case_hash_normalizes_crlf(self):
        """LF 与 CRLF 同一份内容 → 同一 hash（否则 Windows 提交索引后 Linux CI 永久红）。"""
        a = self.root / "a.yaml"
        b = self.root / "b.yaml"
        a.write_bytes("x: 1\ny: 2\n".encode())
        b.write_bytes("x: 1\r\ny: 2\r\n".encode())
        self.assertEqual(bi.case_hash(a), bi.case_hash(b))

    def test_case_hash_changes_with_content(self):
        a = self.root / "a.yaml"
        b = self.root / "b.yaml"
        a.write_text("x: 1\n", encoding="utf-8")
        b.write_text("x: 2\n", encoding="utf-8")
        self.assertNotEqual(bi.case_hash(a), bi.case_hash(b))

    # ---------------------------------------------------------------- 收集口径
    def test_collect_skips_generated_and_archived(self):
        self.write_case("inference/vllm-ascend/interrupt/TEST-1.yaml", cid="TEST-1")
        self.write_case("_archive/inference/vllm-ascend/interrupt/OLD.yaml", cid="OLD-1")
        (self.root / "knowledge" / "_index").mkdir(parents=True)
        (self.root / "knowledge" / "_index" / "inference__vllm-ascend.yaml").write_text(
            "namespaces: {}\n", encoding="utf-8")
        (self.root / "knowledge" / "_index.yaml").write_text("namespaces: {}\n", encoding="utf-8")

        ns = bi.collect(self.root)
        ids = [c["id"] for cells in ns.values() for cs in cells.values() for c in cs]
        self.assertEqual(ids, ["TEST-1"])

    def test_category_comes_from_case_field_not_directory(self):
        """目录停在工作负载层，category 是正交轴、从 case 字段取（ADR-0004）。"""
        self.write_case("inference/vllm-ascend/interrupt/TEST-1.yaml", cid="TEST-1", cat="precision")
        ns = bi.collect(self.root)
        self.assertIn("precision", ns["inference/vllm-ascend"])
        self.assertNotIn("interrupt", ns["inference/vllm-ascend"])

    def test_framework_dir_folds_into_namespace(self):
        """inference/training 折叠到两级（三级会让面板渲染出重复 category）；common 停在 common。"""
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.write_case("training/verl/interrupt/B.yaml", cid="B-1")
        self.write_case("common/performance/C.yaml", cid="C-1", cat="performance")
        ns = bi.collect(self.root)
        self.assertEqual(sorted(ns), ["common", "inference/vllm-ascend", "training/verl"])

    def test_illegal_category_raises(self):
        """三分类强制：other/空值直接抛，不能变成不可达格子。"""
        self.write_case("inference/vllm-ascend/interrupt/X.yaml", cid="X-1", cat="other")
        with self.assertRaises(ValueError):
            bi.collect(self.root)

    # ---------------------------------------------------------------- 行宽口径
    def test_row_is_compressed_for_phase_one(self):
        """F2/F5：symptoms 只留首条 120 字、title 截 160、tags 截 6——阶段一拿这一行做过滤。"""
        long_title = "标" * 200
        long_sym = "症" * 200
        self.write_case("inference/vllm-ascend/interrupt/T.yaml", cid="T-1",
                        title=long_title, tags=",".join(f"t{i}" for i in range(9)), sym=long_sym)
        ns = bi.collect(self.root)
        row = ns["inference/vllm-ascend"]["interrupt"][0]
        self.assertEqual(len(row["title"]), 161)          # 160 + 省略号
        self.assertTrue(row["title"].endswith("…"))
        self.assertEqual(len(row["tags"]), 6)
        self.assertEqual(len(row["symptoms"]), 1)
        self.assertEqual(len(row["symptoms"][0]), 121)    # 120 + 省略号
        self.assertEqual(row["file"], "knowledge/inference/vllm-ascend/interrupt/T.yaml")

    # ---------------------------------------------------------------- 一致性门口径
    # 门是**覆盖检查**（每条 case 的索引行都在、与内容对得上），不是逐字节相同：
    # 并发合并后文件内容对、条目顺序可能与重新生成不同（索引故意没配 merge=union，
    # 同一格并发要重跑一次生成器；顺序差异仍不必判红）。
    # 所以下面既测"五种漂移都红"，也测"顺序不同但内容齐全的文件不许红"。
    def generate_all(self, ns=None):
        """分片 + 总表都写出来（模拟一次完整的"跑了一遍生成器"）。"""
        ns = bi.collect(self.root) if ns is None else ns
        (self.root / "knowledge" / "_index").mkdir(parents=True, exist_ok=True)
        for nsk, cells in ns.items():
            bi.shard_path(self.root, nsk).write_text(bi.render_shard(nsk, cells), encoding="utf-8")
            for cat, cases in cells.items():
                bi.shard_path(self.root, f"{nsk}__{cat}").write_text(
                    bi.render_shard(f"{nsk}__{cat}", {cat: cases}), encoding="utf-8")
        (self.root / "knowledge" / "_index.yaml").write_text(bi.render(ns), encoding="utf-8")
        return ns

    def problems(self):
        return bi.coverage_problems(self.root, bi.collect(self.root))

    def test_coverage_green_after_generate(self):
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        self.assertEqual(self.problems(), [])
        self.assertEqual(bi.canonical_dirty(self.root, bi.collect(self.root)), [])

    def test_coverage_flags_changed_case(self):
        p = self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        self.assertEqual(self.problems(), [])
        p.write_text(p.read_text(encoding="utf-8").replace("score: 0.6", "score: 0.9"),
                     encoding="utf-8")
        probs = self.problems()
        # 读侧视图与总表各报一次（两处都存着这条 case 的旧行）——这正是"两层都得跟上"的意思
        self.assertEqual(len(probs), 2, probs)
        self.assertTrue(all("S-1" in p for p in probs), probs)
        self.assertTrue(any("对不上" in p and "__interrupt.list" in p for p in probs), probs)
        self.assertTrue(any("总表" in p for p in probs), probs)

    def test_coverage_flags_added_case(self):
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.generate_all()
        self.write_case("inference/vllm-ascend/interrupt/B.yaml", cid="B-1")
        probs = self.problems()
        self.assertTrue(any("B-1" in p and "缺条目" in p for p in probs), probs)

    def test_coverage_flags_deleted_case(self):
        p = self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        p.unlink()
        probs = self.problems()
        self.assertTrue(any("S-1" in p and "库里没有" in p for p in probs), probs)

    def test_coverage_flags_hand_edited_row(self):
        """手改读侧视图的行（case 内容没动）→ 红。总表的 hash 查不出这种改动，行级比对能——
        这是覆盖检查比"只比 hash"强的地方。"""
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        p = bi.shard_path(self.root, "inference/vllm-ascend__interrupt")
        p.write_text(p.read_text(encoding="utf-8").replace("title: t", "title: 手改过的标题"),
                     encoding="utf-8")
        probs = self.problems()
        self.assertTrue(any("对不上" in x for x in probs), probs)

    def test_union_merged_index_is_green(self):
        """**关键一条**：两人同一天各加一条 case，合并出来的读侧视图/总表（两条目都在、
        顺序可能与重新生成不同）必须是**绿的**——否则"不用任何人跑命令"就白拿了。
        内容出错（丢条目）仍然红，见上面几条。"""
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.write_case("inference/vllm-ascend/interrupt/B.yaml", cid="B-1")
        ns = bi.collect(self.root)
        self.generate_all(ns)
        # 模拟行级合并：把 B 那一行挪到 A 前面（顺序非规范，内容齐全）
        p = bi.shard_path(self.root, "inference/vllm-ascend__interrupt")
        text = p.read_text(encoding="utf-8")
        head, *rows = text.splitlines()
        rows = [ln for ln in rows if ln.strip()]
        header = [ln for ln in rows if ln.startswith("#")]
        body = [ln for ln in rows if not ln.startswith("#")]
        self.assertEqual(len(body), 2, body)
        p.write_text("\n".join(header + [body[1], body[0]]) + "\n", encoding="utf-8")
        self.assertEqual(self.problems(), [])                      # 门：绿（内容齐全）
        self.assertTrue(bi.canonical_dirty(self.root, ns))         # 逐字节自检：非规范（可选归一）

    def test_coverage_flags_duplicate_rows(self):
        """同一条 case 在读侧视图里出现两次（行级合并/重复 rebase 的产物，内容完全相同 → git 不报冲突，
        行比对也一致）→ 必须报出来。只按 id 建字典的话第二份被静静吃掉（评审抓到的洞）。"""
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        p = bi.shard_path(self.root, "inference/vllm-ascend__interrupt")
        text = p.read_text(encoding="utf-8")
        body = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        p.write_text(text + body[0] + "\n", encoding="utf-8")   # 同一行再来一份（内容完全相同）
        probs = self.problems()
        self.assertTrue(any("出现 2 次" in x for x in probs), probs)

    def test_coverage_red_when_cell_view_emptied(self):
        """把某一格的视图掏空（条目还在 ns 兜底视图里）→ 必须红。

        为什么单列（独立预核 2026-09-29 指出的既有洞）：只按 id 建全局索引时，"这条在别处找得到"
        会盖住"它自己那一格没了"——而阶段一命中该格时读的正是那一份。
        """
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        p = bi.shard_path(self.root, "inference/vllm-ascend__interrupt")
        head = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("#")]
        p.write_text("\n".join(head) + "\n", encoding="utf-8")          # 头注留着，条目清空
        probs = self.problems()
        self.assertTrue(any("缺 S-1" in x for x in probs), probs)

    def test_coverage_red_when_fallback_view_emptied(self):
        """ns 兜底视图被掏空 → 必须红。

        为什么单列：它是 category 判不出时**唯一**能读的那份（且更贵），但条目在类视图里也找得到，
        只按 id 建全局索引就看不出来（独立预核 2026-09-29 指出这条路径没被覆盖）。
        """
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.write_case("inference/vllm-ascend/precision/P.yaml", cid="P-1", cat="precision")
        self.generate_all()
        fb = bi.shard_path(self.root, "inference/vllm-ascend")
        head = [ln for ln in fb.read_text(encoding="utf-8").splitlines() if ln.startswith("#")]
        fb.write_text("\n".join(head) + "\n", encoding="utf-8")
        probs = self.problems()
        self.assertTrue(any("ns 兜底视图" in x and "缺 S-1" in x for x in probs), probs)

    def test_coverage_red_when_shard_missing(self):
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        bi.shard_path(self.root, "inference/vllm-ascend__interrupt").unlink()
        probs = self.problems()
        # 少了该类读侧视图：条目还在 ns 兜底视图里（覆盖不破），但阶段一命中该格的路径读不到了 → 必须报
        self.assertTrue(any("读侧视图缺失" in p and "inference__vllm-ascend__interrupt" in p for p in probs), probs)

    def test_shard_with_conflict_markers_is_reported_not_merged(self):
        """读侧视图里出现冲突标记（不该有——索引故意没配 union，撞了就该重跑）→ 点名，动作是重跑生成器。"""
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        p = bi.shard_path(self.root, "inference/vllm-ascend__interrupt")
        p.write_text("<<<<<<< HEAD\nid: S-1 | title: t\n=======\nid: S-1 | title: t\n>>>>>>> other\n",
                     encoding="utf-8")
        _rows, broken = bi.shard_lines(self.root)
        self.assertTrue(broken and "冲突标记" in broken[0], broken)
        self.assertTrue(any("冲突标记" in x for x in self.problems()), self.problems())

    def test_header_has_no_numbers(self):
        """生成物头注里不留数字（条数/容量/日期）：数字一进 git，两人并发合并时要么撞同一行、
        要么漂移成错的数。数字改成现算（scripts/index_counts.py）。"""
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        text = bi.render(bi.collect(self.root))
        self.assertEqual(text, bi.render(bi.collect(self.root)))
        head = text.split("namespaces:")[0]
        self.assertNotIn("生成日期：", head)
        self.assertNotIn("case 总数：", head)
        self.assertNotIn("容量(", head)
        self.assertNotRegex(head, r"20\d\d-\d\d-\d\d")
        shard_head = bi.render_shard("inference/vllm-ascend__interrupt",
                                     {"interrupt": bi.collect(self.root)["inference/vllm-ascend"]["interrupt"]}
                                     ).split("\n\n")[0]
        self.assertNotRegex(shard_head, r"（\d+ 条 case）")
        self.assertNotRegex(shard_head, r"20\d\d-\d\d-\d\d")

    def test_sig_and_tok_fields_for_phase_one_ranking(self):
        """行内签名面字段（EV-2026-111）：sig 只收纯字面量、tok 覆盖全部症状且上限 12。"""
        p = self.root / "knowledge" / "inference" / "vllm-ascend" / "interrupt" / "S.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        # 用单引号 YAML 标量：双引号会处理反斜杠转义，把正则分支写坏
        p.write_text(
            "cases:\n"
            "  - id: S-1\n"
            "    title: 't'\n"
            "    category: interrupt\n"
            "    tags: [a]\n"
            "    confidence: {score: 0.5}\n"
            "    symptoms:\n"
            "      - '首条症状，无字面量'\n"
            "      - '第二条症状：error code 507014，kernel_name=MoeDistributeDispatchV2'\n"
            "    quickly_check:\n"
            "      primary:\n"
            "        expected: 'regex:507014|\\d+\\(\\)|aicore exception'\n",
            encoding="utf-8")
        row = bi.collect(self.root)["inference/vllm-ascend"]["interrupt"][0]
        self.assertIn("507014", row["sig"])
        self.assertIn("aicore exception", row["sig"])
        self.assertNotIn("\\d+", " ".join(row["sig"]))       # 正则元字符分支不入 sig
        self.assertIn("507014", row["tok"])                  # 判别信号在第二条症状 → tok 收得到
        self.assertLessEqual(len(row["tok"]), 12)

    # ------------------------------------------------- 读侧视图（一行一条 case）
    # 阶段一读的是这份东西，不是 YAML：判据字段一个不少，但 `file`（可由 id 推出）与 `hash`
    # （只服务新鲜度门）不进读侧。下面钉住这个投影的形态与可解析性。
    def test_read_view_carries_judgement_evidence_not_gate_fields(self):
        self.write_case("inference/vllm-ascend/interrupt/R.yaml", cid="R-1", title="标题 t", sym="症状 s")
        ns = bi.collect(self.root)
        line = [ln for ln in bi.render_shard("inference/vllm-ascend",
                                             ns["inference/vllm-ascend"]).splitlines()
                if not ln.startswith("#") and ln.strip()][0]
        for want in ("id: R-1", "category: interrupt", "title: 标题 t", "symptoms: 症状 s"):
            self.assertIn(want, line)
        self.assertNotIn("knowledge/inference", line)   # file 可由 id 推出，不进读侧
        self.assertNotIn("hash:", line)                 # hash 只在总表里（门用）

    def test_read_view_field_sequence_is_pinned(self):
        """读侧字段**序列**逐项钉住（不只是"某几个子串在"）。

        为什么（独立预核 2026-09-29 的反例）：只查子串时，把 `tok` 段整段删掉、重新生成，
        `--check --canonical` 仍绿、全部测试仍过——"悄悄砍掉判断证据"能一路通过。
        这里断言键的序列：少一个、多一个、换个顺序都红。
        """
        p = self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        p.write_text(
            "cases:\n"
            "  - id: A-1\n"
            "    title: t\n"
            "    category: interrupt\n"
            "    tags: [a]\n"
            "    compat:\n"
            "      - framework: vllm-ascend\n"
            "        ranges: [\"0.23.0\"]\n"
            "    confidence: {score: 0.5}\n"
            "    symptoms: ['首条症状：error code 507014']\n"
            "    quickly_check:\n"
            "      primary:\n"
            "        expected: 'regex:507014|error code 5'\n",
            encoding="utf-8")
        row = bi.collect(self.root)["inference/vllm-ascend"]["interrupt"][0]
        names = [part.split(": ", 1)[0] for part in bi.compact_line(row).split(bi.SEP)]
        self.assertEqual(names, list(bi.READ_FIELDS))         # 全字段用例：九段一个不少、顺序即 READ_FIELDS
        self.assertNotIn("file", names)                      # 路径统一时逐行不带 file（由头注给目录）
        # 缺字段的用例：只允许"按序省略"，不许改序、不许冒出外来键
        self.write_case("inference/vllm-ascend/interrupt/B.yaml", cid="B-1", title="t2")
        row2 = [r for r in bi.collect(self.root)["inference/vllm-ascend"]["interrupt"] if r["id"] == "B-1"][0]
        names2 = [part.split(": ", 1)[0] for part in bi.compact_line(row2).split(bi.SEP)]
        self.assertEqual(names2, [f for f in bi.READ_FIELDS if f in names2])

    def test_read_view_carries_file_when_paths_are_not_uniform(self):
        """条目路径不统一时逐行带 `file`——否则读者按头注的目录去找会 404。

        真实例外：`knowledge/inference/sglang/` 下没有 category 层，那条 case 的路径推不出来
        （全库 168 条里 1 条）。这里的合成场景与它同类：同一个 ns 视图里两条 case 落在不同目录。
        """
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.write_case("inference/vllm-ascend/precision/B.yaml", cid="B-1", cat="precision")
        ns = bi.collect(self.root)
        text = bi.render_shard("inference/vllm-ascend", ns["inference/vllm-ascend"])
        self.assertIn("条目路径不统一", text)
        body = [ln for ln in text.splitlines() if not ln.startswith("#")]
        self.assertTrue(all("file: knowledge/" in ln for ln in body), body)
        # 而单格视图路径统一 → 头注给目录、逐行不带 file
        cell = bi.render_shard("inference/vllm-ascend__interrupt", {"interrupt": ns["inference/vllm-ascend"]["interrupt"]})
        self.assertIn("条目所在目录：knowledge/inference/vllm-ascend/interrupt/", cell)
        self.assertNotIn("file: knowledge/", cell)

    def test_read_view_line_round_trips(self):
        """一行要能解析回字段——门是按行比对，但消费者（体检、上限判定）要能按字段读。"""
        self.write_case("inference/vllm-ascend/interrupt/R.yaml", cid="R-1", title="a: b | c", sym="症状 s")
        row = bi.collect(self.root)["inference/vllm-ascend"]["interrupt"][0]
        line = bi.compact_line(row)
        self.assertNotIn(" | ", line.split("title: ")[1].split(" | ")[0])   # 值里的 | 已折成 ¦
        back = bi.parse_read_line(line)
        self.assertEqual(back["id"], "R-1")
        self.assertEqual(back["category"], "interrupt")
        self.assertEqual(back["title"], "a: b ¦ c")
        self.assertEqual(back["symptoms"], "症状 s")

    def test_read_view_ignores_unknown_keys(self):
        """手改进来的杂字段不该被当成字段（解析器只认 READ_FIELDS）。"""
        back = bi.parse_read_line("id: X-1 | 备注: 手写的 | title: t")
        self.assertEqual(back, {"id": "X-1", "title": "t"})

    def test_legacy_yaml_shard_is_reported(self):
        """旧形态（.yaml）分片残留在目录里 → 报出来催回收（换形态那次迁移的护栏）。"""
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        legacy = bi.shard_path(self.root, "inference/vllm-ascend").with_suffix(".yaml")
        legacy.write_text("namespaces: {}\n", encoding="utf-8")
        probs = self.problems()
        self.assertTrue(any("旧形态分片" in p for p in probs), probs)

    def test_duplicate_read_view_line_is_reported(self):
        """同一行原样留两份（行级合并的典型产物）→ 报重复，别被字典静静吃掉。"""
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        p = bi.shard_path(self.root, "inference/vllm-ascend__interrupt")
        body = [ln for ln in p.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
        p.write_text("\n".join(body + [body[-1]]) + "\n", encoding="utf-8")
        self.assertTrue(any("出现 2 次" in x for x in self.problems()), self.problems())

    def test_compat_string_valued_range_is_not_split_into_chars(self):
        """cann/hdk 写成字符串时不能被逐字符 join（实测：库里有一条 `cann: "<9.1.0.beta2"`）。

        这是渲染的健壮性，不是 schema 变更：那条 case 的字段类型属 compat 面（高风险），不改。
        """
        self.assertEqual(bi.compat_summary([{"framework": "vllm-ascend", "ranges": ["0.23.0"],
                                            "cann": "<9.1.0.beta2"}]),
                         "vllm-ascend 0.23.0 (cann:<9.1.0.beta2)")
        self.assertEqual(bi.compat_summary([{"framework": "v", "ranges": ["1"], "hdk": ["<25.5.1"]}]),
                         "v 1 (hdk:<25.5.1)")


    # ------------------------------------------------- 目录 × category 一致门口径
    # 目录表达性质（人翻目录、将来按目录切子族都靠它），字段是索引真正的格子来源——
    # 两者不一致时索引自洽、实体合法，只有"按目录找"会错位，且没有任何别的信号报它。
    def test_dir_category_mismatch_is_reported(self):
        self.write_case("inference/vllm-ascend/interrupt/M.yaml", cid="M-1", cat="precision")
        probs = bi.dir_category_problems(self.root)
        self.assertEqual(len(probs), 1)
        self.assertIn("M-1", probs[0])
        self.assertIn("interrupt", probs[0])

    def test_dir_category_match_is_silent(self):
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1", cat="interrupt")
        self.write_case("common/performance/B.yaml", cid="B-1", cat="performance")
        self.assertEqual(bi.dir_category_problems(self.root), [])

    def test_dir_without_category_layer_is_silent(self):
        """`knowledge/inference/sglang/` 这类直接把 case 放在框架层的形态：目录不表达性质，不报。"""
        self.write_case("inference/sglang/C.yaml", cid="C-1", cat="interrupt")
        self.assertEqual(bi.dir_category_problems(self.root), [])

    def test_dir_check_covers_common_and_nested(self):
        self.write_case("common/precision/D.yaml", cid="D-1", cat="interrupt")
        self.write_case("training/verl/performance/E.yaml", cid="E-1", cat="interrupt")
        probs = bi.dir_category_problems(self.root)
        self.assertEqual(len(probs), 2)
        self.assertTrue(any("D-1" in p for p in probs))
        self.assertTrue(any("E-1" in p for p in probs))

    def test_dir_check_skips_archive_and_generated(self):
        self.write_case("_archive/inference/vllm-ascend/interrupt/OLD.yaml", cid="OLD-1", cat="precision")
        self.write_case("_index/inference/vllm-ascend/interrupt/X.yaml", cid="X-1", cat="precision")
        self.assertEqual(bi.dir_category_problems(self.root), [])


if __name__ == "__main__":
    unittest.main()
