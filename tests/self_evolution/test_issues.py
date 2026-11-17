"""issue → 候选样本：元数据、过滤、body、state 与 dry-run。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.adapters import AdapterError  # noqa: E402
from evolve.adapters import issues  # noqa: E402
from evolve.samples import SampleStore  # noqa: E402

LONG_BODY = "Traceback ... runtime error on this node; reproduce steps and logs " * 2


def item(number, **overrides):
    values = {
        "number": number,
        "title": f"T{number}",
        "comments": 5,
        "closed_at": "2026-11-01T00:00:00Z",
        "state_reason": "completed",
        "labels": ["triaged"],
    }
    values.update(overrides)
    return values


def body(text=LONG_BODY, title=None, closed_at="2026-11-01T00:00:00Z"):
    return {"title": title, "body": text, "closed_at": closed_at}


class FetchWsTest(unittest.TestCase):
    def test_fetch_metadata_uses_slim_and_excludes_prs(self):
        captured = {}

        class FakeFetch:
            @staticmethod
            def gh_api(url):
                captured["url"] = url
                return [
                    {"number": 1, "title": "issue", "pull_request": None},
                    {"number": 2, "title": "pr", "pull_request": {}},
                ]

            @staticmethod
            def slim(value):
                return {"number": value["number"], "title": value["title"]}

        with mock.patch.object(issues, "load_legacy", return_value=FakeFetch):
            result = issues.fetch_metadata(
                "vllm-project/vllm-ascend", labels=["triaged"], since="2026-01-01T00:00:00Z",
            )
        self.assertEqual([row["number"] for row in result], [1])
        self.assertIn("labels=triaged", captured["url"])
        self.assertIn("since=2026-01-01T00:00:00Z", captured["url"])

    def test_fetch_body_keeps_only_first_post(self):
        class FakeFetch:
            @staticmethod
            def gh_api(url):
                return {
                    "title": "issue title",
                    "body": "first post body",
                    "closed_at": "2026-11-01T00:00:00Z",
                    "comments": 9,
                    "comments_url": "https://example.com/comments",
                }

        with mock.patch.object(issues, "load_legacy", return_value=FakeFetch):
            result = issues.fetch_body("o/r", {"number": 7})
        self.assertEqual(result, {
            "title": "issue title",
            "body": "first post body",
            "closed_at": "2026-11-01T00:00:00Z",
        })
        self.assertNotIn("comments", result)

    def test_gh_missing_has_actionable_error(self):
        class FakeFetch:
            @staticmethod
            def gh_api(url):
                raise FileNotFoundError("gh")

        with mock.patch.object(issues, "load_legacy", return_value=FakeFetch):
            with self.assertRaises(AdapterError) as ctx:
                issues.fetch_metadata("o/r")
        self.assertIn("gh CLI not found", str(ctx.exception))


class FilterTest(unittest.TestCase):
    def test_hard_filter_and_sort(self):
        rows = [
            item(1),
            item(2, pull_request={}),
            item(3),
            item(4, labels=["documentation"]),
            item(5, comments=1),
            item(6, title="[Feature] add option"),
            item(7, labels=["bug"], comments=8),
        ]
        candidates = issues.filter_candidates(
            rows, processed={3}, labels=["triaged", "bug"], min_comments=3, limit=None,
        )
        self.assertEqual([row["number"] for row in candidates], [1, 7])
        self.assertEqual(
            [row["number"] for row in issues.filter_candidates(
                rows, processed=set(), labels=["triaged", "bug"],
                min_comments=3, limit=1,
            )],
            [1],
        )

    def test_unknown_labels_do_not_crash(self):
        self.assertEqual(
            [row["number"] for row in issues.filter_candidates(
                [item(1, labels=[])], processed=None, labels=[], min_comments=0, limit=None,
            )],
            [1],
        )

    def test_invalid_limits(self):
        for value in (-1, "1", True):
            with self.subTest(value=value):
                with self.assertRaises(AdapterError):
                    issues.filter_candidates([], set(), [], 3, value)


class CandidateTest(unittest.TestCase):
    def test_candidate_fields_and_no_answer(self):
        metadata = item(
            42, title="metadata title", labels=[{"name": "triaged"}],
            closed_at="2026-11-02T00:00:00Z",
        )
        candidate = issues.issue_to_candidate(
            metadata, body("body text " * 4, title="body title"), "vllm-project/vllm-ascend",
        )
        self.assertTrue(candidate["id"].startswith("GH-VLLM-PROJECT-VLLM-ASCEND-42"))
        self.assertEqual(candidate["object_type"], "diagnosis")
        self.assertEqual(candidate["origin"], "field")
        self.assertEqual(candidate["purpose"], "evaluation")
        self.assertEqual(candidate["source"], "github/vllm-project/vllm-ascend#42")
        self.assertEqual(candidate["input"], {"title": "body title", "body": "body text " * 4})
        self.assertIsNone(candidate["expected"])
        self.assertEqual(candidate["proposed"]["labels"], ["triaged"])
        self.assertEqual(candidate["proposed"]["closed_at"], "2026-11-01T00:00:00Z")
        self.assertIn("/issues/42", candidate["proposed"]["url"])
        self.assertNotIn("comments", candidate["input"])
        self.assertNotIn("resolution", candidate["input"])


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = SampleStore(self.root)
        self.state = self.root / "ingest-state.json"

    def run_ingest(self, items, bodies, **kwargs):
        calls = []

        def fetch_body(repo, issue):
            calls.append(issue["number"])
            value = bodies[issue["number"]]
            if isinstance(value, BaseException):
                raise value
            return value

        stats = issues.ingest_issues(
            self.root,
            "o/r",
            store=self.store,
            state_path=self.state,
            fetch_metadata_fn=lambda repo, labels, since: items,
            fetch_body_fn=fetch_body,
            **kwargs,
        )
        return stats, calls

    def test_creates_candidate_without_expected_and_marks_state(self):
        stats, calls = self.run_ingest([item(1)], {1: body()})
        self.assertEqual(stats["created"], 1)
        self.assertEqual(calls, [1])
        sample = self.store.require(stats["created_ids"][0])
        self.assertEqual(sample.status, "candidate")
        self.assertIsNone(sample.expected)
        self.assertEqual(sample.source, "github/o/r#1")
        self.assertIn("Traceback", sample.input["body"])
        self.assertTrue(Path(stats["created_paths"][0]).exists())
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(state["sources"]["github/o/r"]["processed"], [1])
        self.assertFalse(list(self.state.parent.glob(".tmp-*.json")))

    def test_dry_run_writes_nothing(self):
        stats, _ = self.run_ingest([item(1)], {1: body()}, dry_run=True)
        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["would_create"], ["GH-O-R-1"])
        self.assertFalse(self.store.samples_dir.exists())
        self.assertFalse(self.state.exists())

    def test_duplicate_source_is_skipped_on_second_run(self):
        self.run_ingest([item(1)], {1: body()})
        stats, calls = self.run_ingest([item(1)], {1: body()})
        self.assertEqual(stats["created"], 0)
        self.assertEqual(calls, [])
        self.assertEqual(stats["skipped_processed"], 1)

    def test_body_empty_short_and_feature_title_are_skipped(self):
        items = [item(1), item(2), item(3), item(4)]
        bodies = {
            1: body(""),
            2: body("short"),
            3: body(LONG_BODY, title="[Feature] add option"),
            4: body(),
        }
        stats, _ = self.run_ingest(items, bodies)
        self.assertEqual(stats["created"], 1)
        self.assertEqual(stats["skipped_empty_body"], 1)
        self.assertEqual(stats["skipped_short_body"], 1)
        self.assertEqual(stats["skipped_feature_title"], 1)

    def test_limit_caps_created_not_body_attempts(self):
        items = [item(1), item(2)]
        stats, calls = self.run_ingest(items, {1: body(""), 2: body()}, limit=1)
        self.assertEqual(stats["created"], 1)
        self.assertEqual(calls, [1, 2])
        self.assertFalse(stats["limit_reached"])

    def test_limit_zero_does_not_fetch_body(self):
        stats, calls = self.run_ingest([item(1)], {1: body()}, limit=0)
        self.assertEqual(stats["created"], 0)
        self.assertEqual(calls, [])
        self.assertTrue(stats["limit_reached"])

    def test_processed_state_excludes_issue(self):
        self.state.write_text(
            json.dumps({"sources": {"github/o/r": {"processed": [1]}}}),
            encoding="utf-8",
        )
        stats, calls = self.run_ingest([item(1)], {1: body()})
        self.assertEqual(stats["created"], 0)
        self.assertEqual(stats["skipped_processed"], 1)
        self.assertEqual(calls, [])

    def test_fetch_failure_does_not_mark_processed(self):
        with self.assertRaises(AdapterError):
            self.run_ingest([item(1), item(2)], {1: body(), 2: FileNotFoundError("gh")})
        self.assertFalse(self.state.exists())
        self.assertEqual(len(self.store.list(status="candidate")), 1)

    def test_dry_run_honours_limit_and_does_not_fetch_extra_bodies(self):
        stats, calls = self.run_ingest(
            [item(1), item(2)], {1: body(), 2: body()}, dry_run=True, limit=1,
        )
        self.assertEqual(stats["would_create"], ["GH-O-R-1"])
        self.assertEqual(stats["created"], 0)
        self.assertEqual(calls, [1])
        self.assertTrue(stats["limit_reached"])

    def test_state_root_and_sample_base_can_differ(self):
        state_root = self.root / "worktree"
        state_root.mkdir()
        sample_base = self.root / "main" / ".s2-replay" / "evolve"
        store = SampleStore(base=sample_base)
        stats = issues.ingest_issues(
            state_root, "o/r", store=store, state_path="ingest-state.json",
            fetch_metadata_fn=lambda repo, labels, since: [item(1)],
            fetch_body_fn=lambda repo, issue: body(),
        )
        self.assertEqual(stats["created"], 1)
        self.assertTrue((state_root / "ingest-state.json").exists())
        self.assertTrue((sample_base / "samples" / "GH-O-R-1.yaml").exists())
        self.assertFalse((state_root / ".s2-replay").exists())

    def test_evaluation_state_namespace_is_separate_from_case_ingest(self):
        stats = issues.ingest_issues(
            self.root, "o/r", store=self.store, state_path=self.state,
            state_key="github/o/r/evaluation",
            fetch_metadata_fn=lambda repo, labels, since: [item(1)],
            fetch_body_fn=lambda repo, issue: body(),
        )
        self.assertEqual(stats["state_key"], "github/o/r/evaluation")
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertIn("github/o/r/evaluation", state["sources"])
        self.assertNotIn("github/o/r", state["sources"])

    def test_metadata_failure_is_adapter_error(self):
        def failing(repo, labels, since):
            raise FileNotFoundError("gh")

        with self.assertRaises(AdapterError) as ctx:
            issues.ingest_issues(
                self.root, "o/r", store=self.store, state_path=self.state,
                fetch_metadata_fn=failing, fetch_body_fn=lambda repo, issue: body(),
            )
        self.assertIn("gh CLI not found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
