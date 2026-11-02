"""ref_gap_index 的口径回归测试。

护六件事，每件错了都不会报错，只会让人多做一次无用功或把建议指错方向：

1. **三种动作分得开**：键有对应词条 → 回链；没有对应词条、但 case 被非 active 词条反向
   引用过 → 复审；两者都没有 → 提炼。
2. **「已连」认 case 侧的正向边**（`ref_knowledge`），不认词条侧的 `sources[].cases`：
   诊断按 `ref_knowledge` 加载词条，反向边不把词条送进上下文。
3. **回链目标按 case 算**：键命中给的目标对整组有效；键没命中时，只有「确实被那条 active
   词条引用过」的 case 才拿得到目标，同伴不能跟着挂上去。
4. **键只从 title 与 symptoms 抽**：diagnosis / quickly_check 里的码常是判别句。
5. **没有键的 case 按引用关系分三段点名**，且不会被组表阈值或 tag_hygiene 的「已收录剔除」
   吞掉；有键但没进表的 case 也要点名。
6. **边界与参数**：`507903` 不命中 `1507903`，`HCCL_DEBUG` 不命中 `HCCL_DEBUG_INFO`，
   内置异常名不构成键；`--top < 1` 是用法错误，`--json` 也吃 `--top`。
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ref_gap_index as rg  # noqa: E402


def write_case(root: Path, cid: str, symptom: str, ref_knowledge=None, diagnosis=None) -> None:
    d = root / "knowledge" / "inference" / "vllm-ascend" / "interrupt"
    d.mkdir(parents=True, exist_ok=True)
    lines = [
        "cases:",
        f"  - id: {cid}",
        f'    title: "测试 case {cid}"',
        "    category: interrupt",
        "    symptoms:",
        f"      - {json.dumps(symptom, ensure_ascii=False)}",
    ]
    if diagnosis:
        lines.append("    diagnosis:")
        lines.append(f"      - {json.dumps(diagnosis, ensure_ascii=False)}")
    if ref_knowledge:
        lines.append("    ref_knowledge:")
        for ref in ref_knowledge:
            lines.append(f"      - {{ref: {ref}, role: signature-source}}")
    (d / f"{cid}.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_ref(root: Path, rid: str, status: str, cases=None, extra: str = "") -> Path:
    d = root / "references" / "methodologies"
    d.mkdir(parents=True, exist_ok=True)
    lines = [f"id: {rid}", "type: methodology", f'title: "测试词条 {rid}"', "sources:"]
    if cases:
        lines.append(f"  - {{type: case-derived, cases: [{', '.join(cases)}]}}")
    else:
        lines.append("  - {type: official-doc, url: 'https://example.invalid/x'}")
    lines += ["status: " + status, "content:", "  flow: []"]
    p = d / f"{rid}.yaml"
    p.write_text("\n".join(lines) + "\n" + extra, encoding="utf-8")
    return p


def write_error_table(
    root: Path, rel: str, codes, status: str = "active", rid: str = "test-error-codes"
) -> None:
    p = root / "references" / "errors" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    entries = "\n".join(f'      - code: "{c}"\n        meaning: "测试码"' for c in codes)
    p.write_text(
        f"id: {rid}\n"
        "type: error-code\n"
        'title: "测试错误码表"\n'
        f"status: {status}\n"
        "content:\n"
        "  errors:\n" + entries + "\n",
        encoding="utf-8",
    )


class KeysTest(unittest.TestCase):
    def test_builtin_exception_is_not_a_key(self):
        for name in ("AttributeError", "FileNotFoundError", "CancelledError"):
            self.assertEqual(set(), rg.keys_of(f"raise {name}('x')"))

    def test_specific_exception_is_a_key(self):
        self.assertIn(("exc", "EngineDeadError"), rg.keys_of("vLLM EngineDeadError"))

    def test_code_inside_longer_number_is_not_a_code(self):
        self.assertNotIn(("code", "507903"), rg.keys_of("port=1507903"))

    def test_env_name_is_matched_on_boundary(self):
        self.assertNotIn(("env", "HCCL_DEBUG"), rg.keys_of("HCCL_DEBUG_INFO=1"))
        self.assertIn(("env", "HCCL_DEBUG"), rg.keys_of("export HCCL_DEBUG=1"))

    def test_alpha_code_is_matched_on_boundary(self):
        self.assertNotIn(("code", "EZ1001"), rg.keys_of("见 FEZ10010"))
        self.assertIn(("code", "EZ1001"), rg.keys_of("报 EZ1001 退出"))

    def test_keys_only_come_from_title_and_symptoms(self):
        case = {"title": "普通标题", "symptoms": ["无报错"], "diagnosis": [{"check": "报 507057 还是 507014？"}]}
        self.assertEqual(set(), rg.keys_of(rg.case_text(case)))
        case["symptoms"] = ["报错 507014 后退出"]
        self.assertIn(("code", "507014"), rg.keys_of(rg.case_text(case)))

    def test_torch_op_key_has_no_trailing_dot(self):
        self.assertIn(
            ("torch-op", "torch.ops.npu_fused_attention"),
            rg.keys_of("调用 torch.ops.npu_fused_attention."),
        )


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ref-gap-")
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def rows_by_key(self):
        index = rg.build_index(self.root)
        out = {}
        for row in index["groups"]:
            out.setdefault(row["key"], {})[row["action"]] = row
        return out

    def test_extract_when_nothing_exists(self):
        for cid in ("C-1", "C-2", "C-3"):
            write_case(self.root, cid, "报错 507034 启动失败")
        row = self.rows_by_key()["code:507034"]["extract"]
        self.assertEqual(3, row["actionable"])
        self.assertEqual([], row["home"])

    def test_relink_when_code_has_active_table(self):
        for cid in ("C-1", "C-2", "C-3"):
            write_case(self.root, cid, "报错 507015")
        write_error_table(self.root, "cann-runtime.yaml", ["507015"])
        row = self.rows_by_key()["code:507015"]["relink"]
        self.assertEqual(["test-error-codes"], row["home"])
        self.assertEqual("key", row["home_kind"])

    def test_relink_points_at_seen_in_entry_when_code_gap_indexed(self):
        for cid in ("C-1", "C-2", "C-3"):
            write_case(self.root, cid, "报错 507035")
        write_ref(self.root, "movement-patterns", "active")
        gaps = self.root / "references" / "errors" / "_code-gaps.yaml"
        gaps.parent.mkdir(parents=True, exist_ok=True)
        gaps.write_text(
            "code_gaps:\n"
            "  - code: '507035'\n"
            "    seen_in:\n"
            "      - references/methodologies/movement-patterns.yaml\n",
            encoding="utf-8",
        )
        row = self.rows_by_key()["code:507035"]["relink"]
        self.assertEqual(["movement-patterns"], row["home"])

    def test_seen_in_pointing_at_inactive_ref_is_not_a_home(self):
        for cid in ("C-1", "C-2", "C-3"):
            write_case(self.root, cid, "报错 507035")
        write_ref(self.root, "old-patterns", "deprecated", cases=["C-1", "C-2", "C-3"])
        gaps = self.root / "references" / "errors" / "_code-gaps.yaml"
        gaps.parent.mkdir(parents=True, exist_ok=True)
        gaps.write_text(
            "code_gaps:\n"
            "  - code: '507035'\n"
            "    seen_in:\n"
            "      - references/methodologies/old-patterns.yaml\n",
            encoding="utf-8",
        )
        rows = self.rows_by_key()["code:507035"]
        self.assertIn("recheck", rows)
        self.assertEqual([], rows["recheck"]["home"])

    def test_recheck_when_only_inactive_ref_cites_cases(self):
        for cid in ("C-1", "C-2", "C-3"):
            write_case(self.root, cid, "报错 507034")
        write_ref(self.root, "old-triage", "deprecated", cases=["C-1", "C-2", "C-3"])
        row = self.rows_by_key()["code:507034"]["recheck"]
        self.assertEqual(["old-triage"], row["cited_by_inactive"])

    def test_reverse_active_citation_becomes_the_relink_target(self):
        for cid in ("C-1", "C-2", "C-3"):
            write_case(self.root, cid, "报错 507034")
        write_ref(self.root, "new-triage", "active", cases=["C-1", "C-2", "C-3"])
        row = self.rows_by_key()["code:507034"]["relink"]
        self.assertEqual(["new-triage"], row["home"])
        self.assertEqual("cited", row["home_kind"])
        self.assertEqual(3, row["actionable"])

    def test_extract_only_when_no_ref_cites_the_cases(self):
        for cid in ("C-1", "C-2", "C-3"):
            write_case(self.root, cid, "报错 507034")
        write_ref(self.root, "some-triage", "active", cases=["OTHER-9"])
        row = self.rows_by_key()["code:507034"]["extract"]
        self.assertEqual([], row["home"])

    def test_forward_edge_to_home_counts_as_linked(self):
        write_case(self.root, "C-1", "报错 507015", ref_knowledge=["test-error-codes"])
        write_case(self.root, "C-2", "报错 507015")
        write_case(self.root, "C-3", "报错 507015")
        write_error_table(self.root, "cann-runtime.yaml", ["507015"])
        row = self.rows_by_key()["code:507015"]["relink"]
        self.assertEqual(2, row["actionable"])
        self.assertEqual(3, row["size"])
        self.assertEqual(["C-2", "C-3"], row["cases"])

    def test_forward_edge_to_other_ref_is_not_enough_for_this_home(self):
        write_case(self.root, "C-1", "报错 507015", ref_knowledge=["some-other-triage"])
        write_case(self.root, "C-2", "报错 507015")
        write_error_table(self.root, "cann-runtime.yaml", ["507015"])
        write_ref(self.root, "some-other-triage", "active")
        row = self.rows_by_key()["code:507015"]["relink"]
        self.assertEqual(2, row["actionable"])

    def test_forward_edge_to_inactive_ref_does_not_link(self):
        write_case(self.root, "C-1", "报错 507015", ref_knowledge=["old-triage"])
        write_case(self.root, "C-2", "报错 507015")
        write_error_table(self.root, "cann-runtime.yaml", ["507015"])
        write_ref(self.root, "old-triage", "deprecated")
        row = self.rows_by_key()["code:507015"]["relink"]
        self.assertEqual(2, row["actionable"])
        self.assertEqual(["C-1", "C-2"], row["cases"])

    def test_reverse_home_applies_only_to_the_cited_cases(self):
        # 键没有对应词条：C-1 被 active 词条引用 → 回链；C-3 只被非 active 引用 → 复审；
        # C-2 谁也没引用 → 提炼。同一组拆成三行，各自只带自己的 case。
        write_case(self.root, "C-1", "报错 107027")
        write_case(self.root, "C-2", "报错 107027")
        write_case(self.root, "C-3", "报错 107027")
        write_ref(self.root, "active-triage", "active", cases=["C-1"])
        write_ref(self.root, "old-triage", "deprecated", cases=["C-3"])
        rows = self.rows_by_key()["code:107027"]
        self.assertEqual(["C-1"], rows["relink"]["cases"])
        self.assertEqual(["active-triage"], rows["relink"]["home"])
        self.assertEqual("cited", rows["relink"]["home_kind"])
        self.assertEqual(["C-2"], rows["extract"]["cases"])
        self.assertEqual(["C-3"], rows["recheck"]["cases"])

    def test_group_fully_forward_linked_is_not_reported(self):
        for cid in ("C-1", "C-2", "C-3"):
            write_case(self.root, cid, "报错 507034", ref_knowledge=["some-triage"])
        write_ref(self.root, "some-triage", "active")
        self.assertNotIn("code:507034", self.rows_by_key())

    def test_archived_case_is_not_counted(self):
        write_case(self.root, "C-1", "报错 507034")
        archived = self.root / "knowledge" / "_archive" / "old.yaml"
        archived.parent.mkdir(parents=True, exist_ok=True)
        archived.write_text(
            "cases:\n  - id: OLD-1\n    title: 旧\n    symptoms:\n      - 报错 507034\n",
            encoding="utf-8",
        )
        row = self.rows_by_key()["code:507034"]["extract"]
        self.assertEqual(1, row["actionable"])

    def test_keyed_inactive_only_case_is_not_in_the_keyless_lists(self):
        write_case(self.root, "K-1", "报错 507034")
        write_ref(self.root, "old-triage", "deprecated", cases=["K-1"])
        index = rg.build_index(self.root)
        for name in (
            "no_key_cases_cited_by_active",
            "no_key_cases_inactive_only",
            "no_key_uncited_ids",
        ):
            self.assertNotIn("K-1", index[name])

    def test_keyless_cases_are_split_into_three_lists(self):
        write_case(self.root, "K-ACTIVE", "训练启动后挂住，无报错")
        write_case(self.root, "K-INACTIVE", "训练启动后挂住，无报错")
        write_case(self.root, "K-NONE", "训练启动后挂住，无报错")
        write_ref(self.root, "active-ref", "active", cases=["K-ACTIVE"])
        write_ref(self.root, "old-ref", "deprecated", cases=["K-INACTIVE"])
        index = rg.build_index(self.root)
        self.assertEqual(["K-ACTIVE"], index["no_key_cases_cited_by_active"])
        self.assertEqual(["K-INACTIVE"], index["no_key_cases_inactive_only"])
        self.assertEqual(["K-NONE"], index["no_key_uncited_ids"])
        text = "\n".join(rg.render(index, min_n=3, top=10))
        for cid in ("K-ACTIVE", "K-INACTIVE", "K-NONE"):
            self.assertIn(cid, text)

    def test_keyless_case_cited_by_both_lists_goes_to_the_active_list(self):
        # 同一条无键 case 被 active 词条与非 active 词条一起引用：只算「被 active 引用」，
        # headline 的「只被非 active 反向引用」不能把它也数进去。
        write_case(self.root, "K-BOTH", "无报错")
        write_case(self.root, "K-ACTIVE", "无报错")
        write_ref(self.root, "active-ref", "active", cases=["K-BOTH", "K-ACTIVE"])
        write_ref(self.root, "old-ref", "deprecated", cases=["K-BOTH"])
        index = rg.build_index(self.root)
        self.assertEqual(["K-ACTIVE", "K-BOTH"], index["no_key_cases_cited_by_active"])
        self.assertEqual([], index["no_key_cases_inactive_only"])
        self.assertEqual([], index["no_key_uncited_ids"])
        self.assertEqual(0, index["cases_only_inactive_cited"])

    def test_every_unlinked_case_appears_in_the_output(self):
        for i in range(3):
            write_case(self.root, f"G-{i}", "报错 507034")
        for i in range(2):
            write_case(self.root, f"S-{i}", "报错 507015")
        write_case(self.root, "K-A", "无报错")
        write_case(self.root, "K-B", "无报错")
        write_ref(self.root, "active-ref", "active", cases=["K-A"])
        write_ref(self.root, "old-ref", "deprecated", cases=["K-B"])
        index = rg.build_index(self.root)
        text = "\n".join(rg.render(index, min_n=3, top=10))
        self.assertIn("code:507034", text)
        for cid in ("S-0", "S-1", "K-A", "K-B"):
            self.assertIn(cid, text)
        self.assertIn("未进表的未连 case：2 条", text)
        self.assertEqual(7, index["cases_without_active_link"])

    def test_missed_list_accounts_for_top_truncation(self):
        for i in range(3):
            write_case(self.root, f"A-{i}", "报错 507034")
        for i in range(3):
            write_case(self.root, f"B-{i}", "报错 507015")
        index = rg.build_index(self.root)
        text = "\n".join(rg.render(index, min_n=3, top=1))
        # 两行都达到阈值，--top 1 只显示排在前面的 code:507015；另一行的 3 条 case 必须落到
        # 「未进表」清单里，不能跟着被截断的行一起消失。
        self.assertIn("code:507015", text)
        for cid in ("A-0", "A-1", "A-2"):
            self.assertIn(cid, text)

    def test_min_filter_and_top_truncation(self):
        for i in range(3):
            write_case(self.root, f"A-{i}", "报错 507034")
        for i in range(2):
            write_case(self.root, f"B-{i}", "报错 507015")
        index = rg.build_index(self.root)
        text = "\n".join(rg.render(index, min_n=3, top=10))
        self.assertIn("code:507034", text)
        self.assertNotIn("code:507015", text)

        text = "\n".join(rg.render(index, min_n=2, top=1))
        self.assertIn("另有 1 行未列出", text)

    def test_top_below_one_is_usage_error(self):
        write_case(self.root, "C-1", "报错 507034")
        write_ref(self.root, "some-triage", "active")
        for bad in ("0", "-5"):
            self.assertEqual(2, rg.main(["--root", str(self.root), "--top", bad]))

    def test_missing_root_is_usage_error(self):
        self.assertEqual(2, rg.main(["--root", str(self.root / "nope")]))


class JsonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ref-gap-json-")
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_json(self, *extra):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = rg.main(["--root", str(self.root), "--json", *extra])
        return rc, json.loads(buf.getvalue())

    def test_payload_shape_and_top(self):
        for i in range(3):
            write_case(self.root, f"A-{i}", "报错 507034")
        for i in range(3):
            write_case(self.root, f"B-{i}", "报错 507015")
        write_ref(self.root, "some-triage", "active")
        rc, payload = self.run_json("--min", "2", "--top", "1")
        self.assertEqual(0, rc)
        for key in (
            "cases",
            "refs_active",
            "refs_inactive",
            "cases_without_active_link",
            "cases_only_inactive_cited",
            "cases_without_any_key",
            "no_key_cases_cited_by_active",
            "no_key_cases_inactive_only",
            "no_key_cases_uncited",
            "no_key_uncited_ids",
            "unlinked_keyed_cases",
            "groups",
            "groups_total",
        ):
            self.assertIn(key, payload)
        self.assertEqual(1, len(payload["groups"]))
        self.assertEqual(2, payload["groups_total"])


if __name__ == "__main__":
    unittest.main()
