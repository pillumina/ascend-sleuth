"""ev_proposal 的合入指针回写与候选水位读数（本卡机制修正）。

护的是两件会直接把演进闭环的读数带偏的事：
① **回写指针**：判据「待合入积压」数的是"已验证但没有合入指针的卡"。指针只能写进卡文本，
   而从来没有机制保证它被写——实测一批 7 张卡随同一个 PR 合入 main、7 张全部无指针，判据读成
   "未合入"。回写因此必须是脚本（保留注释、只追加、可重复执行）。
② **水位读数**：设计处把「候选水位上限」标为蓝图态、启用条件是"积压真实发生（>20 在池）"；
   该条件早已满足，而 skill 正文那句"超限只记信号不产卡"既无数值也无读数。水位是一条读数 + 退出码。
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ev_proposal as ep  # noqa: E402

CARD = """\
# 一张带注释的卡（回写必须保留注释与既有内容）
id: EV-2026-900
layer: L2
title: 示例
status: validated
authorization: review
dimension: evolvability
created_at: 2026-09-17
source_signals:
  - signal: process_friction
    evidence: "示例"
    trajectory:
      - "traces/x.yaml"
hypothesis: 示例
predicted_effect:
  metric: m
  from: a
  to: b
  measure:
    command: "true"
    expect_exit: 0
validation:
  method: scan_review
  baseline: b
  success_criteria: s
  rollback: r
gate:
  condition: c
risk: low
principle_refs: [10]
decisions:
  - who: agent
    when: 2026-09-17
    type: proposal
    conclusion: "产卡"
