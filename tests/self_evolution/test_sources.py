"""issue 数据源：GitHub 包装、本地导出、registry 与 state 分区。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.adapters import AdapterError  # noqa: E402
from evolve.adapters import issues  # noqa: E402
from evolve.samples import SampleStore  # noqa: E402
from evolve.sources import GitHubSource, LocalSource, get_source  # noqa: E402


class GitHubSourceTest(unittest.TestCase):
    def test_source_id_and_list_fetch(self):
        calls = []

        class FakeFetch:
            @staticmethod
            def gh_api(url):
                calls.append(url)
                if "/issues/7" in url:
                    return {"title": "T7", "body": "body", "closed_at": None,
                            "comments": 9}
                return [
                    {"number": 1, "title": "issue", "pull_request": None},
                    {"number": 2, "title": "pr", "pull_request": {}},
                ]

            @staticmethod
            def slim(item):
                return {"number": item["number"], "title": item["title"]}

        source = GitHubSource("o/r", loader=lambda name: FakeFetch)
        self.assertEqual(source.source_id, "github/o/r")
        items = source.list_issues("o/r", labels=["triaged"], since="2026-01-01T00:00:00Z")
        self.assertEqual([item["number"] for item in items], [1])
        self.assertIn("labels=triaged", calls[0])
        body = source.fetch_issue("o/r", 7)
        self.assertEqual(body, {"title": "T7", "body": "body", "closed_at": None})


class LocalSourceTest(unittest.TestCase):
    def write(self, path, data):
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_json_list_with_body(self):
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "issues.json"
            self.write(cache, [
                {"number": 1, "title": "T1", "body": "long body", "repo": "o/r",
                 "state": "closed", "labels": ["triaged"]},
                {"number": 2, "title": "T2", "body": "other", "repo": "x/y",
                 "state": "closed"},
                {"number": 3, "title": "T3", "body": "open", "repo": "o/r",
                 "state": "open"},
            ])
            source = LocalSource(cache, repo="o/r")
            self.assertEqual(source.source_id, "local/o/r")
            items = source.list_issues("o/r", labels=None, since=None, state="closed")
            self.assertEqual([item["number"] for item in items], [1])
            self.assertEqual(source.fetch_issue("o/r", 1)["body"], "long body")
            with self.assertRaises(AdapterError):
                source.fetch_issue("o/r", 99)

    def test_yaml_issues_envelope(self):
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "issues.yaml"
            cache.write_text(
                "issues:\n- {number: 4, title: T4, body: b, state: closed}\n",
                encoding="utf-8",
            )
            source = LocalSource(cache, repo="o/r")
            self.assertEqual([item["number"] for item in source.list_issues(
                "o/r", None, None, "closed")], [4])

    def test_bad_cache_is_adapter_error(self):
        with tempfile.TemporaryDirectory() as td:
            source = LocalSource(Path(td) / "missing.json", repo="o/r")
            with self.assertRaises(AdapterError):
                source.list_issues("o/r", None, None, "closed")


class RegistryTest(unittest.TestCase):
    def test_known_sources_and_unknown(self):
        self.assertIsInstance(get_source("github", repo="o/r"), GitHubSource)
        with tempfile.TemporaryDirectory() as td:
            cache = Path(td) / "issues.json"
            cache.write_text("[]", encoding="utf-8")
            self.assertIsInstance(get_source("local", repo="o/r", cache=cache), LocalSource)
        with self.assertRaises(AdapterError):
            get_source("gitcode", repo="o/r")
        with self.assertRaises(AdapterError):
            get_source("local", repo="o/r")


class StateSeparationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = SampleStore(self.root)
        self.state = self.root / "state.json"

    def test_local_and_github_keep_separate_state_and_sources(self):
        cache = self.root / "issues.json"
        cache.write_text(json.dumps([{
            "number": 1, "title": "T1", "body": "long body enough for ingest " * 2,
            "comments": 5, "state": "closed", "labels": ["triaged"],
        }]), encoding="utf-8")
        local = LocalSource(cache, repo="o/r")
        local_stats = issues.ingest_issues(
            self.root, "o/r", store=self.store, state_path=self.state,
            source=local, fetch_metadata_fn=None, fetch_body_fn=None,
        )
        self.assertEqual(local_stats["source"], "local/o/r")
        sample = self.store.require(local_stats["created_ids"][0])
        self.assertTrue(sample.source.startswith("local/o/r#"))
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertIn("local/o/r", state["sources"])

        class FakeGitHub:
            source_id = "github/o/r"

            def list_issues(self, repo, labels, since, state="closed"):
                return [{"number": 2, "title": "T2", "comments": 5,
                         "labels": ["triaged"], "state_reason": "completed"}]

            def fetch_issue(self, repo, number):
                return {"title": "T2", "body": "long body enough for ingest " * 2,
                        "closed_at": None}

        github_stats = issues.ingest_issues(
            self.root, "o/r", store=self.store, state_path=self.state,
            source=FakeGitHub(),
        )
        self.assertEqual(github_stats["source"], "github/o/r")
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(sorted(state["sources"]), ["github/o/r", "local/o/r"])


if __name__ == "__main__":
    unittest.main()
