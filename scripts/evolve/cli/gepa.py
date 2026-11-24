"""``gepa`` 命令组：agent-GEPA 状态机的命令行接入。

驱动协议的最小实现：``next`` 返回 ``{kind, payload}``，``apply`` 按 kind 回写，
状态是 ``GepaSession.to_dict()`` 的纯 JSON。核心模块不打印、不读文件；CLI 负责
路径、终端输出与退出码（``0`` 成功；``1`` 状态机转换非法——动作顺序、预算、
未知候选；``2`` 输入或文件错误）。
"""

import argparse
import json
import sys
from pathlib import Path

from ..agent_gepa import GepaError, GepaSession

# 状态转换非法（GepaError）与输入/文件错误分开报，按 cli/__init__ 头注释的
# 三档退出码语义。
EXIT_STATE = 1
EXIT_INPUT = 2


def _load_session(path: Path) -> GepaSession:
    data = json.loads(path.read_text(encoding="utf-8"))
    return GepaSession.from_dict(data)


def _save_session(path: Path, session: GepaSession) -> None:
    path.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _read_text(path: str, what: str) -> str:
    text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        raise GepaError(f"{what} file is empty: {path}")
    return text


def _csv_list(raw: str) -> list:
    return [item.strip() for item in raw.split(",") if item.strip()]


def cmd_gepa_init(args: argparse.Namespace) -> int:
    state = Path(args.state)
    if state.exists() and not args.overwrite:
        print(f"error: state exists (use --overwrite): {state}", file=sys.stderr)
        return EXIT_INPUT
    try:
        seed_skill = _read_text(args.seed_file, "seed")
        session = GepaSession(
            seed_skill=seed_skill,
            samples=_csv_list(args.samples),
            max_metric_calls=args.max_metric_calls,
            population=args.population,
            seed=args.seed,
            min_score=args.min_score,
            target_skill=args.target or "",
            mutable_region=args.mutable_region or "",
            select_stage=args.select_stage,
            propose_stage=args.propose_stage,
        )
        state.parent.mkdir(parents=True, exist_ok=True)
        _save_session(state, session)
    except GepaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_STATE
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    print(json.dumps({"state": str(state), "samples": session.samples,
                      "max_metric_calls": session.max_metric_calls,
                      "population": session.population}, ensure_ascii=False, indent=2))
    return 0


def cmd_gepa_next(args: argparse.Namespace) -> int:
    try:
        state = Path(args.state)
        session = _load_session(state)
        action = session.next_action()
        if action.get("kind") == "reflect":
            # next_action 的副作用（pending_reflect）必须落盘，否则下一条
            # apply reflect 在重载状态后报 no reflect action pending。
            _save_session(state, session)
        print(json.dumps(action, ensure_ascii=False, indent=2))
    except GepaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_STATE
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    return 0


def cmd_gepa_apply(args: argparse.Namespace) -> int:
    # 参数组合缺失属命令行输入错误，先于状态机校验。
    if args.kind == "evaluate" and (not args.candidate_id or not args.sample_id
                                    or args.score is None):
        print("error: evaluate requires --candidate-id, --sample-id, --score",
              file=sys.stderr)
        return EXIT_INPUT
    if args.kind == "reflect" and not args.skill_file:
        print("error: reflect requires --skill-file with the mutated region text",
              file=sys.stderr)
        return EXIT_INPUT
    try:
        session = _load_session(Path(args.state))
        if args.kind == "evaluate":
            session.record_evaluation(args.candidate_id, args.sample_id,
                                      args.score, args.feedback or "")
        else:
            session.record_candidate(_read_text(args.skill_file, "skill"))
        _save_session(Path(args.state), session)
        print(json.dumps({"calls": session.calls,
                          "candidates": len(session.candidates)},
                         ensure_ascii=False, indent=2))
    except GepaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_STATE
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    return 0


def cmd_gepa_result(args: argparse.Namespace) -> int:
    try:
        session = _load_session(Path(args.state))
        print(json.dumps(session.result(), ensure_ascii=False, indent=2))
    except GepaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_STATE
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    sub = subparsers.add_parser(
        "gepa", help="agent-GEPA 状态机驱动：init / next / apply / result")
    gepa_sub = sub.add_subparsers(dest="gepa_command", required=True)

    init = gepa_sub.add_parser("init", help="新建实验状态（seed 区域文本 + 样本 + 预算）")
    init.add_argument("--state", required=True, help="状态 JSON 路径")
    init.add_argument("--seed-file", required=True, help="seed 可变异区文本文件")
    init.add_argument("--samples", required=True, help="逗号分隔的样本 id")
    init.add_argument("--max-metric-calls", type=int, required=True)
    init.add_argument("--population", type=int, required=True)
    init.add_argument("--select-stage", default="select.pareto")
    init.add_argument("--propose-stage", default="propose.reflection")
    init.add_argument("--min-score", type=float, default=0.0)
    init.add_argument("--target", default="", help="target_kind，仅记录")
    init.add_argument("--mutable-region", default="", help="可变异区名，仅记录")
    init.add_argument("--seed", type=int, default=0)
    init.add_argument("--overwrite", action="store_true")
    init.set_defaults(func=cmd_gepa_init)

    nxt = gepa_sub.add_parser("next", help="取下一个动作（evaluate / reflect / stop）")
    nxt.add_argument("--state", required=True)
    nxt.set_defaults(func=cmd_gepa_next)

    apply_p = gepa_sub.add_parser("apply", help="回写动作结果并推进状态")
    apply_p.add_argument("--state", required=True)
    apply_p.add_argument("--kind", required=True, choices=["evaluate", "reflect"])
    apply_p.add_argument("--candidate-id", default=None)
    apply_p.add_argument("--sample-id", default=None)
    apply_p.add_argument("--score", type=float, default=None)
    apply_p.add_argument("--feedback", default="")
    apply_p.add_argument("--skill-file", default=None,
                         help="reflect：变异后的区域文本文件")
    apply_p.set_defaults(func=cmd_gepa_apply)

    result = gepa_sub.add_parser("result", help="输出当前最优候选与 Pareto 前沿")
    result.add_argument("--state", required=True)
    result.set_defaults(func=cmd_gepa_result)
