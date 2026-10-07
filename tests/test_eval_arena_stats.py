"""eval_arena 打分侧的三处口径（本卡机制修正）。

护三件事：
① **result 字段两套写法都认**：盘上的 result 文件写 `tier2_hit` / `routing_ok` / `root_cause_ok`，
   而工具早期只读 `hit_case` / `route` / `rc_match`。只认一套的代价是**结论一致（rc）一路恒为
   None**——判定少一路证据，账本里也分不清"没有数据"和"结论不一致"。
② **缺参要明确退化**：`--gate` 不给 baseline/candidate 时，旧行为是拿空路径去读仓库根，报
   "Is a directory" 这种和真因无关的错；现在退 2 并打印"下一步该建池/跑 stats"。
③ **吸收状态在运行期重判、held_out 真的不参与判定**：池建好之后答案仍会进知识库，那时池测的
   是背诵而不是检索能力；`held_out` 此前只被建池写过、没有读取方。两件事都在
   `AbsorptionRuntimeRecheckTest` 与 `HeldOutSkipTest` 里守住。
"""

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import eval_arena as ea  # noqa: E402
import yaml  # noqa: E402

POOL = """\
name: pool-t
split: selection
issues:
  - {id: "101", expected_ns: "inference/vllm-ascend", fix_ref: "PR#1"}
  - {id: "102", expected_ns: "inference/vllm-ascend", fix_ref: "PR#2"}
"""

NEW_STYLE = """\
namespace: inference/vllm-ascend
category: interrupt
hit_case: ""
tier2_hit: false
routing_ok: true
root_cause_ok: true
"""

OLD_STYLE = """\
namespace: inference/vllm-ascend
route: ok
hit_case: CASE-A
rc_match: false
"""


class StatsFieldCompatTest(unittest.TestCase):
    def _run(self, results):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        arena = root / ".s2-replay" / "arena"
        arena.mkdir(parents=True)
        (arena / "pool-t.yaml").write_text(POOL, encoding="utf-8")
        for iid, text in results.items():
            (root / ".s2-replay" / f"{iid}.result.yaml").write_text(text, encoding="utf-8")
        self.assertEqual(ea.cmd_stats(root, arena / "pool-t.yaml"), 0, "cmd_stats 应成功")
        return yaml.safe_load((arena / "stats-pool-t.yaml").read_text(encoding="utf-8"))

    def test_reads_new_style_fields(self):
        s = self._run({"101": NEW_STYLE, "102": NEW_STYLE})
        self.assertTrue(all(v["route_ok"] for v in s["issues"]))
        self.assertTrue(all(v["rc_match"] is True for v in s["issues"]),
                        "root_cause_ok 必须被读成 rc_match（旧实现恒为 None）")
        self.assertTrue(all(v["hit"] is False for v in s["issues"]))

    def test_reads_old_style_fields(self):
        s = self._run({"101": OLD_STYLE, "102": OLD_STYLE})
        self.assertTrue(all(v["hit"] for v in s["issues"]))
        self.assertTrue(all(v["rc_match"] is False for v in s["issues"]))
        self.assertTrue(all(v["route_ok"] for v in s["issues"]))

    def test_pool_hash_written(self):
        s = self._run({"101": NEW_STYLE, "102": NEW_STYLE})
        self.assertTrue(s.get("pool_hash"), "池内容哈希缺失 → 复用计数无法按量尺归零")


class GateArgValidationTest(unittest.TestCase):
    def test_gate_without_args_exits_2_with_next_step(self):
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "eval_arena.py"), "--gate"],
                           capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
        self.assertEqual(p.returncode, 2)
        self.assertIn("baseline", p.stderr)
        self.assertIn("--self-test", p.stderr, "缺数据时要说清该怎么走，而不是报与真因无关的错")


if __name__ == "__main__":
    unittest.main()


class ArenaPoolBuildTest(unittest.TestCase):
    """池可从已跟踪的 S2 校准集机械重建——这是"门控数据不可复核"的结构性修法。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        d = self.root / "eval" / "s2"
        d.mkdir(parents=True)
        (d / "pool.yaml").write_text("""\
calibration:
- issue: 111
  split: selection
  expected: {namespace: inference/vllm-ascend, category: interrupt, fix_commit: "PR #1"}
