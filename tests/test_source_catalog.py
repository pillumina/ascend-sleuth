#!/usr/bin/env python3
"""源码仓目录（source-catalog.d）的加载、等价性与校验测试。

这一层是数据，行为的失败形态是**静默**的：仓表挪进 YAML 后，写坏一条别名或漏一条
self_test，脚本只会给出不同的候选或不给候选，不会报错。所以这里钉住三件事：
①加载结果与迁移前的常量逐条等价（21 种写法、16 个已知仓、13 个签名候选、12 条真实签名）
②结构校验能报出写坏的数据 ③`--catalog` 能隔离加载（场景测试与私有部署的入口）。
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import source_catalog  # noqa: E402


# 迁移前 scripts/src_fetch.py 的 KNOWN_REPOS 等价快照：写法 → (canonical, 有序 host)
LEGACY_KNOWN = {
    "vllm-ascend": ("vllm-project/vllm-ascend", ["github"]),
    "vllm-project/vllm-ascend": ("vllm-project/vllm-ascend", ["github"]),
    "mindspeed-llm": ("Ascend/MindSpeed-LLM", ["gitcode"]),
    "Ascend/MindSpeed-LLM": ("Ascend/MindSpeed-LLM", ["gitcode"]),
    "mindspeed-mm": ("Ascend/MindSpeed-MM", ["gitcode"]),
    "Ascend/MindSpeed-MM": ("Ascend/MindSpeed-MM", ["gitcode"]),
    "torch-npu": ("Ascend/pytorch", ["gitcode", "github"]),
    "Ascend/pytorch": ("Ascend/pytorch", ["gitcode", "github"]),
    "verl": ("volcengine/verl", ["github"]),
    "volcengine/verl": ("volcengine/verl", ["github"]),
    "cann/ops-nn": ("cann/ops-nn", ["gitcode"]),
    "cann/ops-transformer": ("cann/ops-transformer", ["gitcode"]),
    "cann/ops-math": ("cann/ops-math", ["gitcode"]),
    "cann/ops-cv": ("cann/ops-cv", ["gitcode"]),
    "cann/hccl": ("cann/hccl", ["gitcode"]),
    "cann/hcomm": ("cann/hcomm", ["gitcode"]),
    "cann/ge": ("cann/ge", ["gitcode"]),
    "cann/metadef": ("cann/metadef", ["gitcode"]),
    "cann/runtime": ("cann/runtime", ["gitcode"]),
    "cann/driver": ("cann/driver", ["gitcode"]),
    "cann/asc-devkit": ("cann/asc-devkit", ["gitcode"]),
}

# 迁移前 ORG_SIGNATURE_REPOS 的候选仓顺序（同分时的稳定次序）
LEGACY_CANDIDATE_REPOS = [
    "ops-nn", "ops-transformer", "ops-math", "ops-cv", "hccl", "hcomm", "ge",
    "metadef", "runtime", "driver", "asc-devkit", "pyasc", "oam-tools",
]


class DefaultCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = source_catalog.load_catalog(source_catalog.default_dir(ROOT))

    def test_catalog_has_no_problems(self):
        self.assertEqual(self.cat.problems, [])
        self.assertEqual(self.cat.validate(), [])

    def test_known_table_equals_legacy_constants(self):
        """21 种写法逐条等价：canonical 与 host 顺序都不能变（host 顺序就是回退顺序）。"""
        got = {}
        for key in LEGACY_KNOWN:
            canonical, sources = self.cat.lookup(key)
            self.assertIsNotNone(sources, f"{key} 在目录里查不到")
            got[key] = (canonical, [src["host"] for src in sources])
        self.assertEqual(got, LEGACY_KNOWN)

    def test_known_table_keeps_legacy_repos(self):
        """旧的 16 个仓必须都在；新增仓只改数据，所以这里不钉总数。"""
        known_canonicals = {canonical for canonical, _sources in self.cat.known.values()}
        legacy_canonicals = {canonical for canonical, _hosts in LEGACY_KNOWN.values()}
        self.assertLessEqual(legacy_canonicals, known_canonicals)
        self.assertGreaterEqual(len(self.cat.known), len(LEGACY_KNOWN))
        for repo in ("cann/pyasc", "cann/oam-tools"):
            self.assertIn(repo, self.cat.repos)
            self.assertIsNone(self.cat.lookup(repo)[1], f"{repo} 不该进已知表")
            self.assertTrue(self.cat.sources_for(repo), f"{repo} 的 sources 要能按 canonical 取到")

    def test_cann_candidates_keep_legacy_order(self):
        got = [repo.short for repo in self.cat.discover_repos("cann")]
        self.assertEqual(got[:len(LEGACY_CANDIDATE_REPOS)], LEGACY_CANDIDATE_REPOS)

    def test_self_test_cases_cover_real_signatures(self):
        legacy_cases = set()
        for _org, sig, expect in self.cat.self_tests:
            self.assertIn(expect, self.cat.repos)
            legacy_cases.add((sig, expect))
        self.assertEqual(len(legacy_cases), len(self.cat.self_tests), "同一条签名用例重复")
        self.assertGreaterEqual(len(self.cat.self_tests), 12)

    def test_added_layer_does_not_break_legacy_snapshot(self):
        """只改数据加一个层/仓，不该让等价性用例红（RFC 的「补仓只改数据」）。"""
        import shutil
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "source-catalog.d"
            shutil.copytree(source_catalog.default_dir(ROOT), base)
            (base / "review.yaml").write_text("""
