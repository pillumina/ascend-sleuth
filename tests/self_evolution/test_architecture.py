"""架构边界：核心不 import CLI/适配器/旧脚本，不打印，不各自实现统计与状态机。"""

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "scripts" / "evolve"
ADAPTERS_DIR = PACKAGE / "adapters"

PURE_MODULES = (
    "contracts.py",
    "object_types.py",
    "metrics.py",
    "statistics.py",
    "decision.py",
    "pools.py",
    "ports.py",
)
ALL_MODULES = [path.name for path in sorted(PACKAGE.glob("*.py"))]
IO_MODULES = ("samples.py", "records.py", "policy.py", "cli.py")
ADAPTER_MODULES = [
    path.name for path in sorted(ADAPTERS_DIR.glob("*.py"))
]
# 适配器允许反向 import 旧脚本；核心模块不允许。这里只做正向声明，反向边界由
# ImportBoundaryTest 守。
ADAPTER_LEGACY_MAP = {
    "replay.py": "s2_replay",
    "evidence.py": "verify_evidence",
    "cards.py": "ev_proposal",
    "health.py": "evolution_health",
    "issues.py": "issue_filter",
}

FORBIDDEN = (
    "evolve.cli",
    "evolve.adapters",
    "eval_arena",
    "s2_replay",
    "ev_proposal",
    "verify_evidence",
    "evolution_health",
    "metrics_health",
    "evolve_intake",
    "evolve_mode",
    "evolve_signals",
    "doctor",
)

NETWORK_OR_MODEL = ("requests", "urllib", "http", "socket", "openai", "anthropic",
                    "transformers", "torch")


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = "evolve" + ("." + module if module else "")
            modules.append(module)
            modules.extend(f"{module}.{alias.name}" for alias in node.names)
    return modules


def calls_to(tree, name):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == name:
            found.append(node.lineno)
    return found


def function_names(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


class PackageLayoutTest(unittest.TestCase):
    def test_required_modules_exist(self):
        required = {
            "__init__.py", "contracts.py", "object_types.py", "metrics.py",
            "statistics.py", "decision.py", "pools.py", "policy.py",
            "samples.py", "records.py", "ports.py", "runner.py", "cli.py",
        }
        self.assertEqual(required - set(ALL_MODULES), set())
        self.assertEqual(
            {"__init__.py", "s2.py", "arena.py", "replay.py",
             "evidence.py", "cards.py", "health.py", "issues.py"} - set(ADAPTER_MODULES),
            set(),
        )
        self.assertTrue((ROOT / "scripts" / "evolve.py").exists())
        self.assertTrue((ROOT / "sleuth.config.yaml").exists())

    def test_wrapper_is_thin(self):
        text = (ROOT / "scripts" / "evolve.py").read_text(encoding="utf-8")
        self.assertIn("from evolve.cli import main", text)
        self.assertLessEqual(len(text.splitlines()), 30)


class ImportBoundaryTest(unittest.TestCase):
    def test_non_cli_modules_do_not_import_cli_adapters_or_old_scripts(self):
        for name in ALL_MODULES:
            if name in ("cli.py", "__init__.py"):
                continue
            modules = imported_modules(PACKAGE / name)
            for forbidden in FORBIDDEN:
                self.assertFalse(
                    any(module == forbidden or module.startswith(forbidden + ".")
                        for module in modules),
                    f"{name} must not import {forbidden}",
                )

    def test_no_network_or_model_dependency(self):
        for path in [PACKAGE / name for name in ALL_MODULES] + [ROOT / "scripts" / "evolve.py"]:
            for module in imported_modules(path):
                root = module.split(".")[0]
                self.assertNotIn(root, NETWORK_OR_MODEL, f"{path.name} imports {module}")

    def test_adapters_may_reference_legacy_scripts(self):
        """适配器是反向依赖的允许方向：它们可以包旧脚本，核心不行。"""
        for name, legacy in ADAPTER_LEGACY_MAP.items():
            source = (ADAPTERS_DIR / name).read_text(encoding="utf-8")
            self.assertIn(f'load_legacy("{legacy}")', source,
                          f"{name} should wrap {legacy} through load_legacy")

    def test_core_modules_do_not_import_adapters(self):
        for name in ALL_MODULES:
            if name in ("cli.py", "__init__.py"):
                continue
            modules = imported_modules(PACKAGE / name)
            self.assertFalse(
                any(module == "evolve.adapters" or module.startswith("evolve.adapters.")
                    for module in modules),
                f"{name} must not import evolve.adapters",
            )

    def test_decision_depends_on_statistics(self):
        modules = imported_modules(PACKAGE / "decision.py")
        self.assertIn("evolve.statistics", modules)

    def test_samples_delegates_state_machine_to_pools(self):
        modules = imported_modules(PACKAGE / "samples.py")
        self.assertIn("evolve.pools", modules)
        text = (PACKAGE / "samples.py").read_text(encoding="utf-8")
        self.assertNotIn("STATUS_TRANSITIONS =", text)
        self.assertIn("assert_transition(", text)


class PurityTest(unittest.TestCase):
    def test_pure_core_does_not_print(self):
        for name in ALL_MODULES:
            tree = ast.parse((PACKAGE / name).read_text(encoding="utf-8"))
            if name == "cli.py":
                continue
            self.assertEqual(calls_to(tree, "print"), [], f"{name} must not print")

    def test_pure_core_does_not_read_files_or_environment(self):
        for name in PURE_MODULES:
            source = (PACKAGE / name).read_text(encoding="utf-8")
            tree = ast.parse(source)
            self.assertEqual(calls_to(tree, "open"), [], f"{name} must not open files")
            for forbidden in ("os.environ", "os.getenv", "pathlib", "open("):
                self.assertNotIn(forbidden, source, f"{name} must not use {forbidden}")

    def test_only_statistics_defines_paired_test(self):
        definitions = []
        for path in PACKAGE.glob("*.py"):
            if "exact_mcnemar_ge" in function_names(path):
                definitions.append(path.name)
        self.assertEqual(definitions, ["statistics.py"])

    def test_only_pools_defines_transition_table(self):
        definitions = []
        for path in PACKAGE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                targets = []
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, ast.AnnAssign):
                    targets = [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id == "STATUS_TRANSITIONS":
                        definitions.append(path.name)
        self.assertEqual(definitions, ["pools.py"])

    def test_ports_only_protocols(self):
        tree = ast.parse((PACKAGE / "ports.py").read_text(encoding="utf-8"))
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        self.assertTrue(classes)
        for node in classes:
            bases = [getattr(base, "id", getattr(base, "attr", "")) for base in node.bases]
            self.assertIn("Protocol", bases, f"{node.name} must be a Protocol")


if __name__ == "__main__":
    unittest.main()