- issue: 222
  split: test
  expected: {namespace: training/verl, category: precision, fix_commit: "PR #2"}
- issue: 333
  split: selection
  expected: {namespace: common, category: performance, fix_commit: ""}
""", encoding="utf-8")

    def test_builds_selection_pool_and_excludes_test(self):
        out = self.root / ".s2-replay" / "arena" / "pool-val.yaml"
        rc = ea.build_pool(self.root, "eval/s2/pool.yaml", "val", "selection", False, str(out))
        self.assertEqual(rc, 0)
        pool = yaml.safe_load(out.read_text(encoding="utf-8"))
        ids = [it["id"] for it in pool["issues"]]
        self.assertEqual(ids, ["111", "333"], "test 条目不得进 gate 池")
        self.assertEqual(pool["issues"][0]["expected_ns"], "inference/vllm-ascend")
        self.assertEqual(pool["issues"][0]["fix_ref"], "PR #1")

    def test_only_scored_filters_unscored(self):
        (self.root / ".s2-replay").mkdir(parents=True, exist_ok=True)
        (self.root / ".s2-replay" / "111.result.yaml").write_text("namespace: x\n", encoding="utf-8")
        out = self.root / ".s2-replay" / "arena" / "pool-s.yaml"
        self.assertEqual(ea.build_pool(self.root, "eval/s2/pool.yaml", "s", "selection", True, str(out)), 0)
        pool = yaml.safe_load(out.read_text(encoding="utf-8"))
        self.assertEqual([it["id"] for it in pool["issues"]], ["111"])

    def test_missing_source_exits_2(self):
        self.assertEqual(ea.build_pool(self.root, "eval/s2/nope.yaml", "x", "selection", False,
                                       str(self.root / "o.yaml")), 2)


class EmptyExpectedNsTest(unittest.TestCase):
    """池条目没有 expected_ns 时不得崩，也不得把"无从对照"算成路由成功/失败。

    实测来源：真实池里 11 条 expected 没写 namespace，`(expected_ns and ...)` 返回空串，
    一路传到 int('') 让 --stats 崩掉——fixture 里 expected_ns 都有值，所以之前没暴露。
    """

    def test_stats_survives_empty_expected_ns(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        arena = root / ".s2-replay" / "arena"
        arena.mkdir(parents=True)
        (arena / "pool-e.yaml").write_text("""\
name: pool-e
split: selection
issues:
  - {id: "901", expected_ns: "", category: "", fix_ref: ""}