"""


class MarkMergedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "proposals" / "ideas").mkdir(parents=True)
        self.card = self.root / "proposals" / "ideas" / "EV-2026-900.yaml"
        self.card.write_text(CARD, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_appends_pointer_and_preserves_everything(self):
        rc = ep.mark_merged(self.root, "242", [], all_pending=True, dry_run=False)
        self.assertEqual(rc, 0)
        text = self.card.read_text(encoding="utf-8")
        self.assertIn("PR #242", text)
        self.assertTrue(text.startswith("# 一张带注释的卡"))          # 注释保留
        self.assertIn('conclusion: "产卡"', text)                      # 既有内容保留
        doc = ep.load_yaml(self.card)
        self.assertEqual(doc["decisions"][-1]["type"], "action")       # 结构仍是合法卡
        self.assertEqual(doc["id"], "EV-2026-900")

    def test_idempotent(self):
        ep.mark_merged(self.root, "242", [], all_pending=True, dry_run=False)
        before = self.card.read_text(encoding="utf-8")
        ep.mark_merged(self.root, "242", [], all_pending=True, dry_run=False)
        self.assertEqual(before, self.card.read_text(encoding="utf-8"))

    def test_dry_run_writes_nothing(self):
        before = self.card.read_text(encoding="utf-8")
        rc = ep.mark_merged(self.root, "242", [], all_pending=True, dry_run=True)
        self.assertEqual(rc, 0)
        self.assertEqual(before, self.card.read_text(encoding="utf-8"))

    def test_only_validated_cards_are_pending(self):
        """已 rejected / in_experiment 的卡不进 --all-pending（它们不是"待合入"）。"""
        d = ep.load_yaml(self.card)
        d["status"] = "rejected"
        ep.write_text_lf(self.card, __import__("yaml").safe_dump(d, allow_unicode=True, sort_keys=False),
                         encoding="utf-8")
        rc = ep.mark_merged(self.root, "242", [], all_pending=True, dry_run=False)
        self.assertEqual(rc, 0)
        self.assertNotIn("PR #242", self.card.read_text(encoding="utf-8"))

    def test_inserts_inside_decisions_when_other_keys_follow(self):
        """decisions 之后还有别的顶层键时，指针插进 decisions 块末尾（不是文件末尾）。"""
        self.card.write_text(CARD + "template_index: [1, 2]\n", encoding="utf-8")
        rc = ep.mark_merged(self.root, "242", ["EV-2026-900"], all_pending=False, dry_run=False)
        self.assertEqual(rc, 0)
        doc = ep.load_yaml(self.card)
        self.assertEqual(doc["decisions"][-1]["type"], "action")          # YAML 仍合法
        self.assertEqual(doc["template_index"], [1, 2])                    # 后面的键没被吃掉
        self.assertIn("PR #242", self.card.read_text(encoding="utf-8"))

    def test_unknown_card_is_an_error(self):
        self.assertEqual(ep.mark_merged(self.root, "242", ["EV-9999-999"], False, False), 2)


class WaterlineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "proposals" / "ideas").mkdir(parents=True)
        for i in range(3):
            p = self.root / "proposals" / "ideas" / f"EV-2026-90{i}.yaml"
            p.write_text(CARD.replace("EV-2026-900", f"EV-2026-90{i}"), encoding="utf-8")
        # 一张已带指针的卡：不应计入待回写
        p = self.root / "proposals" / "ideas" / "EV-2026-909.yaml"
        p.write_text(CARD.replace("EV-2026-900", "EV-2026-909").replace(
            'conclusion: "产卡"', 'conclusion: "随 PR #99 合入"'), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_pending_without_pointer(self):
        self.assertEqual(ep.waterline(self.root, 20), 0)   # 3 < 20 → 未超限
        self.assertEqual(ep.waterline(self.root, 3), 1)    # 3 >= 3 → 超限（退 1）
        self.assertEqual(ep.waterline(self.root, 4), 0)


if __name__ == "__main__":
    unittest.main()


class ImpactViewTest(unittest.TestCase):
    """同组件先例视图：按组件聚合尝试与结局（有否决/换方向的组件才让"先例咨询"有信息量）。"""

    def _card(self, cid, status, component):
        return (CARD.replace("EV-2026-900", cid)
                    .replace("layer: L2", f"layer: L2\ntarget_component: {component}")
                    .replace("status: validated", f"status: {status}"))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        d = self.root / "proposals" / "ideas"
        d.mkdir(parents=True)
        (d / "EV-2026-901.yaml").write_text(self._card("EV-2026-901", "validated", "scripts/same.py"),
                                            encoding="utf-8")
        (d / "EV-2026-902.yaml").write_text(self._card("EV-2026-902", "rejected", "scripts/same.py"),
                                            encoding="utf-8")
        (d / "EV-2026-903.yaml").write_text(self._card("EV-2026-903", "validated", "scripts/other.py"),
                                            encoding="utf-8")

    def test_aggregates_by_target_component_and_flags_divergence(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ep.impact(self.root)
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("scripts/same.py：2 次", out)
        self.assertIn("有结局分歧", out)
        self.assertIn("1 个有结局分歧", out)

    def test_unknown_component_exits_2(self):
        self.assertEqual(ep.impact(self.root, component="不存在的组件"), 2)


class ImpactViewTest(unittest.TestCase):
    """同组件先例视图：按组件聚合尝试与结局（有否决/换方向的组件才让"先例咨询"有信息量）。"""

    def _card(self, cid, status, component):
        return (CARD.replace("EV-2026-900", cid)
                    .replace("layer: L2", f"layer: L2\ntarget_component: {component}")
                    .replace("status: validated", f"status: {status}"))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        d = self.root / "proposals" / "ideas"
        d.mkdir(parents=True)
        (d / "EV-2026-901.yaml").write_text(self._card("EV-2026-901", "validated", "scripts/same.py"),
                                            encoding="utf-8")
        (d / "EV-2026-902.yaml").write_text(self._card("EV-2026-902", "rejected", "scripts/same.py"),
                                            encoding="utf-8")
        (d / "EV-2026-903.yaml").write_text(self._card("EV-2026-903", "validated", "scripts/other.py"),
                                            encoding="utf-8")

    def test_aggregates_by_target_component_and_flags_divergence(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ep.impact(self.root)
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("scripts/same.py：2 次", out)
        self.assertIn("有结局分歧", out)
        self.assertIn("1 个有结局分歧", out)

    def test_unknown_component_exits_2(self):
        self.assertEqual(ep.impact(self.root, component="不存在的组件"), 2)


class ImpactViewTest(unittest.TestCase):
    """同组件先例视图：按组件聚合尝试与结局（有否决/换方向的组件才让"先例咨询"有信息量）。"""

    def _card(self, cid, status, component):
        return (CARD.replace("EV-2026-900", cid)
                    .replace("layer: L2", f"layer: L2\ntarget_component: {component}")
                    .replace("status: validated", f"status: {status}"))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        d = self.root / "proposals" / "ideas"
        d.mkdir(parents=True)
        (d / "EV-2026-901.yaml").write_text(self._card("EV-2026-901", "validated", "scripts/same.py"),
                                            encoding="utf-8")
        (d / "EV-2026-902.yaml").write_text(self._card("EV-2026-902", "rejected", "scripts/same.py"),
                                            encoding="utf-8")
        (d / "EV-2026-903.yaml").write_text(self._card("EV-2026-903", "validated", "scripts/other.py"),
                                            encoding="utf-8")

    def test_aggregates_by_target_component_and_flags_divergence(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ep.impact(self.root)
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("scripts/same.py：2 次", out)
        self.assertIn("有结局分歧", out)
        self.assertIn("1 个有结局分歧", out)

    def test_unknown_component_exits_2(self):
        self.assertEqual(ep.impact(self.root, component="不存在的组件"), 2)


class MarkMergedFromPrsTest(unittest.TestCase):
    """按 PR 逐卡匹配回写：不用一个号刷全部；插入点与缩进跟卡自身风格走。"""

    CARD = """id: {cid}
