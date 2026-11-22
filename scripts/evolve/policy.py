"""可调策略：默认值、加载校验、规范化哈希与自动化档位解析。

``sleuth.config.yaml`` 的 ``evolution.policy`` 是唯一调参入口；旧路径仅兼容。加载时递归校验未知键与非法枚举，
未知键直接报错，不静默忽略；哈希只覆盖影响判定的内容，写进结论的
``versions.policy``。
"""

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .algorithms.registry import ALGORITHMS
from .targets.registry import TARGETS, get_target
from .stages import get_stage
from .decision import DECISION_METHODS
from .metrics import DEFAULT_METRICS

AUTONOMY_LEVELS = ("A0", "A1", "A2", "A3", "A4", "A5")
OBJECTIVE_PRIMARY = ("case_hit", "root_cause", "rubric")
SPLIT_METHODS = ("hash", "group")
COST_DIMENSIONS = ("tokens", "calls", "rounds", "time")
BUDGET_METRICS = ("billed", "uncached", "out", "uncached_out", "cache_read",
                  "calls", "rounds", "ms", "time")
HARD_CONSTRAINT_NAMES = tuple(DEFAULT_METRICS) + ("regression", "test")

# RFC §12 默认值；和 tracked 的 sleuth.config.yaml evolution.policy 保持一致，测试会比对。
DEFAULTS: Dict[str, Any] = {
    "autonomy": {
        "default": "A2",
        "overrides": {
            "docs.non_normative": "A3",
            "docs.normative": "A1",
            "feedback.candidate": "A3",
            "feedback.pool": "A2",
        },
        "auto_merge": {"enabled": False},
    },
    "objective": {
        "primary": "case_hit",
        "hard_constraints": ["safety", "fix", "regression", "test"],
    },
    "decision": {"method": "paired_binary", "alpha": 0.10},
    "samples": {
        "core_regression": 30,
        "field_eval": 9,
        "test": 4,
        "split": "hash",
        "strata": {},
    },
    "cost": {
        "primary_dimension": "tokens",
        "budget_metric": "billed",
        "B": 0.10,
        "epsilon": 0.10,
        "delta": 0,
        "runs": {
            "max_pairs": 9,
            "max_tokens": None,
            "early_stop": True,
            "baseline_reuse": True,
            "regression_pairs": 6,
            "regression_full_pairs": 30,
            "benchmark_runs": 3,
        },
    },
    "rubrics": {
        "case_version": "case-v1",
        "reference_version": "ref-v1",
        "threshold": 0.7,
        "double_label": 10,
    },
    "experiment": {
        "target": "skill",
        "algorithm": "baseline",
        "stages": {
            "attribute": "attribute.trace_rule",
            "select_region": "select.region_hardcount",
            "select_candidate": "select.best",
            "propose": "propose.agent",
            "judge": "judge.subagent",
            "gate": "gate.paired",
        },
        "budget": {},
        "seed": 0,
    },
}

# 自由形态映射：键由部署决定，值仍逐项校验。
_FREE_FORM = {"autonomy.overrides", "samples.strata", "experiment.budget"}


class PolicyError(ValueError):
    """策略文件缺失、含未知键或非法取值。"""


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _unknown_paths(data: Any, schema: Any, prefix: str = "") -> List[str]:
    if prefix in _FREE_FORM:
        return []
    if not isinstance(data, dict):
        return [f"{prefix or '<root>'}: expected an object"]
    errors: List[str] = []
    for key, value in data.items():
        child = f"{prefix}.{key}" if prefix else str(key)
        if not isinstance(schema, dict) or key not in schema:
            errors.append(f"unknown policy key: {child}")
            continue
        if isinstance(value, dict) and isinstance(schema[key], dict):
            errors.extend(_unknown_paths(value, schema[key], child))
    return errors


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_level(value: Any, where: str, errors: List[str]) -> None:
    if value not in AUTONOMY_LEVELS:
        errors.append(f"{where} must be one of {list(AUTONOMY_LEVELS)}, got {value!r}")


def _validate_int(value: Any, where: str, errors: List[str], minimum: int = 1) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        errors.append(f"{where} must be an integer >= {minimum}, got {value!r}")


def _validate_number(value: Any, where: str, errors: List[str], minimum: float = 0.0) -> None:
    if not _is_number(value) or value < minimum:
        errors.append(f"{where} must be a number >= {minimum}, got {value!r}")


