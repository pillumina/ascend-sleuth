"""外部能力枚举与工具词条必须一一对上（`verify_references.check_external_capabilities`）。

护的三条静默失效：词条声明了未登记的能力 → trace 的 capability 出现词表外取值；
枚举登记了但没有词条声明 → 给了一个取不到的枚举；两个工具声明同一能力 →
external_lookup 的读数分不清是谁。三种都由这条校验在 CI 报出。
"""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_references as vr  # noqa: E402


class ExternalCapabilityTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.refs = Path(self._tmp.name)
        (self.refs / "tools").mkdir()
        self.types = {"external_capabilities": ["versioned-code"]}

    def tearDown(self):
        self._tmp.cleanup()

    def _tool(self, name, cap, status="active"):
        (self.refs / "tools" / f"{name}.yaml").write_text(yaml.safe_dump({
            "id": name, "type": "tool", "status": status,
            "content": {"tool_name": name, "invocation": "x", "capability": cap},
        }, allow_unicode=True), encoding="utf-8")

    def test_nested_tool_is_scanned(self):
        # 同一脚本的 id 查重与词条计数走 rglob；能力门若只 glob 平铺目录，
        # 嵌套词条会被当词条收下却逃过能力门（实测可静默通过）。
        sub = self.refs / "tools" / "cloud"
        sub.mkdir()
        (sub / "t-nested.yaml").write_text(yaml.safe_dump({
            "id": "t-nested", "type": "tool", "status": "active",
            "content": {"tool_name": "t-nested", "invocation": "x", "capability": "bench"},
        }, allow_unicode=True), encoding="utf-8")
        errs = vr.check_external_capabilities(self.refs, self.types, [])
        self.assertTrue(any("bench" in e and "未在" in e for e in errs), errs)

    def test_deprecated_tool_still_counts_as_owner(self):
        # 工具退役时枚举要留着，否则历史 trace 的 capability 变词表外取值
        self._tool("t-old", "versioned-code", status="deprecated")
        self.assertEqual(vr.check_external_capabilities(self.refs, self.types, []), [])

    def test_archived_deprecated_tool_counts_as_owner(self):
        # README 约定退役词条移入 _archive/（保留 deprecated）；若属主扫描跳过下划线目录，
        # 退役就只能删枚举，历史 trace 的 capability 会变词表外取值。
        arc = self.refs / "tools" / "_archive"
        arc.mkdir()
        (arc / "t-old.yaml").write_text(yaml.safe_dump({
            "id": "t-old", "type": "tool", "status": "deprecated",
            "content": {"tool_name": "t-old", "invocation": "x", "capability": "versioned-code"},
        }, allow_unicode=True), encoding="utf-8")
        self.assertEqual(vr.check_external_capabilities(self.refs, self.types, []), [])


    def test_duplicate_enum_value_fails(self):
        self.types = {"external_capabilities": ["versioned-code", "versioned-code"]}
        self._tool("t1", "versioned-code")
        errs = vr.check_external_capabilities(self.refs, self.types, [])
        self.assertTrue(any("重复取值" in e for e in errs), errs)


    def test_registered_capability_passes(self):
        self._tool("t1", "versioned-code")
        self.assertEqual(vr.check_external_capabilities(self.refs, self.types, []), [])

    def test_unregistered_capability_fails(self):
        self._tool("t1", "bench")
        errs = vr.check_external_capabilities(self.refs, self.types, [])
        self.assertTrue(any("bench" in e and "未在" in e for e in errs), errs)

    def test_registered_without_tool_fails(self):
        errs = vr.check_external_capabilities(self.refs, self.types, [])
        self.assertTrue(any("没有 active 或 deprecated 工具词条声明" in e for e in errs), errs)

    def test_inactive_tool_does_not_count(self):
        self._tool("t1", "versioned-code", status="draft")
        errs = vr.check_external_capabilities(self.refs, self.types, [])
        self.assertTrue(any("没有 active 或 deprecated 工具词条声明" in e for e in errs), errs)

    def test_two_tools_same_capability_fails(self):
        self._tool("t1", "versioned-code")
        self._tool("t2", "versioned-code")
        errs = vr.check_external_capabilities(self.refs, self.types, [])
        self.assertTrue(any("被多个工具词条声明" in e for e in errs), errs)

    def test_missing_enum_block_fails(self):
        self._tool("t1", "versioned-code")
        errs = vr.check_external_capabilities(self.refs, {}, [])
        self.assertTrue(any("external_capabilities 必须" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
