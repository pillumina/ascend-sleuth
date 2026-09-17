"""三处「读数口径」回归：死引用不过报、信号口径统一、归因通道两套词表都认。

为什么值得单测：这三处都是**判据/面板的分子**，错了不会崩、只会给出一个看起来正常的数——
本轮实测代价分别是：死引用 6 个里 4 个是假红（真腐烂只有 2 个）；同一面板里同一概念两个数
（40 vs 35）；"硬归因"这条腿从未有过数据（4 条归因事件、0 条被计）。读数错 = 决策错。
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import component_tally as ct  # noqa: E402
import ev_board_data as ebd  # noqa: E402


class DeadRefsTest(unittest.TestCase):
    """scan_dead_refs：只报"真腐烂"，不报相对路径 / 仓外路径 / 否定语境的路径。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "alive.md").write_text("x", encoding="utf-8")
        (self.root / "skills" / "diagnose" / "references").mkdir(parents=True)
        (self.root / "skills" / "diagnose" / "references" / "trace.md").write_text("x", encoding="utf-8")

    def dead(self, text):
        return ebd.scan_dead_refs(self.root, {"text": text})

    def test_real_rot_is_reported(self):
        self.assertEqual(self.dead("见 `docs/removed.md` 的说明"), ["docs/removed.md"])

    def test_relative_path_reference_is_not_rot(self):
        """`references/trace.md` 的真身在 skills/diagnose/references/ —— 按那个 skill 视角写的。"""
        self.assertEqual(self.dead("新增 `references/trace.md`"), [])

    def test_out_of_repo_path_is_not_rot(self):
        """父目录不在检出里 → 不是"被删"，是仓外/上游路径。"""
        self.assertEqual(self.dead("上游仓 `vendor/foo/bar.md`"), [])

    def test_negation_context_is_not_rot(self):
        """卡在陈述"该路径不存在"时，不能读成死指针。"""
        self.assertEqual(self.dead("真实生成物是 `_summary-index.yaml`，与 `references/_index.yaml` 均不存在"),
                         [])

    def test_existing_path_is_not_rot(self):
        self.assertEqual(self.dead("见 `docs/alive.md`"), [])


class SignalShareTest(unittest.TestCase):
    """by_signal 必须用全量信号，与体检判决（signals_all）同口径。"""

    def test_by_signal_counts_all_signals_not_first_three(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "proposals" / "ideas").mkdir(parents=True)
        card = """\
id: EV-2026-901
layer: L2
title: t
status: validated
authorization: review
dimension: evolvability
created_at: 2026-09-17
source_signals:
  - {signal: process_friction, evidence: a, trajectory: [x]}
  - {signal: process_friction, evidence: b, trajectory: [x]}
  - {signal: process_friction, evidence: c, trajectory: [x]}
  - {signal: process_friction, evidence: d, trajectory: [x]}
hypothesis: h
predicted_effect:
  metric: m
  from: a
  to: b
  measure: {command: "true", expect_exit: 0}
validation: {method: scan_review, baseline: b, success_criteria: s, rollback: r}
gate: {condition: c}
risk: low
principle_refs: [10]
decisions:
  - {who: agent, when: 2026-09-17, type: decision, conclusion: "随 PR #1 合入"}
"""
        (root / "proposals" / "ideas" / "EV-2026-901.yaml").write_text(card, encoding="utf-8")
        st = ebd.collect_stats(ebd.collect_ideas(root))
        # 一张卡、4 条同族信号 → 按卡去重记 1（不是 4，也不是被 [:3] 截断后的 3）
        self.assertEqual(st["by_signal"].get("process_friction"), 1)
        self.assertEqual(st["top_signal_share"], 1.0)


class AttributionVocabularyTest(unittest.TestCase):
    """component_tally：生产端写 attribution_kind，消费端必须认，否则硬归因恒为 0。"""

    def test_execution_kind_counts_as_hard(self):
        self.assertTrue(ct.is_hard({"source": "trace", "attribution_kind": "execution"}))
        self.assertFalse(ct.is_hard({"source": "trace", "attribution_kind": "improvement"}))
        self.assertFalse(ct.is_hard({"source": "trace", "attribution_kind": "design"}))

    def test_legacy_verdict_still_counts(self):
        self.assertTrue(ct.is_hard({"source": "trace", "verdict": "execution_error"}))

    def test_aggregate_puts_execution_kind_in_failure_cluster(self):
        entries = [
            {"source": "trace", "trace": "t1.yaml", "component": "skill:diagnose",
             "attribution_kind": "execution", "verdict": None},
            {"source": "trace", "trace": "t1.yaml", "component": "skill:diagnose",
             "attribution_kind": "design", "verdict": None},
        ]
        agg = ct.aggregate(entries)
        self.assertEqual(agg["skill:diagnose"]["trace_mis"], 1)
        self.assertEqual(agg["skill:diagnose"]["s2_candidate"], 0)


