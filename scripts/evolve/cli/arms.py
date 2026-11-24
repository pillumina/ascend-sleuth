# -*- coding: utf-8 -*-
"""``experiment arms`` 命令组：组合实验的驱动入口。

多臂或顺序链都在一个状态文件里：``next`` 返回 ``{arm, loop, action}``，``apply``
按动作回写，``result`` 读每臂结果与主臂读数。最终合入仍走配对门，不在本组下
结论。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml
from typing import Any, Dict

from ..experiment_session import ExperimentError, ExperimentSession, init_session
from ..experiment_spec import ExperimentSpecError
from ..loops import LoopError
from ..recipes import RecipeError
from .common import PolicyError, policy_for

EXIT_STATE = 1
EXIT_INPUT = 2


def _load(path: Path) -> ExperimentSession:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ExperimentSession.from_dict(data)


def _save(path: Path, session: ExperimentSession) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8")


def cmd_arms_init(args: argparse.Namespace) -> int:
    state = Path(args.state)
    if state.exists() and not args.overwrite:
        print(f"error: state exists (use --overwrite): {state}", file=sys.stderr)
        return EXIT_INPUT
    try:
        session = init_session(
            args.spec, seed_file=args.seed_file,
            decisions_path=args.records or (str(state) + ".decisions.jsonl"),
            policy=policy_for(args), root=args.root,
        )
        _save(state, session)
    except (ExperimentSpecError, LoopError, PolicyError, RecipeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_STATE
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    print(json.dumps({"experiment": session.spec.id, "state": str(state),
                      "arms": [arm.name for arm in session.spec.arms],
                      "composition": session.spec.composition,
                      "primary_arm": session.spec.primary_arm},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_arms_next(args: argparse.Namespace) -> int:
    state = Path(args.state)
    try:
        session = _load(state)
        action = session.next_action()
        _save(state, session)
        print(json.dumps(action, ensure_ascii=False, indent=2))
    except (ExperimentError, LoopError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_STATE
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    return 0


def cmd_arms_apply(args: argparse.Namespace) -> int:
    state = Path(args.state)
    try:
        session = _load(state)
        pending = session.pending
        if pending is None:
            raise ExperimentError("no pending action; call next first")
        kind = pending["action"].get("kind")
        if args.kind and args.kind != kind:
            raise ExperimentError(f"pending action is {kind!r}, not {args.kind!r}")
        result: Dict[str, Any] = {}
        if kind == "evaluate":
            if args.score is None:
                raise ExperimentError("evaluate requires --score")
            result["score"] = args.score
            result["feedback"] = args.feedback or ""
        elif kind in ("reflect", "merge"):
            if not args.text_file:
                raise ExperimentError(f"{kind} requires --text-file")
            result["text"] = Path(args.text_file).read_text(encoding="utf-8")
        else:
            raise ExperimentError(f"action {kind!r} is not appliable")
        session.apply(pending, result)
        _save(state, session)
        print(json.dumps({"arm": pending["arm"], "applied": kind},
                         ensure_ascii=False, indent=2))
    except (ExperimentError, LoopError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_STATE
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    return 0


def cmd_arms_result(args: argparse.Namespace) -> int:
    try:
        session = _load(Path(args.state))
        print(json.dumps(session.result(), ensure_ascii=False, indent=2))
    except (ExperimentError, LoopError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_STATE
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    return 0


def register(experiment_subparsers: argparse._SubParsersAction) -> None:
    arms = experiment_subparsers.add_parser(
        "arms", help="多臂/顺序链组合实验：init / next / apply / result")
    sub = arms.add_subparsers(dest="arms_command", required=True)

    init = sub.add_parser("init", help="按 spec 新建实验状态")
    init.add_argument("--spec", required=True, help="实验 spec YAML")
    init.add_argument("--state", required=True, help="状态 JSON 路径")
    init.add_argument("--seed-file", default=None, help="覆盖 spec 的 seed 文本")
    init.add_argument("--records", default=None, help="决策记录 JSONL；默认 <state>.decisions.jsonl")
    init.add_argument("--root", default=None, help="策略根目录（默认当前目录）")
    init.add_argument("--policy", default=None, help="显式策略文件")
    init.add_argument("--profile", default=None)
    init.add_argument("--pipeline", default=None)
    init.add_argument("--overwrite", action="store_true")
    init.set_defaults(func=cmd_arms_init)

    nxt = sub.add_parser("next", help="取下一个 {arm, loop, action}")
    nxt.add_argument("--state", required=True)
    nxt.set_defaults(func=cmd_arms_next)

    apply_p = sub.add_parser("apply", help="按动作回写结果")
    apply_p.add_argument("--state", required=True)
    apply_p.add_argument("--kind", default=None,
                         choices=["evaluate", "reflect", "merge"])
    apply_p.add_argument("--score", type=float, default=None)
    apply_p.add_argument("--feedback", default="")
    apply_p.add_argument("--text-file", default=None)
    apply_p.set_defaults(func=cmd_arms_apply)

    result = sub.add_parser("result", help="输出每臂结果与主臂读数")
    result.add_argument("--state", required=True)
    result.set_defaults(func=cmd_arms_result)
