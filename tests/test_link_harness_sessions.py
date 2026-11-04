"""link_harness_sessions.py 的显式会话号分支：空值可补、非空不覆盖。

为什么单测：面板给用户的补录命令就是这条；空值 `harness_session: ""` 在旧单里很常见，
若脚本把"有这一行"当成"已写过"，命令会打印成功却不改文件，用户以为补上了。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


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


if __name__ == "__main__":
    unittest.main()