if __name__ == "__main__":
    unittest.main()


class StaleMeasureDepTest(unittest.TestCase):
    """判据依赖只认「读取语境」——实测两类假阳性都要挡住（它们曾进健康判据的读数）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "alive.md").write_text("x", encoding="utf-8")

    def _card(self, cmd):
        return {"predicted_effect": {"measure": {"command": cmd, "expect_exit": 0}}}

    def test_missing_read_file_is_stale(self):
        import ev_measure as em
        self.assertEqual(em.stale_deps(self.root, self._card("python3 -c \"open('docs/gone.md')\"")),
                         ["docs/gone.md"])

    def test_existing_read_file_is_not_stale(self):
        import ev_measure as em
        self.assertEqual(em.stale_deps(self.root, self._card("cat docs/alive.md")), [])

    def test_noise_sample_list_is_not_a_dependency(self):
        """命令里当「期望不存在的噪音样本」列出的字符串不是依赖（实测 EV-2026-091 就是这么被误判的）。"""
        import ev_measure as em
        cmd = "python3 -c \"noise=['CMakeLists.txt','autofuse/README.md'];print(noise)\""
        self.assertNotIn("autofuse/README.md", em.stale_deps(self.root, self._card(cmd)))

    def test_string_literal_comparison_is_not_a_dependency(self):
        """代码里当字面量比较的路径不是依赖（实测 EV-2026-094：`'compat-matrices/cann-hdk.yaml' in p`）。"""
        import ev_measure as em
        cmd = "python3 -c \"p=open('docs/alive.md').read();named='compat-matrices/cann-hdk.yaml' in p\""
        self.assertNotIn("compat-matrices/cann-hdk.yaml", em.stale_deps(self.root, self._card(cmd)))

    def test_runtime_paths_count_as_dependencies(self):
        """运行时件（traces/、/tmp）缺失同样是依赖蒸发——判据跑不起来就是跑不起来。"""
        import ev_measure as em
        self.assertEqual(
            em.stale_deps(self.root, self._card("python3 scripts/x.py traces/gone.md")),
            ["traces/gone.md"])

    def test_script_argument_path_is_a_dependency(self):
        import ev_measure as em
        self.assertEqual(
            em.stale_deps(self.root, self._card("python3 scripts/report_lint.py docs/gone.md")),
            ["docs/gone.md"])

    def test_declared_unmeasurable_has_no_deps(self):
        import ev_measure as em
        self.assertEqual(em.stale_deps(self.root, {"predicted_effect": {"measure": {"command": None, "reason": "r"}}}), [])


class TargetComponentGateTest(unittest.TestCase):
    """target_component 对生效日之后的卡强制——它是同组件先例咨询的键。"""

    def _run(self, created):
        import subprocess
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        d = root / "proposals" / "ideas"
        d.mkdir(parents=True)
        (d / "EV-2026-901.yaml").write_text(f"""\
id: EV-2026-901
layer: L2
title: t
status: in_experiment
authorization: review
dimension: evolvability
created_at: {created}
source_signals:
  - {{signal: process_friction, evidence: e, trajectory: [traces/x.yaml]}}
hypothesis: h
predicted_effect:
  metric: m
  from: a
  to: b
  measure: {{command: "true", expect_exit: 0}}
validation: {{method: scan_review, baseline: b, success_criteria: s, rollback: r}}
gate: {{condition: c}}
risk: low
principle_refs: [10]
decisions:
  - {{who: agent, when: 2026-09-17, type: proposal, conclusion: p}}
""", encoding="utf-8")
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_proposals.py"), "--check",
                            "--root", str(root)], capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def test_card_after_cutover_requires_component(self):
        rc, out = self._run("2026-09-18")
        self.assertNotEqual(rc, 0)
        self.assertIn("target_component", out)

    def test_card_before_cutover_is_exempt(self):
        rc, out = self._run("2026-09-10")
        self.assertNotIn("target_component", out, out[-300:])


class DeadRefsSkipDecisionsTest(unittest.TestCase):
    """decisions 是只追加的审计链：那里的历史路径不算「腐烂」（判据 action 与 append-only 规则冲突过）。"""

    def test_path_only_in_decisions_is_not_rot(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "docs").mkdir()
        doc = {"id": "EV-2026-901", "title": "t",
               "decisions": [{"who": "agent", "conclusion": "当时引用的是 `docs/gone.md` §4（现已迁移）"}]}
        self.assertEqual(ebd.scan_dead_refs(root, doc), [])

    def test_path_in_other_fields_is_still_rot(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "docs").mkdir()
        doc = {"id": "EV-2026-902", "title": "t", "hypothesis": "见 `docs/gone.md`"}
        self.assertEqual(ebd.scan_dead_refs(root, doc), ["docs/gone.md"])