def validate_policy(policy: Dict[str, Any]) -> None:
    """校验一份完整策略（通常已与默认值合并）；失败抛 ``PolicyError``。"""
    if not isinstance(policy, dict):
        raise PolicyError(f"policy must be an object, got {type(policy).__name__}")
    errors: List[str] = _unknown_paths(policy, DEFAULTS)
    if not isinstance(policy.get("autonomy"), dict):
        errors.append("autonomy must be an object")
    else:
        autonomy = policy["autonomy"]
        _validate_level(autonomy.get("default"), "autonomy.default", errors)
        overrides = autonomy.get("overrides")
        if not isinstance(overrides, dict):
            errors.append("autonomy.overrides must be an object")
        else:
            for component, level in overrides.items():
                if not isinstance(component, str) or not component.strip():
                    errors.append("autonomy.overrides keys must be non-empty strings")
                _validate_level(level, f"autonomy.overrides.{component}", errors)
        auto_merge = autonomy.get("auto_merge")
        if not isinstance(auto_merge, dict):
            errors.append("autonomy.auto_merge must be an object")
        elif not isinstance(auto_merge.get("enabled"), bool):
            errors.append("autonomy.auto_merge.enabled must be a boolean")

    objective = policy.get("objective")
    if not isinstance(objective, dict):
        errors.append("objective must be an object")
    else:
        if objective.get("primary") not in OBJECTIVE_PRIMARY:
            errors.append(
                f"objective.primary must be one of {list(OBJECTIVE_PRIMARY)}, "
                f"got {objective.get('primary')!r}"
            )
        constraints = objective.get("hard_constraints")
        if not isinstance(constraints, list) or not all(isinstance(c, str) for c in constraints):
            errors.append("objective.hard_constraints must be a list of strings")
        else:
            unknown = [c for c in constraints if c not in HARD_CONSTRAINT_NAMES]
            if unknown:
                errors.append(
                    f"objective.hard_constraints has unknown item(s): {unknown}; "
                    f"expected subset of {list(HARD_CONSTRAINT_NAMES)}"
                )

    decision = policy.get("decision")
    if not isinstance(decision, dict):
        errors.append("decision must be an object")
    else:
        method = decision.get("method")
        if method not in DECISION_METHODS:
            errors.append(
                f"decision.method must be one of {list(DECISION_METHODS)}, got {method!r}"
            )
        alpha = decision.get("alpha")
        if not _is_number(alpha) or not (0 < alpha < 1):
            errors.append(f"decision.alpha must be a number between 0 and 1, got {alpha!r}")

    samples = policy.get("samples")
    if not isinstance(samples, dict):
        errors.append("samples must be an object")
    else:
        for key in ("core_regression", "field_eval", "test"):
            _validate_int(samples.get(key), f"samples.{key}", errors)
        if samples.get("split") not in SPLIT_METHODS:
            errors.append(
                f"samples.split must be one of {list(SPLIT_METHODS)}, got {samples.get('split')!r}"
            )
        strata = samples.get("strata")
        if not isinstance(strata, dict):
            errors.append("samples.strata must be an object")
        else:
            for key, value in strata.items():
                if not isinstance(key, str) or not key.strip():
                    errors.append("samples.strata keys must be non-empty strings")
                _validate_int(value, f"samples.strata.{key}", errors, minimum=0)

    cost = policy.get("cost")
    if not isinstance(cost, dict):
        errors.append("cost must be an object")
    else:
        runs = cost.get("runs")
        if runs is not None:
            if not isinstance(runs, dict):
                errors.append("cost.runs must be an object")
            else:
                max_pairs = runs.get("max_pairs")
                if max_pairs is not None and (
                        not isinstance(max_pairs, int) or isinstance(max_pairs, bool)
                        or max_pairs < 0):
                    errors.append("cost.runs.max_pairs must be a non-negative integer or null")
                max_tokens = runs.get("max_tokens")
                if max_tokens is not None and (
                        not isinstance(max_tokens, int) or isinstance(max_tokens, bool)
                        or max_tokens < 0):
                    errors.append("cost.runs.max_tokens must be a non-negative integer or null")
                if not isinstance(runs.get("early_stop", True), bool):
                    errors.append("cost.runs.early_stop must be boolean")
                if not isinstance(runs.get("baseline_reuse", True), bool):
                    errors.append("cost.runs.baseline_reuse must be boolean")
                for key in ("regression_pairs", "regression_full_pairs", "benchmark_runs"):
                    value = runs.get(key)
                    if value is not None and (
                            not isinstance(value, int) or isinstance(value, bool)
                            or value < 0):
                        errors.append(f"cost.runs.{key} must be a non-negative integer or null")
        if cost.get("primary_dimension") not in COST_DIMENSIONS:
            errors.append(
                f"cost.primary_dimension must be one of {list(COST_DIMENSIONS)}, "
                f"got {cost.get('primary_dimension')!r}"
            )
        if cost.get("budget_metric") not in BUDGET_METRICS:
            errors.append(
                f"cost.budget_metric must be one of {list(BUDGET_METRICS)}, "
                f"got {cost.get('budget_metric')!r}"
            )
        for key in ("B", "epsilon", "delta"):
            _validate_number(cost.get(key), f"cost.{key}", errors)
        if _is_number(cost.get("epsilon")) and not (0 <= cost["epsilon"] <= 1):
            errors.append("cost.epsilon must be between 0 and 1")

    experiment = policy.get("experiment")
    if not isinstance(experiment, dict):
        errors.append("experiment must be an object")
    else:
        if experiment.get("target") not in TARGETS:
            errors.append(
                f"experiment.target must be one of {sorted(TARGETS)}, "
                f"got {experiment.get('target')!r}"
            )
        elif experiment.get("algorithm") not in get_target(experiment["target"]).allowed_algorithms:
            errors.append(
                f"experiment.algorithm {experiment.get('algorithm')!r} is not allowed "
                f"for target {experiment.get('target')!r}"
            )
        if experiment.get("algorithm") not in ALGORITHMS:
            errors.append(
                f"experiment.algorithm must be one of {sorted(ALGORITHMS)}, "
                f"got {experiment.get('algorithm')!r}"
            )
        stages = experiment.get("stages")
        if not isinstance(stages, dict):
            errors.append("experiment.stages must be an object")
        else:
            for point, stage_id in stages.items():
                try:
                    spec = get_stage(str(stage_id))
                except ValueError as exc:
                    errors.append(f"experiment.stages.{point}: {exc}")
                    continue
                if spec.point != point:
                    errors.append(
                        f"experiment.stages.{point} must be a {point} stage, "
                        f"got {spec.id!r}"
                    )
        if not isinstance(experiment.get("budget"), dict):
            errors.append("experiment.budget must be an object")
        _validate_int(experiment.get("seed"), "experiment.seed", errors, minimum=0)

    rubrics = policy.get("rubrics")
    if not isinstance(rubrics, dict):
        errors.append("rubrics must be an object")
    else:
        for key in ("case_version", "reference_version"):
            if not isinstance(rubrics.get(key), str) or not rubrics[key].strip():
                errors.append(f"rubrics.{key} must be a non-empty string")
        threshold = rubrics.get("threshold")
        if not _is_number(threshold) or not (0 <= threshold <= 1):
            errors.append(f"rubrics.threshold must be a number between 0 and 1, got {threshold!r}")
        _validate_int(rubrics.get("double_label"), "rubrics.double_label", errors)

    if errors:
        raise PolicyError("; ".join(errors))


