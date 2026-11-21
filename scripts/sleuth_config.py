#!/usr/bin/env python3
"""单一部署配置（sleuth.yaml）的读取、校验与旧配置兼容。

新用户只维护仓库根的 sleuth.yaml：部署角色、自演进策略、成本 profile、
RSI store 与同步模式都在这一份文件里。旧的 deployment.yaml、
eval/policy*.yaml、.s2-replay/evolve/store.yaml 只在没有 sleuth.yaml 时
作为 legacy fallback 读取，不再作为新入口。
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

CONFIG_NAME = "sleuth.yaml"
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
        if (candidate / CONFIG_NAME).is_file() or (candidate / "deployment.yaml").is_file():
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


def _legacy(root: Path) -> Dict[str, Any]:
    cfg = copy.deepcopy(DEFAULTS)
    evo = cfg["evolution"]
    decl = root / "deployment.yaml"
    if decl.is_file():
        doc = _read_yaml(decl)
        evo["role"] = _normalize_role((doc.get("evolution") or {}).get("mode", "full"),
                                      "deployment.yaml")
        if (doc.get("sync") or {}).get("mode"):
            cfg["sync"]["mode"] = str(doc["sync"]["mode"])
    policy_path = root / "eval" / "policy.yaml"
    if policy_path.is_file():
        evo["policy"] = _read_yaml(policy_path)
    latency = root / "eval" / "policy-latency.yaml"
    if latency.is_file():
        evo["profiles"] = {"latency": _read_yaml(latency)}
    store = root / ".s2-replay" / "evolve" / "store.yaml"
    if store.is_file():
        evo["store"] = _read_yaml(store)
    return cfg


def load_config(root: Optional[Path] = None, path: Optional[Path] = None) -> Dict[str, Any]:
    root = Path(root or find_root()).resolve()
    config_path = Path(path) if path else root / CONFIG_NAME
    if not config_path.is_file():
        cfg = _legacy(root)
        cfg["_source"] = "legacy（deployment.yaml / eval/policy*.yaml / store.yaml）"
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
    if not isinstance(evolution.get("policy"), dict):
        raise ConfigError("evolution.policy 必须是映射")
    if not isinstance(evolution.get("profiles"), dict):
        raise ConfigError("evolution.profiles 必须是映射")
    if not isinstance(evolution.get("store"), dict):
        raise ConfigError("evolution.store 必须是映射")
    if cfg["sync"].get("mode") not in SYNC_MODES:
        raise ConfigError(f"sync.mode 必须是 {list(SYNC_MODES)} 之一")
    cfg["_source"] = str(config_path)
    cfg["_root"] = str(root)
    return cfg


def policy_for(config: Dict[str, Any], profile: Optional[str] = None) -> Dict[str, Any]:
    evolution = config.get("evolution") or {}
    policy = copy.deepcopy(evolution.get("policy") or {})
    if profile:
        profiles = evolution.get("profiles") or {}
        if profile not in profiles:
            raise ConfigError(f"未知策略 profile {profile!r}；可选 {sorted(profiles)}")
        policy = _deep_merge(policy, profiles[profile])
    return policy


def store_for(config: Dict[str, Any]) -> Dict[str, Any]:
    return dict((config.get("evolution") or {}).get("store") or {})


def role(config: Dict[str, Any]) -> str:
    return str((config.get("evolution") or {}).get("role") or "maintainer")


def sync_mode(config: Dict[str, Any]) -> str:
    return str((config.get("sync") or {}).get("mode") or "auto")


def main(argv=None):
    import argparse
    import json
    parser = argparse.ArgumentParser(description="读取/校验 sleuth.yaml")
    parser.add_argument("--root", default=None)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(Path(args.root) if args.root else None)
    except ConfigError as exc:
        print(f"error: {exc}", file=__import__("sys").stderr)
        return 2
    payload = {
        "source": cfg.get("_source"),
        "role": role(cfg),
        "sync": sync_mode(cfg),
        "store": store_for(cfg),
        "profiles": sorted((cfg.get("evolution") or {}).get("profiles") or {}),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"source={payload['source']}")
        print(f"role={payload['role']} sync={payload['sync']}")
        print(f"store={payload['store']}")
        print(f"profiles={','.join(payload['profiles']) or '—'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
