"""端到端冒烟：candidate → worktree → 回放收集 → 判定 → 记录。

不调用模型、不联网：用合成 trace 代替真实 diagnose。覆盖两条路径：
- tooling 候选（4 条成对翻盘）走 accept，并写 Run/Conclusion；
- knowledge 候选只有 2 条可命中时，容量不足会把 accept 降为 insufficient。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.pilot import collect, decide, prepare  # noqa: E402


SKILL_TEXT = "# diagnose\n\n阶段二载全文，按知识候选核对。\n"
TOOL_TEXT = "def fetch(ref):\n    return ref\n"


def _trace(sid, *, hits=True, calls=3, cache=0):
    events = [
        {"action": "load_index", "considered_candidates": ["C-1", "C-2"]},
        {"action": "load_full", "candidates": ["C-1"]},
        {"action": "quickly_check", "case": "C-1"},
    ]
    if hits:
        events.append({"action": "hit", "case": "C-1", "step": 3})
    events.append({
        "action": "source_analysis", "repo": "r", "ref": "main",
        "files_read": ["a.py"],
        "tool_calls": ["src_fetch.py r main"] * calls,
        "tool_ms": 10.0, "cache_hits": cache, "fetch_exit": 0,
    })
    return {
        "session_id": sid, "harness_session": f"h-{sid}",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:02+00:00",
        "trace": events,
    }


class _Repo:
    def __init__(self, root: Path):
        self.root = root
        (root / "skills" / "diagnose").mkdir(parents=True)
        (root / "scripts").mkdir()
        (root / "eval").mkdir()
        (root / "skills" / "diagnose" / "SKILL.md").write_text(SKILL_TEXT, encoding="utf-8")
        (root / "scripts" / "src_fetch.py").write_text(TOOL_TEXT, encoding="utf-8")
        (root / "eval" / "policy.yaml").write_text(
            "decision:\n  alpha: 0.10\ncost:\n  primary_dimension: tokens\n"
            "  B: 0.10\n  epsilon: 0.10\n  delta: 0\nsamples:\n  field_eval: 4\n",
            encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(root), "-c", "user.email=a@b", "-c", "user.name=t",
             "commit", "-qm", "init"], check=True)


class E2ELoopTest(unittest.TestCase):
    def _run(self, target, patch, hits, judge_ids=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "repo"
        root.mkdir()
        _Repo(root)
        output = Path(tmp.name) / "pilot"
        samples = []
        for index, sid in enumerate(("E2E-1001", "E2E-1002", "E2E-1003", "E2E-1004")):
            path = Path(tmp.name) / f"{sid}.yaml"
            path.write_text(yaml.safe_dump({
                "id": sid, "source": f"github/e2e#{sid}",
                "input": {"title": sid}, "expected": {"resolution": "ok"},
            }), encoding="utf-8")
            samples.append(str(path))
        candidate = {
            "candidate_id": "C-E2E-001", "target_kind": target,
            "target_component": patch["region"], "region": patch["region"],
            "file": patch["file"], "old_text": patch["old"], "new_text": patch["new"],
            "base_rev": "HEAD", "checks": patch.get("checks", []),
        }
        cand_path = Path(tmp.name) / "candidate.json"
        cand_path.write_text(json.dumps(candidate), encoding="utf-8")
        prepare(root, cand_path, samples, output)
        short_ids = ("1001", "1002", "1003", "1004")
        for arm in ("baseline", "candidate"):
            for index, sid in enumerate(short_ids):
                doc = _trace(sid, hits=(index < hits.get(arm, 0)),
                             calls=3 if arm == "baseline" else 1)
                (output / arm / "traces" / f"{sid}.yaml").write_text(
                    yaml.safe_dump(doc), encoding="utf-8")
                (output / arm / "out" / f"{sid}.out.md").write_text("report", encoding="utf-8")
        judged = tuple(judge_ids or short_ids)
        judge = {
            "baseline": {sid: 0 for sid in judged},
            "candidate": {sid: 1 for sid in judged},
        }
        judge_path = Path(tmp.name) / "judge.json"
        judge_path.write_text(json.dumps(judge), encoding="utf-8")
        collected = collect(output, judge=judge_path)
        result = decide(output, judge_path, yaml.safe_load(
            (root / "eval" / "policy.yaml").read_text(encoding="utf-8")))
        return root, output, collected, result, judge_path

    def test_tooling_candidate_accepts_and_records(self):
        root, output, collected, result, judge_path = self._run(
            "tooling",
            {"region": "tooling.source_fetch", "file": "scripts/src_fetch.py",
             "old": "def fetch(ref):\n    return ref\n",
             "new": "def fetch(ref):\n    return ref.strip()\n",
             "checks": ["py_compile"]},
            hits={"baseline": 0, "candidate": 0},
        )
        conclusion = result["conclusion"]
        self.assertEqual(conclusion["decision"], "accept")
        self.assertEqual((conclusion["b"], conclusion["c"], conclusion["n"]), (4, 0, 4))
        self.assertAlmostEqual(conclusion["p_value"], 0.0625)
        self.assertEqual(conclusion["versions"]["protocol"], "evolve-v1")
        self.assertEqual(conclusion["versions"]["candidate"], "C-E2E-001")
        self.assertEqual(result["runs"]["written"], 8)
        base = output.parent
        self.assertTrue((base / "conclusions.jsonl").exists())
        self.assertTrue((base / "runs.jsonl").exists())
        self.assertEqual(len((base / "runs.jsonl").read_text(encoding="utf-8").splitlines()), 8)
        # 候选 worktree 里补丁生效，src_fetch 可解析。
        self.assertIn("strip", (output / "candidate-worktree" / "scripts" / "src_fetch.py")
                      .read_text(encoding="utf-8"))
        policy = yaml.safe_load((root / "eval" / "policy.yaml").read_text(encoding="utf-8"))
        again = decide(output, judge_path, policy, reuse_index=0)
        self.assertTrue(again.get("duplicate"))
        self.assertEqual(len((output.parent / "conclusions.jsonl")
                             .read_text(encoding="utf-8").splitlines()), 1)
        changed = json.loads((output / "tasks.json").read_text(encoding="utf-8"))
        changed["candidate_id"] = "C-OTHER"
        (output / "tasks.json").write_text(json.dumps(changed), encoding="utf-8")
        third = decide(output, judge_path, policy)
        self.assertFalse(third.get("duplicate"))
        fourth = decide(output, judge_path, policy, reuse_index=2)
        self.assertFalse(fourth.get("duplicate"))

    def test_prepare_reuses_baseline_traces(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "repo"
        root.mkdir()
        _Repo(root)
        output = Path(tmp.name) / "pilot"
        samples = []
        for sid in ("E2E-1001", "E2E-1002"):
            path = Path(tmp.name) / f"{sid}.yaml"
            path.write_text(yaml.safe_dump({
                "id": sid, "source": f"github/e2e#{sid}",
                "input": {"title": sid}, "expected": {"resolution": "ok"},
            }), encoding="utf-8")
            samples.append(str(path))
        candidate = {
            "candidate_id": "C-E2E-001", "target_kind": "tooling",
            "target_component": "tooling.source_fetch", "region": "tooling.source_fetch",
            "file": "scripts/src_fetch.py",
            "old_text": "def fetch(ref):\n    return ref\n",
            "new_text": "def fetch(ref):\n    return ref.strip()\n",
            "base_rev": "HEAD", "checks": ["py_compile"],
        }
        cand_path = Path(tmp.name) / "candidate.json"
        cand_path.write_text(json.dumps(candidate), encoding="utf-8")
        source = Path(tmp.name) / "old-pilot"
        for arm in ("traces", "out"):
            (source / arm).mkdir(parents=True)
        for sid in ("1001", "1002"):
            (source / "traces" / f"{sid}.yaml").write_text(
                yaml.safe_dump(_trace(sid, hits=True, calls=3)), encoding="utf-8")
            (source / "out" / f"{sid}.out.md").write_text("report", encoding="utf-8")
        tasks = prepare(root, cand_path, samples, output, baseline_traces=source)
        self.assertTrue(tasks["budget"]["baseline_reused"])
        self.assertTrue(tasks["arms"]["baseline"]["reused"])
        self.assertEqual(tasks["budget"]["baseline_source"], str(source))
        self.assertTrue((output / "baseline" / "traces" / "1001.yaml").exists())
        self.assertTrue((output / "baseline" / "out" / "1002.out.md").exists())
        self.assertFalse((output / "candidate" / "traces" / "1001.yaml").exists())

    def test_small_pool_cannot_accept(self):
        root, output, collected, result, judge_path = self._run(
            "skill",
            {"region": "diagnose.knowledge_usage", "file": "skills/diagnose/SKILL.md",
             "old": "阶段二载全文，按知识候选核对。",
             "new": "阶段二只载筛出的候选全文，按知识候选核对。"},
            hits={"baseline": 1, "candidate": 2},
            judge_ids=("1001", "1002"),
        )
        conclusion = result["conclusion"]
        self.assertEqual(conclusion["decision"], "insufficient")
        self.assertEqual((conclusion["b"], conclusion["c"], conclusion["n"]), (2, 0, 2))


if __name__ == "__main__":
    unittest.main()