layer: review
title: 评审夹具层
orgs:
  - {name: acme, host: github, enumerable: false}
repos:
  - repo: acme/ops-new
    sources: [{host: github, owner: acme, repo: ops-new}]
    discover: {any_of: [brandnew], primary: [brandnew]}
self_test:
  - {sig: "brandnew failure", expect: acme/ops-new}
""", encoding="utf-8")
            cat = source_catalog.load_catalog(base)
            self.assertEqual(cat.validate(), [])
            self.assertIn("review", cat.layers)
            self.assertEqual(cat.lookup("acme/ops-new")[0], "acme/ops-new")
            for key in LEGACY_KNOWN:
                self.assertIsNotNone(cat.lookup(key)[1], f"新增层后 {key} 仍要能查到")

    def test_top_candidates_for_representative_signatures(self):
        cases = {
            "HcclCommInitRootInfo failed": "hccl",
            "ge::GEExecuteRun error": "ge",
            "aclnnQuantBatchMatMulV3 execute failed": "ops-math",
            "aclnnFlashAttentionScore failed": "ops-transformer",
        }
        for sig, expected in cases.items():
            with self.subTest(sig=sig):
                self.assertEqual(self.cat.candidates("cann", sig)[0][0], expected)

    def test_unknown_repo_keeps_input_spelling(self):
        """未登记的仓保留调用方写法：转小写可能让区分大小写的 host 取不到仓。"""
        canonical, sources = self.cat.lookup("NoSuch/Repo-Name.git")
        self.assertEqual(canonical, "NoSuch/Repo-Name")
        self.assertIsNone(sources)

    def test_cann_org_is_enumerable_gitcode(self):
        org = self.cat.orgs["cann"]
        self.assertEqual(org.host, "gitcode")
        self.assertTrue(org.enumerable)
        self.assertEqual(self.cat.orgs["cann"].name, "cann")


class FixtureCatalogTest(unittest.TestCase):
    def _write(self, base: Path, name: str, text: str) -> None:
        (base / name).write_text(text, encoding="utf-8")

    def test_bad_data_is_reported_not_swallowed(self):
        """写坏的数据必须在加载时报出来：大写关键词、重复别名、缺 sources。"""
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            self._write(base, "a.yaml", """
layer: a
orgs:
  - {name: acme, host: gitcode, enumerable: false}
repos:
  - repo: acme/foo
    sources: [{host: gitcode, owner: acme, repo: foo}]
    aliases: [dupe]
    discover: {any_of: [FooBar], primary: [FooBar]}
  - repo: acme/bar
    aliases: [dupe]
    discover: {any_of: [bar], primary: [bar]}
""")
            cat = source_catalog.load_catalog(base)
            problems = "\n".join(cat.validate())
            self.assertIn("大写", problems)
            self.assertIn("缺 sources", problems)
            self.assertIn("同时指向", problems)

    def test_custom_catalog_isolated(self):
        """--catalog 用夹具目录时，不该看到默认目录的仓。"""
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            self._write(base, "fixture.yaml", """
layer: fixture
orgs:
  - {name: acme, host: custom, enumerable: false}
repos:
  - repo: acme/ops-foo
    sources: [{host: custom, url: "file:///tmp/does-not-matter"}]
    discover: {any_of: [foox], primary: [foox]}
self_test:
  - {sig: "foox failed", expect: acme/ops-foo}
""")
            cat = source_catalog.load_catalog(base)
            self.assertEqual(cat.validate(), [])
            self.assertEqual(cat.lookup("acme/ops-foo")[0], "acme/ops-foo")
            self.assertIsNotNone(cat.lookup("acme/ops-foo")[1])
            self.assertIsNone(cat.lookup("vllm-ascend")[1])
            self.assertEqual(cat.candidates("acme", "foox failed")[0][0], "ops-foo")


if __name__ == "__main__":
    unittest.main()
