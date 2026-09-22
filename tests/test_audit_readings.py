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

    def test_self_created_outside_path_is_not_a_dependency(self):
        """命令**自己会写**的仓外暂存件不算依赖（实测 EV-2026-092：判据跑起来 PASS，
        却被报成"依赖已蒸发"，体检因此常年挂着一项无法处理的红）。"""
        import ev_measure as em
        cmd = ("python3 -c \"from pathlib import Path;p=Path('/tmp/check.yaml');"
               "p.unlink(missing_ok=True);p.write_text('a');print(p.read_text())\"")
        self.assertEqual(em.stale_deps(self.root, self._card(cmd)), [])
        # 对照组：同一个仓外路径，命令不写它 → 仍然是依赖蒸发
        self.assertEqual(
            em.stale_deps(self.root, self._card("python3 -c \"print(open('/tmp/check.yaml').read())\"")),
            ["/tmp/check.yaml"])

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


class S2ClipKeepsTriggerParamsTest(unittest.TestCase):
    """夹具裁剪不得吃掉触发参数（实测：guided_decoding 落在被裁中段 → 触发证据不可见）。"""

    def test_middle_trigger_params_are_preserved(self):
        import s2_calibration as sc
        body = "A" * 3000 + "\nguided_decoding=GuidedDecodingParams(json_object=True)\n" + "x" * 5000
        out = sc.clip_text(body, 900)
        self.assertIn("guided_decoding=GuidedDecodingParams", out)
        self.assertLess(len(out), len(body))          # 仍然裁了，不是全量塞回

    def test_short_body_untouched(self):
        import s2_calibration as sc
        self.assertEqual(sc.clip_text("短正文", 900), "短正文")


class S2SampleIndependenceTest(unittest.TestCase):
    """cross 样本的独立性守卫：case 正文引用了这个 issue → 不能算独立的「外部验证」。

    为什么值得单测：这是 `validation_record.consistent` 的唯一来源，错了不会崩、只会虚增
    外部验证权重（与自证同一条纪律）。实测起因：#2723（同签名、有维护者结论）一度被当作
    VLLM-ASC-1767 的合格 cross 样本，但该 case 的 verification.detail 里就写着
    「#2723（同签名，2025-12-15 关闭 COMPLETED）上同一维护者记为…」——结论正是写 case 时
    从它那儿读来的。守卫只挡「正文点名」这一种，半硬，别读成「信息独立」。
    """

    def setUp(self):
        import settle_s2_feedback as ssf
        self.ssf = ssf

    def test_cited_forms_are_detected(self):
        case = {
            "verification": {"detail": "#2723 上同一维护者记为 known issue"},
            "references": ["https://github.com/vllm-project/vllm-ascend/issues/2723"],
            "fix": "见 PR #3967（与本号无关的另一处引用）",
            "diagnosis": [{"step": 1, "note": "对照 pulls/2723 的改动"}],
        }
        self.assertTrue(self.ssf.case_cites_issue(case, 2723))

    def test_uncited_neighbour_is_independent(self):
        case = {"verification": {"detail": "同签名 issue #3979 上维护者给出结论"},
                "references": ["https://github.com/vllm-project/vllm-ascend/issues/1767"]}
        self.assertFalse(self.ssf.case_cites_issue(case, 2723))
        self.assertTrue(self.ssf.case_cites_issue(case, 3979))

    def test_bare_number_is_not_a_citation(self):
        """裸数字不算引用——否则行号 / 版本号 / 容量值会把独立样本误判成非独立。"""
        case = {"root_cause": "num_batch_tokens(2723) 超 MC2 容量", "fix": "见 v0.2723"}
        self.assertFalse(self.ssf.case_cites_issue(case, 2723))


