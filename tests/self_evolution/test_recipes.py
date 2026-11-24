# -*- coding: utf-8 -*-
"""recipe 目录：加载、字段校验与未知名字。"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.recipes import RecipeError, get_recipe, load_recipes  # noqa: E402


class RecipeLoadTest(unittest.TestCase):
    def test_shipped_recipes_load(self):
        recipes = load_recipes(ROOT)
        self.assertEqual(sorted(recipes), ["control", "gepa-default", "skillopt-fast"])
        self.assertEqual(recipes["control"].loop, "baseline")
        self.assertEqual(recipes["gepa-default"].loop, "gepa")
        self.assertEqual(recipes["skillopt-fast"].loop, "skillopt")
        self.assertEqual(recipes["skillopt-fast"].params["epochs"], 2)
        self.assertEqual(recipes["skillopt-fast"].budget["target_runs"], 30)
        self.assertEqual(get_recipe("skillopt-fast", ROOT).id, "skillopt-fast")

    def test_guide_lists_every_recipe(self):
        guide = (ROOT / "docs" / "guide" / "algorithm-recipes.md").read_text(
            encoding="utf-8")
        for name in load_recipes(ROOT):
            self.assertIn(f"`{name}`", guide)

    def test_unknown_recipe_rejected(self):
        with self.assertRaises(RecipeError):
            get_recipe("nope", ROOT)


class RecipeValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dir = self.root / "config" / "rsi" / "recipes"
        self.dir.mkdir(parents=True)

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_id_must_match_filename(self):
        self.write("a.yaml", "id: b\nloop: baseline\nroles: {eval: eval}\n"
                             "description: d\nuse_when: u\nsource: s\n")
        with self.assertRaises(RecipeError):
            load_recipes(self.root)

    def test_id_and_version_are_optional(self):
        self.write("new.yaml", "loop: baseline\nroles: {eval: eval}\n"
                             "description: d\nuse_when: u\nsource: s\n")
        recipe = load_recipes(self.root)["new"]
        self.assertEqual(recipe.id, "new")
        self.assertEqual(recipe.version, 1)

    def test_unknown_loop_rejected(self):
        self.write("a.yaml", "id: a\nloop: nope\nroles: {eval: eval}\n"
                             "description: d\nuse_when: u\nsource: s\n")
        with self.assertRaises(RecipeError):
            load_recipes(self.root)

    def test_roles_must_cover_loop(self):
        self.write("a.yaml", "id: a\nloop: skillopt\nroles: {eval: eval}\n"
                             "description: d\nuse_when: u\nsource: s\n")
        with self.assertRaises(RecipeError):
            load_recipes(self.root)

    def test_unknown_param_rejected(self):
        self.write("a.yaml", "id: a\nloop: skillopt\n"
                             "roles: {train: train, dev: dev}\n"
                             "params: {nope: 1}\n"
                             "description: d\nuse_when: u\nsource: s\n")
        with self.assertRaises(RecipeError):
            load_recipes(self.root)

    def test_zero_budget_rejected(self):
        self.write("a.yaml", "id: a\nloop: baseline\nroles: {eval: eval}\n"
                             "budget: {target_runs: 0}\n"
                             "description: d\nuse_when: u\nsource: s\n")
        with self.assertRaises(RecipeError):
            load_recipes(self.root)


if __name__ == "__main__":
    unittest.main()
