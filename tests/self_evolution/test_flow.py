# -*- coding: utf-8 -*-
"""Proposal -> candidate -> pilot -> judge -> gate -> archive 端到端。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.flow import FlowError, _experiment_record, run_proposal  # noqa: E402
from evolve.policy import load_policy  # noqa: E402


def _policy():
    policy = load_policy(None)
    policy["samples"]["field_eval"] = 4
    return policy
from tests.self_evolution.test_cli import run_cli  # noqa: E402
from evolve.proposal_engine import ProposalArchive, ProposalEngine  # noqa: E402
from evolve.readback import latest_by_proposal  # noqa: E402
from evolve.rsi_store import RSIStore  # noqa: E402


def _repo(root: Path):
    (root / "skills" / "diagnose").mkdir(parents=True)
    (root / "skills" / "diagnose" / "SKILL.md").write_text(
        "# diagnose\n\n阶段二载全文，按知识候选核对。\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)


def _draft():
    return {
        "target_kind": "skill",
        "target_component": "diagnose.verification_checklist",
        "summary": "阶段二只载筛出的候选",
        "expected": "读取量下降",
        "risk": "低",
        "rollback": "恢复原阶段二",
        "candidate": {
            "candidate_id": "C-FLOW-1", "target_kind": "skill",
            "target_component": "diagnose.verification_checklist",
            "region": "diagnose.verification_checklist",
            "file": "skills/diagnose/SKILL.md", "base_rev": "HEAD",
            "old_text": "阶段二载全文，按知识候选核对。\n",
            "new_text": "阶段二只载筛出的候选全文，按知识候选核对。\n",
        },
    }


class FlowTest(unittest.TestCase):
    def test_proposal_to_decision_and_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"; root.mkdir(); _repo(root)
            archive = ProposalArchive(Path(td) / "proposals.jsonl")
            engine = ProposalEngine(archive)
            proposal = engine.add(_draft())
            samples = []
            for i in range(4):
                path = Path(td) / f"S-{1000+i}.yaml"
                path.write_text(yaml.safe_dump({
                    "id": f"S-{1000+i}", "source": f"github/x/{i}",
                    "input": {"title": f"S-{i}"}, "expected": {"resolution": "ok"},
                }), encoding="utf-8")
                samples.append(str(path))
            judge = Path(td) / "judge.json"
            judge.write_text(json.dumps({
                "baseline": {str(1000+i): 0 for i in range(4)},
                "candidate": {str(1000+i): 1 for i in range(4)},
                "meta": {"agent": "test"},
            }), encoding="utf-8")

            def runner(tasks):
                for arm in ("baseline", "candidate"):
                    for sample in tasks["samples"]:
                        sid = sample["short_id"]
                        (Path(tasks["arms"][arm]["trace_dir"]) / f"{sid}.yaml").write_text(
                            yaml.safe_dump({"session_id": sid, "model": "test", "trace": []}),
                            encoding="utf-8")
                        (Path(tasks["arms"][arm]["out_dir"]) / f"{sid}.out.md").write_text(
                            "ok", encoding="utf-8")

            result = run_proposal(root, proposal, samples, Path(td) / "pilot",
                                  _policy(), judge, archive, runner=runner,
                                  card="EV-2026-001")
            self.assertEqual(result["conclusion"]["decision"], "accept")
            self.assertEqual(result["conclusion"]["card"], "EV-2026-001")
            self.assertEqual(result["experiment"]["ev_card"], "EV-2026-001")
            self.assertEqual(result["conclusion"]["proposal"], proposal.id)
            rows = ProposalArchive(Path(td) / "proposals.jsonl").read()
            self.assertEqual(rows[-1]["status"], "accept")
            record = latest_by_proposal(proposal.id, Path(td))
            self.assertEqual(record["decision"], "accept")
            exp = json.loads((Path(td) / "experiments.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(exp["proposal"], proposal.id)
            self.assertEqual(exp["decision"], "accept")
            self.assertEqual(len(exp["stage_reports"]), 7)
            self.assertEqual(set(exp["baseline"]["per_sample"]), set(exp["samples"]))
            self.assertEqual(exp["proposal_snapshot"]["id"], proposal.id)
            self.assertEqual(exp["conclusion_snapshot"]["decision"], "accept")
            events = RSIStore(Path(td)).history(proposal_id=proposal.id)
            self.assertEqual(events[-1]["kind"], "experiment")
            self.assertEqual(events[-1]["data"]["proposal"]["id"], proposal.id)
            self.assertEqual(events[-1]["data"]["rollout"]["decision"], "accept")
            self.assertEqual(len(events[-1]["data"]["rollout"]["arms"]), 2)
            self.assertTrue((Path(td) / "pilot" / "candidate-worktree").exists())

    def test_cli_flow_with_external_runner(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"; root.mkdir(); _repo(root)
            draft = Path(td) / "draft.json"
            draft.write_text(json.dumps(_draft(), ensure_ascii=False), encoding="utf-8")
            samples = []
            for i in range(4):
                path = Path(td) / f"S-{2000+i}.yaml"
                path.write_text(yaml.safe_dump({
                    "id": f"S-{2000+i}", "source": f"github/x/{i}",
                    "input": {"title": f"S-{i}"}, "expected": {"resolution": "ok"},
                }), encoding="utf-8")
                samples.append(str(path))
            judge = Path(td) / "judge.json"
            judge.write_text(json.dumps({
                "baseline": {str(2000+i): 0 for i in range(4)},
                "candidate": {str(2000+i): 1 for i in range(4)},
                "meta": {"agent": "test"},
            }), encoding="utf-8")
            policy_path = Path(td) / "policy.yaml"
            policy_path.write_text("samples:\n  field_eval: 4\n", encoding="utf-8")
            result = run_cli(
                "experiment", "flow", "--root", str(root),
                "--proposal", str(draft), "--samples", *samples,
                "--policy", str(policy_path),
                "--output", str(Path(td) / "pilot"), "--judge", str(judge),
                "--runner-command", json.dumps([
                    sys.executable, "-c",
                    "import os,pathlib;"
                    "pathlib.Path(os.environ['SLEUTH_TRACE']).write_text("
                    "'session_id: '+os.environ['SLEUTH_SHORT_ID']+'\\ntrace: []\\n');"
                    "pathlib.Path(os.environ['SLEUTH_OUT']).write_text('ok')",
                ]),
                "--archive", str(Path(td) / "proposals.jsonl"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["decision"], "accept")

    def test_rejected_proposal_rolls_back_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"; root.mkdir(); _repo(root)
            archive = ProposalArchive(Path(td) / "proposals.jsonl")
            engine = ProposalEngine(archive)
            proposal = engine.add(_draft())
            samples = []
            for i in range(4):
                path = Path(td) / f"S-{3000+i}.yaml"
                path.write_text(yaml.safe_dump({
                    "id": f"S-{3000+i}", "source": f"github/x/{i}",
                    "input": {"title": f"S-{i}"}, "expected": {"resolution": "ok"},
                }), encoding="utf-8")
                samples.append(str(path))
            judge = Path(td) / "judge.json"
            judge.write_text(json.dumps({
                "baseline": {str(3000+i): 1 for i in range(4)},
                "candidate": {str(3000+i): 0 for i in range(4)},
                "meta": {"agent": "test"},
            }), encoding="utf-8")

            def runner(tasks):
                for arm in ("baseline", "candidate"):
                    for sample in tasks["samples"]:
                        sid = sample["short_id"]
                        (Path(tasks["arms"][arm]["trace_dir"]) / f"{sid}.yaml").write_text(
                            yaml.safe_dump({"session_id": sid, "model": "test", "trace": []}),
                            encoding="utf-8")
                        (Path(tasks["arms"][arm]["out_dir"]) / f"{sid}.out.md").write_text(
                            "ok", encoding="utf-8")

            result = run_proposal(root, proposal, samples, Path(td) / "pilot",
                                  _policy(), judge, archive, runner=runner)
            self.assertNotEqual(result["decision"], "accept")
            self.assertFalse((Path(td) / "pilot" / "candidate-worktree").exists())
            rows = ProposalArchive(Path(td) / "proposals.jsonl").read()
            self.assertTrue(rows[-1]["rolled_back"])
            artifact = result["event"]["data"]["proposal"]["artifact"]
            self.assertTrue(artifact["diff"].startswith("diff --git"))
            self.assertEqual(artifact["diff_kind"], "unified")
            self.assertNotIn("workspace", artifact)

    def test_adapter_fallback_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"; root.mkdir(); _repo(root)
            archive = ProposalArchive(Path(td) / "proposals.jsonl")
            proposal = ProposalEngine(archive).add(_draft())
            sample = Path(td) / "S-4000.yaml"
            sample.write_text(yaml.safe_dump({
                "id": "S-4000", "source": "github/x/0",
                "input": {"title": "S-0"}, "expected": {"resolution": "ok"},
            }), encoding="utf-8")
            judge = Path(td) / "judge.json"
            judge.write_text(json.dumps({"baseline": {"4000": 0}, "candidate": {"4000": 1},
                                         "meta": {"agent": "test"}}), encoding="utf-8")

            def runner(tasks):
                for arm in ("baseline", "candidate"):
                    for row in tasks["samples"]:
                        sid = row["short_id"]
                        (Path(tasks["arms"][arm]["trace_dir"]) / f"{sid}.yaml").write_text(
                            yaml.safe_dump({"adapter_fallback": True, "trace": []}),
                            encoding="utf-8")
                        (Path(tasks["arms"][arm]["out_dir"]) / f"{sid}.out.md").write_text(
                            "ok", encoding="utf-8")

            with self.assertRaises(FlowError):
                run_proposal(root, proposal, [str(sample)], Path(td) / "pilot",
                             _policy(), judge, archive, runner=runner)

    def test_harness_proposal_reaches_experiment_record(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"; root.mkdir(); _repo(root)
            (root / "eval").mkdir()
            (root / "eval" / "scheduler.yaml").write_text("scheduler: old\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "scheduler"], cwd=root, check=True)
            archive = ProposalArchive(Path(td) / "proposals.jsonl")
            proposal = ProposalEngine(archive).add({
                "target_kind": "harness",
                "target_component": "harness.scheduler",
                "summary": "调整调度",
                "expected": "减少空转",
                "risk": "高",
                "rollback": "恢复调度",
                "candidate": {
                    "candidate_id": "C-HF-1", "target_kind": "harness",
                    "target_component": "harness.scheduler",
                    "region": "harness.scheduler",
                    "file": "eval/scheduler.yaml", "base_rev": "HEAD",
                    "old_text": "scheduler: old\n",
                    "new_text": "scheduler: new\n",
                },
            })
            samples = []
            for i in range(4):
                path = Path(td) / f"S-{5000+i}.yaml"
                path.write_text(yaml.safe_dump({
                    "id": f"S-{5000+i}", "source": f"github/x/{i}",
                    "input": {"title": f"S-{i}"}, "expected": {"resolution": "ok"},
                }), encoding="utf-8")
                samples.append(str(path))
            judge = Path(td) / "judge.json"
            judge.write_text(json.dumps({
                "baseline": {str(5000+i): 0 for i in range(4)},
                "candidate": {str(5000+i): 1 for i in range(4)},
                "meta": {"agent": "test"},
            }), encoding="utf-8")

            def runner(tasks):
                for arm in ("baseline", "candidate"):
                    for row in tasks["samples"]:
                        sid = row["short_id"]
                        (Path(tasks["arms"][arm]["trace_dir"]) / f"{sid}.yaml").write_text(
                            yaml.safe_dump({"session_id": sid, "trace": []}), encoding="utf-8")
                        (Path(tasks["arms"][arm]["out_dir"]) / f"{sid}.out.md").write_text(
                            "ok", encoding="utf-8")

            result = run_proposal(root, proposal, samples, Path(td) / "pilot",
                                  _policy(), judge, archive, runner=runner)
            self.assertEqual(result["decision"], "accept")
            exp = json.loads((Path(td) / "experiments.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(exp["target_kind"], "harness")
            self.assertEqual(exp["proposal"], proposal.id)

    def test_usage_accept_record_carries_usage_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            archive = ProposalArchive(Path(td) / "proposals.jsonl")
            proposal = ProposalEngine(archive).add({
                "target_kind": "skill",
                "target_component": "diagnose.knowledge_usage",
                "summary": "只载候选",
                "change": {"files": ["skills/diagnose/SKILL.md"], "diff": "+ x"},
                "expected": "读取下降", "risk": "低", "rollback": "恢复",
            })
            samples = [{"id": f"S-{6000+i}", "short_id": str(6000+i)} for i in range(4)]
            judge = Path(td) / "judge.json"
            judge.write_text(json.dumps({
                "baseline": {str(6000+i): 0 for i in range(4)},
                "candidate": {str(6000+i): 1 for i in range(4)},
                "meta": {"agent": "test"},
            }), encoding="utf-8")
            def usage(read, tokens):
                return [{
                    "sample_id": str(6000+i), "hit": True, "wrong_cases": 0,
                    "candidates_examined": 2, "full_body_reads": read,
                    "reference_lookups": 0, "first_hit_step": 1,
                    "tokens": tokens, "elapsed_ms": 100.0, "resolution_ok": True,
                } for i in range(4)]
            collected = {"arms": {
                "baseline": [{"knowledge_usage": row} for row in usage(4, 1000)],
                "candidate": [{"knowledge_usage": row} for row in usage(1, 400)],
            }}
            record = _experiment_record(proposal, {"samples": samples}, judge, "accept",
                                        {"b": 4, "c": 0, "n": 4, "alpha_eff": 0.1}, collected)
            self.assertEqual(record["knowledge_usage"]["decision"], "accept")
            self.assertIn("full_body_reads", record["knowledge_usage"]["deltas"])

    def test_dry_run_prepares_without_judge(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"; root.mkdir(); _repo(root)
            engine = ProposalEngine(ProposalArchive(Path(td) / "proposals.jsonl"))
            proposal = engine.add(_draft())
            sample = Path(td) / "S-7000.yaml"
            sample.write_text(yaml.safe_dump({
                "id": "S-7000", "source": "github/x/0",
                "input": {"title": "S-0"}, "expected": {"resolution": "ok"},
            }), encoding="utf-8")
            result = run_proposal(root, proposal, [str(sample)], Path(td) / "pilot",
                                  _policy(), None,
                                  ProposalArchive(Path(td) / "proposals.jsonl"),
                                  dry_run=True)
            self.assertTrue(result["dry_run"])
            self.assertTrue((Path(td) / "pilot" / "tasks.json").exists())
            self.assertTrue((Path(td) / "pilot" / "candidate-worktree").exists())

    def test_knowledge_and_tooling_proposals_reach_experiment_records(self):
        cases = [
            ("knowledge", "knowledge.case_content", {
                "candidate_id": "C-KF-1", "target_kind": "knowledge",
                "target_component": "knowledge.case_content",
                "region": "knowledge.case_content",
                "file": "knowledge/inference/vllm-ascend/case.yaml",
                "base_rev": "HEAD",
                "old_text": "quickly_check: old\n",
                "new_text": "quickly_check: new\n",
            }, "knowledge/inference/vllm-ascend/case.yaml",
               "id: K-1\nquickly_check: old\n"),
            ("tooling", "tooling.source_fetch", {
                "candidate_id": "C-TF-1", "target_kind": "tooling",
                "target_component": "tooling.source_fetch",
                "region": "tooling.source_fetch",
                "file": "scripts/src_fetch.py", "base_rev": "HEAD",
                "old_text": "def fetch(ref):\n    return ref\n",
                "new_text": "def fetch(ref):\n    return ref.strip()\n",
            }, "scripts/src_fetch.py",
               "def fetch(ref):\n    return ref\n"),
        ]
        for index, (target, component, candidate, path, content) in enumerate(cases):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td) / "repo"; root.mkdir(); _repo(root)
                file = root / path
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(content, encoding="utf-8")
                subprocess.run(["git", "add", "."], cwd=root, check=True)
                subprocess.run(["git", "commit", "-qm", "case"], cwd=root, check=True)
                archive = ProposalArchive(Path(td) / "proposals.jsonl")
                proposal = ProposalEngine(archive).add({
                    "target_kind": target, "target_component": component,
                    "summary": "target flow", "expected": "effect",
                    "risk": "低", "rollback": "restore",
                    "candidate": candidate,
                })
                samples = []
                for i in range(4):
                    sample = Path(td) / f"S-{8000+index*10+i}.yaml"
                    sample.write_text(yaml.safe_dump({
                        "id": f"S-{8000+index*10+i}", "source": f"github/x/{i}",
                        "input": {"title": f"S-{i}"}, "expected": {"resolution": "ok"},
                    }), encoding="utf-8")
                    samples.append(str(sample))
                judge = Path(td) / "judge.json"
                judge.write_text(json.dumps({
                    "baseline": {str(8000+index*10+i): 0 for i in range(4)},
                    "candidate": {str(8000+index*10+i): 1 for i in range(4)},
                    "meta": {"agent": "test"},
                }), encoding="utf-8")

                def runner(tasks):
                    for arm in ("baseline", "candidate"):
                        for row in tasks["samples"]:
                            sid = row["short_id"]
                            (Path(tasks["arms"][arm]["trace_dir"]) / f"{sid}.yaml").write_text(
                                yaml.safe_dump({"session_id": sid, "trace": []}),
                                encoding="utf-8")
                            (Path(tasks["arms"][arm]["out_dir"]) / f"{sid}.out.md").write_text(
                                "ok", encoding="utf-8")

                result = run_proposal(root, proposal, samples, Path(td) / "pilot",
                                      _policy(), judge, archive, runner=runner)
                self.assertEqual(result["decision"], "accept")
                exp = json.loads((Path(td) / "experiments.jsonl").read_text(encoding="utf-8").splitlines()[-1])
                self.assertEqual(exp["target_kind"], target)
                self.assertEqual(exp["proposal"], proposal.id)

    def test_incomplete_trace_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"; root.mkdir(); _repo(root)
            archive = ProposalArchive(Path(td) / "proposals.jsonl")
            proposal = ProposalEngine(archive).add(_draft())
            sample = Path(td) / "S-9000.yaml"
            sample.write_text(yaml.safe_dump({
                "id": "S-9000", "source": "github/x/0",
                "input": {"title": "S-0"}, "expected": {"resolution": "ok"},
            }), encoding="utf-8")
            judge = Path(td) / "judge.json"
            judge.write_text(json.dumps({"baseline": {"9000": 0}, "candidate": {"9000": 1},
                                         "meta": {"agent": "test"}}), encoding="utf-8")
            with self.assertRaises(Exception):
                run_proposal(root, proposal, [str(sample)], Path(td) / "pilot",
                             _policy(), judge, archive, runner=lambda tasks: None)
            self.assertFalse((Path(td) / "conclusions.jsonl").exists())

    def test_small_pool_cannot_accept(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"; root.mkdir(); _repo(root)
            archive = ProposalArchive(Path(td) / "proposals.jsonl")
            proposal = ProposalEngine(archive).add(_draft())
            samples = []
            for i in range(4):
                sample = Path(td) / f"S-{9500+i}.yaml"
                sample.write_text(yaml.safe_dump({
                    "id": f"S-{9500+i}", "source": f"github/x/{i}",
                    "input": {"title": f"S-{i}"}, "expected": {"resolution": "ok"},
                }), encoding="utf-8")
                samples.append(str(sample))
            judge = Path(td) / "judge.json"
            judge.write_text(json.dumps({
                "baseline": {str(9500+i): 0 for i in range(4)},
                "candidate": {str(9500+i): 1 for i in range(4)},
                "meta": {"agent": "test"},
            }), encoding="utf-8")

            def runner(tasks):
                for arm in ("baseline", "candidate"):
                    for row in tasks["samples"]:
                        sid = row["short_id"]
                        (Path(tasks["arms"][arm]["trace_dir"]) / f"{sid}.yaml").write_text(
                            yaml.safe_dump({"session_id": sid, "trace": []}), encoding="utf-8")
                        (Path(tasks["arms"][arm]["out_dir"]) / f"{sid}.out.md").write_text(
                            "ok", encoding="utf-8")

            result = run_proposal(root, proposal, samples, Path(td) / "pilot",
                                  load_policy(None), judge, archive, runner=runner)
            self.assertEqual(result["decision"], "insufficient")
            self.assertIn("capacity_short", (result["conclusion"] or {}).get("reason", ""))

    def test_judge_provenance_is_required(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"; root.mkdir(); _repo(root)
            archive = ProposalArchive(Path(td) / "proposals.jsonl")
            proposal = ProposalEngine(archive).add(_draft())
            sample = Path(td) / "S-9900.yaml"
            sample.write_text(yaml.safe_dump({
                "id": "S-9900", "source": "github/x/0",
                "input": {"title": "S-0"}, "expected": {"resolution": "ok"},
            }), encoding="utf-8")
            judge = Path(td) / "judge.json"
            judge.write_text(json.dumps({"baseline": {"9900": 0}, "candidate": {"9900": 1}}),
                             encoding="utf-8")

            def runner(tasks):
                for arm in ("baseline", "candidate"):
                    for row in tasks["samples"]:
                        sid = row["short_id"]
                        (Path(tasks["arms"][arm]["trace_dir"]) / f"{sid}.yaml").write_text(
                            yaml.safe_dump({"session_id": sid, "trace": []}), encoding="utf-8")
                        (Path(tasks["arms"][arm]["out_dir"]) / f"{sid}.out.md").write_text(
                            "ok", encoding="utf-8")

            with self.assertRaises(FlowError):
                run_proposal(root, proposal, [str(sample)], Path(td) / "pilot",
                             load_policy(None), judge, archive, runner=runner)

    def test_requires_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            engine = ProposalEngine(ProposalArchive(Path(td) / "proposals.jsonl"))
            p = engine.add({
                "target_kind": "skill", "target_component": "diagnose.knowledge_usage",
                "summary": "x", "change": {"files": ["skills/diagnose/SKILL.md"], "diff": "+ x"},
                "expected": "x", "risk": "低", "rollback": "x",
            })
            with self.assertRaises(Exception):
                run_proposal(Path(td), p, ["s"], Path(td) / "out", _policy(),
                             Path(td) / "j", ProposalArchive(Path(td) / "a.jsonl"))


if __name__ == "__main__":
    unittest.main()
