#!/usr/bin/env python3
"""单一部署配置（sleuth.config.yaml）的读取与校验。

新用户只维护仓库根的 sleuth.config.yaml：部署角色、自演进策略、成本 profile、
RSI store 与同步模式都在这一份文件里。没有旧文件 fallback；
没有 sleuth.config.yaml 时使用内置默认值。
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

CONFIG_NAME = "sleuth.config.yaml"
SCHEMA = "sleuth-config-v1"
ROLES = ("maintainer", "signal-only", "off")
ROLE_ALIASES = {"full": "maintainer", "record-only": "signal-only"}
SYNC_MODES = ("auto", "offline")

DEFAULTS: Dict[str, Any] = {
    "schema": SCHEMA,
    "deployment": {"name": ""},
    "evolution": {
        "role": "maintainer",
        "store": {"backend": "local", "path": ".s2-replay/evolve/rsi-events.jsonl"},
        "policy": {},
        "profiles": {},
    },
    "sync": {"mode": "auto"},
}


class ConfigError(ValueError):
    pass


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = copy.deepcopy(base)
        for key, value in override.items():
            merged[key] = _deep_merge(merged.get(key), value)
        return merged
    return copy.deepcopy(override)


def find_root(start: Optional[Path] = None) -> Path:
    start = Path(start or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / CONFIG_NAME).is_file():
            return candidate
    return start


def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} 解析失败：{exc}") from exc
    except OSError as exc:
        raise ConfigError(f"读不到 {path}：{exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} 顶层必须是映射")
    return raw


def _normalize_role(value: Any, source: str) -> str:
    if isinstance(value, bool):
        if value is False:
            return "off"
        raise ConfigError(f"{source} 的 evolution.role 被读成布尔值 True；请加引号")
    role = str(value or "").strip()
    role = ROLE_ALIASES.get(role, role)
    if role not in ROLES:
        raise ConfigError(
            f"{source} 的 evolution.role 是 {value!r}，不在 {list(ROLES)} 里"
        )
    return role



def load_config(root: Optional[Path] = None, path: Optional[Path] = None) -> Dict[str, Any]:
    root = Path(root or find_root()).resolve()
    config_path = Path(path) if path else root / CONFIG_NAME
    if not config_path.is_file():
        cfg = copy.deepcopy(DEFAULTS)
        cfg["_source"] = "built-in defaults（无 sleuth.config.yaml）"
        cfg["_root"] = str(root)
        return cfg
    raw = _read_yaml(config_path)
    allowed = set(DEFAULTS)
    unknown = set(raw) - allowed
    if unknown:
        raise ConfigError(f"{config_path} 含未知顶层键：{sorted(unknown)}")
    cfg = _deep_merge(DEFAULTS, raw)
    if cfg.get("schema") != SCHEMA:
        raise ConfigError(f"{config_path} 的 schema 必须是 {SCHEMA!r}")
    if not isinstance(cfg.get("deployment"), dict):
        raise ConfigError(f"{config_path} 的 deployment 必须是映射")
    evolution = cfg.get("evolution")
    if not isinstance(evolution, dict):
        raise ConfigError(f"{config_path} 的 evolution 必须是映射")
    evolution["role"] = _normalize_role(evolution.get("role"), str(config_path))
    policy = evolution.get("policy")
    if not isinstance(policy, dict):
        raise ConfigError("evolution.policy 必须是映射")
    if not isinstance(policy.get("experiment", {}), dict):
        raise ConfigError("evolution.policy.experiment 必须是映射")
    profiles = evolution.get("profiles")
    if not isinstance(profiles, dict):
        raise ConfigError("evolution.profiles 必须是映射")
    for name, value in profiles.items():
        if not isinstance(value, dict):
            raise ConfigError(f"evolution.profiles.{name} 必须是映射")
        if not isinstance(value.get("experiment", {}), dict):
            raise ConfigError(f"evolution.profiles.{name}.experiment 必须是映射")
    if not isinstance(evolution.get("store"), dict):
        raise ConfigError("evolution.store 必须是映射")
    sources = evolution.get("pipeline_config") or []
    if isinstance(sources, str):
        sources = [sources]
    if not isinstance(sources, list):
        raise ConfigError("evolution.pipeline_config 必须是字符串或字符串列表")
    for rel in sources:
        path = (root / str(rel)).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ConfigError(f"pipeline_config 逃出仓库根：{rel}") from exc
        if not path.is_file():
            raise ConfigError(f"pipeline_config 文件不存在：{path}")
    sync = cfg.get("sync")
    if not isinstance(sync, dict):
        raise ConfigError("sync 必须是映射，例如 sync: {mode: auto}")
    if sync.get("mode") not in SYNC_MODES:
        raise ConfigError(f"sync.mode 必须是 {list(SYNC_MODES)} 之一")
    cfg["_source"] = str(config_path)
    cfg["_root"] = str(root)
    return cfg


POLICY_KEY_ALIASES = {
    "objective.primary_metric": "objective.primary",
    "cost.primary_cost_metric": "cost.primary_dimension",
    "cost.maximum_cost_increase_ratio": "cost.B",
    "cost.minimum_cost_improvement": "cost.epsilon",
    "cost.max_quality_drop": "cost.delta",
    "samples.field_evaluation": "samples.field_eval",
}
COST_VALUE_ALIASES = {
    "elapsed_time": "time",
    "tool_calls": "calls",
}
AUTONOMY_VALUE_ALIASES = {
    "observe": "A0",
    "propose": "A1",
    "batch_review": "A2",
    "supervised_auto": "A3",
    "policy_auto": "A4",
    "full_auto": "A5",
}


def _normalize_policy(raw: Dict[str, Any]) -> Dict[str, Any]:
    def walk(value: Any, prefix: str = "") -> Any:
        if not isinstance(value, dict):
            return value
        out: Dict[str, Any] = {}
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            target = POLICY_KEY_ALIASES.get(path)
            if target:
                target_key = target.rsplit(".", 1)[-1]
                out[target_key] = walk(item, target)
            else:
                out[key] = walk(item, path)
        return out
    normalized = walk(copy.deepcopy(raw))
    cost = normalized.get("cost")
    if isinstance(cost, dict) and cost.get("primary_dimension") in COST_VALUE_ALIASES:
        cost["primary_dimension"] = COST_VALUE_ALIASES[cost["primary_dimension"]]
    autonomy = normalized.get("autonomy")
    if isinstance(autonomy, dict):
        level = autonomy.get("default")
        if isinstance(level, str) and level in AUTONOMY_VALUE_ALIASES:
            autonomy["default"] = AUTONOMY_VALUE_ALIASES[level]
        overrides = autonomy.get("overrides")
        if isinstance(overrides, dict):
            autonomy["overrides"] = {
                key: AUTONOMY_VALUE_ALIASES.get(value, value) if isinstance(value, str) else value
                for key, value in overrides.items()
            }
    return normalized


def policy_for(config: Dict[str, Any], profile: Optional[str] = None) -> Dict[str, Any]:
    evolution = config.get("evolution") or {}
    policy = copy.deepcopy(evolution.get("policy") or {})
    if profile:
        profiles = evolution.get("profiles") or {}
        if profile not in profiles:
            raise ConfigError(f"未知策略 profile {profile!r}；可选 {sorted(profiles)}")
        policy = _deep_merge(policy, profiles[profile])
    return _normalize_policy(policy)


def _load_pipeline_sources(config: Dict[str, Any]) -> Dict[str, Any]:
    root = Path(config.get("_root") or ".")
    evolution = config.get("evolution") or {}
    sources = evolution.get("pipeline_config") or []
    if isinstance(sources, str):
        sources = [sources]
    if not isinstance(sources, list):
        raise ConfigError("evolution.pipeline_config 必须是字符串或字符串列表")
    merged: Dict[str, Any] = {}
    for rel in sources:
        path = (root / str(rel)).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise ConfigError(f"pipeline_config 逃出仓库根：{rel}") from exc
        if not path.is_file():
            raise ConfigError(f"pipeline_config 文件不存在：{path}")
        doc = _read_yaml(path)
        pipelines = doc.get("pipelines")
        if not isinstance(pipelines, dict):
            raise ConfigError(f"{path} 必须包含 pipelines 映射")
        merged = _deep_merge(merged, pipelines)
    return merged


def pipeline_names(config: Dict[str, Any]) -> list:
    return sorted(_load_pipeline_sources(config))


def pipeline_for(config: Dict[str, Any], name: Optional[str] = None) -> Dict[str, Any]:
    evolution = config.get("evolution") or {}
    pipelines = _load_pipeline_sources(config)
    selected = name or evolution.get("pipeline") or "default"
    if not pipelines:
        return {"name": "default", "description": "built-in stage defaults", "stages": {}}
    if selected not in pipelines:
        raise ConfigError(f"未知 pipeline {selected!r}；可选 {sorted(pipelines)}")
    def resolve(key: str, seen: tuple = ()) -> Dict[str, Any]:
        if key in seen:
            raise ConfigError(f"pipeline extends 循环：{' -> '.join(seen + (key,))}")
        item = pipelines.get(key)
        if not isinstance(item, dict):
            raise ConfigError(f"pipeline {key!r} 必须是映射")
        base = {}
        parent = item.get("extends")
        if parent:
            base = resolve(str(parent), seen + (key,))
        stages = _deep_merge(base.get("stages") or {}, item.get("stages") or {})
        return {"name": key, "description": item.get("description") or "",
                "stages": stages}
    return resolve(str(selected))


def store_for(config: Dict[str, Any]) -> Dict[str, Any]:
    return dict((config.get("evolution") or {}).get("store") or {})


def role(config: Dict[str, Any]) -> str:
    return str((config.get("evolution") or {}).get("role") or "maintainer")


def sync_mode(config: Dict[str, Any]) -> str:
    return str((config.get("sync") or {}).get("mode") or "auto")


def main(argv=None):
    import argparse
    import json
    parser = argparse.ArgumentParser(description="读取/校验 sleuth.config.yaml")
    parser.add_argument("--root", default=None)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(Path(args.root) if args.root else None)
        pipeline = pipeline_for(cfg)
    except ConfigError as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 2
    payload = {
        "source": cfg.get("_source"),
        "role": role(cfg),
        "sync": sync_mode(cfg),
        "store": store_for(cfg),
        "profiles": sorted((cfg.get("evolution") or {}).get("profiles") or {}),
        "pipeline": pipeline["name"],
        "pipelines": pipeline_names(cfg),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"source={payload['source']}")
        print(f"role={payload['role']} sync={payload['sync']}")
        print(f"store={payload['store']}")
        print(f"profiles={','.join(payload['profiles']) or '—'}")
        print(f"pipeline={payload['pipeline']} pipelines={','.join(payload['pipelines']) or '—'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
