# -*- coding: utf-8 -*-
"""搜索循环 recipe：一个文件一条，供 `sleuth.config.yaml` 按名字选择。

recipe 是用户可复制的完整包：loop、params、budget、roles 与用途说明。参数
注释写在同一文件里；用户复制一份、改文件名与 id，再改参数即可派生新 recipe。
本模块只读与校验，不调用模型、不写文件。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .errors import EvolveError
from .loops import get_loop, param_errors
from .loops.budget import BUDGET_KINDS


class RecipeError(EvolveError, ValueError):
    """recipe 文件缺失、字段不合法或重名。"""


@dataclass(frozen=True)
class Recipe:
    id: str
    loop: str
    description: str
    use_when: str
    roles: Dict[str, str] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    budget: Dict[str, int] = field(default_factory=dict)
    source: str = ""
    version: int = 1
    path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "loop": self.loop,
            "description": self.description, "use_when": self.use_when,
            "roles": dict(self.roles), "params": dict(self.params),
            "budget": dict(self.budget), "source": self.source,
            "version": self.version, "path": self.path,
        }


def default_recipes_dir(root: Optional[Any] = None) -> Path:
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    return base / "config" / "rsi" / "recipes"


def _text(data: Dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RecipeError(f"{path}: {key} must be a non-empty string")
    return value.strip()


def _recipe_from_file(path: Path) -> Recipe:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RecipeError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise RecipeError(f"{path}: recipe must be an object")
    recipe_id = raw.get("id") or path.stem
    if recipe_id != path.stem:
        raise RecipeError(
            f"{path}: id {recipe_id!r} must match filename {path.stem!r}"
        )
    loop = raw.get("loop")
    if not isinstance(loop, str) or not loop.strip():
        raise RecipeError(f"{path}: loop is required")
    try:
        spec = get_loop(loop)
    except ValueError as exc:
        raise RecipeError(f"{path}: {exc}") from exc
    roles = raw.get("roles") or {}
    if not isinstance(roles, dict):
        raise RecipeError(f"{path}: roles must be an object")
    expected = set(spec.required_roles)
    if set(roles) != expected:
        raise RecipeError(
            f"{path}: roles must match {sorted(expected)}, got {sorted(roles)}"
        )
    for role, mapped in roles.items():
        if not isinstance(mapped, str) or not mapped.strip():
            raise RecipeError(f"{path}: roles.{role} must be a non-empty string")
    params = raw.get("params") or {}
    errors = param_errors(spec, params)
    if errors:
        raise RecipeError(f"{path}: params: {'; '.join(errors)}")
    budget = raw.get("budget") or {}
    if not isinstance(budget, dict):
        raise RecipeError(f"{path}: budget must be an object")
    for key, value in budget.items():
        if key not in BUDGET_KINDS:
            raise RecipeError(
                f"{path}: budget.{key} is not one of {list(BUDGET_KINDS)}"
            )
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 1
        ):
            raise RecipeError(
                f"{path}: budget.{key} must be a positive integer or null"
            )
    version = raw.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise RecipeError(f"{path}: version must be a positive integer")
    return Recipe(
        id=str(recipe_id), loop=str(loop),
        description=_text(raw, "description", path),
        use_when=_text(raw, "use_when", path),
        roles={str(k): str(v) for k, v in roles.items()},
        params=dict(params), budget=dict(budget),
        source=_text(raw, "source", path),
        version=version, path=str(path),
    )


def load_recipes(root: Optional[Any] = None) -> Dict[str, Recipe]:
    directory = default_recipes_dir(root)
    if not directory.is_dir():
        raise RecipeError(f"recipe directory not found: {directory}")
    recipes: Dict[str, Recipe] = {}
    for path in sorted(directory.glob("*.yaml")):
        recipe = _recipe_from_file(path)
        if recipe.id in recipes:
            raise RecipeError(f"duplicate recipe id {recipe.id!r}")
        recipes[recipe.id] = recipe
    if not recipes:
        raise RecipeError(f"no recipes in {directory}")
    return recipes


def get_recipe(name: str, root: Optional[Any] = None) -> Recipe:
    recipes = load_recipes(root)
    try:
        return recipes[str(name)]
    except KeyError as exc:
        raise RecipeError(
            f"unknown recipe {name!r}; expected one of {sorted(recipes)}"
        ) from exc


def recipe_ids(root: Optional[Any] = None) -> List[str]:
    return sorted(load_recipes(root))