""", encoding="utf-8")
        (root / ".s2-replay" / "901.result.yaml").write_text(
            "namespace: inference/vllm-ascend\nroute: ''\nrouting_ok: false\n"
            "hit_case: ''\ntier2_hit: false\nroot_cause_ok: false\n", encoding="utf-8")
        self.assertEqual(ea.cmd_stats(root, arena / "pool-e.yaml"), 0)
        s = yaml.safe_load((arena / "stats-pool-e.yaml").read_text(encoding="utf-8"))
        self.assertFalse(s["issues"][0]["route_ok"])          # 缺真值 → 不判为通过
        self.assertIsNone(s["metrics"]["route_ok"]["rate"])   # 分母为 0 → 不编造路由率
        self.assertEqual(s["metrics"]["route_ok"]["unjudgeable"], 1)


class AbsorbedRoutingTest(unittest.TestCase):
    """池按吸收状态分流：答案已进知识库的样本只进回归池，不参与门控判定。

    为什么要分流：那类样本的答案已被知识库吸收（自洽样本 self_consistent），
    留在判定池里等于把"答案已知"当"答对"，判定池的读数就不再有外部含义。
    吸收判据用 **case 实名**（`knowledge/**/VLLM-ASC-<issue>.yaml`），不用正文文本——
    正文提到别的 issue 是常事，文本搜索会把没被吸收的样本误判成已吸收。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        d = self.root / "eval" / "s2"
        d.mkdir(parents=True)
        (d / "pool.yaml").write_text("""\
calibration:
- issue: 111
  split: selection
  expected: {namespace: inference/vllm-ascend, category: interrupt, fix_commit: "PR #1"}
- issue: 222
  split: selection
  expected: {namespace: common, category: performance, fix_commit: "PR #2"}
""", encoding="utf-8")
        cases = self.root / "knowledge" / "inference" / "vllm-ascend" / "interrupt"
        cases.mkdir(parents=True)
        (cases / "VLLM-ASC-111.yaml").write_text("- id: VLLM-ASC-111\n", encoding="utf-8")
        # 正文提及不算吸收：真实例子里 VLLM-ASC-13639 的边界判别就写着别的 issue 号
        (cases / "VLLM-ASC-13639.yaml").write_text(
            'check: "边界判别：若签名不是 RPC 超时 hang 而是 222，属其他 case 勿混判"\n',
            encoding="utf-8")

    def _build(self):
        out = self.root / ".s2-replay" / "arena" / "pool-val.yaml"
        # 打印里有非 GBK 字符（既有行为），Windows 控制台编码下会抛 UnicodeEncodeError；
        # 断言与打印无关，这里把输出吞掉，测试只在 Linux 与 Windows 上同样成立。
        with contextlib.redirect_stdout(io.StringIO()):
            rc = ea.build_pool(self.root, "eval/s2/pool.yaml", "val", "selection", False, str(out))
        self.assertEqual(rc, 0)
        return (yaml.safe_load(out.read_text(encoding="utf-8")),
                yaml.safe_load(out.with_name("pool-val-absorbed.yaml").read_text(encoding="utf-8")))

    def test_absorbed_sample_moves_to_regression_pool(self):
        jud, reg = self._build()
        self.assertEqual([it["id"] for it in jud["issues"]], ["222"])
        self.assertEqual(jud["role"], "judgment")
        self.assertEqual([it["id"] for it in reg["issues"]], ["111"])
        self.assertEqual(reg["role"], "regression")
        self.assertEqual(reg["issues"][0]["absorbed_case"], "VLLM-ASC-111")
        self.assertEqual(jud["absorption"]["absorbed"], 1)

    def test_text_mention_is_not_absorption(self):
        _jud, reg = self._build()
        self.assertEqual([it["id"] for it in reg["issues"]], ["111"],
                         "正文提到 issue 号不算吸收，只有 case 实名算")

    def test_unmatched_prefix_is_reported_not_read_as_nothing_absorbed(self):
        out = self.root / ".s2-replay" / "arena" / "pool-nope.yaml"
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = ea.build_pool(self.root, "eval/s2/pool.yaml", "nope", "selection", False, str(out),
                               case_prefix="ZZZ-NOPE")
        self.assertEqual(rc, 0)
        self.assertIn("没有匹配到任何 case 文件", err.getvalue(),
                      "前缀一条 case 都没匹配到时要明说，不能与「没有样本被吸收」同形")
        ab = yaml.safe_load(out.read_text(encoding="utf-8"))["absorption"]
        self.assertEqual((ab["cases_in_kb"], ab["cases_with_prefix"], ab["absorbed"]), (2, 0, 0))

    def test_stats_records_role_and_gate_refuses_regression(self):
        _jud, _reg = self._build()
        (self.root / ".s2-replay" / "111.result.yaml").write_text("tier2_hit: true\n", encoding="utf-8")
        arena = self.root / ".s2-replay" / "arena"
        reg_file = arena / "pool-val-absorbed.yaml"
        with contextlib.redirect_stdout(io.StringIO()):
            rc = ea.cmd_stats(self.root, reg_file)
        self.assertEqual(rc, 0)
        s = yaml.safe_load((arena / "stats-val-absorbed.yaml").read_text(encoding="utf-8"))
        self.assertEqual(s["role"], "regression")
        f1, f2 = self.root / "a.yaml", self.root / "b.yaml"
        for p in (f1, f2):
            p.write_text(yaml.safe_dump(s, allow_unicode=True), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = ea.cmd_gate(self.root, f1, f2, "triage:demo", "EV-TEST", "", 0.1)
        self.assertEqual(rc, 2, "--gate 必须拒绝回归池：自洽样本不进判定")
        self.assertFalse((self.root / ea.IMPACT_REL).exists(), "拒绝时不得写影响账本")


class AbsorptionRuntimeRecheckTest(unittest.TestCase):
    """吸收状态在运行期重判：池建好之后，沉淀闭环仍可能把样本的答案写进知识库。

    那时池测的是背诵而不是检索能力，而 `--gate` 照样会出判词——这是本轮要消掉的假绿。
    三件事必须成立：①`--stats` 每次重算指纹并把结论写进 stats；②`--gate` 在判定时刻自己重算
    （沉淀可能正好落在 `--stats` 与 `--gate` 之间，沿用那份记录就会漏掉），见到不新鲜就拒绝
    出判词，且**不写账本**（账本里的复用计数不得被一次作废运行推高，否则误判一次就永久收紧
    阈值）；③池文件没有指纹（旧池、手写池）时**不拦**，但必须说明"无法校验"——"没有校验"与
    "校验通过"混淆，诚实退化就退化成静默放行。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        d = self.root / "eval" / "s2"
        d.mkdir(parents=True)
        (d / "pool.yaml").write_text("""\
calibration:
- issue: 511
  split: selection
  expected: {namespace: inference/vllm-ascend, category: interrupt, fix_commit: "PR #1"}
- issue: 512
  split: selection
  expected: {namespace: inference/vllm-ascend, category: interrupt, fix_commit: "PR #2"}
""", encoding="utf-8")
        (self.root / ".s2-replay").mkdir(parents=True, exist_ok=True)
        for iid in ("511", "512"):
            (self.root / ".s2-replay" / f"{iid}.result.yaml").write_text(
                "namespace: inference/vllm-ascend\nrouting_ok: true\ntier2_hit: false\n"
                "root_cause_ok: true\n", encoding="utf-8")

    def _build(self):
        out = self.root / ".s2-replay" / "arena" / "pool-r.yaml"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ea.build_pool(self.root, "eval/s2/pool.yaml", "r", "selection",
                                           False, str(out)), 0)
        return out

    def _stats(self, pool_file, name):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ea.cmd_stats(self.root, pool_file), 0)
        return yaml.safe_load(pool_file.with_name(f"stats-{name}.yaml").read_text(encoding="utf-8"))

    def _plant_case(self, iid):
        """把池内某条样本的答案"沉淀"进知识库：case 文件名用它的 issue 号。"""
        d = self.root / "knowledge" / "inference" / "vllm-ascend" / "interrupt"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"VLLM-ASC-{iid}.yaml").write_text("- id: x\n", encoding="utf-8")

    def _write(self, path, doc):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return path

    def test_stats_writes_recheck_and_newly_absorbed(self):
        pf = self._build()
        rc1 = self._stats(pf, "r")["absorption_recheck"]
        self.assertTrue(rc1["checked"], "建池时写的指纹必须能在 --stats 里用")
        self.assertFalse(rc1["stale"])
        self.assertEqual(rc1["newly_absorbed"], [])
        self._plant_case("511")
        rc2 = self._stats(pf, "r")["absorption_recheck"]
        self.assertTrue(rc2["stale"], "样本答案进库后池必须被判成不新鲜")
        self.assertNotEqual(rc2["rev_pool"], rc2["rev_now"])
        self.assertEqual(rc2["newly_absorbed"], ["511"])

    def test_stale_pool_makes_gate_refuse_and_write_no_ledger(self):
        pf = self._build()
        self._stats(pf, "r")
        self._plant_case("511")
        s = self._stats(pf, "r")
        f1 = self._write(self.root / "a.yaml", s)
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = ea.cmd_gate(self.root, f1, f1, "triage:demo", "EV-TEST", "", 0.1)
        self.assertEqual(rc, 3, "池不新鲜必须拒绝出判词（不是 reject，是判词作废）")
        self.assertIn("511", err.getvalue(), "要说清是哪条样本进了库，否则无法定位")
        self.assertFalse((self.root / ea.IMPACT_REL).exists(),
                         "判词作废时不得写账本：复用计数不得被作废运行推高")

    def test_gate_rechecks_at_decision_time_not_from_stale_stats(self):
        """池在 `--stats` 之后才变旧：判定时刻必须重算，不沿用那份旧读数。

        这是 `--stats` 与 `--gate` 之间的窗口——stats 里还写着"不新鲜为假"，而沉淀在那之后
        把样本的答案写进了库。沿用记录就会照常出判词并推高复用计数。
        """
        pf = self._build()
        s = self._stats(pf, "r")
        self.assertFalse(s["absorption_recheck"]["stale"])
        f1 = self._write(self.root / "a.yaml", s)
        self._plant_case("512")                      # 落在这个窗口里
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = ea.cmd_gate(self.root, f1, f1, "triage:demo", "EV-TEST", "", 0.1)
        self.assertEqual(rc, 3, "stats 之后变旧也必须拒绝：新鲜度以判定时刻为准")
        self.assertIn("512", err.getvalue())
        self.assertFalse((self.root / ea.IMPACT_REL).exists())

    def test_gate_recomputes_without_vectors_from_recorded_ids(self):
        """池里一条 replay 结果都没有时，判定时刻仍要能按 stats 记下的行 id 重算。

        逐条向量是配对检验的输入，没跑 replay 的样本不在向量里；拿向量当行集合重算，指纹
        会算成空字符串的哈希，把一份本来有效的池误判成不新鲜——假过期与真过期的读数长得
        一样，而这一池根本没被吸收。
        """
        for iid in ("511", "512"):
            (self.root / ".s2-replay" / f"{iid}.result.yaml").unlink()
        pf = self._build()
        s = self._stats(pf, "r")
        self.assertEqual(s["issues"], [], "没跑 replay 时不该有逐条向量")
        self.assertEqual(s["judged_ids"], ["511", "512"], "行集合要单独记，不能靠向量推")
        self.assertFalse(s["absorption_recheck"]["stale"])
        f1 = self._write(self.root / "a.yaml", s)
        self._plant_case("512")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = ea.cmd_gate(self.root, f1, f1, "triage:demo", "EV-TEST", "", 0.1)
        self.assertEqual(rc, 3, "没有向量也要按行 id 重算，该拒就拒")
        self.assertIn("512", err.getvalue())
        self.assertNotIn("e3b0c44298fc", err.getvalue(),
                         "空字符串的哈希说明行集合取错了（假过期）")

    def test_stats_without_judged_ids_says_it_cannot_recheck(self):
        """本字段落地前的 stats 有指纹、没行集合：说明"判定时刻无法重算"，不假装校验过。"""
        pf = self._build()
        s = self._stats(pf, "r")
        s.pop("judged_ids")
        f1 = self._write(self.root / "a.yaml", s)
        self._plant_case("512")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = ea.cmd_gate(self.root, f1, f1, "triage:demo", "EV-TEST", "", 0.1)
        self.assertEqual(rc, 0, "算不了就沿用 --stats 的读数并写明，不因此改变判词")
        self.assertIn("无法重算", err.getvalue())

    def test_pool_without_fingerprint_passes_as_unchecked(self):
        rows = [{"id": "511", "expected_ns": "inference/vllm-ascend",
                 "category": "interrupt", "fix_ref": ""}]
        pf = self._write(self.root / ".s2-replay" / "arena" / "pool-old.yaml",
                         {"name": "old", "split": "selection", "role": "judgment", "issues": rows})
        s = self._stats(pf, "old")
        self.assertFalse(s["absorption_recheck"]["checked"])
        self.assertFalse(s["absorption_recheck"]["stale"], "没有指纹不等于不新鲜")
        f1 = self._write(self.root / "a.yaml", s)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = ea.cmd_gate(self.root, f1, f1, "triage:demo", "EV-TEST", "", 0.1)
        self.assertEqual(rc, 0, "旧池应仍可判；未校验只记进账本，不拦")
        self.assertTrue((self.root / ea.IMPACT_REL).exists())


class HeldOutSkipTest(unittest.TestCase):
    """held_out（终判集）不进判定：--stats 不读它的 result、不进指标、不进逐条向量。

    此前这个键只出现在建池与结构校验里，"不参与 gate 决策"的声明只在 `--split selection`
    的默认参数下侥幸成立；用 `--split all` 建池时它会进统计与配对。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / ".s2-replay").mkdir(parents=True, exist_ok=True)
        for iid in ("511", "512", "599"):
            (self.root / ".s2-replay" / f"{iid}.result.yaml").write_text(
                "namespace: inference/vllm-ascend\nrouting_ok: true\ntier2_hit: true\n"
                "root_cause_ok: true\n", encoding="utf-8")

    def test_held_out_row_is_skipped_and_not_paired(self):
        rows = [{"id": "511", "expected_ns": "inference/vllm-ascend", "category": "interrupt",
                 "fix_ref": ""},
                {"id": "512", "expected_ns": "inference/vllm-ascend", "category": "interrupt",
                 "fix_ref": ""},
                {"id": "599", "expected_ns": "inference/vllm-ascend", "category": "interrupt",
                 "fix_ref": "", "held_out": True}]
        pf = self.root / ".s2-replay" / "arena" / "pool-h.yaml"
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(yaml.safe_dump({
            "name": "h", "split": "all", "role": "judgment",
            "absorption": {"case_prefix": "VLLM-ASC"},
            "absorption_rev": ea.absorption_rev(ea.judged_rows(rows), ea.case_index(self.root)),
            "issues": rows}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ea.cmd_stats(self.root, pf), 0)
        s = yaml.safe_load((pf.parent / "stats-h.yaml").read_text(encoding="utf-8"))
        self.assertEqual(s["issues_total"], 3)
        self.assertEqual(s["held_out_skipped"], 1)
        self.assertEqual(s["issues_scored"], 2)
        self.assertEqual([v["id"] for v in s["issues"]], ["511", "512"])
        self.assertTrue(all(v["held_out"] is False for v in s["issues"]))
        self.assertNotIn("599", ea.vectors(s))
        other = dict(s, issues=[dict(v, hit=False) for v in s["issues"]])
        self.assertEqual(ea.decide(s, other, 0.1)["paired"]["n_common"], 2)
        # held_out 行不进指纹：终判子集本来就不进判定，把它算进去会造出假过期
        # （同一份池两边算出不同指纹，--gate 会拒绝一份本来有效的判定）。
        self.assertTrue(s["absorption_recheck"]["checked"])
        self.assertFalse(s["absorption_recheck"]["stale"])


ND_POOL = """\
name: pool-nd
split: selection
issues:
  - {id: "101", expected_ns: "inference/vllm-ascend", fix_ref: "PR#1"}
  - {id: "102", expected_ns: "inference/vllm-ascend", fix_ref: "PR#2"}
  - {id: "103", expected_ns: "", fix_ref: "", non_diagnostic: "正文只有环境信息，没有可判别症状"}
"""

ND_POOL_UNMARKED = """\
name: pool-nd
split: selection
issues:
  - {id: "101", expected_ns: "inference/vllm-ascend", fix_ref: "PR#1"}
  - {id: "102", expected_ns: "inference/vllm-ascend", fix_ref: "PR#2"}
  - {id: "103", expected_ns: "", fix_ref: ""}
"""


class NonDiagnosticRowTest(unittest.TestCase):
    """非诊断样本（输入里没有可判别信号）不进命中率分母与配对。

    文档 docs/mechanism/eval-arena.md §3 早就写了这条口径，但全仓没有读取方——与 held_out
    同一类"说了没做"。这里钉住四件事：显式标注→单列并剔出一切指标与指纹行集合；没标注的行
    照旧参与（只认标注，不从正文猜）；手写 stats 带着这一行时配对也滤掉；--build-pool 把
    校准集行上的标注原样带进池行。
    """

    def _stats(self, results, pool=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        arena = root / ".s2-replay" / "arena"
        arena.mkdir(parents=True)
        (arena / "pool-nd.yaml").write_text(pool or ND_POOL, encoding="utf-8")
        for iid, text in results.items():
            (root / ".s2-replay" / f"{iid}.result.yaml").write_text(text, encoding="utf-8")
        self.assertEqual(ea.cmd_stats(root, arena / "pool-nd.yaml"), 0, "cmd_stats 应成功")
        return yaml.safe_load((arena / "stats-pool-nd.yaml").read_text(encoding="utf-8"))

    def test_marked_row_is_singled_out_and_not_scored(self):
        s = self._stats({"101": NEW_STYLE, "102": OLD_STYLE, "103": OLD_STYLE})
        self.assertEqual([r["id"] for r in s["non_diagnostic_rows"]], ["103"])
        self.assertIn("环境信息", s["non_diagnostic_rows"][0]["reason"], "原因要照原样带出来")
        self.assertEqual(s["metrics"]["hit"]["n"], 2, "命中率分母不含非诊断样本")
        self.assertEqual(s["issues_scored"], 2)
        self.assertEqual([v["id"] for v in s["issues"]], ["101", "102"])
        self.assertNotIn("103", s["judged_ids"], "参与判定的行集合不含非诊断样本")

    def test_unmarked_row_still_counts(self):
        """只认显式标注，不从正文猜：没标注的行照旧进分母。"""
        s = self._stats({"101": NEW_STYLE, "102": NEW_STYLE, "103": OLD_STYLE},
                        pool=ND_POOL_UNMARKED)
        self.assertEqual(s["non_diagnostic_rows"], [])
        self.assertEqual(s["metrics"]["hit"]["n"], 3)

    def test_hand_written_stats_vector_is_filtered(self):
        """手写/旧版 stats 带着这一行：配对也滤掉（--stats 之外的第二道），不给它造出翻转。"""
        s = self._stats({"101": NEW_STYLE, "102": NEW_STYLE})
        other = dict(s, issues=list(s["issues"]) + [
            {"id": "103", "hit": True, "route_ok": True, "rc_match": None, "non_diagnostic": True}])
        self.assertNotIn("103", ea.vectors(other))
        self.assertEqual(ea.decide(s, other, 0.1)["paired"]["n_common"], 2)

    def test_build_pool_carries_the_flag(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        d = root / "eval" / "s2"
        d.mkdir(parents=True)
        (d / "pool.yaml").write_text("""\
calibration:
- issue: 111
  split: selection
  expected: {namespace: inference/vllm-ascend, category: interrupt, fix_commit: "PR #1"}
  non_diagnostic: "正文只有环境信息，没有可判别症状"
- issue: 222
  split: selection
  expected: {namespace: inference/vllm-ascend, category: interrupt, fix_commit: "PR #2"}
""", encoding="utf-8")
        out = root / ".s2-replay" / "arena" / "pool-val.yaml"
        self.assertEqual(
            ea.build_pool(root, "eval/s2/pool.yaml", "val", "selection", False, str(out)), 0)
        pool = yaml.safe_load(out.read_text(encoding="utf-8"))
        rows = {it["id"]: it for it in pool["issues"]}
        self.assertIn("环境信息", str(rows["111"].get("non_diagnostic")))
        self.assertNotIn("non_diagnostic", rows["222"], "没标的行不带这个键")
        # 指纹只算参与判定的行：标了非诊断的那条不进指纹
        self.assertEqual(pool["absorption_rev"],
                         ea.absorption_rev(ea.judged_rows(pool["issues"]), ea.case_index(root)))
        self.assertEqual(len(ea.judged_rows(pool["issues"])), 1)


EV_POOL = """\
name: pool-ev
split: selection
issues:
  - {id: "201", expected_ns: "inference/vllm-ascend", fix_ref: "PR#1"}
  - {id: "202", expected_ns: "inference/vllm-ascend", fix_ref: "PR#2"}
"""


class EvidenceFieldTest(unittest.TestCase):
    """可证伪性（ground_truth）与重放版本（kb_rev）在判定层留痕。

    两处都是同一类"文档写了、判定层不读"：①`ground_truth: none` 的样本（外部没有结论可对照）
    在结算侧 scripts/settle_s2_feedback.py 被跳过，判定侧却只要它写了 `root_cause_ok: true`
    就把"没有真值的猜测"记成"结论一致"，推高结论一致率；②result 里没有"这次回放在哪份知识库
    上跑的"，而一批结果常跨若干次 git pull 才跑完，跨版本混算出来的分数前后不可比。

    这里钉住五件事：none 不进结论一致率分母；字段缺席按旧行为计入（缺席 ≠ none，不得偷偷
    变成 none）；两个字段的条数与 mixed 标记进 stats；--gate 把两侧的读数记进账本；只留痕了
    一部分时不得说成"版本一致"。
    """

    NEW_STYLE = ("namespace: inference/vllm-ascend\nrouting_ok: true\ntier2_hit: false\n"
                 "root_cause_ok: true\n")

    def _stats(self, results, pool=EV_POOL):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        arena = root / ".s2-replay" / "arena"
        arena.mkdir(parents=True)
        (arena / "pool-ev.yaml").write_text(pool, encoding="utf-8")
        for iid, text in results.items():
            (root / ".s2-replay" / f"{iid}.result.yaml").write_text(text, encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ea.cmd_stats(root, arena / "pool-ev.yaml"), 0, "cmd_stats 应成功")
        self.last_stdout = buf.getvalue()
        return root, yaml.safe_load((arena / "stats-pool-ev.yaml").read_text(encoding="utf-8"))

    def test_ground_truth_none_is_not_counted_as_agreement(self):
        _, s = self._stats({
            "201": self.NEW_STYLE + "ground_truth: none\n",
            "202": self.NEW_STYLE + "ground_truth: both\n",
        })
        self.assertEqual(s["ground_truth"]["none"], 1)
        self.assertEqual(s["ground_truth"]["counts"], {"none": 1, "both": 1})
        vec = {v["id"]: v for v in s["issues"]}
        self.assertIsNone(vec["201"]["rc_match"], "无外部结论 = 没有真值，不得记成结论一致")
        self.assertTrue(vec["202"]["rc_match"], "有外部结论的样本照旧对照")
        self.assertEqual(s["metrics"]["rc_match"]["n"], 1, "结论一致率分母剔掉 none 行")
        self.assertEqual(vec["201"]["ground_truth"], "none")

    def test_absent_ground_truth_keeps_old_behavior(self):
        """缺席 ≠ none：没写这个字段的 result 按旧行为计入分母，不得静默变成"整体跳过"。"""
        _, s = self._stats({"201": self.NEW_STYLE, "202": self.NEW_STYLE})
        self.assertEqual(s["ground_truth"]["none"], 0)
        self.assertEqual(s["ground_truth"]["absent"], 2)
        self.assertEqual(s["metrics"]["rc_match"]["n"], 2)
        self.assertIsNone(s["issues"][0]["ground_truth"])

    def test_replay_revs_records_mix_and_warns_in_gate_ledger(self):
        root, s = self._stats({
            "201": self.NEW_STYLE + "kb_rev: 3c3ba14\n",
            "202": self.NEW_STYLE + "kb_rev: d29d450\n",
        })
        self.assertTrue(s["replay_revs"]["mixed"], "两条来自不同版本，必须标成混算")
        self.assertEqual(s["replay_revs"]["counts"], {"3c3ba14": 1, "d29d450": 1})
        self.assertEqual(s["replay_revs"]["absent"], 0)
        pf = root / ".s2-replay" / "arena" / "pool-ev.yaml"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ea.cmd_gate(root, pf.with_name("stats-pool-ev.yaml"),
                                         pf.with_name("stats-pool-ev.yaml"),
                                         "triage:demo", "EV-TEST", "", 0.1), 0)
        led = yaml.safe_load((root / ea.IMPACT_REL).read_text(encoding="utf-8"))
        rec = led["records"][-1]
        self.assertTrue(rec["replay_revs"]["baseline"]["mixed"])
        self.assertEqual(rec["replay_revs"]["baseline"]["counts"],
                         {"3c3ba14": 1, "d29d450": 1})
        self.assertIn("ground_truth", rec, "账本要能事后看出这批样本有没有无真值的行")

    def test_unrecorded_revs_are_not_read_as_one_version(self):
        """一条都没留痕时 mixed 必须是假、absent 记数——不得把"没写"读成"版本一致"。"""
        _, s = self._stats({"201": self.NEW_STYLE, "202": self.NEW_STYLE})
        self.assertFalse(s["replay_revs"]["mixed"])
        self.assertEqual(s["replay_revs"]["counts"], {})
        self.assertEqual(s["replay_revs"]["absent"], 2)

    def test_partly_recorded_revs_are_not_called_consistent(self):
        """只留痕了一部分时不得说"版本一致"：没记的那些无从判断，措辞要带上这个不确定性。"""
        _, s = self._stats({
            "201": self.NEW_STYLE + "kb_rev: 3c3ba14\n",
            "202": self.NEW_STYLE,
        })
        self.assertFalse(s["replay_revs"]["mixed"])
        self.assertEqual(s["replay_revs"]["counts"], {"3c3ba14": 1})
        self.assertEqual(s["replay_revs"]["absent"], 1)
        self.assertIn("已记版本的 1 条一致", self.last_stdout)
        self.assertIn("另有 1 条 result 没记 kb_rev", self.last_stdout)
        self.assertNotIn("重放版本一致", self.last_stdout)
