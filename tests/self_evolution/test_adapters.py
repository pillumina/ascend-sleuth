"""适配器层：S2 导入、arena 配对与旧脚本薄包装。

不连模型、不连网络。S2 导入用临时校准集；arena 配对只喂 stats 字典；replay 包装
真跑旧脚本的 prepare/collect（写的是临时目录）。
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import yaml  # noqa: E402

from evolve.adapters import AdapterError, load_legacy  # noqa: E402
from evolve.adapters import arena, cards, evidence, replay, s2  # noqa: E402
from evolve.samples import SampleStore  # noqa: E402

S2_FIXTURE = """\
calibration:
- issue: 111
  split: selection
  title: "T1: first"
  input:
    symptoms: "traceback line 1\\nline 2"
  expected: {namespace: inference/vllm-ascend, category: interrupt,
             resolution: "fixed by PR #1", fix_commit: "PR #1", confidence: high}
- issue: 222
  split: selection
  title: "T2: no signal"
  non_diagnostic: "正文只有环境信息，没有可判别症状"
  input: {symptoms: "env only"}
- issue: 333
  split: selection
  title: "T3: no symptoms"
  input: {title: "no symptoms here"}
- issue: 444
  split: selection
  title: "T4: second"
  input: {symptoms: "another symptom"}
  expected: {namespace: training/verl, category: precision,
             resolution: "PR #4", fix_commit: "PR #4", confidence: medium}
- issue: 555
  split: test
  title: "T5: test split"
  input: {symptoms: "test split symptom"}
  expected: {namespace: inference/vllm-ascend, category: interrupt,
             resolution: "PR #5", fix_commit: "PR #5"}
- issue: 666
  split: selection
  title: "T6: no answer"
  input: {symptoms: "has symptoms but no expected"}
- issue: 777
  split: cross
  title: "T7: cross split"
  input: {symptoms: "cross split symptom"}
  expected: {namespace: inference/vllm-ascend, category: interrupt,
             resolution: "PR #7", fix_commit: "PR #7"}
