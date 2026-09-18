"""verify_evidence：引文回验的判据与三态。

为什么值得单测：这条判据的**松紧**决定它是"反幻觉"还是"走过场"。
外部同类实现的 PARTIAL 档（引文是实际行的子串或超集就算过）在这里被刻意去掉——
超集意味着"引文里混进原件没有的内容"也能通过，正是要抓的那种错。
所以本测试钉住四件事：①逐字相等才算过（空白归一化除外）；②截断必须显式标 `...` 且分段按序；
③编码问题记 READ-ERROR 而不是 MISMATCH（不把读不出报成"引文错"）；
④没有原件的条目记 NO-ORIGIN，既不算过也不算失败。
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_evidence as ve  # noqa: E402

LOG = "\n".join([
    "[INFO] boot ok",                                             # 1
    "[2026-01-02 10:19:58.123] [ERROR:DEV] device 3 ecc error a",  # 2
    "[2026-01-02 10:20:01.004] [ERROR:HCCL] rank 3 timeout",       # 3
    "",                                                           # 4
    "tail line",                                                  # 5
]) + "\n"


class VerifyEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "plog").mkdir()
        (self.root / "plog" / "device-3.log").write_text(LOG, encoding="utf-8")

    def _trace(self, quotes, name="t.yaml"):
        """按 quotes 列表造一份 trace；quote 传 None 表示该条不带 quote 键。"""
        lines = ["session_id: t", "trace:"]
        lines.append("- role: user")
        lines.append("  step: 1")
        lines.append("  content: 贴日志")
        if quotes is not None:
            lines.append("  evidence:")
            lines.append("    files: [plog/device-3.log]")
            lines.append("    quotes:")
            for q in quotes:
                if q is None:
                    lines.append("      - {file: plog/device-3.log}")
                    continue
                parts = ", ".join(f'{k}: "{v}"' for k, v in q.items())
                lines.append(f"      - {{{parts}}}")
        p = self.root / name
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return p

    def _run(self, trace, *extra):
        """跑 main 并吞掉它的 stdout——报告类输出不该把单测结果刷出屏幕。"""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = ve.main([str(trace), "--root", str(self.root), *extra])
        return code

    def test_exact_match_passes(self):
        t = self._trace([{"file": "plog/device-3.log", "line": 2,
                          "quote": "[2026-01-02 10:19:58.123] [ERROR:DEV] device 3 ecc error a"}])
        self.assertEqual(self._run(t), 0)

    def test_whitespace_normalized(self):
        t = self._trace([{"file": "plog/device-3.log", "line": 2,
                          "quote": "[2026-01-02 10:19:58.123]   [ERROR:DEV]  device 3 ecc error a"}])
        self.assertEqual(self._run(t), 0)

    def test_truncation_with_marker_passes(self):
        t = self._trace([{"file": "plog/device-3.log", "line": 2,
                          "quote": "[2026-01-02 10:19:58.123] ... device 3 ecc error a"}])
        self.assertEqual(self._run(t), 0)

    def test_truncation_segments_out_of_order_fails(self):
        t = self._trace([{"file": "plog/device-3.log", "line": 2,
                          "quote": "device 3 ecc error a ... [2026-01-02 10:19:58.123]"}])
        self.assertEqual(self._run(t), 1)

    def test_superset_quote_fails(self):
        """关键回归：引文比实际行更长（混进编造内容）必须判不一致。"""
        t = self._trace([{"file": "plog/device-3.log", "line": 2,
                          "quote": "[2026-01-02 10:19:58.123] [ERROR:DEV] device 3 ecc error a 且 ECC 计数已达阈值"}])
        self.assertEqual(self._run(t), 1)

    def test_altered_line_number_fails(self):
        t = self._trace([{"file": "plog/device-3.log", "line": 3,
                          "quote": "[2026-01-02 10:19:58.123] [ERROR:DEV] device 3 ecc error a"}])
        self.assertEqual(self._run(t), 1)

    def test_missing_file_and_out_of_range(self):
        t = self._trace([
            {"file": "plog/nope.log", "line": 1, "quote": "x"},
            {"file": "plog/device-3.log", "line": 999, "quote": "x"},
        ])
        self.assertEqual(self._run(t), 1)

    def test_no_origin_does_not_fail(self):
        """粘贴件（没有原件）既不降级也不失败。"""
        t = self._trace([None, {"file": "plog/device-3.log", "quote": "x"}])
        self.assertEqual(self._run(t), 0)

    def test_trace_without_quotes_is_clean(self):
        t = self._trace(None)
        self.assertEqual(self._run(t), 0)

    def test_encoding_failure_is_not_mismatch(self):
        (self.root / "plog" / "gb.log").write_bytes(b"[ERROR]\xff\xfe\x00 garbage\n")
        t = self._trace([{"file": "plog/gb.log", "line": 1, "quote": "[ERROR] garbage"}])
        items, err = ve.collect_items(t)
        self.assertIsNone(err)
        rec = ve.verify_item(items[0], self.root, ve.DEFAULT_MAX_CHARS)
        self.assertEqual(rec["verdict"], "READ-ERROR")

    def test_non_trace_file_is_usage_error(self):
        p = self.root / "other.yaml"
        p.write_text("cases: []\n", encoding="utf-8")
        self.assertEqual(ve.main([str(p), "--root", str(self.root)]), 2)

    def test_missing_trace_file_is_usage_error(self):
        self.assertEqual(ve.main([str(self.root / "nope.yaml"), "--root", str(self.root)]), 2)

    def test_counts_summary_json(self):
        t = self._trace([
            {"file": "plog/device-3.log", "line": 2, "quote": "[2026-01-02 10:19:58.123] [ERROR:DEV] device 3 ecc error a"},
            {"file": "plog/device-3.log", "line": 3, "quote": "not the line"},
            None,
        ])
        self.assertEqual(self._run(t, "--json"), 1)
        items, _ = ve.collect_items(t)
        verdicts = [ve.verify_item(i, self.root, ve.DEFAULT_MAX_CHARS)["verdict"] for i in items]
        self.assertEqual(verdicts, ["PASS", "MISMATCH", "NO-ORIGIN"])


if __name__ == "__main__":
    unittest.main()
