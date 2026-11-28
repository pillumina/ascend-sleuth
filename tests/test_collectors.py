#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户现场采集器的清单、交付说明与打包测试。

打包只复制文件，不执行采集、不访问网络；测试也不运行任何采集脚本。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "scripts" / "collectors" / "cli.py"
BASE_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def run_cli(args, timeout: int = 120):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=BASE_ENV,
        timeout=timeout,
    )


class CollectorTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="sleuth-collectors-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def bundle(self, name: str) -> Path:
        out = self.tmp / "bundles" / name
        proc = run_cli(["bundle", name, "--out-dir", str(out)])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return out


class RegistryTests(CollectorTestBase):
    def test_list_json_has_expected_collectors(self):
        proc = run_cli(["list", "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        items = {item["name"]: item for item in json.loads(proc.stdout)}
        for name in (
            "env-snapshot",
            "cpu-trace",
            "network-evidence",
            "cpu-power-audit",
            "ibmc-dump",
            "ascend-logs",
        ):
            self.assertIn(name, items)
            self.assertTrue(items[name]["purpose"])
            self.assertTrue(items[name]["outputs"])
            self.assertIn(items[name]["kind"], ("script", "manual"))

    def test_show_gives_delivery_fields(self):
        proc = run_cli(["show", "env-snapshot", "--json"])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        for key in ("purpose", "environments", "privilege", "impact", "outputs", "consumer"):
            self.assertTrue(payload[key], key)
        self.assertTrue(payload["source_command"].startswith("python3 "))
        self.assertTrue(payload["installed"])
        self.assertEqual(payload["consumer"], "ascend-dump-analyzer")

    def test_unknown_name_is_rejected(self):
        proc = run_cli(["show", "does-not-exist"])
        self.assertEqual(proc.returncode, 2)

    def test_every_collector_is_in_dispatch_doc(self):
        doc = (REPO / "skills" / "diagnose" / "references" / "collector-dispatch.md").read_text(
            encoding="utf-8"
        )
        for name in (
            "env-snapshot",
            "cpu-trace",
            "network-evidence",
            "cpu-power-audit",
            "ibmc-dump",
            "ascend-logs",
        ):
            self.assertIn(f"`{name}`", doc, f"采集器 {name} 没有进推荐表，Agent 选不到")

    def test_gate_binds_collector_reference(self):
        gates = (REPO / "skills" / "diagnose" / "references" / "collect-gates.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("id: collector-tooling", gates)
        self.assertIn("sleuth-collectors", gates)
        self.assertTrue((REPO / "references" / "tools" / "sleuth-collectors.yaml").is_file())


class BundleTests(CollectorTestBase):
    def test_script_bundle_contains_files_readme_and_hashes(self):
        out = self.bundle("env-snapshot")
        self.assertTrue((out / "msprechecker_dump.py").is_file())
        self.assertTrue((out / "README.md").is_file())
        manifest = json.loads((out / "collector.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "env-snapshot")
        self.assertTrue(manifest["files"])
        for item in manifest["files"]:
            digest = hashlib.sha256((out / item["path"]).read_bytes()).hexdigest()
            self.assertEqual(digest, item["sha256"])
        self.assertIn("--no-probes", manifest["command"])
        self.assertIn("ascend-dump-analyzer", (out / "README.md").read_text(encoding="utf-8"))

    def test_network_bundle_keeps_import_layout(self):
        out = self.bundle("network-evidence")
        self.assertTrue((out / "scripts" / "collect_network_evidence.py").is_file())
        self.assertTrue((out / "hostbind" / "network.py").is_file())
        code = "import sys; sys.path.insert(0, 'scripts'); import hostbind.network; print('ok')"
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(out),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=BASE_ENV,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ok", proc.stdout)

    def test_manual_bundle_copies_instruction(self):
        out = self.bundle("ibmc-dump")
        self.assertTrue((out / "ibmc-dump.md").is_file())
        self.assertTrue((out / "README.md").is_file())
        manifest = json.loads((out / "collector.json").read_text(encoding="utf-8"))
        self.assertIsNone(manifest["command"])
        self.assertTrue(manifest["steps"])

    def test_cpu_trace_bundle_recommends_scoped_capture(self):
        out = self.bundle("cpu-trace")
        manifest = json.loads((out / "collector.json").read_text(encoding="utf-8"))
        command = manifest["command"]
        for option in (
            "--minimal", "--no-hostbound", "--no-ascend-dump", "--duration 5",
            "--buffer-size 1024", "--cpu-list '<业务CPU列表>'",
        ):
            self.assertIn(option, command)
        self.assertNotIn(" -p ", command)
        self.assertIn("每 CPU 请求 1 MiB", manifest["impact"])

    def test_bundle_does_not_run_collection(self):
        out = self.tmp / "bundles" / "no-run"
        proc = run_cli(["bundle", "env-snapshot", "--out-dir", str(out), "--json"])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(list(out.glob("snapshot*.json")), [], "打包不应执行采集")
        self.assertFalse((out / "result.json").exists())

    def test_bundle_refuses_non_empty_dir(self):
        out = self.tmp / "bundles" / "occupied"
        out.mkdir(parents=True)
        (out / "keep.txt").write_text("keep", encoding="utf-8")
        proc = run_cli(["bundle", "env-snapshot", "--out-dir", str(out)])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("拒绝覆盖", proc.stderr)
        self.assertTrue((out / "keep.txt").is_file(), "拒绝时不应改动已有文件")


if __name__ == "__main__":
    unittest.main()
