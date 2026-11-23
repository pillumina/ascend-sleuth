"""render_review_summary：代号解码的纯函数口径。"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import yaml  # noqa: E402

import render_review_summary as rrs  # noqa: E402


def make_glossary(root: Path, entries):
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "glossary.yaml").write_text(
        yaml.safe_dump({"entries": entries}, allow_unicode=True), encoding="utf-8")
    return rrs.Glossary(root)


class GlossaryTest(unittest.TestCase):
    def test_annotate_uses_short_then_meaning(self):
        with tempfile.TemporaryDirectory() as td:
            gl = make_glossary(Path(td), [
                {"token": "EV", "meaning": "证据版本", "short": "版本"},
                {"token": "A2", "meaning": "授权二级"},
            ])
            self.assertEqual(gl.annotate("EV"), "EV〔版本〕")
            self.assertEqual(gl.annotate("A2"), "A2〔授权二级〕")
            self.assertEqual(gl.annotate("ZZ"), "ZZ")


class SplitCodeSpansTest(unittest.TestCase):
    def test_fenced_and_inline_are_code(self):
        segs = rrs.split_code_spans("a `EV` b ```\nEV\n``` c")
        self.assertEqual([is_code for is_code, _ in segs], [False, True, False, True, False])
        self.assertEqual([chunk for is_code, chunk in segs if is_code], ["`EV`", "```\nEV\n```"])

    def test_empty_text(self):
        self.assertEqual(rrs.split_code_spans(""), [])


class UnknownTokensTest(unittest.TestCase):
    def test_registered_token_and_ev_instance_are_not_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            gl = make_glossary(Path(td), [{"token": "EV", "meaning": "证据版本"}])
            self.assertEqual(rrs.unknown_tokens("EV 已登记", gl), set())
            self.assertEqual(rrs.unknown_tokens("EV-2026-001 是实例", gl), set())

    def test_unregistered_token_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            gl = make_glossary(Path(td), [{"token": "EV", "meaning": "证据版本"}])
            found = {token for token, _family in rrs.unknown_tokens("A2 还在用", gl)}
            self.assertIn("A2", found)


class OutOfScopeTest(unittest.TestCase):
    def test_scope_mismatch_is_reported_except_exempt_paths(self):
        with tempfile.TemporaryDirectory() as td:
            gl = make_glossary(Path(td), [
                {"token": "P1", "meaning": "流程事项", "scope": ["docs/plan/roadmap.md"]}])
            self.assertEqual(rrs.out_of_scope_tokens("P1", "docs/guide/x.md", gl), {"P1"})
            self.assertEqual(rrs.out_of_scope_tokens("P1", "docs/plan/roadmap.md", gl), set())
            self.assertEqual(rrs.out_of_scope_tokens("P1", "proposals/x.md", gl), set())

    def test_platform_suffix_is_not_a_scope_violation(self):
        with tempfile.TemporaryDirectory() as td:
            gl = make_glossary(Path(td), [
                {"token": "A2", "meaning": "事项", "scope": ["docs/plan/roadmap.md"]}])
            self.assertEqual(rrs.out_of_scope_tokens("A2-910B", "docs/guide/x.md", gl), set())


class ExpandPathsTest(unittest.TestCase):
    def test_directory_expands_to_posix_relative_markdown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "docs").mkdir()
            (root / "docs" / "b.md").write_text("b", encoding="utf-8")
            (root / "docs" / "a.md").write_text("a", encoding="utf-8")
            (root / "docs" / "skip.txt").write_text("x", encoding="utf-8")
            out = rrs.expand_paths(["docs"], root)
            self.assertEqual(out, ["docs/a.md", "docs/b.md"])

    def test_file_path_is_normalized(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(rrs.expand_paths(["docs\\x.md"], Path(td)), ["docs/x.md"])


if __name__ == "__main__":
    unittest.main()
