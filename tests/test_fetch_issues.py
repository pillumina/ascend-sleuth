"""fetch_issues 的 GitCode 后端：字段归一、分页合并、CLI 未就绪时如实报错。

护三条静默失效：number 不转整数会让下游按字符串比号；labels 不取 name 会让过滤
永远不命中；CLI 缺失时回退到空结果会让「没拉到」看起来像「没有 issue」。
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_issues as F  # noqa: E402


class SlimGitcodeTest(unittest.TestCase):
    def test_maps_fields_to_github_shape(self):
        got = F.slim_gitcode({
            "number": "10351", "title": "x", "comments": 2,
            "finished_at": "2026-11-27T06:01:42+08:00",
            "labels": [{"name": "bug-report"}, "triaged"],
        })
        self.assertEqual(got["number"], 10351)
        self.assertEqual(got["closed_at"], "2026-11-27T06:01:42+08:00")
        self.assertEqual(got["labels"], ["bug-report", "triaged"])
        self.assertIsNone(got["state_reason"])

    def test_closed_at_prefers_explicit_field(self):
        got = F.slim_gitcode({"number": 1, "closed_at": "a", "finished_at": "b"})
        self.assertEqual(got["closed_at"], "a")


class GitcodePagingTest(unittest.TestCase):
    def _proc(self, payload, code=0):
        return mock.Mock(returncode=code, stdout=json.dumps(payload), stderr="")

    def test_pages_until_short_page(self):
        first = [{"number": str(i)} for i in range(100)]
        second = [{"number": "100"}]
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return self._proc(first if len(calls) == 1 else second)

        with mock.patch.object(F, "_gitcode_bin", return_value="gitcode"), \
             mock.patch.object(F.subprocess, "run", side_effect=fake_run):
            items = F.gitcode_api("repos/cann/ops-nn/issues?state=closed")
        self.assertEqual(len(items), 101)
        self.assertIn("page=1", calls[0][2])
        self.assertIn("page=2", calls[1][2])
        self.assertTrue(all("per_page=100" in c[2] for c in calls))

    def test_cli_auth_failure_points_to_login(self):
        with mock.patch.object(F, "_gitcode_bin", return_value="gitcode"), \
             mock.patch.object(F.subprocess, "run", return_value=self._proc({}, code=4)):
            with self.assertRaises(SystemExit) as ctx:
                F.gitcode_api("repos/cann/ops-nn/issues")
        msg = str(ctx.exception)
        self.assertIn("GitCode CLI 调用失败", msg)
        self.assertIn("未登录", msg)

    def test_cli_not_found_does_not_blame_login(self):
        with mock.patch.object(F, "_gitcode_bin", return_value="gitcode"), \
             mock.patch.object(F.subprocess, "run", return_value=self._proc({}, code=3)):
            with self.assertRaises(SystemExit) as ctx:
                F.gitcode_api("repos/cann/ops-nn/issues")
        msg = str(ctx.exception)
        self.assertIn("不存在", msg)
        self.assertNotIn("未登录", msg)

    def test_missing_cli_raises_with_fix(self):
        with mock.patch.object(F.shutil, "which", return_value=None):
            with self.assertRaises(SystemExit) as ctx:
                F._gitcode_bin()
        self.assertIn("atomgit-cli", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
