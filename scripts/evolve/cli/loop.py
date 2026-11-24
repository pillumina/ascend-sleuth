# -*- coding: utf-8 -*-
"""``loop`` 命令组：搜索循环的通用驱动入口。

与 ``gepa`` / ``loo`` 两个旧命令组并存：旧组读旧状态文件，本组用统一包装
``{loop, state}``，可跑注册表里的任意循环。驱动协议不变：``next`` 返回动作并
落盘待回写动作，``apply`` 按动作回写，``result`` 读结果。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from ..loops import LoopError, get_loop, loop_ids, loop_table, restore_loop
from ..recipes import RecipeError, get_recipe
from .common import PolicyError, policy_for

EXIT_STATE = 1
EXIT_INPUT = 2


def _load_config(path: str) -> Dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise LoopError("loop config must be an object")
    return data


def _factory_config(config: Dict[str, Any]) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {key: value for key, value in config.items()
                           if key not in ("params", "seed_file", "budget")}
    cfg.update(dict(config.get("params") or {}))
    budget = config.get("budget") or {}
    if not isinstance(budget, dict):
        raise LoopError("config.budget must be an object")
    for key in ("target_runs", "worker_calls", "tokens"):
        if cfg.get(key) is None and budget.get(key) is not None:
            cfg[key] = budget[key]
    if cfg.get("target_runs") is None and cfg.get("max_metric_calls") is not None:
        cfg["target_runs"] = cfg["max_metric_calls"]
    if not cfg.get("seed_text") and config.get("seed_file"):
        cfg["seed_text"] = Path(str(config["seed_file"])).read_text(encoding="utf-8")
    return cfg


def _check_config(spec, cfg: Dict[str, Any]) -> None:
    fixed = {"seed_text", "data", "target", "component", "seed", "run_id",
             "decision_log", "target_runs", "worker_calls", "tokens",
             "max_metric_calls"}
    unknown = set(cfg) - fixed - set(spec.params)
    if unknown:
        raise LoopError(
            f"unknown params for loop {spec.id!r}: {sorted(unknown)}; "
            f"allowed: {sorted(spec.params)}"
        )
    for key in ("target_runs", "worker_calls", "tokens"):
        value = cfg.get(key)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 1
        ):
            raise LoopError(f"budget {key} must be a positive integer or null")
    from ..loops import param_errors
    params = {key: value for key, value in cfg.items() if key in spec.params}
    errors = param_errors(spec, params)
    if errors:
        raise LoopError(
            f"invalid params for loop {spec.id!r}: {'; '.join(errors)}"
        )


def _read_wrapper(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise LoopError("loop state must be an object")
    if isinstance(data.get("state"), dict) and data.get("loop"):
        return data
    schema = data.get("state_schema")
    inferred = {"agent-gepa-v1": "gepa", "loo-audit-v1": "loo",
                "baseline-control-v1": "baseline", "skillopt-fast-v1": "skillopt"}
    if schema in inferred:
        return {"loop": inferred[schema], "state": data}
    raise LoopError("state is neither a loop wrapper nor a known loop schema")


def _save_wrapper(path: Path, loop_id: str, loop: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"loop": loop_id, "state": loop.to_dict()},
                               ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_loop_list(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps(loop_table(), ensure_ascii=False, indent=2))
        return 0
    for item in loop_table():
        print(f"{item['id']}\t{item['kind']}\t{item['version']}\t{item['description']}")
    return 0


def cmd_loop_show(args: argparse.Namespace) -> int:
    spec = get_loop(args.loop)
    print(json.dumps({
        "id": spec.id, "version": spec.version, "kind": spec.kind,
        "targets": list(spec.targets), "required_roles": list(spec.required_roles),
        "actions": [action.to_dict() for action in spec.actions],
        "state_schema": spec.state_schema, "params": dict(spec.params),
        "description": spec.description,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_loop_init(args: argparse.Namespace) -> int:
    state = Path(args.state)
    if state.exists() and not args.overwrite:
        print(f"error: state exists (use --overwrite): {state}", file=sys.stderr)
        return EXIT_INPUT
    try:
        policy = policy_for(args)
        experiment = policy.get("experiment") or {}
        if args.loop and args.recipe:
            raise LoopError("--loop and --recipe are mutually exclusive")
        recipe = None
        if args.loop:
            loop_id = args.loop
        else:
            recipe_name = args.recipe or str(experiment.get("recipe") or "")
            if recipe_name:
                recipe = get_recipe(recipe_name, root=args.root)
                loop_id = recipe.loop
            else:
                loop_id = str(experiment.get("loop") or "")
        if not loop_id:
            raise LoopError(
                "no loop selected: pass --recipe/--loop or set "
                "evolution.policy.experiment.recipe/loop"
            )
        spec = get_loop(loop_id)
        cfg = _factory_config(_load_config(args.config))
        if recipe is not None:
            for key, value in recipe.params.items():
                cfg.setdefault(key, value)
            for key, value in recipe.budget.items():
                if cfg.get(key) is None:
                    cfg[key] = value
        else:
            defaults = ((experiment.get("loops") or {}).get(spec.id) or {})
            for key, value in (defaults.get("params") or {}).items():
                cfg.setdefault(key, value)
            for key, value in (defaults.get("budget") or {}).items():
                if cfg.get(key) is None:
                    cfg[key] = value
        _check_config(spec, cfg)
        cfg.setdefault("decision_log", args.records or (str(state) + ".decisions.jsonl"))
        loop = spec.factory(cfg)
        _save_wrapper(state, spec.id, loop)
    except (LoopError, PolicyError, RecipeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_STATE
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    print(json.dumps({"loop": spec.id, "state": str(state),
                      "roles": list(spec.required_roles)},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_loop_next(args: argparse.Namespace) -> int:
    state = Path(args.state)
    action_path = Path(args.action or (str(state) + ".action.json"))
    try:
        wrapper = _read_wrapper(state)
        loop = restore_loop(str(wrapper["loop"]), wrapper["state"])
        action = loop.next_action()
        _save_wrapper(state, str(wrapper["loop"]), loop)
        action_path.write_text(json.dumps(action, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        print(json.dumps(action, ensure_ascii=False, indent=2))
    except LoopError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_STATE
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    return 0


def cmd_loop_apply(args: argparse.Namespace) -> int:
    state = Path(args.state)
    action_path = Path(args.action or (str(state) + ".action.json"))
    try:
        action = json.loads(action_path.read_text(encoding="utf-8"))
        if not isinstance(action, dict) or not action.get("kind"):
            raise LoopError("pending action file has no kind")
        if args.kind and args.kind != action["kind"]:
            raise LoopError(
                f"pending action is {action['kind']!r}, not {args.kind!r}"
            )
        result: Dict[str, Any] = {}
        if action["kind"] == "evaluate":
            if args.score is None:
                raise LoopError("evaluate requires --score")
            result["score"] = args.score
            result["feedback"] = args.feedback or ""
        elif action["kind"] in ("reflect", "merge"):
            if not args.text_file:
                raise LoopError(f"{action['kind']} requires --text-file")
            result["text"] = Path(args.text_file).read_text(encoding="utf-8")
        else:
            raise LoopError(f"action {action['kind']!r} is not appliable")
        wrapper = _read_wrapper(state)
        loop = restore_loop(str(wrapper["loop"]), wrapper["state"])
        loop.apply(action, result)
        _save_wrapper(state, str(wrapper["loop"]), loop)
        action_path.unlink(missing_ok=True)
        print(json.dumps({"loop": wrapper["loop"], "applied": action["kind"]},
                         ensure_ascii=False, indent=2))
    except LoopError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_STATE
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    return 0


def cmd_loop_result(args: argparse.Namespace) -> int:
    try:
        wrapper = _read_wrapper(Path(args.state))
        loop = restore_loop(str(wrapper["loop"]), wrapper["state"])
        print(json.dumps(loop.result(), ensure_ascii=False, indent=2))
    except LoopError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_STATE
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    loop = subparsers.add_parser("loop", help="搜索循环注册表与通用驱动：list/show/init/next/apply/result")
    sub = loop.add_subparsers(dest="loop_command", required=True)

    listing = sub.add_parser("list", help="列出已注册搜索循环")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_loop_list)

    show = sub.add_parser("show", help="查看一个搜索循环的动作与样本角色")
    show.add_argument("--loop", required=True, choices=loop_ids())
    show.set_defaults(func=cmd_loop_show)

    init = sub.add_parser("init", help="按配置新建循环状态")
    init.add_argument("--loop", default=None, choices=loop_ids())
    init.add_argument("--recipe", default=None, help="搜索循环 recipe 名（config/rsi/recipes/ 下的文件名）")
    init.add_argument("--root", default=None, help="策略根目录（默认当前目录）")
    init.add_argument("--policy", default=None, help="显式策略文件")
    init.add_argument("--profile", default=None)
    init.add_argument("--pipeline", default=None)
    init.add_argument("--state", required=True)
    init.add_argument("--config", required=True, help="YAML：seed_text/seed_file、data、params")
    init.add_argument("--records", default=None, help="决策记录 JSONL；默认 <state>.decisions.jsonl")
    init.add_argument("--overwrite", action="store_true")
    init.set_defaults(func=cmd_loop_init)

    nxt = sub.add_parser("next", help="取下一个动作并落盘")
    nxt.add_argument("--state", required=True)
    nxt.add_argument("--action", default=None)
    nxt.set_defaults(func=cmd_loop_next)

    apply_p = sub.add_parser("apply", help="按动作回写结果")
    apply_p.add_argument("--state", required=True)
    apply_p.add_argument("--action", default=None)
    apply_p.add_argument("--kind", default=None,
                         choices=["evaluate", "reflect", "merge"])
    apply_p.add_argument("--score", type=float, default=None)
    apply_p.add_argument("--feedback", default="")
    apply_p.add_argument("--text-file", default=None)
    apply_p.set_defaults(func=cmd_loop_apply)

    result = sub.add_parser("result", help="输出循环结果")
    result.add_argument("--state", required=True)
    result.set_defaults(func=cmd_loop_result)
