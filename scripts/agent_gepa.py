#!/usr/bin/env python3
"""agent-native GEPA 的状态机 CLI；不调用模型，只吃/吐 JSON 动作。

用法：
  python3 scripts/agent_gepa.py init --seed-file seed.md --samples S-1,S-2 --state gepa.json
  python3 scripts/agent_gepa.py next --state gepa.json        # evaluate/reflect/stop
  python3 scripts/agent_gepa.py record --state gepa.json --candidate seed --sample S-1 --score 0.0 --feedback "..."
  python3 scripts/agent_gepa.py candidate --state gepa.json --skill-file candidate.md
  python3 scripts/agent_gepa.py result --state gepa.json
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

from evolve.agent_gepa import GepaError, GepaSession


def _load(path: Path) -> GepaSession:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GepaError(f"cannot read state: {exc}") from exc
    return GepaSession.from_dict(data)


def _save(session: GepaSession, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            json.dump(session.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
        Path(tmp).replace(path)
    finally:
        try:
            Path(tmp).unlink()
        except OSError:
            pass


def cmd_init(args) -> int:
    seed = Path(args.seed_file).read_text(encoding="utf-8") if args.seed_file else args.seed
    samples = [item.strip() for item in args.samples.split(",") if item.strip()]
    session = GepaSession(
        seed, samples, max_metric_calls=args.max_metric_calls,
        population=args.population, seed=args.seed_value,
        target_skill=args.target_skill or "", mutable_region=args.region or "",
        min_score=args.min_score,
        select_stage=args.select or "select.pareto",
        propose_stage=args.propose or "propose.agent",
    )
    _save(session, Path(args.state))
    print(f"initialized: {len(samples)} sample(s), budget={args.max_metric_calls}")
    return 0


def cmd_next(args) -> int:
    session = _load(Path(args.state))
    action = session.next_action()
    _save(session, Path(args.state))
    print(json.dumps(action, ensure_ascii=False, indent=2))
    return 0


def cmd_record(args) -> int:
    session = _load(Path(args.state))
    session.record_evaluation(args.candidate, args.sample, args.score, args.feedback or "")
    _save(session, Path(args.state))
    print("recorded")
    return 0


def cmd_candidate(args) -> int:
    skill = Path(args.skill_file).read_text(encoding="utf-8") if args.skill_file else args.skill
    session = _load(Path(args.state))
    candidate = session.record_candidate(skill)
    _save(session, Path(args.state))
    print(f"candidate: {candidate.id}")
    return 0


def cmd_result(args) -> int:
    print(json.dumps(_load(Path(args.state)).result(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="agent-native GEPA 状态机")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--seed", default="")
    init.add_argument("--seed-file")
    init.add_argument("--samples", required=True)
    init.add_argument("--state", required=True)
    init.add_argument("--max-metric-calls", type=int, default=12)
    init.add_argument("--population", type=int, default=4)
    init.add_argument("--seed-value", type=int, default=0)
    init.add_argument("--target-skill", default="")
    init.add_argument("--region", default="")
    init.add_argument("--min-score", type=float, default=0.0,
                      help="score <= this is a reflection failure")
    init.add_argument("--select", default="select.pareto")
    init.add_argument("--propose", default="propose.agent")
    init.set_defaults(func=cmd_init)
    nxt = sub.add_parser("next")
    nxt.add_argument("--state", required=True)
    nxt.set_defaults(func=cmd_next)
    record = sub.add_parser("record")
    record.add_argument("--state", required=True)
    record.add_argument("--candidate", required=True)
    record.add_argument("--sample", required=True)
    record.add_argument("--score", type=float, required=True)
    record.add_argument("--feedback", default="")
    record.set_defaults(func=cmd_record)
    candidate = sub.add_parser("candidate")
    candidate.add_argument("--state", required=True)
    candidate.add_argument("--skill", default="")
    candidate.add_argument("--skill-file")
    candidate.set_defaults(func=cmd_candidate)
    result = sub.add_parser("result")
    result.add_argument("--state", required=True)
    result.set_defaults(func=cmd_result)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (GepaError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
