"""CLI 回归：help、策略命令、样本生命周期子进程与 judge 输出。"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import yaml  # noqa: E402

from evolve import cli  # noqa: E402
from evolve.adapters import AdapterError  # noqa: E402
from evolve.adapters import issues as issue_adapter  # noqa: E402
from evolve.records import ConclusionStore  # noqa: E402
from evolve.samples import SampleStore  # noqa: E402

SCRIPT = ROOT / "scripts" / "evolve.py"


def run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(cwd or ROOT),
    )


class HelpAndPolicyCliTest(unittest.TestCase):
    def test_help_lists_commands(self):
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("policy", "sample", "judge", "judge-stats", "replay", "brief"):
            self.assertIn(command, result.stdout)

    def test_policy_check_on_tracked_policy(self):
        result = run_cli("policy", "check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("policy: ok", result.stdout)
        self.assertIn("policy_hash:", result.stdout)

    def test_policy_show_includes_defaults(self):
        result = run_cli("policy", "show")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("autonomy:", result.stdout)
        self.assertIn("paired_binary", result.stdout)
        self.assertIn("# policy_hash:", result.stdout)

    def test_policy_autonomy_resolves_component(self):
        normal = run_cli("policy", "autonomy", "--component", "docs.normative")
        self.assertEqual(normal.returncode, 0, normal.stderr)
        self.assertIn("autonomy: A1", normal.stdout)
        non_norm = run_cli("policy", "autonomy", "--component", "docs.non_normative")
        self.assertEqual(non_norm.returncode, 0, non_norm.stderr)
        self.assertIn("autonomy: A2", non_norm.stdout)

    def test_policy_check_unknown_key_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            import yaml
            cfg = yaml.safe_load((ROOT / "sleuth.config.yaml").read_text(encoding="utf-8"))
            cfg["evolution"]["policy"]["surprise"] = True
            (root / "config" / "rsi").mkdir(parents=True)
            (root / "config" / "rsi" / "pipelines.yaml").write_text(
                (ROOT / "config" / "rsi" / "pipelines.yaml").read_text(encoding="utf-8"),
                encoding="utf-8")
            (root / "sleuth.config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
            result = run_cli("policy", "check", "--root", td)
            self.assertEqual(result.returncode, 1)
            self.assertIn("unknown policy key", result.stderr)

    def test_policy_check_defaults_without_config(self):
        with tempfile.TemporaryDirectory() as td:
            result = run_cli("policy", "check", "--root", td)
            self.assertEqual(result.returncode, 0)
            self.assertIn("policy: ok", result.stdout)


class HealthCliTest(unittest.TestCase):
    def test_health_check_broken_metrics_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            metrics = Path(td) / "metrics"
            metrics.mkdir()
            (metrics / "gates.yaml").write_text("gates: [", encoding="utf-8")
            result = run_cli("health", "--root", td, "--check")
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("broken:", result.stdout)
            readout = run_cli("health", "--root", td)
            self.assertEqual(readout.returncode, 0, readout.stdout + readout.stderr)

    def test_traces_sync_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / "traces" / "t1.yaml"
            trace.parent.mkdir()
            trace.write_text("trace:\n- {action: attribution, attribution_kind: execution, component: diagnose}\n", encoding="utf-8")
            first = run_cli("traces", "sync", "--root", td, "--state", str(Path(td) / "state.json"))
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("new=1", first.stdout)
            second = run_cli("traces", "sync", "--root", td, "--state", str(Path(td) / "state.json"))
            self.assertIn("reused=1", second.stdout)
            status = run_cli("traces", "status", "--root", td, "--state", str(Path(td) / "state.json"))
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("snapshot_id", status.stdout)

    def test_health_json_is_machine_readable(self):
        result = run_cli("health", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["available"])
        self.assertIn("check_verdict", payload)


class SampleLifecycleCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def cli(self, *args):
        return run_cli(*args, "--root", str(self.root))

    def create(self, sid="S-1"):
        return self.cli(
            "sample", "new", "--id", sid, "--object-type", "diagnosis",
            "--origin", "field", "--purpose", "evaluation",
            "--source", f"https://example.com/issues/{sid}",
            "--expected", '{"namespace": "inference/vllm-ascend"}',
        )

    def test_full_lifecycle(self):
        created = self.create()
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertIn("created: S-1", created.stdout)
        self.assertIn("status: candidate", created.stdout)

        checked = self.cli("sample", "check", "--id", "S-1")
        self.assertEqual(checked.returncode, 0, checked.stderr)

        listed = self.cli("sample", "list")
        self.assertIn("S-1\tcandidate\tfield\tevaluation\tdiagnosis", listed.stdout)
        self.assertIn("total: 1", listed.stdout)

        reviewed = self.cli("sample", "review", "--id", "S-1", "--approve")
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        self.assertIn("S-1: active", reviewed.stdout)

        promoted = self.cli("sample", "promote", "--id", "S-1", "--to", "core")
        self.assertEqual(promoted.returncode, 0, promoted.stderr)
        self.assertIn("S-1: active (core)", promoted.stdout)
        listed = self.cli("sample", "list", "--status", "active")
        self.assertIn("S-1\tactive\tcore\tevaluation\tdiagnosis", listed.stdout)

        retired = self.cli("sample", "retire", "--id", "S-1")
        self.assertEqual(retired.returncode, 0, retired.stderr)
        self.assertIn("S-1: retired", retired.stdout)

        listed = self.cli("sample", "list", "--status", "retired")
        self.assertIn("S-1\tretired", listed.stdout)

    def test_experiment_gate_scores_knowledge_rubric(self):
        rubric = json.dumps({
            "dimensions": ["来源可追", "根因完整"], "threshold": 0.7,
        })
        created = self.cli(
            "sample", "new", "--id", "K-1", "--object-type", "case",
            "--source", "https://example.com/issues/K-1", "--rubric", rubric,
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        passed = self.cli(
            "experiment", "gate", "--target", "knowledge", "--sample", "K-1",
            "--scores", json.dumps({"来源可追": 2, "根因完整": 2}),
        )
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertIn("passed: true", passed.stdout)
        failed = self.cli(
            "experiment", "gate", "--target", "knowledge", "--sample", "K-1",
            "--scores", json.dumps({"来源可追": 2, "根因完整": 0}),
        )
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertIn("failed_dimensions: 根因完整", failed.stdout)

    def test_experiment_gate_rejects_wrong_object_type(self):
        created = self.cli(
            "sample", "new", "--id", "K-3", "--object-type", "diagnosis",
            "--source", "https://example.com/issues/K-3",
            "--rubric", json.dumps({"dimensions": ["来源可追"]}),
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        result = self.cli(
            "experiment", "gate", "--target", "knowledge", "--sample", "K-3",
            "--scores", json.dumps({"来源可追": 2}),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("object_type", result.stderr)

    def test_experiment_gate_rejects_unimplemented_target(self):
        created = self.cli(
            "sample", "new", "--id", "K-2", "--object-type", "case",
            "--source", "https://example.com/issues/K-2",
            "--rubric", json.dumps({"dimensions": ["来源可追"]}),
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        result = self.cli(
            "experiment", "gate", "--target", "harness", "--sample", "K-2",
            "--scores", json.dumps({"来源可追": 2}),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("no implemented evaluator", result.stderr)

    def test_sample_new_rejects_holdout_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "eval").mkdir()
            (root / "eval" / "holdout.yaml").write_text(
                "entries:\n- fixture: VLLM-ASC-13329.fixture.yaml\n", encoding="utf-8",
            )
            result = run_cli(
                "sample", "new", "--root", td, "--id", "X-1",
                "--object-type", "diagnosis",
                "--source", "https://github.com/vllm-project/vllm-ascend/issues/13329",
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("holdout", result.stderr)

    def test_reject(self):
        self.create()
        result = self.cli("sample", "review", "--id", "S-1", "--reject")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("S-1: rejected", result.stdout)

    def test_duplicate_id_fails(self):
        self.create()
        duplicate = self.create()
        self.assertEqual(duplicate.returncode, 1)
        self.assertIn("duplicate sample id", duplicate.stderr)

    def test_missing_answer_fails_check(self):
        result = self.cli(
            "sample", "new", "--id", "S-2", "--object-type", "diagnosis",
            "--source", "https://example.com/issues/S-2",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        checked = self.cli("sample", "check", "--id", "S-2")
        self.assertEqual(checked.returncode, 1)
        self.assertIn("expected or rubric", checked.stderr)

    def test_set_answer_unblocks_review(self):
        created = self.cli(
            "sample", "new", "--id", "S-5", "--object-type", "diagnosis",
            "--source", "https://example.com/issues/S-5",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        updated = self.cli(
            "sample", "set-answer", "--id", "S-5",
            "--expected", '{"namespace": "inference/vllm-ascend"}',
        )
        self.assertEqual(updated.returncode, 0, updated.stderr)
        self.assertIn("updated: S-5", updated.stdout)
        self.assertIn("path:", updated.stdout)
        checked = self.cli("sample", "check", "--id", "S-5")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        reviewed = self.cli("sample", "review", "--id", "S-5", "--approve")
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)

    def test_promote_before_review_fails(self):
        self.create()
        result = self.cli("sample", "promote", "--id", "S-1", "--to", "core")
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid transition", result.stderr)

    def test_review_rejects_missing_answer_and_reject_still_works(self):
        created = self.cli(
            "sample", "new", "--id", "S-2", "--object-type", "diagnosis",
            "--source", "https://example.com/issues/S-2",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        rejected = self.cli("sample", "review", "--id", "S-2", "--approve")
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("expected or rubric", rejected.stderr)
        terminal = self.cli("sample", "review", "--id", "S-2", "--reject")
        self.assertEqual(terminal.returncode, 0, terminal.stderr)

    def test_test_purpose_candidate_is_rejected_at_review(self):
        created = self.cli(
            "sample", "new", "--id", "S-3", "--object-type", "diagnosis",
            "--purpose", "test", "--source", "https://example.com/issues/S-3",
            "--expected", '{"namespace": "inference/vllm-ascend"}',
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        reviewed = self.cli("sample", "review", "--id", "S-3", "--approve")
        self.assertEqual(reviewed.returncode, 1)
        self.assertIn("purpose=test", reviewed.stderr)
        listed = self.cli("sample", "list", "--status", "candidate")
        self.assertIn("S-3", listed.stdout)

    def test_feedback_cannot_be_promoted_to_core(self):
        created = self.cli(
            "sample", "new", "--id", "S-4", "--object-type", "diagnosis",
            "--purpose", "feedback", "--source", "https://example.com/issues/S-4",
            "--expected", '{"namespace": "inference/vllm-ascend"}',
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        reviewed = self.cli("sample", "review", "--id", "S-4", "--approve")
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        promoted = self.cli("sample", "promote", "--id", "S-4", "--to", "core")
        self.assertEqual(promoted.returncode, 1)
        self.assertIn("feedback", promoted.stderr)

    def test_set_purpose_and_test_guard(self):
        self.create("S-1")
        self.cli("sample", "review", "--id", "S-1", "--approve")
        self.cli("sample", "promote", "--id", "S-1", "--to", "core")
        result = self.cli("sample", "set-purpose", "--id", "S-1", "--purpose", "test")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("S-1: test", result.stdout)

        self.create("S-2")
        self.cli("sample", "review", "--id", "S-2", "--approve")
        rejected = self.cli("sample", "set-purpose", "--id", "S-2", "--purpose", "test")
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("origin=core", rejected.stderr)

    def test_absorb_evaluation_and_test(self):
        self.create("S-1")
        self.cli("sample", "review", "--id", "S-1", "--approve")
        result = self.cli("sample", "absorb", "--id", "S-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("S-1: active (regression)", result.stdout)

        self.create("S-2")
        self.cli("sample", "review", "--id", "S-2", "--approve")
        self.cli("sample", "promote", "--id", "S-2", "--to", "core")
        self.cli("sample", "set-purpose", "--id", "S-2", "--purpose", "test")
        invalidated = self.cli("sample", "absorb", "--id", "S-2")
        self.assertEqual(invalidated.returncode, 0, invalidated.stderr)
        self.assertIn("S-2: retired (test)", invalidated.stdout)

    def test_draw_test_only_selects_core_evaluation(self):
        for sid in ("S-1", "S-2"):
            self.create(sid)
            self.cli("sample", "review", "--id", sid, "--approve")
            self.cli("sample", "promote", "--id", sid, "--to", "core")
        self.create("S-3")
        self.cli("sample", "review", "--id", "S-3", "--approve")
        result = self.cli("sample", "draw-test", "--size", "4")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("drawn: 2", result.stdout)
        self.assertNotIn("S-3", result.stdout)
        listed = self.cli("sample", "list", "--status", "active")
        self.assertIn("S-1\tactive\tcore\ttest", listed.stdout)
        self.assertIn("S-2\tactive\tcore\ttest", listed.stdout)
        self.assertIn("S-3\tactive\tfield\tevaluation", listed.stdout)

    def test_list_does_not_accept_core_as_status(self):
        result = self.cli("sample", "list", "--status", "core")
        self.assertEqual(result.returncode, 2)

    def test_new_cannot_start_at_core_origin(self):
        result = self.cli(
            "sample", "new", "--id", "S-2", "--object-type", "diagnosis",
            "--origin", "core", "--source", "https://example.com/issues/S-2",
            "--expected", '{"namespace": "inference/vllm-ascend"}',
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("origin=field", result.stderr)

    def test_review_requires_a_verdict(self):
        self.create()
        result = self.cli("sample", "review", "--id", "S-1")
        self.assertEqual(result.returncode, 2)

    def test_brief_counts_and_last_conclusion(self):
        self.create()
        self.cli("sample", "review", "--id", "S-1", "--approve")
        ConclusionStore.for_root(self.root).append({
            "decision": "accept",
            "reason": "b=4, c=0, p=0.0625 <= alpha_eff=0.10",
        })
        result = self.cli("brief")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("policy_hash:", result.stdout)
        self.assertIn("samples: 1", result.stdout)
        self.assertIn("by_status: active=1", result.stdout)
        self.assertIn("by_origin: field=1", result.stdout)
        self.assertIn("conclusions: 1", result.stdout)
        self.assertIn("last conclusion: accept", result.stdout)


class IngestCliTest(unittest.TestCase):
    def test_help_lists_ingest(self):
        result = run_cli("sample", "ingest-issues", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--repo", result.stdout)
        self.assertIn("--dry-run", result.stdout)

    def test_fetch_error_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(cli, "ingest_issues",
                                   side_effect=AdapterError("gh CLI not found")):
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    rc = cli.main([
                        "sample", "ingest-issues", "--repo", "o/r",
                        "--root", td, "--state", "ingest-state.json",
                    ])
            self.assertEqual(rc, 2)
            self.assertIn("gh CLI not found", err.getvalue())

    def test_dry_run_output_does_not_claim_writes(self):
        stats = {
            "created": 0, "created_ids": [], "created_paths": [],
            "would_create": ["GH-O-R-1"], "source": "github/o/r",
            "skipped_pr": 0, "skipped_processed": 0, "skipped_no_label": 0,
            "skipped_low_comments": 0, "skipped_title": 0,
            "skipped_empty_body": 0, "skipped_short_body": 0,
            "skipped_feature_title": 0, "skipped_duplicate_source": 0,
            "skipped_duplicate_id": 0, "limit_reached": False,
            "state_updated": False,
        }
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(cli, "ingest_issues", return_value=stats):
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    rc = cli.main([
                        "sample", "ingest-issues", "--repo", "o/r",
                        "--root", td, "--state", "ingest-state.json", "--dry-run",
                    ])
            self.assertEqual(rc, 0)
            self.assertIn("would create: GH-O-R-1", out.getvalue())
            self.assertIn("dry-run", out.getvalue())

    def test_local_source_end_to_end(self):
        cache = Path(tempfile.mkdtemp()) / "issues.json"
        cache.write_text(json.dumps([{
            "number": 9, "title": "T9", "body": "long local body for ingest " * 2,
            "comments": 5, "state": "closed", "labels": ["triaged"],
        }]), encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            result = run_cli(
                "sample", "ingest-issues", "--source", "local", "--cache", str(cache),
                "--repo", "o/r", "--root", td, "--state", "ingest-state.json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("created: 1", result.stdout)
            self.assertIn("candidate:", result.stdout)
            sample = Path(td) / ".s2-replay" / "evolve" / "samples" / "LOCAL-O-R-9.yaml"
            self.assertTrue(sample.exists())
            state = json.loads((Path(td) / "ingest-state.json").read_text(encoding="utf-8"))
            self.assertIn("local/o/r/evaluation", state["sources"])

    def test_experiment_propose_records_baseline_patch(self):
        with tempfile.TemporaryDirectory() as td:
            result = run_cli(
                "experiment", "propose", "--root", td, "--target", "skill",
                "--component", "triage:branch", "--summary", "manual test patch",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("algorithm: baseline", result.stdout)
            path = Path(td) / ".s2-replay" / "evolve" / "experiments.jsonl"
            self.assertTrue(path.exists())
            record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(record["target_kind"], "skill")
            self.assertEqual(record["target_component"], "triage:branch")
            self.assertEqual(record["summary"], "manual test patch")
            self.assertEqual(record["algorithm"], "baseline")
            self.assertEqual(record["execution"], "manual")
            self.assertEqual(record["payload"]["role"], "control")
            self.assertFalse(record["payload"]["proposal"])
            self.assertEqual(record["eval_profile_id"], "arena")
            self.assertTrue(record["eval_ready"])

    def test_experiment_search_selects_with_gepa(self):
        with tempfile.TemporaryDirectory() as td:
            scenario = Path(td) / "scenario.json"
            scenario.write_text(json.dumps({
                "target_kind": "skill",
                "target_component": "diagnose.knowledge_usage",
                "samples": ["s1", "s2"],
                "candidates": [
                    {"draft": {"target_kind": "skill", "target_component": "diagnose.knowledge_usage",
                               "summary": "seed", "change": {"files": ["skills/diagnose/SKILL.md"], "diff": "+ seed"},
                               "expected": "提升", "risk": "低", "rollback": "恢复"},
                     "scores": {"s1": 1, "s2": 0}},
                    {"draft": {"target_kind": "skill", "target_component": "diagnose.knowledge_usage",
                               "summary": "child", "change": {"files": ["skills/diagnose/SKILL.md"], "diff": "+ child"},
                               "expected": "提升", "risk": "低", "rollback": "恢复"},
                     "scores": {"s1": 1, "s2": 1}},
                ],
            }, ensure_ascii=False), encoding="utf-8")
            result = run_cli("experiment", "search", "--root", td,
                             "--scenario", str(scenario), "--policy", "gepa")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["selected"]["artifact"]["diff"], "+ child")
            self.assertTrue((Path(td) / ".s2-replay" / "evolve" / "proposals.jsonl").exists())

    def test_experiment_propose_agent_draft_any_target(self):
        with tempfile.TemporaryDirectory() as td:
            draft = Path(td) / "draft.json"
            draft.write_text(json.dumps({
                "target_kind": "knowledge",
                "target_component": "knowledge.case_content",
                "summary": "补 VLLM-ASC-10892 的长请求分块判别",
                "change": {"files": ["knowledge/inference/vllm-ascend/precision/VLLM-ASC-10892.yaml"],
                           "diff": "quickly_check 增加 >1024 token 分块检查"},
                "expected": "该 case 的复核命中率提升",
                "risk": "低",
                "rollback": "恢复原判别条件",
            }, ensure_ascii=False), encoding="utf-8")
            result = run_cli("experiment", "propose", "--root", td, "--draft", str(draft))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("algorithm: agent_draft", result.stdout)
            path = Path(td) / ".s2-replay" / "evolve" / "experiments.jsonl"
            record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(record["target_kind"], "knowledge")
            self.assertEqual(record["target_component"], "knowledge.case_content")
            self.assertEqual(record["algorithm"], "agent_draft")
            self.assertEqual(record["execution"], "subagent")
            self.assertEqual(record["source"], "agent_draft")
            self.assertEqual(record["payload"]["expected"], "该 case 的复核命中率提升")

    def test_agent_draft_rejects_missing_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            draft = Path(td) / "draft.json"
            draft.write_text(json.dumps({
                "target_kind": "tooling",
                "target_component": "tooling.source_fetch",
                "summary": "缓存",
                "change": {"files": ["scripts/src_fetch.py"]},
                "expected": "减少抓取",
                "risk": "低",
            }), encoding="utf-8")
            result = run_cli("experiment", "propose", "--root", td, "--draft", str(draft))
            self.assertEqual(result.returncode, 2)
            self.assertIn("rollback", result.stderr)

    def test_experiment_propose_official_gepa_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            result = run_cli(
                "experiment", "propose", "--root", td, "--target", "skill",
                "--algorithm", "gepa",
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("not allowed", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_experiment_propose_rejects_invalid_patch_fields(self):
        with tempfile.TemporaryDirectory() as td:
            result = run_cli(
                "experiment", "propose", "--root", td, "--target", "skill",
                "--seed", "-1",
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("seed", result.stderr)

    def test_experiment_record_persists_subagent_result(self):
        result = {
            "target_kind": "skill", "target_component": "diagnosis-skill",
            "algorithm": "subagent-reflection", "algorithm_version": "workflow-1",
            "execution": "subagent", "decision": "reject", "samples": ["S-1", "S-2"],
            "baseline": {"score": 1.0, "samples": ["S-1", "S-2"]},
            "candidate": {"score": 0.5, "samples": ["S-1", "S-2"]},
            "eval_profile_id": "subagent_judge", "eval_ready": False,
            "summary": "candidate regressed on S-2",
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "result.json"
            path.write_text(json.dumps(result), encoding="utf-8")
            created = run_cli("experiment", "record", "--root", td, "--file", str(path))
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertIn("decision: reject", created.stdout)
            records = run_cli("experiment", "records", "--root", td)
            self.assertIn("subagent-reflection", records.stdout)
            self.assertIn("baseline=1.0 candidate=0.5", records.stdout)

    def test_experiment_record_rejects_foreign_eval_profile(self):
        result = {
            "target_kind": "tooling", "target_component": "router",
            "algorithm": "subagent-reflection", "algorithm_version": "1",
            "execution": "subagent", "decision": "reject", "samples": ["S-1"],
            "baseline": {"score": 1, "samples": ["S-1"]},
            "candidate": {"score": 0, "samples": ["S-1"]},
            "eval_profile_id": "arena",
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text(json.dumps(result), encoding="utf-8")
            created = run_cli("experiment", "record", "--root", td, "--file", str(path))
            self.assertEqual(created.returncode, 2)
            self.assertIn("subagent_judge", created.stderr)

    def test_knowledge_usage_compare_cli(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "base.json"
            cand = Path(td) / "cand.json"
            base.write_text(json.dumps([
                {"sample_id": "a", "hit": True, "first_hit_step": 4,
                 "candidates_examined": 3, "full_body_reads": 3,
                 "reference_lookups": 1, "wrong_cases": 0, "tokens": 100},
            ]), encoding="utf-8")
            cand.write_text(json.dumps([
                {"sample_id": "a", "hit": True, "first_hit_step": 2,
                 "candidates_examined": 1, "full_body_reads": 1,
                 "reference_lookups": 0, "wrong_cases": 0, "tokens": 50},
            ]), encoding="utf-8")
            result = run_cli("knowledge-usage", "compare",
                             "--baseline", str(base), "--candidate", str(cand), "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"decision": "accept"', result.stdout)

    def test_experiment_record_rejects_fake_p_value(self):
        result = {
            "target_kind": "skill", "target_component": "x",
            "algorithm": "subagent-reflection", "algorithm_version": "1",
            "execution": "subagent", "decision": "accept", "samples": ["S-1"],
            "baseline": {"score": 0, "samples": ["S-1"]},
            "candidate": {"score": 1, "samples": ["S-1"]},
            "paired": {"b": 1, "c": 0, "n": 1, "p_value": 0, "alpha_eff": 0.1},
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text(json.dumps(result), encoding="utf-8")
            created = run_cli("experiment", "record", "--root", td, "--file", str(path))
            self.assertEqual(created.returncode, 2)
            self.assertIn("exact paired p", created.stderr)

    def test_experiment_record_rejects_mismatched_samples(self):
        result = {
            "target_kind": "skill", "target_component": "x",
            "algorithm": "subagent-reflection", "algorithm_version": "1",
            "execution": "subagent", "decision": "reject", "samples": ["S-1"],
            "baseline": {"score": 1, "samples": ["S-1"]},
            "candidate": {"score": 0, "samples": ["S-2"]},
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text(json.dumps(result), encoding="utf-8")
            created = run_cli("experiment", "record", "--root", td, "--file", str(path))
            self.assertEqual(created.returncode, 2)
            self.assertIn("same set", created.stderr)

    def test_experiment_records_lists_written_patch(self):
        with tempfile.TemporaryDirectory() as td:
            run_cli("experiment", "propose", "--root", td, "--target", "skill",
                    "--component", "triage:branch", "--summary", "manual")
            result = run_cli("experiment", "records", "--root", td)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("experiments: 1", result.stdout)
            self.assertIn("triage:branch", result.stdout)

    def test_experiment_list_marks_policy_algorithm(self):
        with tempfile.TemporaryDirectory() as td:
            result = run_cli("experiment", "list", "--root", td)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("* baseline", result.stdout)

    def test_issue_ingest_uses_quality_answer(self):
        cache = Path(tempfile.mkdtemp()) / "issues.json"
        cache.write_text(json.dumps([{
            "number": 9, "title": "T9", "body": "long local body for ingest " * 2,
            "comments": 5, "state": "closed", "labels": ["triaged"],
        }]), encoding="utf-8")
        quality = Path(tempfile.mkdtemp()) / "quality.json"
        quality.write_text(json.dumps({
            "9": {"score": 0.9, "answer": "specific fix", "namespace": "inference/vllm-ascend",
                  "category": "interrupt", "evidence": "comment"},
        }), encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            result = run_cli(
                "sample", "ingest-issues", "--source", "local", "--cache", str(cache),
                "--repo", "o/r", "--root", td, "--state", "ingest-state.json",
                "--quality-file", str(quality),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            sample = Path(td) / ".s2-replay" / "evolve" / "samples" / "LOCAL-O-R-9.yaml"
            self.assertIn("specific fix", sample.read_text(encoding="utf-8"))

    def test_issue_ingest_skips_issue_missing_from_quality_file(self):
        cache = Path(tempfile.mkdtemp()) / "issues.json"
        cache.write_text(json.dumps([{
            "number": 10, "title": "T10", "body": "long local body for ingest " * 2,
            "comments": 5, "state": "closed", "labels": ["triaged"],
        }]), encoding="utf-8")
        quality = Path(tempfile.mkdtemp()) / "quality.json"
        quality.write_text(json.dumps({}), encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            result = run_cli(
                "sample", "ingest-issues", "--source", "local", "--cache", str(cache),
                "--repo", "o/r", "--root", td, "--state", "ingest-state.json",
                "--quality-file", str(quality),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("created: 0", result.stdout)

    def test_issue_ingest_malformed_quality_file_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            quality = Path(td) / "quality.json"
            quality.write_text("{bad", encoding="utf-8")
            result = run_cli(
                "sample", "ingest-issues", "--source", "local", "--cache", "/tmp/none.json",
                "--repo", "o/r", "--root", td, "--state", "ingest-state.json",
                "--quality-file", str(quality),
            )
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)

    def test_issue_ingest_rejects_low_quality(self):
        cache = Path(tempfile.mkdtemp()) / "issues.json"
        cache.write_text(json.dumps([{
            "number": 9, "title": "T9", "body": "long local body for ingest " * 2,
            "comments": 5, "state": "closed", "labels": ["triaged"],
        }]), encoding="utf-8")
        quality = Path(tempfile.mkdtemp()) / "quality.json"
        quality.write_text(json.dumps({"9": {"score": 0.2, "answer": "x"}}), encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            result = run_cli(
                "sample", "ingest-issues", "--source", "local", "--cache", str(cache),
                "--repo", "o/r", "--root", td, "--state", "ingest-state.json",
                "--quality-file", str(quality),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("created: 0", result.stdout)

    def test_unknown_source_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            result = run_cli(
                "sample", "ingest-issues", "--source", "gitcode",
                "--repo", "o/r", "--root", td,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("unknown issue source", result.stderr)

    def test_local_source_missing_cache_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            result = run_cli(
                "sample", "ingest-issues", "--source", "local",
                "--repo", "o/r", "--root", td,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("cache", result.stderr.lower())

    def test_ingested_candidate_can_be_answered_and_reviewed(self):
        body_text = "Traceback: runtime error on this node; logs and reproduce steps " * 2
        with tempfile.TemporaryDirectory() as td:
            store = SampleStore(base=Path(td) / ".s2-replay" / "evolve")
            stats = issue_adapter.ingest_issues(
                Path(td), "o/r", store=store, state_path="ingest-state.json",
                fetch_metadata_fn=lambda repo, labels, since: [{
                    "number": 1, "title": "runtime error", "comments": 5,
                    "closed_at": "2026-11-01T00:00:00Z",
                    "state_reason": "completed", "labels": ["triaged"],
                }],
                fetch_body_fn=lambda repo, issue: {
                    "title": "runtime error", "body": body_text,
                    "closed_at": "2026-11-01T00:00:00Z",
                },
            )
            sample_id = stats["created_ids"][0]
            self.assertTrue(Path(stats["created_paths"][0]).exists())
            answered = run_cli(
                "sample", "set-answer", "--root", td, "--id", sample_id,
                "--expected", '{"namespace": "inference/vllm-ascend"}',
            )
            self.assertEqual(answered.returncode, 0, answered.stderr)
            reviewed = run_cli("sample", "review", "--root", td,
                               "--id", sample_id, "--approve")
            self.assertEqual(reviewed.returncode, 0, reviewed.stderr)

    def test_candidate_path_is_printed(self):
        stats = {
            "created": 1, "created_ids": ["GH-O-R-1"],
            "created_paths": ["/tmp/samples/GH-O-R-1.yaml"],
            "would_create": [], "source": "github/o/r",
            "skipped_pr": 0, "skipped_processed": 0, "skipped_no_label": 0,
            "skipped_low_comments": 0, "skipped_title": 0,
            "skipped_empty_body": 0, "skipped_short_body": 0,
            "skipped_feature_title": 0, "skipped_duplicate_source": 0,
            "skipped_duplicate_id": 0, "limit_reached": False,
            "state_updated": True, "state_path": "/tmp/ingest-state.json",
        }
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(cli, "ingest_issues", return_value=stats):
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    rc = cli.main([
                        "sample", "ingest-issues", "--repo", "o/r",
                        "--root", td, "--state", "ingest-state.json",
                    ])
            self.assertEqual(rc, 0)
            self.assertIn("candidate: GH-O-R-1\t/tmp/samples/GH-O-R-1.yaml", out.getvalue())


class JudgeCliTest(unittest.TestCase):
    def judge(self, *args, cwd=None):
        return run_cli("judge", *args, cwd=cwd)

    def test_accept(self):
        result = self.judge("--b", "4", "--c", "0", "--n", "9")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("decision: accept", result.stdout)
        self.assertIn("p_value: 0.0625", result.stdout)

    def test_insufficient(self):
        result = self.judge("--b", "1", "--c", "0", "--n", "9")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("decision: insufficient", result.stdout)

    def test_reject(self):
        result = self.judge("--b", "0", "--c", "1", "--n", "9")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("decision: reject", result.stdout)

    def test_zero_discordant_pairs_is_insufficient(self):
        result = self.judge("--b", "0", "--c", "0", "--n", "9")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("decision: insufficient", result.stdout)

    def test_reuse_index_tightens_evidence(self):
        result = self.judge("--b", "4", "--c", "0", "--n", "9", "--k", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("decision: insufficient", result.stdout)

    def test_cost_over_budget(self):
        result = self.judge(
            "--b", "4", "--c", "0", "--n", "9",
            "--cost-b", "100", "--cost-c", "120",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("decision: insufficient", result.stdout)

    def test_invalid_input_exits_2(self):
        bad_n = self.judge("--b", "4", "--c", "0", "--n", "3")
        self.assertEqual(bad_n.returncode, 2)
        self.assertIn("n must be >= b + c", bad_n.stderr)
        negative = self.judge("--b", "-1", "--c", "0", "--n", "9")
        self.assertEqual(negative.returncode, 2)

    def test_missing_policy_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.judge("--b", "1", "--c", "0", "--n", "9",
                                "--policy", str(Path(td) / "missing.yaml"))
            self.assertEqual(result.returncode, 2)
            self.assertIn("not found", result.stderr)

    def test_invalid_policy_method_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policy.yaml"
            path.write_text(
                "decision:\n  method: magic\n", encoding="utf-8")
            result = self.judge("--b", "1", "--c", "0", "--n", "9",
                                "--policy", str(path))
            self.assertEqual(result.returncode, 2)
            self.assertIn("decision.method", result.stderr)

    VERSIONS = (
        '{"protocol": "p1", "policy": "policy-3", "base_kb": "9f2c1a", '
        '"candidate_kb": "9f2c1a", "candidate": "4d8e0b", '
        '"model": "deepseek-flash/default"}'
    )

    def test_record_appends_conclusion_and_brief_sees_it(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.judge(
                "--b", "4", "--c", "0", "--n", "9",
                "--record", "--root", td, "--versions", self.VERSIONS,
                "--sample", "S-1", "--pool", "pool-x",
                "--pool-hash", "abc123", "--cost-b", "100", "--cost-c", "100",
                "--metrics-json", '{"case_hit": 0.6}',
                "--cost-json", '{"tokens": 10}',
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("recorded:", result.stdout)
            records = ConclusionStore.for_root(Path(td)).read()
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record["decision"], "accept")
            self.assertEqual((record["b"], record["c"], record["n"]), (4, 0, 9))
            self.assertAlmostEqual(record["p_value"], 0.0625)
            self.assertAlmostEqual(record["alpha_eff"], 0.10)
            self.assertAlmostEqual(record["delta_q"], 4 / 9)
            self.assertAlmostEqual(record["cost_ratio"], 1.0)
            self.assertEqual(record["reuse_index"], 0)
            self.assertEqual(record["pool_hash"], "abc123")
            self.assertEqual(record["metrics"], {"case_hit": 0.6})
            self.assertEqual(record["cost"], {"tokens": 10})
            self.assertEqual(record["versions"], {
                "protocol": "p1",
                "policy": "policy-3",
                "base_kb": "9f2c1a",
                "candidate_kb": "9f2c1a",
                "candidate": "4d8e0b",
                "model": "deepseek-flash/default",
                "algorithm": "baseline",
                "algorithm_version": "manual",
            })
            self.assertTrue(record["at"])
            self.assertEqual(record["sample"], "S-1")
            self.assertEqual(record["pool"], "pool-x")
            brief = run_cli("brief", "--root", td)
            self.assertEqual(brief.returncode, 0, brief.stderr)
            self.assertIn("conclusions: 1", brief.stdout)
            self.assertIn("last conclusion: accept", brief.stdout)

    def test_record_writes_reuse_index(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.judge("--b", "4", "--c", "0", "--n", "9", "--k", "2",
                                "--record", "--root", td,
                                "--versions", self.VERSIONS)
            self.assertEqual(result.returncode, 0, result.stderr)
            record = ConclusionStore.for_root(Path(td)).read()[0]
            self.assertEqual(record["decision"], "insufficient")
            self.assertEqual(record["reuse_index"], 2)
            self.assertAlmostEqual(record["alpha_eff"], 0.10 / 3)

    def test_record_accepts_versions_yaml_file(self):
        versions = {
            "protocol": "p1",
            "policy": "policy-3",
            "base_kb": "9f2c1a",
            "candidate_kb": "9f2c1a",
            "candidate": "4d8e0b",
            "model": "deepseek-flash/default",
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "versions.yaml"
            path.write_text(
                "protocol: p1\npolicy: policy-3\nbase_kb: 9f2c1a\n"
                "candidate_kb: 9f2c1a\ncandidate: 4d8e0b\n"
                "model: deepseek-flash/default\n",
                encoding="utf-8",
            )
            result = self.judge("--b", "4", "--c", "0", "--n", "9",
                                "--record", "--root", td, "--versions", str(path))
            self.assertEqual(result.returncode, 0, result.stderr)
            record = ConclusionStore.for_root(Path(td)).read()[0]
            expected_versions = dict(versions)
        expected_versions.update({"algorithm": "baseline", "algorithm_version": "manual"})
        self.assertEqual(record["versions"], expected_versions)

    def test_record_requires_versions(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.judge("--b", "4", "--c", "0", "--n", "9",
                                "--record", "--root", td)
            self.assertEqual(result.returncode, 2)
            self.assertIn("--versions is required", result.stderr)
            self.assertEqual(ConclusionStore.for_root(Path(td)).read(), [])

    def test_record_rejects_incomplete_versions(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.judge("--b", "4", "--c", "0", "--n", "9",
                                "--record", "--root", td,
                                "--versions", '{"protocol": "p1"}')
            self.assertEqual(result.returncode, 2)
            self.assertIn("versions.", result.stderr)
            self.assertEqual(ConclusionStore.for_root(Path(td)).read(), [])

    def test_default_judge_does_not_record(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.judge("--b", "4", "--c", "0", "--n", "9", "--root", td)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(ConclusionStore.for_root(Path(td)).read(), [])

    def test_record_does_not_fabricate_missing_fields(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.judge("--b", "4", "--c", "0", "--n", "9",
                                "--record", "--root", td,
                                "--versions", self.VERSIONS)
            self.assertEqual(result.returncode, 0, result.stderr)
            record = ConclusionStore.for_root(Path(td)).read()[0]
            self.assertNotIn("sample", record)
            self.assertNotIn("pool", record)
            self.assertNotIn("pool_hash", record)
            self.assertNotIn("metrics", record)
            self.assertNotIn("cost", record)
            self.assertNotIn("cost_ratio", record)


class SampleImportS2CliTest(unittest.TestCase):
    FIXTURE = """\