"""


class S2PureTest(unittest.TestCase):
    def test_sample_id_uses_case_prefix_for_vllm_ascend(self):
        self.assertEqual(
            s2.sample_id_for(Path("eval/s2/vllm-ascend.yaml"), 14871),
            "VLLM-ASC-14871",
        )
        self.assertEqual(
            s2.sample_id_for(Path("eval/s2/vllm-ascend-cross.yaml"), 14871),
            "S2-VLLM-ASCEND-CROSS-14871",
        )

    def test_expected_keeps_all_five_fields(self):
        expected = s2.expected_for({
            "expected": {
                "namespace": "inference/vllm-ascend",
                "category": "interrupt",
                "resolution": "PR #1",
                "fix_commit": "PR #1",
                "confidence": "high",
            }
        })
        self.assertEqual(expected, {
            "namespace": "inference/vllm-ascend",
            "category": "interrupt",
            "resolution": "PR #1",
            "fix_commit": "PR #1",
            "confidence": "high",
        })

    def test_expected_defaults_missing_fields_without_fabricating_values(self):
        expected = s2.expected_for({"expected": {"namespace": "ns"}})
        self.assertEqual(expected["namespace"], "ns")
        self.assertEqual(expected["category"], "")
        self.assertEqual(expected["resolution"], "")
        self.assertEqual(expected["fix_commit"], "")
        self.assertEqual(expected["confidence"], "pending")

    def test_candidate_kwargs_are_a_candidate_diagnosis(self):
        row = {
            "issue": 111,
            "title": "T1",
            "input": {"symptoms": "s"},
            "expected": {"namespace": "ns"},
        }
        kwargs = s2.candidate_kwargs(row, "eval/s2/pool.yaml#111", "S2-111")
        self.assertEqual(kwargs["id"], "S2-111")
        self.assertEqual(kwargs["object_type"], "diagnosis")
        self.assertEqual(kwargs["origin"], "field")
        self.assertEqual(kwargs["purpose"], "evaluation")
        self.assertEqual(kwargs["source"], "eval/s2/pool.yaml#111")
        self.assertEqual(kwargs["input"], {"title": "T1", "symptoms": "s"})
        self.assertEqual(kwargs["expected_kind"], "resolution")


class S2ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "eval" / "s2" / "vllm-ascend.yaml"
        self.path.parent.mkdir(parents=True)
        self.path.write_text(S2_FIXTURE, encoding="utf-8")
        self.store = SampleStore(self.root)

    def import_samples(self, limit=None):
        return s2.import_s2_samples(
            self.root, "eval/s2/vllm-ascend.yaml", self.store, limit=limit,
        )

    def test_imports_only_diagnosable_rows_and_reports_skips(self):
        stats = self.import_samples()
        self.assertEqual(stats["total"], 7)
        self.assertEqual(stats["created"], 2)
        self.assertEqual(stats["created_ids"], ["VLLM-ASC-111", "VLLM-ASC-444"])
        self.assertEqual(stats["skipped_non_diagnostic"], 1)
        self.assertEqual(stats["skipped_no_symptoms"], 1)
        self.assertEqual(stats["skipped_no_answer"], 1)
        self.assertEqual(stats["skipped_split"], 2)
        self.assertEqual(stats["skipped_duplicate_source"], 0)
        self.assertEqual(stats["source"], "eval/s2/vllm-ascend.yaml")

    def test_candidate_fields_follow_the_contract(self):
        self.import_samples()
        sample = self.store.load("VLLM-ASC-111")
        self.assertIsNotNone(sample)
        self.assertEqual(sample.status, "candidate")
        self.assertEqual(sample.object_type, "diagnosis")
        self.assertEqual(sample.origin, "field")
        self.assertEqual(sample.purpose, "evaluation")
        self.assertEqual(sample.source, "eval/s2/vllm-ascend.yaml#111")
        self.assertEqual(sample.input["title"], "T1: first")
        self.assertIn("traceback line 1", sample.input["symptoms"])
        self.assertEqual(sample.expected, {
            "namespace": "inference/vllm-ascend",
            "category": "interrupt",
            "resolution": "fixed by PR #1",
            "fix_commit": "PR #1",
            "confidence": "high",
        })

    def test_duplicate_source_is_skipped_on_second_import(self):
        self.import_samples()
        stats = self.import_samples()
        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["skipped_duplicate_source"], 2)
        self.assertEqual(len(self.store.list(status="candidate")), 2)

    def test_limit_caps_created_rows_not_scanned_rows(self):
        stats = self.import_samples(limit=1)
        self.assertEqual(stats["created"], 1)
        self.assertEqual(stats["created_ids"], ["VLLM-ASC-111"])
        self.assertTrue(stats["limit_reached"])

    def test_missing_source_is_a_clear_adapter_error(self):
        with self.assertRaises(AdapterError) as ctx:
            s2.import_s2_samples(
                self.root, "eval/s2/nope.yaml", self.store,
            )
        self.assertIn("cannot read S2 calibration", str(ctx.exception))

    def test_bad_calibration_shape_is_reported(self):
        bad = self.root / "eval" / "s2" / "bad.yaml"
        bad.write_text("calibration: not-a-list\n", encoding="utf-8")
        with self.assertRaises(AdapterError) as ctx:
            s2.import_s2_samples(self.root, "eval/s2/bad.yaml", self.store)
        self.assertIn("no calibration/issues list", str(ctx.exception))


BASE_STATS = {
    "issues": [
        {"id": "1", "hit": True},
        {"id": "2", "hit": False},
        {"id": "3", "hit": True, "held_out": True},
        {"id": "4", "hit": True, "non_diagnostic": "no signal"},
        {"id": "5", "hit": None},
        {"id": "7", "hit": True},
    ]
}

CAND_STATS = {
    "issues": [
        {"id": "1", "hit": False},
        {"id": "2", "hit": True},
        {"id": "3", "hit": False},
        {"id": "4", "hit": False},
        {"id": "5", "hit": True},
        {"id": "6", "hit": True},
        {"id": "7", "hit": True},
    ]
}


class ArenaCountsTest(unittest.TestCase):
    def test_paired_counts_only_uses_same_judgeable_ids(self):
        counts = arena.paired_counts(BASE_STATS, CAND_STATS)
        self.assertEqual(counts["b"], 1, "样本 2：候选命中、基线未命中")
        self.assertEqual(counts["c"], 1, "样本 1：基线命中、候选未命中")
        self.assertEqual(counts["n"], 3, "只有 1/2/7 两侧同 id 且 hit 可判")
        self.assertEqual(counts["paired_ids"], ["1", "2", "7"])
        self.assertEqual(counts["candidate_only_ids"], ["2"])
        self.assertEqual(counts["baseline_only_ids"], ["1"])

    def test_counts_from_files_reads_both_stats(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = root / "stats-a.yaml"
            cand = root / "stats-b.yaml"
            base.write_text(yaml.safe_dump(BASE_STATS), encoding="utf-8")
            cand.write_text(yaml.safe_dump(CAND_STATS), encoding="utf-8")
            counts = arena.counts_from_files(base, cand)
        self.assertEqual((counts["b"], counts["c"], counts["n"]), (1, 1, 3))

    def test_counts_from_files_rejects_cross_pool_epochs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = root / "stats-a.yaml"
            cand = root / "stats-b.yaml"
            base.write_text(yaml.safe_dump(dict(BASE_STATS, pool_hash="h1")), encoding="utf-8")
            cand.write_text(yaml.safe_dump(dict(CAND_STATS, pool_hash="h2")), encoding="utf-8")
            with self.assertRaises(AdapterError) as ctx:
                arena.counts_from_files(base, cand)
        self.assertIn("cross-pool", str(ctx.exception))

    def test_counts_from_files_rejects_stale_absorption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = root / "stats-a.yaml"
            cand = root / "stats-b.yaml"
            stale = {"stale": True, "checked": True}
            base.write_text(yaml.safe_dump(dict(BASE_STATS, absorption_recheck=stale)), encoding="utf-8")
            cand.write_text(yaml.safe_dump(CAND_STATS), encoding="utf-8")
            with self.assertRaises(AdapterError) as ctx:
                arena.counts_from_files(base, cand)
        self.assertIn("stale", str(ctx.exception))

    def test_bad_stats_shape_is_a_clear_adapter_error(self):
        with self.assertRaises(AdapterError):
            arena.paired_counts({"issues": "nope"}, CAND_STATS)
        with self.assertRaises(AdapterError):
            arena.paired_counts([], CAND_STATS)


class LegacyWrapperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "eval" / "s2" / "vllm-ascend.yaml"
        self.path.parent.mkdir(parents=True)
        self.path.write_text(S2_FIXTURE, encoding="utf-8")

    def test_replay_prepare_and_collect_write_to_explicit_paths(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            replay.prepare(self.root)
        input_file = self.root / ".s2-replay" / "111.md"
        self.assertTrue(input_file.exists())
        self.assertIn("issue #111", input_file.read_text(encoding="utf-8"))

        (self.root / ".s2-replay" / "111.result.yaml").write_text(
            "namespace: inference/vllm-ascend\ncategory: interrupt\n"
            "hit_case: VLLM-ASC-111\nroot_cause: fixed by PR #1\n"
            "routing_ok: true\ntier2_hit: true\nroot_cause_ok: true\n",
            encoding="utf-8",
        )
        report = self.root / "reports" / "replay.md"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            replay.collect(self.root, report)
        self.assertTrue(report.exists())
        text = report.read_text(encoding="utf-8")
        self.assertIn("S2 Replay 评分报告", text)
        self.assertIn("111", text)

    def test_import_failure_names_module_and_fix(self):
        with mock.patch(
            "evolve.adapters.importlib.import_module",
            side_effect=ImportError("No module named 's2_replay'"),
        ):
            with self.assertRaises(AdapterError) as ctx:
                load_legacy("s2_replay")
        message = str(ctx.exception)
        self.assertIn("s2_replay", message)
        self.assertIn("scripts/", message)

    def test_evidence_wrapper_forwards_to_legacy_compare(self):
        verdict, note = evidence.compare("same line", "same line")
        self.assertEqual((verdict, note), ("PASS", None))

    def test_cards_wrapper_forwards_next_id(self):
        card_id = cards.next_id(self.root)
        self.assertRegex(card_id, r"^EV-\d{4}-\d{3}$")


if __name__ == "__main__":
    unittest.main()
