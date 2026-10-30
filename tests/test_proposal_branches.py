"""分支记录（alternatives）与演进流程卡的自指度量（external）的回归测试。

这两条护的是同一件事：**别让下一个人重走已经失败的路**，以及**别让改了流程的卡用流程自己
证明自己变好了**。两条都只在生效日之后的卡上强制，存量不追溯（补写只会造事后叙述）。
"""

import datetime
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_proposals as VP  # noqa: E402

CARD = """\
id: {cid}
layer: L2
title: 分支记录测试 {cid}
status: {status}
authorization: review
dimension: evolvability
created_at: {created}
{target_line}
source_signals:
  - signal: process_friction
    evidence: "示例证据"
    trajectory:
      - "traces/x.yaml"
{alternatives}hypothesis: 示例假设
predicted_effect:
  metric: m
  from: a
  to: b
{external}  measure:
    command: "true"
    expect_exit: 0
validation:
  method: scan_review
  baseline: 现状
  success_criteria: 跑通
  rollback: 丢弃分支
risk: low
principle_refs: [2]
actual_cost:
  tokens: 0
  note: 测试口径：不计成本
decisions:
  - who: agent
    when: 2026-11-01
    type: decision
    conclusion: 测试卡
"""


class BranchRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "proposals" / "ideas").mkdir(parents=True)
        # 生效日是"今天之后"时没法造合规的卡（未来日期会被挡），测试里把闸门提前到今天
        self._cuts = (VP.ALTERNATIVES_CUTOVER, VP.EXTERNAL_CUTOVER)
        VP.ALTERNATIVES_CUTOVER = VP.EXTERNAL_CUTOVER = datetime.date(2026, 1, 1)

    def tearDown(self):
        VP.ALTERNATIVES_CUTOVER, VP.EXTERNAL_CUTOVER = self._cuts
        self.tmp.cleanup()

    def write(self, **kw):
        kw.setdefault("status", "validated")
        kw.setdefault("created", "2026-10-30")
        kw.setdefault("target", "skills/example/SKILL.md")
        kw.setdefault("target_line", f"target_component: {kw['target']}")
        kw.setdefault("alternatives", "")
        kw.setdefault("external", "")
        (self.root / "proposals" / "ideas" / f"{kw['cid']}.yaml").write_text(
            CARD.format(**kw), encoding="utf-8")

    def run_check(self):
        argv = sys.argv
        sys.argv = ["verify_proposals.py", "--check", "--root", str(self.root)]
        out = io.StringIO()
        try:
            with redirect_stdout(out):
                VP.main()
        except SystemExit as e:
            return e.code, out.getvalue()
        finally:
            sys.argv = argv
        return 0, out.getvalue()

    def test_plain_card_passes(self):
        self.write(cid="EV-2026-901")
        self.assertEqual(self.run_check()[0], 0)

    def test_alternatives_shape_invalid(self):
        self.write(cid="EV-2026-901", alternatives="alternatives: []\n")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("alternatives 必须是非空列表", out)

    def test_alternatives_require_why_rejected(self):
        self.write(cid="EV-2026-901",
                   alternatives='alternatives:\n  - option: 方案 B\n')
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("缺 why_rejected", out)

    def test_precedent_requires_alternatives(self):
        self.write(cid="EV-2026-900", status="rejected", created="2026-09-01")
        self.write(cid="EV-2026-901")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("同组件有失败先例", out)

    def test_precedent_satisfied_by_alternatives(self):
        self.write(cid="EV-2026-900", status="rejected", created="2026-09-01")
        self.write(cid="EV-2026-901",
                   alternatives='alternatives:\n  - option: 方案 B\n    why_rejected: 实测无回归\n')
        self.assertEqual(self.run_check()[0], 0)

    def test_precedent_before_cutover_not_enforced(self):
        self.write(cid="EV-2026-900", status="rejected", created="2026-09-01")
        self.write(cid="EV-2026-901", created="2025-12-01")
        self.assertEqual(self.run_check()[0], 0)

    def test_evolution_flow_requires_external(self):
        self.write(cid="EV-2026-901", target="skills/self-evolve/SKILL.md",
                   target_line="target_component: skills/self-evolve/SKILL.md")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("缺 predicted_effect.external", out)

    def test_evolution_flow_external_cannot_self_reference(self):
        self.write(cid="EV-2026-901", target="skills/self-evolve/SKILL.md",
                   target_line="target_component: skills/self-evolve/SKILL.md",
                   external='  external: "skills/self-evolve/SKILL.md"\n')
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("不能指回被改的组件本身", out)

    def test_evolution_flow_external_ok(self):
        self.write(cid="EV-2026-901", target="skills/self-evolve/SKILL.md",
                   target_line="target_component: skills/self-evolve/SKILL.md",
                   external='  external: "台账提升率（proposals/signals 的 promoted 占比）"\n')
        self.assertEqual(self.run_check()[0], 0)

    def test_non_evolution_target_needs_no_external(self):
        self.write(cid="EV-2026-901", target="skills/issue-ingest/SKILL.md",
                   target_line="target_component: skills/issue-ingest/SKILL.md")
        self.assertEqual(self.run_check()[0], 0)


if __name__ == "__main__":
    unittest.main()


class BackdateTest(unittest.TestCase):
    """created_at 是自报字段：挡掉未来日期，以及"新增卡把日期倒填到基线之前"。"""

    def test_helper_thresholds(self):
        import datetime
        base = datetime.date(2026, 10, 30)
        self.assertTrue(VP.is_backdated(datetime.date(2026, 10, 1), base))
        self.assertFalse(VP.is_backdated(datetime.date(2026, 10, 29), base))
        self.assertFalse(VP.is_backdated(None, base))
        self.assertFalse(VP.is_backdated(datetime.date(2026, 10, 1), None))

    def test_future_created_at_rejected(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "proposals" / "ideas").mkdir(parents=True)
        card = CARD.format(cid="EV-2026-901", status="validated", created="2099-01-01",
                           target="skills/x/SKILL.md",
                           target_line="target_component: skills/x/SKILL.md",
                           alternatives="", external="")
        (root / "proposals" / "ideas" / "EV-2026-901.yaml").write_text(card, encoding="utf-8")
        argv = sys.argv
        sys.argv = ["verify_proposals.py", "--check", "--root", str(root)]
        out = io.StringIO()
        try:
            with redirect_stdout(out):
                VP.main()
        except SystemExit as e:
            self.assertEqual(e.code, 1)
        finally:
            sys.argv = argv
        self.assertIn("created_at 在未来", out.getvalue())

    def test_backdated_added_card_rejected(self):
        import subprocess
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)

        def git(*a):
            return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)

        git("init", "-q")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
        (root / "proposals" / "ideas").mkdir(parents=True)
        (root / "seed.txt").write_text("x", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        base = git("rev-parse", "HEAD").stdout.strip()

        card = CARD.format(cid="EV-2026-901", status="validated", created="2026-01-01",
                           target="skills/x/SKILL.md",
                           target_line="target_component: skills/x/SKILL.md",
                           alternatives="", external="")
        (root / "proposals" / "ideas" / "EV-2026-901.yaml").write_text(card, encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "add card")

        errors = []
        VP.check_backdated_cards(root, base, errors)
        self.assertTrue(any("倒填" in e for e in errors), errors)
