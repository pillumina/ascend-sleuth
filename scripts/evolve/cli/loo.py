"""``loo`` 命令组：留一效用审计状态机的命令行接入。

与 ``gepa`` 同款驱动协议：``next`` 返回 ``{kind, payload}``，``apply`` 按 kind
回写，状态是 ``LooAudit.to_dict()`` 的纯 JSON。退出码：``0`` 成功；``1`` 状态机
转换非法；``2`` 输入或文件错误。
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List

from ..loo import LooAudit, LooError

EXIT_STATE = 1
EXIT_INPUT = 2


def _load(path: Path) -> LooAudit:
    return LooAudit.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _save(path: Path, audit: LooAudit) -> None:
    path.write_text(json.dumps(audit.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _units_arg(raw: str) -> List:
    from ..loo import AuditUnit
    units = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        unit_id, _, label = item.partition(":")
        units.append(AuditUnit(id=unit_id.strip(), label=label.strip()))
    if not units:
        raise LooError("--units produced no units")
    return units


def cmd_loo_init(args: argparse.Namespace) -> int:
    state = Path(args.state)
    if state.exists() and not args.overwrite:
        print(f"error: state exists (use --overwrite): {state}", file=sys.stderr)
        return EXIT_INPUT
    try:
        audit = LooAudit(units=_units_arg(args.units),
                         samples=[s.strip() for s in args.samples.split(",") if s.strip()],
                         max_audit_calls=args.max_audit_calls,
                         shrink_threshold=args.shrink_threshold,
                         target_kind=args.target or "",
                         audit_set=args.audit_set or "")
        state.parent.mkdir(parents=True, exist_ok=True)
        _save(state, audit)
    except (LooError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    print(json.dumps({"state": str(state), "units": len(audit.units),
                      "samples": audit.samples,
                      "max_audit_calls": audit.max_audit_calls},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_loo_next(args: argparse.Namespace) -> int:
    try:
        state = Path(args.state)
        audit = _load(state)
        action = audit.next_action()
        # evaluate 动作带 pending 副作用，须落盘，否则下一条 apply 报 no matching。
        if action.get("kind") == "evaluate":
            _save(state, audit)
        print(json.dumps(action, ensure_ascii=False, indent=2))
    except (LooError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_STATE if isinstance(exc, LooError) else EXIT_INPUT
    return 0


def cmd_loo_apply(args: argparse.Namespace) -> int:
    if args.kind != "evaluate" or not args.unit_id or not args.sample_id or args.score is None:
        print("error: apply requires --kind evaluate --unit-id --sample-id --score",
              file=sys.stderr)
        return EXIT_INPUT
    try:
        state = Path(args.state)
        audit = _load(state)
        audit.record_evaluation(args.unit_id, args.variant, args.sample_id, args.score)
        _save(state, audit)
        print(json.dumps({"calls": audit.calls}, ensure_ascii=False))
    except LooError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_STATE
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    return 0


def cmd_loo_result(args: argparse.Namespace) -> int:
    try:
        audit = _load(Path(args.state))
        print(json.dumps(audit.result(), ensure_ascii=False, indent=2))
    except LooError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_STATE
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_INPUT
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    sub = subparsers.add_parser(
        "loo", help="留一效用审计：init / next / apply / result")
    loo_sub = sub.add_subparsers(dest="loo_command", required=True)

    init = loo_sub.add_parser("init", help="新建审计状态（单元清单 + 样本 + 预算）")
    init.add_argument("--state", required=True)
    init.add_argument("--units", required=True,
                      help="逗号分隔，条目 id[:标签]，如 case-101:超时分支,case-102")
    init.add_argument("--samples", required=True, help="逗号分隔的审计样本 id")
    init.add_argument("--max-audit-calls", type=int, required=True)
    init.add_argument("--shrink-threshold", type=float, default=0.0)
    init.add_argument("--target", default="", help="target_kind，仅记录")
    init.add_argument("--audit-set", default="", help="审计集标识，仅记录")
    init.add_argument("--overwrite", action="store_true")
    init.set_defaults(func=cmd_loo_init)

    nxt = loo_sub.add_parser("next", help="取下一个消融评测动作")
    nxt.add_argument("--state", required=True)
    nxt.set_defaults(func=cmd_loo_next)

    apply_p = loo_sub.add_parser("apply", help="回写消融评测结果")
    apply_p.add_argument("--state", required=True)
    apply_p.add_argument("--kind", default="evaluate", choices=["evaluate"])
    apply_p.add_argument("--unit-id", default=None)
    apply_p.add_argument("--variant", default=None,
                         help="动作里的 variant（full 或 without:<unit_id>），照抄勿改")
    apply_p.add_argument("--sample-id", default=None)
    apply_p.add_argument("--score", type=float, default=None)
    apply_p.set_defaults(func=cmd_loo_apply)

    result = loo_sub.add_parser("result", help="输出效用与收缩队列")
    result.add_argument("--state", required=True)
    result.set_defaults(func=cmd_loo_result)