layer: L2
target_component: scripts/x.py
title: t
status: validated
authorization: review
dimension: evolvability
created_at: 2026-09-17
source_signals:
  - {{signal: process_friction, evidence: e, trajectory: [t]}}
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
{dec}{tail}"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "proposals" / "ideas").mkdir(parents=True)

    def _write(self, cid, indent, tail=""):
        d = " " * indent
        dec = (f"{d}- who: agent\n{d}  when: 2026-09-17\n{d}  type: proposal\n"
               f"{d}  conclusion: p\n")
        (self.root / "proposals" / "ideas" / f"{cid}.yaml").write_text(
            self.CARD.format(cid=cid, dec=dec, tail=tail), encoding="utf-8")

    def _prs(self, body):
        f = self.root / "prs.json"
        f.write_text('[{"number": 77, "title": "batch", "body": "%s"}]' % body, encoding="utf-8")
        return str(f)

    def test_matches_by_pr_body_for_both_indent_styles(self):
        self._write("EV-2026-901", 2)
        self._write("EV-2026-902", 0, tail="template_index: [1, 2]\n")
        rc = ep.mark_merged_from_prs(self.root, 500, dry_run=False,
                                     prs_file=self._prs("含 EV-2026-901 与 EV-2026-902"))
        self.assertEqual(rc, 0)
        for cid in ("EV-2026-901", "EV-2026-902"):
            p = self.root / "proposals" / "ideas" / f"{cid}.yaml"
            doc = ep.load_yaml(p)
            self.assertEqual(doc["decisions"][-1]["type"], "action", cid)
            self.assertIn("PR #77", p.read_text(encoding="utf-8"))
        tail = (self.root / "proposals" / "ideas" / "EV-2026-902.yaml").read_text(encoding="utf-8")
        self.assertIn("template_index: [1, 2]", tail)

    def test_unmatched_cards_are_not_fabricated(self):
        self._write("EV-2026-903", 2)
        self.assertEqual(ep.mark_merged_from_prs(self.root, 500, dry_run=False,
                                                 prs_file=self._prs("别的批，不含卡号")), 0)
        self.assertNotIn("PR #77",
                         (self.root / "proposals" / "ideas" / "EV-2026-903.yaml").read_text(encoding="utf-8"))


class CliWritebackTest(unittest.TestCase):
    """批收尾那条命令的形态：`--mark-merged --from-prs`。

    护两件事：
    ① **免占位号**——批收尾的标准动作是按已合入 PR 逐卡匹配，PR 号由匹配决定；原先 argparse 强制
       要一个 PR 号，于是标准动作要带一个假参数（`--mark-merged 0 --from-prs`），多一处可错的地方；
    ② **--all-pending 的风险要说在读的那一刻**——它把同一个号写给所有待回写卡，混入旧批的卡就是
       假数据；原先这条只写在 `mark_merged_from_prs` 的 docstring 里，用它的人看不到。
    """

    CARD = """id: EV-2026-911
layer: L2
target_component: scripts/ev_proposal.py
title: t
status: validated
authorization: review
dimension: process
created_at: 2026-09-22
source_signals:
  - {signal: process_friction, evidence: e, trajectory: [t]}
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
        self.card = self.root / "proposals" / "ideas" / "EV-2026-911.yaml"
        self.card.write_text(self.CARD, encoding="utf-8")
        self.prs = self.root / "prs.json"
        self.prs.write_text('[{"number": 88, "title": "批", "body": "含 EV-2026-911"}]', encoding="utf-8")

    def _run(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "ev_proposal.py"),
                               "--root", str(self.root), *args],
                              capture_output=True, text=True)

    def test_from_prs_needs_no_pr_placeholder(self):
        r = self._run("--mark-merged", "--from-prs", "--prs-file", str(self.prs))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PR #88", self.card.read_text(encoding="utf-8"))

    def test_from_prs_dry_run_writes_nothing(self):
        r = self._run("--mark-merged", "--from-prs", "--prs-file", str(self.prs), "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("PR #88", self.card.read_text(encoding="utf-8"))

    def test_all_pending_names_the_risk(self):
        r = self._run("--mark-merged", "77", "--all-pending")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("别的批", r.stderr)