def _load_raw(raw: Any, source: str) -> Dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise PolicyError(f"policy must be an object, got {type(raw).__name__}")
    unknown = _unknown_paths(raw, DEFAULTS)
    if unknown:
        raise PolicyError("; ".join(unknown))
    policy = _deep_merge(DEFAULTS, raw)
    validate_policy(policy)
    return policy


def load_config_policy(config: Dict[str, Any], profile: Optional[str] = None) -> Dict[str, Any]:
    """从 sleuth.config.yaml 的 evolution.policy + profile 读取策略。"""
    import sleuth_config as SC
    try:
        raw = SC.policy_for(config, profile)
        pipeline = SC.pipeline_for(config)
        experiment = raw.setdefault("experiment", {})
        experiment["stages"] = pipeline["stages"]
    except SC.ConfigError as exc:
        raise PolicyError(str(exc)) from exc
    return _load_raw(raw, str(config.get("_source") or SC.CONFIG_NAME))


def load_policy(path: Optional[Path] = None) -> Dict[str, Any]:
    """读取并校验策略；``path=None`` 返回内置默认值。"""
    if path is None:
        policy = copy.deepcopy(DEFAULTS)
        validate_policy(policy)
        return policy
    policy_path = Path(path)
    if not policy_path.exists():
        raise PolicyError(f"policy file not found: {policy_path}")
    try:
        raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PolicyError(f"policy YAML is invalid: {exc}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise PolicyError(f"cannot read policy file {policy_path}: {exc}") from exc
    return _load_raw(raw, str(policy_path))


def canonical_json(policy: Dict[str, Any]) -> str:
    """规范化 JSON：排序键、紧凑分隔符、UTF-8；用于稳定哈希。"""
    return json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def policy_hash(policy: Dict[str, Any]) -> str:
    """返回策略的 SHA-256；同一份策略在任何机器上得到同一值。"""
    return hashlib.sha256(canonical_json(policy).encode("utf-8")).hexdigest()


canonical_hash = policy_hash


def resolve_autonomy(policy: Dict[str, Any], target_component: str) -> str:
    """按 ``target_component`` 解析自动化档位。

    覆盖表是精确匹配（例如 ``docs.non_normative``）；未命中用默认档。
    ``auto_merge.enabled=false`` 时 A3 类降到 A2——没有 auto-merge 就没有
    自动合并，档位不能只写在配置里。
    """
    autonomy = policy.get("autonomy") or {}
    overrides = autonomy.get("overrides") or {}
    level = overrides.get(target_component, autonomy.get("default", "A2"))
    if level not in AUTONOMY_LEVELS:
        raise PolicyError(f"invalid autonomy level: {level!r}")
    enabled = bool((autonomy.get("auto_merge") or {}).get("enabled", False))
    if level == "A3" and not enabled:
        return "A2"
    return level
