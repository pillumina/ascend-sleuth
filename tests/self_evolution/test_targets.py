"""优化目标：与评估对象分开，按 target 静态分发。"""

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.regions import REGIONS  # noqa: E402
from evolve.targets.base import ARTIFACT_KINDS  # noqa: E402
from evolve.targets.registry import (  # noqa: E402
    TARGETS,
    artifact_kind,
    get_target,
    resolve_optimizer,
    target_ids,
)

PACKAGE = ROOT / "scripts" / "evolve"


def _string_literals(node):
    """节点里出现的字符串字面量集合；不是容器则返回 None。"""
    if isinstance(node, ast.Dict):
        return {key.value for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)}
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return {item.value for item in node.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)}
    return None


class TargetRegistryTest(unittest.TestCase):
    def test_four_targets_are_registered(self):
        self.assertEqual(target_ids(), ["harness", "knowledge", "skill", "tooling"])
        self.assertEqual(TARGETS["harness"].authority, "A1")
        self.assertEqual(TARGETS["skill"].authority, "A2")

    def test_unknown_target_is_an_error(self):
        with self.assertRaises(ValueError):
            get_target("magic")

    def test_baseline_resolves_for_every_target(self):
        for key in target_ids():
            spec, optimizer = resolve_optimizer(key)
            self.assertEqual(spec.id, key)
            self.assertEqual(optimizer.id, "baseline")

    def test_unregistered_algorithm_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_optimizer("skill", "magic")

    def test_algorithm_not_allowed_for_target_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_optimizer("harness", "ael")


class TargetSingleSourceTest(unittest.TestCase):
    """一个目标的全部事实只在 TARGETS 里写一遍。"""

    def test_every_target_declares_artifact_and_proposal_boundary(self):
        for key in target_ids():
            spec = get_target(key)
            self.assertIn(spec.artifact.kind, ARTIFACT_KINDS)
            self.assertGreater(spec.artifact.max_text, 0)
            self.assertTrue(spec.allowed_paths)
            self.assertTrue(spec.prompt_rules)
            self.assertTrue(spec.required_checks)

    def test_artifact_kind_is_derived_from_registry(self):
        self.assertEqual(artifact_kind("skill"), "text")
        self.assertEqual(artifact_kind("knowledge"), "yaml")
        self.assertEqual(artifact_kind("tooling"), "code")
        self.assertEqual(artifact_kind("harness"), "config")
        self.assertEqual(artifact_kind("unknown-target"), "unknown")

    def test_every_region_belongs_to_a_registered_target(self):
        for region in REGIONS.values():
            self.assertIn(region.target_kind, TARGETS, region.id)

    def test_no_module_redeclares_the_target_set(self):
        names = set(TARGETS)
        for path in PACKAGE.rglob("*.py"):
            rel = path.relative_to(PACKAGE).as_posix()
            if rel == "targets/registry.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"),
                             filename=str(path))
            for node in ast.walk(tree):
                values = _string_literals(node)
                if values is not None and names <= values:
                    self.fail(
                        f"{rel}:{node.lineno} repeats the target set; "
                        f"read it from targets.registry instead"
                    )


if __name__ == "__main__":
    unittest.main()
