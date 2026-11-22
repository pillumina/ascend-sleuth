# -*- coding: utf-8 -*-
"""agent_adapter 的 DSH 命令契约与 fallback 标记。"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_adapter  # noqa: E402


class AgentAdapterTest(unittest.TestCase):
    def _output(self, td: str):
        output = Path(td) / "out"
        output.mkdir()
        sample = Path(td) / "S-1.yaml"
        sample.write_text(yaml.safe_dump({"id": "S-1", "source": "x", "input": {"title": "S-1"}}),
                          encoding="utf-8")
        (output / "tasks.json").write_text(json.dumps({
            "samples": [{"id": "S-1", "path": str(sample)}],
        }), encoding="utf-8")
        return output

    def test_dsh_cli_command_contract(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}, clear=False), \
                mock.patch.object(agent_adapter.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="report", stderr="")
            result = agent_adapter._run_agent("dsh", "diagnose", Path("."), 5)
        self.assertEqual(result, "report")
        command = run.call_args.args[0]
        self.assertIn("headless", command)
        self.assertIn("--permission-mode", command)
        self.assertIn("workspace-write", command)
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_dsh_preflight_requires_credential(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("DEEPSEEK_API_KEY", "SLEUTH_DSH_ALLOW_STORED")}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(agent_adapter.AdapterError):
                agent_adapter._run_agent("dsh", "prompt", Path("."), 5)

    def test_echo_writes_fallback_marker(self):
        with tempfile.TemporaryDirectory() as td:
            output = self._output(td)
            trace = Path(td) / "trace.yaml"
            out = Path(td) / "out.md"
            env = {
                "SLEUTH_OUTPUT": str(output), "SLEUTH_TRACE": str(trace),
                "SLEUTH_OUT": str(out), "SLEUTH_ROOT": str(ROOT),
                "SLEUTH_SAMPLE_ID": "S-1", "SLEUTH_SHORT_ID": "S-1",
                "SLEUTH_ARM": "candidate", "SLEUTH_STAGE": "pilot",
            }
            with mock.patch.dict(os.environ, env, clear=False):
                result = agent_adapter.run("echo")
            self.assertEqual(result["agent"], "echo")
            doc = yaml.safe_load(trace.read_text(encoding="utf-8"))
            self.assertTrue(doc["adapter_fallback"])
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
