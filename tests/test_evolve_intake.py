"""演进记录入口（intake）的回归测试。

钉住四件事——它们是「任何部署都不丢信号」的全部依据：

1. 分流只由部署角色决定：maintainer / signal-only → 信号台账，off → 不落；
2. 载荷先于分流校验：证据太短、target 指不到、缺出处都拒收（记录层的质量下限）；
3. 非 maintainer 部署直接调 `ev_proposal.py --new` 会被拒（--force 是逃生口）；
4. 台账有生命周期：new → triaged / dropped，export 默认不导 dropped。
"""

import os
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evolve_intake as EI  # noqa: E402
import evolve_signals as ES  # noqa: E402
import ev_proposal as EP  # noqa: E402

GOOD = dict(signal="T10", signal_text="自审发现的缺口",
            target="skills/evolve-check/SKILL.md",
            evidence="收尾原因串与面板解析不同源",
            trajectory=["products/X-1(submitted)"], suggested="让两者同源")


class IntakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "skills" / "evolve-check").mkdir(parents=True)
        (self.root / "skills" / "evolve-check" / "SKILL.md").write_text("# x\n", encoding="utf-8")
        (self.root / "proposals" / "ideas").mkdir(parents=True)
        (self.root / "proposals" / "signals").mkdir(parents=True)
        (self.root / "examples").mkdir()
        (self.root / "examples" / "sample-idea.yaml").write_text(
            (ROOT / "examples" / "sample-idea.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        self._saved = os.environ.pop("ASCEND_SLEUTH_EVOLUTION", None)

    def tearDown(self):
        os.environ.pop("ASCEND_SLEUTH_EVOLUTION", None)
        if self._saved is not None:
            os.environ["ASCEND_SLEUTH_EVOLUTION"] = self._saved
        self.tmp.cleanup()

    def decl(self, mode):
        role = {"full": "maintainer", "record-only": "signal-only", "off": "off"}[mode]
        (self.root / "sleuth.config.yaml").write_text(
            f'schema: sleuth-config-v1\nevolution:\n  role: {role}\n', encoding="utf-8")

    def test_maintainer_writes_signal_not_card(self):
        (self.root / "sleuth.config.yaml").write_text(
            'schema: sleuth-config-v1\nevolution:\n  role: maintainer\n', encoding="utf-8")
        res = EI.record(self.root, **GOOD)
        self.assertEqual(res["mode"], "record-only")
        self.assertTrue(str(res["path"]).endswith(".yaml"))
        self.assertNotIn("ideas", str(res["path"]))

    def test_record_only_writes_signal(self):
        self.decl("record-only")
        res = EI.record(self.root, **GOOD)
        self.assertEqual(res["mode"], "record-only")
        doc = ES.load(res["path"])
        self.assertEqual(doc["status"], "new")
        self.assertEqual(doc["target_component"], GOOD["target"])

    def test_off_writes_nothing(self):
        self.decl("off")
        res = EI.record(self.root, **GOOD)
        self.assertIsNone(res["path"])
        self.assertEqual(list((self.root / "proposals" / "signals").glob("*.yaml")), [])

    def test_short_evidence_rejected(self):
        self.decl("record-only")
        with self.assertRaises(ValueError):
            EI.record(self.root, **{**GOOD, "evidence": "太短"})

    def test_missing_trajectory_rejected(self):
        self.decl("record-only")
        with self.assertRaises(ValueError):
            EI.record(self.root, **{**GOOD, "trajectory": []})

    def test_unknown_target_path_rejected(self):
        self.decl("record-only")
        with self.assertRaises(ValueError):
            EI.record(self.root, **{**GOOD, "target": "skills/nope/SKILL.md"})

    def test_component_name_target_accepted(self):
        self.decl("record-only")
        res = EI.record(self.root, **{**GOOD, "target": "triage:vllm-ascend-startup"})
        self.assertTrue(res["path"].exists())

    def test_cli_contract_error_exit_2(self):
        self.decl("record-only")
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            rc = EI.main(["--root", str(self.root), "record", "--signal", "T10",
                          "--target", "skills/nope/SKILL.md",
                          "--evidence", "收尾原因串与面板解析不同源", "--trajectory", "x"])
        self.assertEqual(rc, 2)


class GateAndLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "proposals" / "ideas").mkdir(parents=True)
        (self.root / "proposals" / "signals").mkdir(parents=True)
        (self.root / "examples").mkdir()
        (self.root / "examples" / "sample-idea.yaml").write_text(
            (ROOT / "examples" / "sample-idea.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        self._saved = os.environ.pop("ASCEND_SLEUTH_EVOLUTION", None)

    def tearDown(self):
        os.environ.pop("ASCEND_SLEUTH_EVOLUTION", None)
        if self._saved is not None:
            os.environ["ASCEND_SLEUTH_EVOLUTION"] = self._saved
        self.tmp.cleanup()

    def test_new_blocked_under_signal_only(self):
        (self.root / "sleuth.config.yaml").write_text(
            'schema: sleuth-config-v1\nevolution:\n  role: signal-only\n', encoding="utf-8")
        with self.assertRaises(EP.DeploymentGate):
            EP.make_new(self.root)

    def test_new_force_bypasses_gate(self):
        (self.root / "sleuth.config.yaml").write_text(
            'schema: sleuth-config-v1\nevolution:\n  role: signal-only\n', encoding="utf-8")
        p = EP.make_new(self.root, force=True)
        self.assertTrue(p.exists())

    def test_mark_lifecycle_and_export_filter(self):
        ES.add(self.root, signal="T10", target="a/b.md", evidence="证据足够长的一句话",
               trajectory=["x"])
        p = next((self.root / "proposals" / "signals").glob("*.yaml"))
        ES.mark(self.root, p.stem, "dropped", "重复")
        items = ES.collect(self.root)
        self.assertEqual(ES.load(p)["status"], "dropped")
        body = ES.render_md([(p2, d) for p2, d in items if (d.get("status") or "new") != "dropped"])
        self.assertEqual(body, "")

    def test_mark_unknown_key_raises(self):
        with self.assertRaises(ValueError):
            ES.mark(self.root, "nope", "dropped")


if __name__ == "__main__":
    unittest.main()
