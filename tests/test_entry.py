# -*- coding: utf-8 -*-
"""知识条目读取入口：枚举、解析、路径→命名空间。"""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import _entry  # noqa: E402


def _write(root: Path, rel: str, doc) -> Path:
    path = root / "knowledge" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


class NamespaceTest(unittest.TestCase):
    def test_framework_layer_is_folded(self):
        self.assertEqual(_entry.namespace_of(Path("training/verl/interrupt/x.yaml")),
                         "training/verl")
        self.assertEqual(_entry.namespace_of(Path("inference/sglang/precision/x.yaml")),
                         "inference/sglang")

    def test_platforms_layer_is_not_a_category(self):
        self.assertEqual(_entry.namespace_of(Path("training/verl/platforms/x.yaml")),
                         "training/verl/platforms")

    def test_common_is_flat(self):
        self.assertEqual(_entry.namespace_of(Path("common/precision/x.yaml")), "common")

    def test_root_level_file_has_empty_namespace(self):
        self.assertEqual(_entry.namespace_of(Path("x.yaml")), "")

    def test_framework_leaf_is_separate_from_namespace(self):
        self.assertEqual(_entry.framework_of(Path("training/verl/interrupt/x.yaml")), "verl")
        self.assertEqual(_entry.framework_of(Path("common/precision/x.yaml")), "common")

    def test_category_dir_of(self):
        cats = ("interrupt", "precision", "performance")
        self.assertEqual(_entry.category_dir_of(Path("training/verl/interrupt/x.yaml"), cats),
                         "interrupt")
        self.assertEqual(_entry.category_dir_of(Path("common/precision/x.yaml"), cats),
                         "precision")
        self.assertEqual(_entry.category_dir_of(Path("training/verl/platforms/x.yaml"), cats), "")
        self.assertEqual(_entry.category_dir_of(Path("x.yaml"), cats), "")


class EnumerateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_skips_archive_and_generated_index(self):
        _write(self.root, "training/verl/interrupt/a.yaml", {"cases": [{"id": "A", "category": "interrupt"}]})
        _write(self.root, "_archive/training/verl/interrupt/old.yaml", {"cases": [{"id": "OLD"}]})
        _write(self.root, "_index/training__verl.list", {})
        _write(self.root, "_index.yaml", {"namespaces": {}})
        files = [rel.as_posix() for _p, rel in _entry.iter_case_files(self.root)]
        self.assertEqual(files, ["training/verl/interrupt/a.yaml"])
        with_archive = [rel.as_posix() for _p, rel in _entry.iter_case_files(
            self.root, include_archive=True)]
        self.assertEqual(with_archive, [
            "_archive/training/verl/interrupt/old.yaml",
            "training/verl/interrupt/a.yaml",
        ])

    def test_iter_case_docs_yields_documents_with_location(self):
        _write(self.root, "training/verl/interrupt/a.yaml", {"cases": [
            {"id": "A-1", "category": "interrupt"},
            {"id": "A-2", "category": "interrupt"},
        ]})
        docs = list(_entry.iter_case_docs(self.root))
        self.assertEqual(len(docs), 1)
        _path, rel, doc = docs[0]
        self.assertEqual([c["id"] for c in doc["cases"]], ["A-1", "A-2"])
        self.assertEqual(rel.as_posix(), "training/verl/interrupt/a.yaml")

    def test_bad_yaml_can_be_skipped_or_raised(self):
        bad = self.root / "knowledge" / "training" / "verl" / "interrupt" / "bad.yaml"
        bad.parent.mkdir(parents=True)
        bad.write_text("cases: [\n", encoding="utf-8")
        with self.assertRaises(yaml.YAMLError):
            list(_entry.iter_case_docs(self.root))
        self.assertEqual(list(_entry.iter_case_docs(self.root, skip_bad=True)), [])

    def test_workload_and_nature(self):
        p = self.root / "knowledge" / "training" / "verl" / "interrupt" / "x.yaml"
        p.parent.mkdir(parents=True)
        p.write_text("cases: []\n", encoding="utf-8")
        self.assertEqual(_entry.workload_and_nature(self.root, p), ("training", "interrupt"))
        common = self.root / "knowledge" / "common" / "precision" / "x.yaml"
        common.parent.mkdir(parents=True)
        common.write_text("cases: []\n", encoding="utf-8")
        self.assertEqual(_entry.workload_and_nature(self.root, common), ("", ""))
        outside = self.root / "docs" / "x.yaml"
        outside.parent.mkdir(parents=True)
        outside.write_text("{}\n", encoding="utf-8")
        self.assertEqual(_entry.workload_and_nature(self.root, outside), ("", ""))


if __name__ == "__main__":
    unittest.main()
