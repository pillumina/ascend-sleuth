"""部署级演进模式（deployment.yaml）的解析回归测试。

钉住四件事，因为收尾检查的产卡行为全压在它们上面：

1. 缺文件 = `full`——没有声明时行为与本改动之前一致，升级不会静默改变任何部署；
2. 文件优先于缺省、环境变量优先于文件；来源（source）要能说出来，收尾说明照抄它；
3. 写坏（未知取值 / 有文件但缺键 / YAML 坏）时报错而不是猜一档——静默降级到 off 会让
   「这个部署在演进」与「这个部署关掉了演进」在数据上无法区分；
4. `--set` 写出来的文件能被自己读回（写入与解析共用同一份模板，不会写出读不回的形状）。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evolve_mode as EM  # noqa: E402


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

    def write(self, text):
        (self.root / EM.DECL_REL).write_text(text, encoding="utf-8")

    def test_missing_file_defaults_to_full(self):
        mode, source = EM.read_mode(self.root)
        self.assertEqual(mode, "full")
        self.assertIn("缺省", source)

    def test_file_value_wins_over_default(self):
        self.write("evolution:\n  mode: record-only\n")
        mode, source = EM.read_mode(self.root)
        self.assertEqual(mode, "record-only")
        self.assertEqual(source, str(EM.DECL_REL))

    def test_env_overrides_file(self):
        self.write("evolution:\n  mode: full\n")
        os.environ[EM.ENV_VAR] = "off"
        mode, source = EM.read_mode(self.root)
        self.assertEqual(mode, "off")
        self.assertIn(EM.ENV_VAR, source)

    def test_unknown_value_raises(self):
        self.write("evolution:\n  mode: half\n")
        with self.assertRaises(EM.ModeError):
            EM.read_mode(self.root)

    def test_file_without_key_raises(self):
        self.write("evolution:\n  other: 1\n")
        with self.assertRaises(EM.ModeError):
            EM.read_mode(self.root)

    def test_broken_yaml_raises(self):
        self.write("evolution: [\n")
        with self.assertRaises(EM.ModeError):
            EM.read_mode(self.root)

    def test_env_unknown_raises(self):
        os.environ[EM.ENV_VAR] = "loud"
        with self.assertRaises(EM.ModeError):
            EM.read_mode(self.root)

    def test_set_roundtrips(self):
        EM.write_mode(self.root, "record-only")
        mode, _ = EM.read_mode(self.root)
        self.assertEqual(mode, "record-only")

    def test_set_every_mode_roundtrips(self):
        for mode in EM.MODES:
            with self.subTest(mode=mode):
                EM.write_mode(self.root, mode)
                self.assertEqual(EM.read_mode(self.root)[0], mode)

    def test_unquoted_off_is_read_as_off(self):
        """YAML 1.1 把 `mode: off` 读成 False；词表里没有 false，只能是想写 off。"""
        self.write("evolution:\n  mode: off\n")
        self.assertEqual(EM.read_mode(self.root)[0], "off")

    def test_boolean_true_raises_with_hint(self):
        self.write("evolution:\n  mode: on\n")
        with self.assertRaises(EM.ModeError) as ctx:
            EM.read_mode(self.root)
        self.assertIn("引号", str(ctx.exception))

    def test_cli_exit_code_on_bad_declaration(self):
        self.write("evolution:\n  mode: nope\n")
        self.assertEqual(EM.main(["--root", str(self.root)]), 2)

    def test_default_declaration_shipped_in_repo_parses(self):
        """仓里提交的那份声明必须能被读端解析（上游是 full，fork 会改成 record-only，两者都合法）。

        不钉具体取值：声明按部署改，fork 的取值与上游本来就不同，钉 full 会让 fork 的 CI 红。
        """
        text = (ROOT / "sleuth.config.yaml").read_text(encoding="utf-8")
        self.assertIn("evolution:", text)
        role, _ = EM.read_role(ROOT)
        self.assertIn(role, ("maintainer", "signal-only", "off"))


if __name__ == "__main__":
    unittest.main()