class S2SettleGatesTest(unittest.TestCase):
    """结算的两个闸门：不可证伪的样本不结算；命中但结论不符要能真的记下来（不崩）。

    为什么值得单测：`inconsistent` 是**复审信号**的唯一入口——它出错不会崩、只会安静地不产生信号，
    或者反过来给一条 case 打进它无从反驳的指控。实测两处：① 不可证伪样本（issue 无外部结论）
    一旦结算，会按 root_cause_ok=false 记 inconsistent；② inconsistent 分支本身从未被执行过，
    一跑就 UnboundLocalError（diff 的"改前"值那行在目标里引用了未赋值的 field）。
    """

    def _fixture(self, result: dict, case_extra: dict | None = None):
        import yaml
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "knowledge" / "inference" / "x").mkdir(parents=True)
        (root / ".s2-replay").mkdir()
        case = {"id": "TEST-1", "title": "t", "category": "interrupt", "symptoms": ["s"],
                "quickly_check": {}, "diagnosis": [], "root_cause": "rc", "fix": "f",
                "severity": "benign", "fix_type": "config-change", "confidence": {"score": 0.3}}
        case.update(case_extra or {})
        (root / "knowledge" / "inference" / "x" / "TEST-1.yaml").write_text(
            yaml.safe_dump({"cases": [case]}, allow_unicode=True), encoding="utf-8")
        (root / ".s2-replay" / "4242.result.yaml").write_text(
            yaml.safe_dump(result, allow_unicode=True), encoding="utf-8")
        return root

    def test_unfalsifiable_sample_is_not_settled(self):
        import settle_s2_feedback as ssf
        root = self._fixture({"hit_case": "TEST-1", "tier2_hit": True, "root_cause_ok": False,
                              "ground_truth": "none"})
        ssf.settle(root, root / "state.json", apply=False, migrate_from=Path("/nonexistent"))
        text = (root / "knowledge" / "inference" / "x" / "TEST-1.yaml").read_text(encoding="utf-8")
        self.assertNotIn("validation_record", text)

    def test_inconsistent_is_recorded_without_crashing(self):
        import settle_s2_feedback as ssf
        root = self._fixture({"hit_case": "TEST-1", "tier2_hit": True, "root_cause_ok": False,
                              "ground_truth": "fix-merged"})
        ssf.settle(root, root / "state.json", apply=True, migrate_from=Path("/nonexistent"))
        text = (root / "knowledge" / "inference" / "x" / "TEST-1.yaml").read_text(encoding="utf-8")
        self.assertIn("inconsistent: 1", text)
        self.assertIn("consistent: 0", text)

    def test_cited_sample_lands_on_self_consistent(self):
        import settle_s2_feedback as ssf
        root = self._fixture({"hit_case": "TEST-1", "tier2_hit": True, "root_cause_ok": True,
                              "ground_truth": "maintainer-conclusion"},
                             case_extra={"verification": {"detail": "同签名 issue #4242 上维护者给出结论"}})
        ssf.settle(root, root / "state.json", apply=True, migrate_from=Path("/nonexistent"))
        text = (root / "knowledge" / "inference" / "x" / "TEST-1.yaml").read_text(encoding="utf-8")
        self.assertIn("self_consistent: 1", text)
        self.assertIn("consistent: 0", text)


class BacklogPredicateTest(unittest.TestCase):
    """「待合入积压」的分子只有一个口径。

    为什么值得单测：它原先有两份实现——`ev_proposal --waterline` 扫全卡文本、
    `ev_board_data.collect_stats` 只扫决策链结论。同一时刻两个读数不等（实测 0 张 vs 8 张），
    而技能让 agent 读前者、面板与体检显示后者，两处都自称是判据 backlog_over 的分子。
    读数不等不会崩，只会让"该不该停产"这个动作在两处得到不同答案。
    """

    CARD = """id: EV-2026-950
layer: L2
title: 示例
status: validated
authorization: review
dimension: process
created_at: 2026-09-22
source_signals:
  - signal: coverage_gap
    evidence: "上游 issue #14363 复现"
    trajectory: [t]
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
actual_cost: {tokens: 0, source: estimate, note: n}
decisions:
  - who: agent
    when: 2026-09-22
    type: proposal
    conclusion: p
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "proposals" / "ideas").mkdir(parents=True)
        self.card = self.root / "proposals" / "ideas" / "EV-2026-950.yaml"
        self.card.write_text(self.CARD, encoding="utf-8")

    def test_board_and_waterline_share_the_predicate(self):
        import ev_proposal as ep
        text = self.card.read_text(encoding="utf-8")
        ideas = ebd.collect_ideas(self.root)
        card = [c for c in ideas if c.get("id") == "EV-2026-950"][0]
        # 同一段文本，两处判定必须一致（issue 号也算指针：松匹配的已知方向）
        self.assertEqual(card["has_pointer"], ep.has_merge_pointer(text))
        stats = ebd.collect_stats(ideas)
        self.assertEqual(stats["backlog_count"], 0)

    def test_card_without_any_ref_counts_as_backlog(self):
        self.card.write_text(self.CARD.replace("上游 issue #14363 复现", "复现"),
                             encoding="utf-8")
        stats = ebd.collect_stats(ebd.collect_ideas(self.root))
        self.assertEqual(stats["backlog_count"], 1)
