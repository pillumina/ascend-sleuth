#!/usr/bin/env python3
"""指标契约：live 快照能出现的字段，必须在白名单与强度名册里。

这一层的失败形态是**下一期才红**：`trace_metrics.py` 新增字段后，白名单 / 强度名册没跟上，
当期不出问题，直到有人用 `--emit-yaml` 产出一期 live 快照才被 `verify_metrics.py --check`
拦下（这就是本次要修的那条链）。所以这里从 `trace_metrics.py` 的真实输出取字段集合，
断言它在两处名册里都有声明：`verify_metrics.LIVE_FIELDS` 与 `metrics/gates.yaml` 的
`metric_strength`。
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import verify_metrics as vm  # noqa: E402

TRACE_TMPL = """session_id: {sid}
status: {status}
kb_behind: 0
kb_merge: ff-only
external_evidence: 'on'
stop_reason: {stop_reason}
trace:
  - role: user
    content: "报错 timeout，训练卡住"
  - role: agent
    action: triage
    routed: [{routed}]
    category: interrupt
    parallel_group: g1
    considered_candidates: [CASE-X]
    candidates: [CASE-X]
  - role: agent
    action: quickly_check
  - role: agent
    action: hit
    case: CASE-X
  - role: agent
    action: reference_lookup
    ref_id: some-ref
    outcome: {ref_outcome}
    purpose: fix
    platform: A2-910B
  - role: agent
    action: external_lookup
    capability: vllm_kb_code
    outcome: hit
  - role: agent
    action: attribution
    verdict: case_error
  - role: agent
    action: feedback
    outcome: {feedback}
"""


class MetricsContractTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def emit_metrics(self):
        """造覆盖多路的事件，跑 trace_metrics 的机器读快照，取 live 快照字段集合。"""
        traces = self.root / "traces"
        traces.mkdir()
        (traces / "s1.yaml").write_text(TRACE_TMPL.format(
            sid="s1", status="resolved", stop_reason="resolved_confirmed",
            routed="inference/vllm-ascend", ref_outcome="hit", feedback="resolved"),
            encoding="utf-8")
        (traces / "s2.yaml").write_text(TRACE_TMPL.format(
            sid="s2", status="feedback_pending", stop_reason="halted_ask_user",
            routed="", ref_outcome="miss", feedback="not_resolved"),
            encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "trace_metrics.py"),
             "--root", str(ROOT), "--traces-dir", str(traces), "--emit-yaml-only"],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return (yaml.safe_load(proc.stdout) or {}).get("metrics") or {}

    def test_emitted_live_fields_are_whitelisted(self):
        metrics = self.emit_metrics()
        self.assertIn("external_evidence", metrics, "夹具应覆盖外部查证字段")
        self.assertIn("external_lookups", metrics)
        self.assertIn("triage_miss_classes", metrics)
        unknown = sorted(set(metrics) - vm.LIVE_FIELDS)
        self.assertEqual(unknown, [], f"live 快照字段没进白名单：{unknown}")

    def test_whitelisted_live_fields_have_strength(self):
        strength = (yaml.safe_load((ROOT / "metrics" / "gates.yaml").read_text(encoding="utf-8"))
                    or {}).get("metric_strength") or {}
        undeclared = sorted(set(vm.LIVE_FIELDS) - set(strength))
        self.assertEqual(undeclared, [], f"白名单字段没声明强度档：{undeclared}")

    def test_full_snapshot_passes_verify_metrics(self):
        """把真实快照装成一期 live 期文件，`verify_metrics.py --check` 应通过。"""
        metrics = self.emit_metrics()
        root = self.root / "deploy"
        (root / "metrics").mkdir(parents=True)
        shutil.copy(ROOT / "metrics" / "gates.yaml", root / "metrics" / "gates.yaml")
        period = {
            "period": "2026-W46-live-1108",
            "kind": "live",
            "title": "指标契约用例",
            "recorded_at": "2026-11-08",
            "source": "trace_metrics.py 合成快照",
            "metrics": metrics,
        }
        (root / "metrics" / "timeline.yaml").write_text(
            yaml.safe_dump({"periods": [period]}, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_metrics.py"),
             "--check", "--root", str(root)],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
