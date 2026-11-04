"""link_harness_sessions.py 的显式会话号分支：空值可补、非空不覆盖。

为什么单测：面板给用户的补录命令就是这条；空值 `harness_session: ""` 在旧单里很常见，
若脚本把"有这一行"当成"已写过"，命令会打印成功却不改文件，用户以为补上了。
"""

from __future__ import annotations

import datetime
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import link_harness_sessions  # noqa: E402


class ExplicitSessionIdTest(unittest.TestCase):
    def _run(self, repo: Path, trace: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "link_harness_sessions.py"),
             "--repo", str(repo), "--trace", trace,
             "--session-id", "session-abc", "--apply"],
            capture_output=True, text=True, timeout=20,
        )

    def _trace(self, repo: Path, name: str, harness_line: str) -> Path:
        traces = repo / "traces"
        traces.mkdir(parents=True)
        path = traces / name
        path.write_text(
            'session_id: "2026-01-01-x"\n'
            + harness_line + "\n"
            + 'created_at: "2026-01-01T00:00:00+08:00"\n'
            + "trace: []\n",
            encoding="utf-8",
        )
        return path

    def test_fills_empty_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._trace(Path(tmp), "2026-01-01-x.yaml", 'harness_session: ""')
            result = self._run(Path(tmp), "2026-01-01-x.yaml")
            self.assertEqual(result.returncode, 0, result.stderr)
            text = path.read_text(encoding="utf-8")
            self.assertIn('harness_session: "session-abc"', text)
            self.assertEqual(text.count("harness_session:"), 1, text)

    def test_does_not_overwrite_existing_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._trace(Path(tmp), "2026-01-01-x.yaml", 'harness_session: "session-old"')
            result = self._run(Path(tmp), "2026-01-01-x.yaml")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('harness_session: "session-old"', path.read_text(encoding="utf-8"))


class PickTimeTest(unittest.TestCase):
    def test_ignores_session_started_after_trace_creation(self):
        created = int(datetime.datetime(
            2026, 9, 8, 15, 29, tzinfo=datetime.timezone(datetime.timedelta(hours=8)),
        ).timestamp() * 1000)
        candidates = [
            # 后开的会话只能引用过这单；不能因为它离 created_at 更近就选它
            ("session-late", created + 10 * 60 * 1000, created + 2 * 60 * 60 * 1000, 20, "late"),
            ("session-early", created - 10 * 60 * 1000, created + 60 * 1000, 5, "early"),
        ]
        sid, basis = link_harness_sessions.pick(candidates, created)
        self.assertEqual((sid, basis), ("session-early", "时间"))

    def test_no_covering_window_falls_back_to_hits(self):
        created = 1_000_000
        candidates = [
            ("session-old", created - 4 * 60 * 60 * 1000, created - 3 * 60 * 60 * 1000, 2, "old"),
            ("session-missing-end", None, None, 7, "unknown"),
        ]
        sid, basis = link_harness_sessions.pick(candidates, created)
        self.assertEqual((sid, basis), ("session-missing-end", "命中次数"))


if __name__ == "__main__":
    unittest.main()
