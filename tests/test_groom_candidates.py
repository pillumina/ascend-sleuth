"""Groom 候选检索：只在快照内查、候选有界、弱证据不排除、无候选不编造。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tests.groom_fixtures import (  # noqa: E402
    git, init_repo, make_index, run_py, snapshot_meta, write_case, write_draft, write_json,
)


class CandidateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="groom-cand-")
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.repo = init_repo(base / "repo")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-LINK.yaml",
                   cid="CASE-LINK", title="HCCL collective timeout caused by network link down",
                   symptoms=("HCCL timeout during allreduce", "network link down on NPU"),
                   root_cause="network link failure causes HCCL collective timeout",
                   fix="check switch port and link", tags=("hccl", "network", "timeout"))
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-OOM.yaml",
                   cid="CASE-OOM", title="KV cache OOM at startup",
                   symptoms=("NPU out of memory",), root_cause="KV cache too large",
                   fix="reduce max model len", tags=("oom", "kv-cache"))
        write_case(self.repo, "knowledge/common/interrupt/CASE-PORT.yaml",
                   cid="CASE-PORT", title="HCCL communication timeout due to port conflict",
                   symptoms=("HCCL init timeout", "port already in use"),
                   root_cause="HCCL port conflict", fix="change port range",
                   tags=("hccl", "port"))
        write_case(self.repo, "knowledge/training/verl/interrupt/CASE-VERL.yaml",
                   cid="CASE-VERL", title="GRPO HCCL timeout after link flap",
                   symptoms=("collective timeout", "link flap"),
                   root_cause="interconnect interruption blocks collective communication",
                   fix="restore interconnect", tags=("hccl", "collective", "link"))
        make_index(self.repo)
        self.meta = write_json(base / "meta.json", snapshot_meta(self.repo))
        self.draft = write_draft(
            self.repo, key="draft-link",
            cid="DRAFT-LINK",
            title="网络链路中断导致集合通信卡住",
            symptoms=("HCCL timeout during allreduce", "interconnect interruption blocked collective communication"),
            root_cause="网络链路故障导致 HCCL 超时",
            fix="恢复链路后重启", tags=("hccl", "network", "link"),
        )
        self.out = base / "work.json"

    def _run(self, *extra):
        return run_py(self.repo, "scripts/groom_candidates.py", "--snapshot", str(self.meta),
                      "--draft", str(self.draft), "--out", str(self.out), *extra)

    def test_finds_paraphrase_and_excludes_unrelated(self):
        p = self._run("--top", "3")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        doc = json.loads(self.out.read_text(encoding="utf-8"))
        order = doc["orders"][0]
        ids = [c["id"] for c in order["candidates"]]
        self.assertLessEqual(len(ids), 3)
        self.assertIn("CASE-LINK", ids)
        self.assertNotIn("CASE-OOM", ids)
        self.assertGreater(order["omitted_candidates"], 0)
        self.assertTrue(all(c.get("root_cause") for c in order["candidates"]))

    def test_cross_namespace_common_is_available(self):
        p = self._run("--top", "4")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        doc = json.loads(self.out.read_text(encoding="utf-8"))
        ids = [c["id"] for c in doc["orders"][0]["candidates"]]
        # common/ 的 HCCL 端口冲突是跨框架权威记录，应在有界候选里被看到
        self.assertIn("CASE-PORT", ids)

    def test_hard_cap_even_if_asked_for_more(self):
        p = self._run("--top", "99")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        doc = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertLessEqual(len(doc["orders"][0]["candidates"]), 8)

    def test_no_drafts_is_not_an_error(self):
        empty = init_repo(Path(self.tmp.name) / "empty")
        meta = write_json(Path(self.tmp.name) / "empty-meta.json", snapshot_meta(empty))
        p = run_py(empty, "scripts/groom_candidates.py", "--snapshot", str(meta), "--all")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("没有草稿", p.stdout)

    def test_missing_index_fails_closed(self):
        bad = init_repo(Path(self.tmp.name) / "bad")
        write_draft(bad, key="bad-draft", cid="BAD-1", title="HCCL timeout")
        meta = write_json(Path(self.tmp.name) / "bad-meta.json", snapshot_meta(bad))
        p = run_py(bad, "scripts/groom_candidates.py", "--snapshot", str(meta), "--all")
        self.assertEqual(p.returncode, 2)

    def test_draft_not_in_inbox_still_works(self):
        outside = write_draft(Path(self.tmp.name) / "outside", key="outside",
                              cid="OUT-1", title="HCCL timeout link")
        p = run_py(self.repo, "scripts/groom_candidates.py", "--snapshot", str(self.meta),
                   "--draft", str(outside), "--out", str(self.out))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(self.out.exists())


if __name__ == "__main__":
    unittest.main()
