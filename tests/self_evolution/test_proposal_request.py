"""提案契约回归：failures 定向批评与 digest 摘要拼进 prompt，且不影响原契约。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

SCRIPT = ROOT / "scripts" / "evolve.py"

from evolve.proposals import request  # noqa: E402


class RequestContractTest(unittest.TestCase):
    def test_base_prompt_unchanged(self):
        result = request("skill", "region-x")
        self.assertNotIn("失败样例", result["prompt"])
        self.assertNotIn("上下文摘要", result["prompt"])
        self.assertIn("只输出一个 JSON 对象", result["prompt"])
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["digest"], {})

    def test_failures_sections(self):
        failures = [{"sample_id": "s1", "expected": "含命令", "actual": "无命令",
                     "feedback": "缺第①条"}]
        result = request("skill", "region-x", failures=failures)
        self.assertIn("上一轮失败样例", result["prompt"])
        self.assertIn("样例 s1", result["prompt"])
        self.assertIn("期望=含命令", result["prompt"])
        self.assertIn("实际=无命令", result["prompt"])
        self.assertEqual(result["failures"], failures)

    def test_digest_sections(self):
        result = request("skill", "region-x", digest={
            "data_digest": "golden 30 条，中断/精度/性能三性质",
            "program_digest": "已有候选：超时分支改写、重试上限提示"})
        self.assertIn("上下文摘要", result["prompt"])
        self.assertIn("超时分支改写", result["prompt"])
        self.assertIn("golden 30 条", result["prompt"])

    def test_cli_request_with_files(self):
        with tempfile.TemporaryDirectory() as td:
            failures_path = Path(td) / "failures.json"
            digest_path = Path(td) / "digest.json"
            failures_path.write_text(json.dumps(
                [{"sample_id": "s1", "expected": "e", "actual": "a", "feedback": "f"}]),
                encoding="utf-8")
            digest_path.write_text(json.dumps(
                {"data_digest": "d", "program_digest": "p"}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "experiment", "request",
                 "--target", "skill", "--component", "region-x",
                 "--failures-file", str(failures_path),
                 "--digest-file", str(digest_path)],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertIn("失败样例", data["prompt"])
            self.assertIn("候选池摘要", data["prompt"])

    def test_cli_rejects_non_array_failures(self):
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.json"
            bad.write_text(json.dumps({"not": "array"}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "experiment", "request",
                 "--target", "skill", "--component", "region-x",
                 "--failures-file", str(bad)],
                capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
            self.assertEqual(result.returncode, 2)
            self.assertIn("array", result.stderr)


if __name__ == "__main__":
    unittest.main()
