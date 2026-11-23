"""各目标的工件规则：路径许可、体积上限与写前检查。

规则按目标各写一条，不在 candidate 里按 target_kind 串 if/elif。新增目标时加一条
规则并在 ``TARGETS`` 里引用；candidate、proposal_engine、migrate 不再各存一份枚举。

写前检查只判语法与结构（YAML 可解析、Python 可编译、scheduler 有键），不判语义。
"""

import json
from typing import Any

import yaml

from .base import ArtifactRule

# 只有 tooling 目标会看这两个清单：它的改动面是工具实现与路由数据。
FORBIDDEN_PREFIXES = (
    ".git/", ".github/", "knowledge/", "references/", "postmortems/",
    "eval/", "tests/", "docs/", "skills/", ".s2-replay/", ".worktrees/",
)
TOOLING_SUFFIXES = (".py", ".yaml", ".yml", ".json")

# harness 不能改演化包自身、封存样本、测试、部署配置与默认流水线
# （两个清单合起来就是这五类）；改了这些路径，实验无法用同一套判据复核。
HARNESS_FORBIDDEN_PREFIXES = ("scripts/evolve/", "eval/core/", "tests/")
HARNESS_FORBIDDEN_FILES = ("eval/holdout.yaml", "sleuth.config.yaml",
                           "config/rsi/pipelines.yaml")


def _skill_allowed(file: str, region: Any) -> bool:
    return file.startswith(f"skills/{region.skill}/") and file.endswith(".md")


def _knowledge_allowed(file: str, region: Any) -> bool:
    del region
    return file.startswith(("knowledge/", "references/")) \
        and file.endswith((".yaml", ".yml"))


def _harness_allowed(file: str, region: Any) -> bool:
    del region
    if file.startswith(HARNESS_FORBIDDEN_PREFIXES):
        return False
    if file in HARNESS_FORBIDDEN_FILES:
        return False
    return file.startswith(("scripts/", "eval/")) \
        and file.endswith((".py", ".yaml", ".yml", ".json"))


def _tooling_allowed(file: str, region: Any) -> bool:
    if any(file == prefix or file.startswith(prefix.rstrip("/") + "/")
           for prefix in FORBIDDEN_PREFIXES):
        return False
    if not file.endswith(TOOLING_SUFFIXES):
        return False
    return any(file == path or file.startswith(path.rstrip("/") + "/")
               for path in region.paths)


def _no_check(file: str, text: str) -> None:
    del file, text


def _knowledge_check(file: str, text: str) -> None:
    del file
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"knowledge YAML is invalid: {exc}") from exc
    if not isinstance(doc, dict) or not doc.get("id"):
        raise ValueError("knowledge YAML must be an object with id")


def _harness_check(file: str, text: str) -> None:
    if file.endswith(".py"):
        try:
            compile(text, file, "exec")
        except SyntaxError as exc:
            raise ValueError(f"harness Python is invalid: {exc}") from exc
    elif file.endswith((".yaml", ".yml")):
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"harness YAML is invalid: {exc}") from exc
        if file.endswith("scheduler.yaml"):
            if not isinstance(doc, dict) or "scheduler" not in doc:
                raise ValueError("harness scheduler.yaml requires scheduler key")
    elif file.endswith(".json"):
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"harness JSON is invalid: {exc}") from exc


def _tooling_check(file: str, text: str) -> None:
    if file.endswith(".py"):
        try:
            compile(text, file, "exec")
        except SyntaxError as exc:
            raise ValueError(f"tooling Python is invalid: {exc}") from exc
    elif file.endswith((".yaml", ".yml")):
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"tooling YAML is invalid: {exc}") from exc
    elif file.endswith(".json"):
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"tooling JSON is invalid: {exc}") from exc


SKILL_ARTIFACT = ArtifactRule(
    kind="text", max_text=8000, allowed=_skill_allowed, check=_no_check,
    region_owns_skill=True,
)
KNOWLEDGE_ARTIFACT = ArtifactRule(
    kind="yaml", max_text=12000, allowed=_knowledge_allowed, check=_knowledge_check,
)
TOOLING_ARTIFACT = ArtifactRule(
    kind="code", max_text=20000, allowed=_tooling_allowed, check=_tooling_check,
)
HARNESS_ARTIFACT = ArtifactRule(
    kind="config", max_text=20000, allowed=_harness_allowed, check=_harness_check,
)
