# -*- coding: utf-8 -*-
"""sleuth.config.yaml 的角色解析测试。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evolve_mode as EM  # noqa: E402
import sleuth_config as SC  # noqa: E402


class ReadModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._saved = os.environ.pop(EM.ENV_VAR, None)

    def tearDown(self):
        os.environ.pop(EM.ENV_VAR, None)
        if self._saved is not None:
            os.environ[EM.ENV_VAR] = self._saved
        self.tmp.cleanup()

    def write(self, role="maintainer"):
        (self.root / SC.CONFIG_NAME).write_text(
            f"schema: {SC.SCHEMA}\nevolution:\n  role: {role}\n", encoding="utf-8")

    def test_missing_config_defaults_to_maintainer(self):
        mode, source = EM.read_mode(self.root)
        self.assertEqual(mode, "full")
        self.assertIn("built-in defaults", source)

    def test_role_wins_over_default(self):
        self.write("signal-only")
        mode, source = EM.read_mode(self.root)
        self.assertEqual(mode, "record-only")
        self.assertTrue(source.endswith(SC.CONFIG_NAME))

    def test_env_overrides_file(self):
        self.write("maintainer")
        os.environ[EM.ENV_VAR] = "off"
        mode, source = EM.read_mode(self.root)
        self.assertEqual(mode, "off")
        self.assertIn(EM.ENV_VAR, source)

    def test_unknown_value_raises(self):
        self.write("half")
        with self.assertRaises(EM.ModeError):
            EM.read_mode(self.root)

    def test_missing_role_defaults_to_maintainer(self):
        (self.root / SC.CONFIG_NAME).write_text(
            f"schema: {SC.SCHEMA}\nevolution:\n  store: {{}}\n", encoding="utf-8")
        self.assertEqual(EM.read_mode(self.root)[0], "full")

    def test_broken_yaml_raises(self):
        (self.root / SC.CONFIG_NAME).write_text("evolution: [\n", encoding="utf-8")
        with self.assertRaises(EM.ModeError):
            EM.read_mode(self.root)

    def test_env_unknown_raises(self):
        os.environ[EM.ENV_VAR] = "loud"
        with self.assertRaises(EM.ModeError):
            EM.read_mode(self.root)

    def test_set_preserves_comments_and_quotes_off(self):
        path = self.root / SC.CONFIG_NAME
        path.write_text(
            '# keep this\nschema: sleuth-config-v1\nevolution:\n'
            '  role: "maintainer"  # why\n  store: {}\n', encoding="utf-8")
        EM.write_mode(self.root, "off")
        text = path.read_text(encoding="utf-8")
        self.assertIn("# keep this", text)
        self.assertIn("# why", text)
        self.assertIn('role: "off"', text)
        self.assertEqual(EM.read_mode(self.root)[0], "off")

    def test_set_roundtrips(self):
        EM.write_mode(self.root, "record-only")
        self.assertEqual(EM.read_mode(self.root)[0], "record-only")

    def test_set_every_mode_roundtrips(self):
        for mode in EM.MODES:
            with self.subTest(mode=mode):
                EM.write_mode(self.root, mode)
                self.assertEqual(EM.read_mode(self.root)[0], mode)

    def test_unquoted_off_is_read_as_off(self):
        self.write("off")
        self.assertEqual(EM.read_mode(self.root)[0], "off")

    def test_boolean_true_raises_with_hint(self):
        self.write("on")
        with self.assertRaises(EM.ModeError) as ctx:
            EM.read_mode(self.root)
        self.assertIn("引号", str(ctx.exception))

    def test_cli_exit_code_on_bad_role(self):
        self.write("nope")
        self.assertEqual(EM.main(["--root", str(self.root)]), 2)

    def test_repo_config_parses(self):
        text = (ROOT / SC.CONFIG_NAME).read_text(encoding="utf-8")
        self.assertIn("evolution:", text)
        role, _ = EM.read_role(ROOT)
        self.assertIn(role, ("maintainer", "signal-only", "off"))


if __name__ == "__main__":
    unittest.main()