calibration:
- issue: 111
  title: "T1"
  input: {symptoms: "symptom 1"}
  expected: {namespace: inference/vllm-ascend, category: interrupt,
             resolution: "fix 1", fix_commit: "PR #1", confidence: high}
- issue: 222
  title: "T2"
  input: {symptoms: "symptom 2"}
  expected: {namespace: training/verl, category: precision,
             resolution: "fix 2", fix_commit: "PR #2", confidence: medium}
- issue: 333
  title: "T3"
  non_diagnostic: "no signal"
  input: {symptoms: "env only"}
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        path = self.root / "eval" / "s2" / "vllm-ascend.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(self.FIXTURE, encoding="utf-8")

    def cli(self, *args):
        return run_cli(*args, "--root", str(self.root))

    def test_import_creates_candidates_and_skips_second_time(self):
        first = self.cli("sample", "import-s2", "--source", "eval/s2/vllm-ascend.yaml")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("created: 2", first.stdout)
        self.assertIn("non_diagnostic=1", first.stdout)
        sample_path = self.root / ".s2-replay" / "evolve" / "samples" / "VLLM-ASC-111.yaml"
        self.assertTrue(sample_path.exists())
        raw = yaml.safe_load(sample_path.read_text(encoding="utf-8"))
        self.assertEqual(raw["source"], "eval/s2/vllm-ascend.yaml#111")
        self.assertEqual(raw["expected"]["fix_commit"], "PR #1")

        second = self.cli("sample", "import-s2", "--source", "eval/s2/vllm-ascend.yaml")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("created: 0", second.stdout)
        self.assertIn("duplicate_source=2", second.stdout)

    def test_import_honours_limit(self):
        result = self.cli(
            "sample", "import-s2", "--source", "eval/s2/vllm-ascend.yaml", "--limit", "1"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("created: 1", result.stdout)
        self.assertIn("limit reached: 1", result.stdout)

    def test_missing_source_exits_2(self):
        result = self.cli("sample", "import-s2", "--source", "eval/s2/nope.yaml")
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot read S2 calibration", result.stderr)


class JudgeStatsCliTest(unittest.TestCase):
    VERSIONS = (
        '{"protocol": "p1", "policy": "policy-3", "base_kb": "9f2c1a", '
        '"candidate_kb": "9f2c1a", "candidate": "4d8e0b", '
        '"model": "deepseek-flash/default"}'
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write_stats(self, name, hits):
        path = self.root / name
        issues = [{"id": str(index), "hit": hit}
                  for index, hit in enumerate(hits, start=1)]
        path.write_text(yaml.safe_dump({"issues": issues}), encoding="utf-8")
        return path

    def test_counts_b_c_n_and_accepts(self):
        baseline = self.write_stats("a.yaml", [False] * 4 + [True] * 5)
        candidate = self.write_stats("b.yaml", [True] * 4 + [True] * 5)
        result = run_cli("judge-stats", "--baseline", str(baseline),
                         "--candidate", str(candidate), "--root", str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("paired: b=4 c=0 n=9", result.stdout)
        self.assertIn("decision: accept", result.stdout)

    def test_records_conclusion_with_versions(self):
        baseline = self.write_stats("a.yaml", [False, False, False, False, True])
        candidate = self.write_stats("b.yaml", [True, True, True, True, True])
        result = run_cli(
            "judge-stats", "--baseline", str(baseline), "--candidate", str(candidate),
            "--root", str(self.root), "--record", "--versions", self.VERSIONS,
            "--pool", "pool-x", "--pool-hash", "abc123",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("recorded:", result.stdout)
        records = ConclusionStore.for_root(self.root).read()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual((record["b"], record["c"], record["n"]), (4, 0, 5))
        self.assertEqual(record["decision"], "accept")
        self.assertEqual(record["pool_hash"], "abc123")

    def test_missing_stats_exits_2(self):
        result = run_cli(
            "judge-stats", "--baseline", str(self.root / "nope.yaml"),
            "--candidate", str(self.root / "nope2.yaml"),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot read baseline stats", result.stderr)


class ReplayCliTest(unittest.TestCase):
    FIXTURE = """\
calibration:
- issue: 111
  title: "T1"
  input: {symptoms: "symptom 1"}
  expected: {namespace: inference/vllm-ascend, category: interrupt, fix_commit: "PR #1"}
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        path = self.root / "eval" / "s2" / "vllm-ascend.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(self.FIXTURE, encoding="utf-8")

    def test_prepare_then_collect_writes_report(self):
        prepared = run_cli("replay", "prepare", "--root", str(self.root))
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertTrue((self.root / ".s2-replay" / "111.md").exists())

        (self.root / ".s2-replay" / "111.result.yaml").write_text(
            "namespace: inference/vllm-ascend\ncategory: interrupt\n"
            "hit_case: VLLM-ASC-111\nroot_cause: fixed by PR #1\n"
            "routing_ok: true\ntier2_hit: true\nroot_cause_ok: true\n",
            encoding="utf-8",
        )
        report = self.root / "reports" / "replay.md"
        collected = run_cli("replay", "collect", "--root", str(self.root),
                            "--report", str(report))
        self.assertEqual(collected.returncode, 0, collected.stderr)
        self.assertTrue(report.exists())
        self.assertIn("| 111 | replayed |", report.read_text(encoding="utf-8"))


class PolicyWiringCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def create_core_sample(self, sample_id):
        created = run_cli(
            "sample", "new", "--root", str(self.root), "--id", sample_id,
            "--object-type", "diagnosis", "--source",
            f"https://example.com/issues/{sample_id}",
            "--expected", '{"namespace": "inference/vllm-ascend"}',
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        reviewed = run_cli("sample", "review", "--root", str(self.root),
                           "--id", sample_id, "--approve")
        self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
        promoted = run_cli("sample", "promote", "--root", str(self.root),
                           "--id", sample_id, "--to", "core")
        self.assertEqual(promoted.returncode, 0, promoted.stderr)

    def test_draw_test_defaults_to_policy_size_and_split(self):
        policy = self.root / "sleuth.config.yaml"
        policy.write_text("schema: sleuth-config-v1\nevolution:\n  policy:\n    samples:\n      test: 1\n      split: hash\n", encoding="utf-8")
        self.create_core_sample("S-1")
        self.create_core_sample("S-2")
        result = run_cli("sample", "draw-test", "--root", str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("drawn: 1", result.stdout)
        self.assertIn("size: 1 (policy)", result.stdout)
        self.assertIn("split: hash (policy)", result.stdout)

    def test_draw_test_explicit_size_still_uses_policy_split(self):
        policy = self.root / "sleuth.config.yaml"
        policy.write_text("schema: sleuth-config-v1\nevolution:\n  policy:\n    samples:\n      test: 4\n      split: group\n", encoding="utf-8")
        self.create_core_sample("S-1")
        self.create_core_sample("S-2")
        result = run_cli("sample", "draw-test", "--root", str(self.root),
                         "--size", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("drawn: 1", result.stdout)
        self.assertIn("split: group (policy)", result.stdout)


if __name__ == "__main__":
    unittest.main()


class ToolingCliTest(unittest.TestCase):
    @staticmethod
    def _row(sample, calls=2, resolved=True):
        return {"sample_id": sample, "tool_calls": calls, "fetch_calls": 1,
                "grep_calls": 1, "retries": 0, "cache_hits": 0,
                "tool_ms": 10.0, "failures": 0, "resolved": resolved}

    def test_tooling_gate_accepts_and_rejects(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = root / "base.json"
            cand = root / "cand.json"
            base.write_text(json.dumps({"samples": [self._row("a", calls=4)]}), encoding="utf-8")
            cand.write_text(json.dumps({"samples": [self._row("a", calls=2)]}), encoding="utf-8")
            result = run_cli("experiment", "gate", "--target", "tooling",
                             "--baseline", str(base), "--candidate", str(cand))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("decision: accept", result.stdout)
            cand.write_text(json.dumps({"samples": [self._row("a", calls=2, resolved=False)]}),
                            encoding="utf-8")
            result = run_cli("experiment", "gate", "--target", "tooling",
                             "--baseline", str(base), "--candidate", str(cand))
            self.assertEqual(result.returncode, 1)
            self.assertIn("decision: reject", result.stdout)

    def test_tool_usage_from_trace_cli(self):
        with tempfile.TemporaryDirectory() as td:
            trace = Path(td) / "t.yaml"
            trace.write_text(yaml.safe_dump({
                "session_id": "s1",
                "trace": [{"action": "source_analysis", "files_read": ["a.py"],
                           "tool_calls": ["src_fetch.py r main", "grep a.py"],
                           "tool_ms": 5.0}],
            }), encoding="utf-8")
            result = run_cli("tool-usage", "from-trace", "--trace", str(trace), "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["tool_calls"], 2)
            self.assertEqual(payload["fetch_calls"], 1)


class SampleIntakeCliTest(unittest.TestCase):
    def test_trace_dry_run_create_answer_and_status(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            traces = root / "traces"
            traces.mkdir()
            trace = traces / "t.yaml"
            trace.write_text(yaml.safe_dump({
                "session_id": "2026-01-01-1001-demo",
                "summary": "现象：启动崩。\n\n根因：模块绑定未刷新。\n\n处置：重绑。",
                "incident_env": "A3",
                "trace": [{"role": "user", "content": "启动崩"}],
            }), encoding="utf-8")
            dry = run_cli("sample", "new", "--from", "trace", "--trace", str(trace),
                          "--root", td, "--dry-run", "--json")
            self.assertEqual(dry.returncode, 0, dry.stderr)
            payload = json.loads(dry.stdout)
            self.assertEqual(payload["completeness"]["state"], "needs_answer")
            created = run_cli("sample", "new", "--from", "trace", "--trace", str(trace),
                              "--root", td)
            self.assertEqual(created.returncode, 0, created.stderr)
            sample_id = created.stdout.split("created: ", 1)[1].splitlines()[0].strip()
            answered = run_cli("sample", "set-answer", "--id", sample_id,
                               "--resolution", "模块绑定未刷新", "--confidence",
                               "maintainer-reviewed", "--sanitized", "true", "--root", td)
            self.assertEqual(answered.returncode, 0, answered.stderr)
            status = run_cli("sample", "status", "--id", sample_id, "--root", td, "--json")
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertEqual(json.loads(status.stdout)["state"], "ready")


class JudgeCalibrationCliTest(unittest.TestCase):
    def test_agreement_and_gate(self):
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            a.write_text(json.dumps({"scores": [
                {"id": "x", "score": 1}, {"id": "y", "score": 0}]}), encoding="utf-8")
            b.write_text(json.dumps({"x": 1, "y": 0}), encoding="utf-8")
            ok = run_cli("judge-calibration", "--a", str(a), "--b", str(b), "--json")
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertTrue(json.loads(ok.stdout)["passed"])
            b.write_text(json.dumps({"x": 0, "y": 0}), encoding="utf-8")
            bad = run_cli("judge-calibration", "--a", str(a), "--b", str(b))
            self.assertEqual(bad.returncode, 1)
            self.assertIn("passed: false", bad.stdout)


class SampleReviewJsonCliTest(unittest.TestCase):
    def test_review_and_promote_json(self):
        with tempfile.TemporaryDirectory() as td:
            created = run_cli("sample", "new", "--root", td, "--id", "S-J",
                              "--object-type", "diagnosis",
                              "--source", "traces/j.yaml",
                              "--expected", '{"resolution": "r"}')
            self.assertEqual(created.returncode, 0, created.stderr)
            answer = run_cli("sample", "set-answer", "--root", td, "--id", "S-J",
                             "--resolution", "r", "--sanitized", "true",
                             "--confidence", "maintainer-reviewed")
            self.assertEqual(answer.returncode, 0, answer.stderr)
            reviewed = run_cli("sample", "review", "--root", td, "--id", "S-J",
                               "--approve", "--json")
            self.assertEqual(reviewed.returncode, 0, reviewed.stderr)
            self.assertEqual(json.loads(reviewed.stdout)["status"], "active")
            promoted = run_cli("sample", "promote", "--root", td, "--id", "S-J",
                               "--to", "core", "--json")
            self.assertEqual(promoted.returncode, 0, promoted.stderr)
            self.assertEqual(json.loads(promoted.stdout)["origin"], "core")
