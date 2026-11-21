"""precheck（触发判定与报告审计）的口径回归测试。

为什么值得测：policy 的判定决定"这次要不要派判断性预核、报告上限多少"，判错两边的代价不同——
把脚本/机制面判成文档档会漏掉反例；把文档面判成脚本档会白付一次会话。audit 是"有没有收益"的
唯一读数，字符与上限模拟算错会把结论带偏。下面钉四件事：档位归类、上限、审计计数、审计的
上限模拟。
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import precheck as PC  # noqa: E402


class ClassifyTest(unittest.TestCase):
    def test_docs_light(self):
        r = PC.classify(["docs/README.md"])
        self.assertEqual(r["mode"], "light")
        self.assertEqual(r["tier"], "docs")
        self.assertEqual(r["caps"]["max_report_chars"], 3000)

    def test_script_full(self):
        r = PC.classify(["scripts/precheck.py"])
        self.assertEqual(r["mode"], "full")
        self.assertEqual(r["tier"], "script")
        self.assertEqual(r["caps"]["max_report_chars"], 6000)
        self.assertEqual(r["caps"]["max_findings"], 5)

    def test_high_risk_label_escalates_docs(self):
        r = PC.classify(["docs/README.md"], ["kb/high-risk"])
        self.assertEqual(r["mode"], "full")
        self.assertEqual(r["tier"], "script")

    def test_content_light(self):
        r = PC.classify(["knowledge/inference/vllm-ascend/interrupt/X-1.yaml"])
        self.assertEqual(r["mode"], "light")
        self.assertEqual(r["tier"], "content")

    def test_selfcheck_data(self):
        r = PC.classify(["metrics/timeline.d/2026-W46.yaml"])
        self.assertEqual(r["mode"], "selfcheck")
        self.assertIsNone(r["caps"])

    def test_unknown_path_falls_back_to_full(self):
        r = PC.classify(["somewhere/else.txt"])
        self.assertEqual(r["mode"], "full")
        self.assertTrue(any("兜底" in x for x in r["reasons"]))

    def test_mixed_paths_take_highest(self):
        r = PC.classify(["docs/README.md", "scripts/precheck.py"])
        self.assertEqual(r["mode"], "full")

    def test_match_normalizes_backslash(self):
        self.assertTrue(PC._match("scripts\\precheck.py", PC.SCRIPT_PREFIXES, PC.SCRIPT_FILES))

    def test_workflow_and_gate_files_are_full(self):
        for p in (".github/workflows/kb-checks.yml", "metrics/gates.yaml",
                  "triage-tree.d/interrupt.yaml", "docs/guide/git-workflow.md",
                  "tests/test_precheck.py", "proposals/ideas/EV-2026-188.yaml"):
            self.assertEqual(PC.classify([p])["mode"], "full", p)


class DocsSyncTest(unittest.TestCase):
    """触发表要能看懂脚本的判定面；少一行，作者就会按「其余→自检」读错。"""

    def test_trigger_table_lists_main_surfaces(self):
        doc = (ROOT / "docs" / "guide" / "git-workflow.md").read_text(encoding="utf-8")
        for pref in ("scripts/", "dsh-plugins/", ".github/workflows/", "eval/",
                     "tests/", "proposals/", "docs/spec/", "docs/mechanism/"):
            self.assertIn(f"`{pref}**`", doc, pref)
        for token in ("`metrics/gates.yaml`", "`triage-tree*`", "`docs/guide/git-workflow.md`",
                      "`AGENTS.md`", "`sleuth.config.yaml`", "`.gitignore`"):
            self.assertIn(token, doc, token)


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_and_cap(self):
        a = "x" * 8000 + "\nMERGE_READY: no\nMERGE_READY: yes\n2 条重要级\n5 条建议级\n"
        b = "y" * 1000 + "\nMERGE_READY: no\n一条重要级\n"
        a_path = self.dir / "a.md"
        b_path = self.dir / "b.md"
        a_path.write_text(a, encoding="utf-8")
        b_path.write_text(b, encoding="utf-8")
        (self.dir / "c-pr-body.md").write_text("z" * 9999 + "\nMERGE_READY", encoding="utf-8")

        # 按磁盘上的实际字符数算：Windows 会把 \n 写成 \r\n，用内存里的 len(a) 会差换行数。
        chars_a = len(a_path.read_text(encoding="utf-8"))
        chars_b = len(b_path.read_text(encoding="utf-8"))
        r = PC.audit_reports(self.dir, cap=6000)
        self.assertEqual(r["files"], 2)
        self.assertEqual(r["chars"], chars_a + chars_b)
        self.assertEqual(r["max_important"], 2)
        self.assertEqual(r["multi"], 1)
        self.assertEqual(r["capped"], min(chars_a, 6000) + min(chars_b, 6000))
        self.assertGreater(r["saving"], 0)

    def test_empty_dir(self):
        r = PC.audit_reports(self.dir, cap=6000)
        self.assertEqual(r["files"], 0)

    def test_section_style_findings(self):
        text = "### 1.1 阻断级\n\n无。\n\n### 1.2 重要级\n\n1. a\n2. b\n3. c\n\n### 1.3 建议级\n\n1. d\n"
        (self.dir / "s.md").write_text(text, encoding="utf-8")
        r = PC.audit_reports(self.dir, cap=6000)
        self.assertEqual(r["max_important"], 3)
        self.assertEqual(r["max_total"], 4)

    def test_combined_heading_counts_important_only(self):
        text = "阻断/重要级：\n\n1. a\n2. b\n"
        (self.dir / "c.md").write_text(text, encoding="utf-8")
        r = PC.audit_reports(self.dir, cap=6000)
        self.assertEqual(r["max_important"], 2)
        self.assertEqual(r["rows"][0]["blocking"], 0)

    def test_bold_heading_findings(self):
        text = "**重要级：**\n\n1. a\n2. b\n\n**建议级：**\n\n1. c\n"
        (self.dir / "b.md").write_text(text, encoding="utf-8")
        r = PC.audit_reports(self.dir, cap=6000)
        self.assertEqual(r["max_important"], 2)
        self.assertEqual(r["max_total"], 3)

    def test_verdicts_count_only_colon_form(self):
        text = "引用这里的 MERGE_READY 写法\nMERGE_READY: yes\n"
        (self.dir / "v.md").write_text(text, encoding="utf-8")
        r = PC.audit_reports(self.dir, cap=6000)
        self.assertEqual(r["rows"][0]["verdicts"], 1)


class GitChangedTest(unittest.TestCase):
    def test_stale_base_uses_merge_base(self):
        """基线前进后，main 侧的新文件不能算进本 PR 的改动面。"""
        with tempfile.TemporaryDirectory() as tmp:
            def git(*args):
                return subprocess.run(
                    ["git", "-C", tmp, "-c", "user.name=t", "-c", "user.email=t@t", *args],
                    check=True, capture_output=True, text=True, encoding="utf-8",
                )
            subprocess.run(["git", "init", "-q", tmp], check=True)
            (Path(tmp) / "base.txt").write_text("x", encoding="utf-8")
            git("add", ".")
            git("commit", "-qm", "base")
            base = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            git("checkout", "-qb", "feature")
            (Path(tmp) / "feature.txt").write_text("y", encoding="utf-8")
            git("add", ".")
            git("commit", "-qm", "feature")
            git("checkout", "-q", base)
            (Path(tmp) / "main-only.txt").write_text("z", encoding="utf-8")
            git("add", ".")
            git("commit", "-qm", "main moves")
            git("checkout", "-q", "feature")

            paths = PC.git_changed(Path(tmp), base)
            self.assertIn("feature.txt", paths)
            self.assertNotIn("main-only.txt", paths)


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "precheck.py"), *args],
            capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
        )

    def test_policy_docs(self):
        r = self.run_cli("policy", "--paths", "docs/README.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mode: light", r.stdout)
        self.assertIn("tier: docs", r.stdout)
        self.assertIn("max_report_chars: 3000", r.stdout)

    def test_policy_outputs_utf8_when_locale_is_cp1252(self):
        """Windows 的 stdout 接管道时走本地编码；脚本入口要自己钉 UTF-8。"""
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "cp1252"
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "precheck.py"),
             "policy", "--paths", "docs/README.md"],
            capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("max_report_chars: 3000", r.stdout)

    def test_policy_script(self):
        r = self.run_cli("policy", "--paths", "scripts/precheck.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mode: full", r.stdout)
        self.assertIn("max_findings: 5", r.stdout)

    def test_policy_empty_diff_is_selfcheck(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            (Path(tmp) / "a.txt").write_text("x", encoding="utf-8")
            subprocess.run(["git", "-C", tmp, "add", "."], check=True)
            subprocess.run(
                ["git", "-C", tmp, "-c", "user.name=t", "-c", "user.email=t@t",
                 "commit", "-qm", "init"], check=True,
            )
            r = self.run_cli("policy", "--root", tmp, "--base", "HEAD")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mode: selfcheck", r.stdout)
        self.assertIn("没有改动", r.stdout)

    def test_policy_empty_paths_reads_git(self):
        # --paths 不带值等于没给改动清单：读 git diff；读不到按用法错误退出，不默认放行。
        with tempfile.TemporaryDirectory() as tmp:
            r = self.run_cli("policy", "--paths", "--root", tmp, "--base", "no-such-base")
        self.assertEqual(r.returncode, 2)
        self.assertIn("读不到改动清单", r.stderr)

    def test_audit_empty_dir_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self.run_cli("audit", "--dir", tmp)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
