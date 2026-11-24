"""``sample`` 命令组：样本队列与生命周期。"""

import argparse
import json
import sys
from pathlib import Path

from .. import cli as cli_api
from ..adapters import AdapterError
from ..adapters.ixn import import_ixn
from ..adapters.s2 import import_s2_samples
from ..contracts import (OBJECT_TYPE_VALUES, ORIGINS, PURPOSES, STATUSES,
                         ContractError)
from ..holdout_guard import issue_numbers
from ..intake import IntakeError, completeness, extract_case, extract_trace, make_sample
from ..policy import PolicyError
from ..quality import QualityError, load_quality
from ..samples import SampleStore, StoreError, import_pilot
from ..sources.registry import get_source
from .common import (CliError, evolve_base, guard_holdout, json_object_arg,
                     policy_for, sample_store)


def cmd_sample_new(args: argparse.Namespace) -> int:
    if getattr(args, "from_source", None):
        store = sample_store(args)
        root = Path(args.root) if args.root else store.root
        try:
            if args.from_source == "trace":
                if not args.trace:
                    raise CliError("--trace is required with --from trace")
                payload = extract_trace(Path(args.trace), root)
            else:
                if not args.case:
                    raise CliError("--case is required with --from postmortem")
                payload = extract_case(Path(args.case), root)
            guard_holdout(args, payload["source"])
            sample = make_sample(payload).validate()
            result = completeness(sample, store=store, root=root)
        except (CliError, OSError, ValueError, IntakeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.dry_run:
            if args.json:
                print(json.dumps({"sample": payload, "completeness": result},
                                 ensure_ascii=False, indent=2))
            else:
                print(f"would create: {payload['id']}")
                print(f"state: {result['state']}")
                print(f"reasons: {', '.join(result['reasons']) or 'none'}")
                print(f"duplicates: {', '.join(result['duplicates']) or 'none'}")
            return 0
        try:
            created = store.new(**payload)
        except (StoreError, ContractError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"created: {created.id}")
        print(f"state: {result['state']}")
        print(f"path: {store.path_for(created.id)}")
        return 0
    if not args.id or not args.object_type or not args.source:
        print("error: manual mode requires --id, --object-type and --source", file=sys.stderr)
        return 2
    try:
        guard_holdout(args, args.source)
    except (CliError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    expected = json_object_arg(args.expected, "--expected")
    rubric = json_object_arg(args.rubric, "--rubric")
    payload = json_object_arg(args.input, "--input")
    proposed = json_object_arg(args.proposed, "--proposed")
    try:
        sample = sample_store(args).new(
            id=args.id,
            object_type=args.object_type,
            origin=args.origin,
            purpose=args.purpose,
            source=args.source,
            expected=expected,
            rubric=rubric,
            input=payload,
            expected_kind=args.expected_kind,
            proposed=proposed,
            notes=args.notes,
        )
    except (StoreError, ContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created: {sample.id}")
    print(f"status: {sample.status}")
    print(f"path: {sample_store(args).path_for(sample.id)}")
    return 0


def cmd_sample_status(args: argparse.Namespace) -> int:
    try:
        store = sample_store(args)
        sample = store.require(args.id)
        root = Path(args.root) if args.root else store.root
        result = completeness(sample, store=store, root=root)
    except (StoreError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"state: {result['state']}")
        print(f"reasons: {', '.join(result['reasons']) or 'none'}")
        print(f"duplicates: {', '.join(result['duplicates']) or 'none'}")
    return 0


def cmd_sample_export_core(args: argparse.Namespace) -> int:
    try:
        path = sample_store(args).export_core(args.id)
    except (StoreError, ContractError, CliError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"exported: {path}")
    return 0


def cmd_sample_import_pilot(args: argparse.Namespace) -> int:
    try:
        result = import_pilot(sample_store(args), Path(args.tasks))
    except (OSError, ValueError, StoreError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created: {len(result['created'])}")
    print(f"skipped: {len(result['skipped'])}")
    return 0


def cmd_sample_set_answer(args: argparse.Namespace) -> int:
    expected = json_object_arg(args.expected, "--expected")
    rubric = json_object_arg(args.rubric, "--rubric")
    if args.resolution:
        expected = dict(expected or {})
        expected["resolution"] = args.resolution
    provenance = {}
    if args.confidence:
        provenance["confidence"] = args.confidence
    if args.sanitized is not None:
        provenance["sanitized"] = args.sanitized == "true"
    if args.redaction:
        provenance["redactions"] = list(args.redaction)
    try:
        sample = sample_store(args).set_answer(
            args.id,
            expected=expected,
            rubric=rubric,
            expected_kind=args.expected_kind,
            provenance=provenance or None,
            actor=args.actor,
            reason=args.reason or "",
        )
    except (StoreError, ContractError, CliError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"updated: {sample.id}")
    print(f"path: {sample_store(args).path_for(sample.id)}")
    return 0


def cmd_sample_ingest_issues(args: argparse.Namespace) -> int:
    base = evolve_base(args)
    # 样本总在主检出（或显式 --root 的本地运行件）；ingest-state.json 是 tracked 文件，
    # 默认跟随当前检出，worktree 里跑完能提交，不会写到主检出却看不见。
    root = Path(args.root) if args.root else Path.cwd()
    try:
        source = get_source(args.source, repo=args.repo, cache=args.cache)
        quality = load_quality(Path(args.quality_file)) if args.quality_file else None
        stats = cli_api.ingest_issues(
            root,
            args.repo,
            labels=args.labels,
            since=args.since,
            min_comments=args.min_comments,
            limit=args.limit,
            state_path=args.state,
            store=SampleStore(base=base),
            dry_run=args.dry_run,
            source=source,
            state_key=f"{source.source_id}/evaluation",
            holdout_numbers=issue_numbers(root),
            quality=quality,
        )
    except (AdapterError, QualityError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (StoreError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created: {stats['created']}")
    for sample_id, path in zip(stats["created_ids"], stats["created_paths"]):
        print(f"candidate: {sample_id}\t{path}")
    for sample_id in stats["would_create"]:
        print(f"would create: {sample_id}")
    print(
        "skipped: "
        f"pr={stats['skipped_pr']} "
        f"processed={stats['skipped_processed']} "
        f"label={stats['skipped_no_label']} "
        f"comments={stats['skipped_low_comments']} "
        f"title={stats['skipped_title']} "
        f"empty_body={stats['skipped_empty_body']} "
        f"short_body={stats['skipped_short_body']} "
        f"feature_title={stats['skipped_feature_title']} "
        f"duplicate_source={stats['skipped_duplicate_source']} "
        f"duplicate_id={stats['skipped_duplicate_id']}"
    )
    if stats["limit_reached"]:
        print(f"limit reached: {args.limit}")
    if args.dry_run:
        print("dry-run: no samples written, state unchanged")
    elif stats["state_updated"]:
        print(f"state: {stats['state_path']}")
    return 0


def cmd_sample_import_s2(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    try:
        stats = import_s2_samples(
            root, args.source, sample_store(args), limit=args.limit,
            holdout_numbers=issue_numbers(root),
        )
    except AdapterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (StoreError, ContractError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created: {stats['created']}")
    print(
        "skipped: "
        f"non_diagnostic={stats['skipped_non_diagnostic']} "
        f"no_symptoms={stats['skipped_no_symptoms']} "
        f"no_answer={stats.get('skipped_no_answer', 0)} "
        f"split={stats.get('skipped_split', 0)} "
        f"missing_issue={stats['skipped_missing_issue']} "
        f"duplicate_source={stats['skipped_duplicate_source']} "
        f"duplicate_id={stats['skipped_duplicate_id']}"
    )
    if stats["limit_reached"]:
        print(f"limit reached: {args.limit}")
    print(f"source: {stats['source']}")
    return 0


def cmd_sample_import_ixn(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    try:
        stats = import_ixn(
            sample_store(args), root, root / args.source, limit=args.limit,
            holdout_numbers=issue_numbers(root),
        )
    except (AdapterError, StoreError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created: {stats['created']}")
    print(f"skipped: held_out={stats['skipped_held_out']} duplicate={stats['skipped_duplicate']} missing={stats['skipped_missing']}")
    return 0


def cmd_sample_list(args: argparse.Namespace) -> int:
    try:
        samples = sample_store(args).list(status=args.status, origin=args.origin)
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not samples:
        print("no samples")
        return 0
    for sample in samples:
        print("\t".join([
            sample.id,
            sample.status,
            sample.origin,
            sample.purpose,
            sample.object_type,
        ]))
    print(f"total: {len(samples)}")
    return 0


def cmd_sample_check(args: argparse.Namespace) -> int:
    errors = sample_store(args).check(args.id)
    if errors:
        print(f"invalid: {args.id}", file=sys.stderr)
        for message in errors:
            print(f"  - {message}", file=sys.stderr)
        return 1
    print(f"ok: {args.id}")
    return 0


def cmd_sample_review(args: argparse.Namespace) -> int:
    approve = args.approve
    if approve is None:
        print("error: one of --approve/--reject is required", file=sys.stderr)
        return 2
    try:
        sample = sample_store(args).require(args.id)
        guard_holdout(args, sample.source)
        sample = sample_store(args).review(
            args.id, approve=approve, actor=args.actor, reason=args.reason or "",
        )
    except (StoreError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"ok": True, "id": sample.id, "status": sample.status},
                         ensure_ascii=False))
    else:
        print(f"{sample.id}: {sample.status}")
    return 0


def cmd_sample_promote(args: argparse.Namespace) -> int:
    try:
        current = sample_store(args).require(args.id)
        guard_holdout(args, current.source)
        sample = sample_store(args).promote(
            args.id, to=args.to, actor=args.actor, reason=args.reason or "",
        )
        exported = None
        if args.export:
            if sample.purpose not in ("test", "regression"):
                raise StoreError("--export requires purpose=test or regression")
            exported = str(sample_store(args).export_core(sample.id))
    except (StoreError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"ok": True, "id": sample.id, "status": sample.status,
                          "origin": sample.origin, "purpose": sample.purpose,
                          "exported": exported},
                         ensure_ascii=False))
    else:
        print(f"{sample.id}: {sample.status} ({sample.origin})")
    return 0


def cmd_sample_retire(args: argparse.Namespace) -> int:
    try:
        sample = sample_store(args).retire(
            args.id, actor=args.actor, reason=args.reason or "",
        )
    except (StoreError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{sample.id}: {sample.status}")
    return 0


def cmd_sample_set_purpose(args: argparse.Namespace) -> int:
    try:
        sample = sample_store(args).set_purpose(
            args.id, args.purpose, actor=args.actor, reason=args.reason or "",
        )
    except (StoreError, ContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{sample.id}: {sample.purpose}")
    return 0


def cmd_sample_absorb(args: argparse.Namespace) -> int:
    try:
        sample = sample_store(args).absorb(
            args.id, actor=args.actor, reason=args.reason or "",
        )
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{sample.id}: {sample.status} ({sample.purpose})")
    return 0


def cmd_sample_draw_test(args: argparse.Namespace) -> int:
    try:
        policy = policy_for(args)
    except PolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    size = args.size if args.size is not None else policy["samples"]["test"]
    method = policy["samples"]["split"]
    try:
        samples = sample_store(args).draw_test(
            size=size, method=method, strata=policy["samples"].get("strata") or {},
            actor=args.actor, reason=args.reason or "",
        )
    except (StoreError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"drawn: {len(samples)}")
    print(f"size: {size} ({'policy' if args.size is None else 'explicit'})")
    print(f"split: {method} (policy)")
    strata = policy["samples"].get("strata") or {}
    if strata:
        print("strata: " + " ".join(f"{key}={value}" for key, value in sorted(strata.items())))
    for sample in samples:
        print(f"{sample.id}\t{sample.status}\t{sample.origin}\t{sample.purpose}")
    return 0


def register(subparsers) -> None:
    sample = subparsers.add_parser("sample", help="样本队列与生命周期")
    sample_sub = sample.add_subparsers(dest="sample_command", required=True)

    new = sample_sub.add_parser("new", help="创建候选样本")
    new.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    new.add_argument("--from", dest="from_source", default=None,
                     choices=("trace", "postmortem"),
                     help="从已闭环的诊断 trace 或 case YAML 生成候选")
    new.add_argument("--trace", default=None, help="--from trace 的 trace 路径")
    new.add_argument("--case", default=None, help="--from postmortem 的 case YAML 路径")
    new.add_argument("--dry-run", action="store_true", help="只打印完整性与查重，不写盘")
    new.add_argument("--json", action="store_true", help="--dry-run 输出 JSON")
    new.add_argument("--id", default=None)
    new.add_argument("--object-type", default=None, choices=OBJECT_TYPE_VALUES)
    new.add_argument("--origin", default="field", choices=ORIGINS)
    new.add_argument("--purpose", default="evaluation", choices=PURPOSES)
    new.add_argument("--source", default=None)
    new.add_argument("--expected", default=None, help="JSON 对象")
    new.add_argument("--rubric", default=None, help="JSON 对象")
    new.add_argument("--input", default=None, help="JSON 对象")
    new.add_argument("--expected-kind", default=None, choices=("resolution", "assertion", "rubric"))
    new.add_argument("--proposed", default=None, help="JSON 对象（候选的待确认字段）")
    new.add_argument("--notes", default=None)
    new.set_defaults(func=cmd_sample_new)

    import_pilot_p = sample_sub.add_parser("import-pilot", help="把一次 pilot 的样本注册进队列")
    import_pilot_p.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    import_pilot_p.add_argument("--tasks", required=True)
    import_pilot_p.set_defaults(func=cmd_sample_import_pilot)
    set_answer = sample_sub.add_parser("set-answer", help="给 candidate/active 补 expected/rubric")
    set_answer.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    set_answer.add_argument("--id", required=True)
    set_answer.add_argument("--expected", default=None, help="JSON 对象")
    set_answer.add_argument("--rubric", default=None, help="JSON 对象")
    set_answer.add_argument("--expected-kind", default=None,
                            choices=("resolution", "assertion", "rubric"))
    set_answer.add_argument("--resolution", default=None,
                            help="直接写根因与修复，免拼 JSON")
    set_answer.add_argument("--confidence", default=None,
                            choices=("issue-verified", "maintainer-reviewed", "agent-reviewed"))
    set_answer.add_argument("--sanitized", default=None, choices=("true", "false"))
    set_answer.add_argument("--redaction", action="append", default=None,
                            help="脱敏项，可重复")
    set_answer.add_argument("--actor", default="maintainer")
    set_answer.add_argument("--reason", default="")
    set_answer.set_defaults(func=cmd_sample_set_answer)
    status = sample_sub.add_parser("status", help="看一条候选样本的完整性与查重")
    status.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    status.add_argument("--id", required=True)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_sample_status)
    export_core = sample_sub.add_parser("export-core", help="把 active/core 样本写入 tracked eval/core")
    export_core.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    export_core.add_argument("--id", required=True)
    export_core.set_defaults(func=cmd_sample_export_core)

    import_s2 = sample_sub.add_parser(
        "import-s2", help="把 eval/s2 校准集导入候选队列（跳过非诊断/无症状/重复来源）"
    )
    import_s2.add_argument("--root", default=None,
                           help="校准集根目录（默认当前目录；样本仍默认锚主检出）")
    import_s2.add_argument("--source", required=True,
                           help="校准集路径，如 eval/s2/vllm-ascend.yaml")
    import_s2.add_argument("--limit", type=int, default=None,
                           help="最多创建多少条候选（默认不限）")
    import_s2.set_defaults(func=cmd_sample_import_s2)

    ingest = sample_sub.add_parser(
        "ingest-issues", help="从 GitHub issue 建诊断候选（先过滤，按需取 body）"
    )
    ingest.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    ingest.add_argument("--source", default="github",
                        help="issue 源（默认 github；已注册 github/local）")
    ingest.add_argument("--cache", default=None, help="local 源的 JSON/YAML issue 导出路径")
    ingest.add_argument("--repo", required=True, help="如 vllm-project/vllm-ascend")
    ingest.add_argument("--labels", default=None, help="逗号分隔 label 池")
    ingest.add_argument("--since", default=None, help="ISO 时间，增量拉取")
    ingest.add_argument("--min-comments", type=int, default=3)
    ingest.add_argument("--limit", type=int, default=20, help="最多创建多少条候选")
    ingest.add_argument("--state", default="ingest-state.json", help="ingest-state.json 路径")
    ingest.add_argument("--dry-run", action="store_true", help="只打印候选，不写库/不更新 state")
    ingest.add_argument("--quality-file", default=None,
                        help="agent 产出的 issue 质量/答案 JSON；低于阈值直接跳过")
    ingest.set_defaults(func=cmd_sample_ingest_issues)

    ixn = sample_sub.add_parser("import-ixn", help="导入 ixn-arena 非 held_out gold 样本")
    ixn.add_argument("--root", default=None)
    ixn.add_argument("--source", default="eval/ixn-arena")
    ixn.add_argument("--limit", type=int, default=None)
    ixn.set_defaults(func=cmd_sample_import_ixn)

    listing = sample_sub.add_parser("list", help="列出样本")
    listing.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    listing.add_argument("--status", default=None, choices=STATUSES)
    listing.add_argument("--origin", default=None, choices=ORIGINS)
    listing.set_defaults(func=cmd_sample_list)

    check_cmd = sample_sub.add_parser("check", help="复核一条样本")
    check_cmd.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    check_cmd.add_argument("--id", required=True)
    check_cmd.set_defaults(func=cmd_sample_check)

    review = sample_sub.add_parser("review", help="维护者复核候选")
    review.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    review.add_argument("--id", required=True)
    verdict = review.add_mutually_exclusive_group(required=True)
    verdict.add_argument("--approve", dest="approve", action="store_true")
    verdict.add_argument("--reject", dest="approve", action="store_false")
    review.add_argument("--actor", default="maintainer")
    review.add_argument("--reason", default="")
    review.add_argument("--json", action="store_true")
    review.set_defaults(func=cmd_sample_review)

    promote = sample_sub.add_parser("promote", help="active/field → active/core（origin 转换）")
    promote.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    promote.add_argument("--id", required=True)
    promote.add_argument("--to", required=True, choices=("core",))
    promote.add_argument("--actor", default="maintainer")
    promote.add_argument("--reason", default="")
    promote.add_argument("--export", action="store_true",
                         help="升 core 后立即写入 tracked eval/core（仅 test/regression）")
    promote.add_argument("--json", action="store_true")
    promote.set_defaults(func=cmd_sample_promote)

    retire = sample_sub.add_parser("retire", help="active（field/core origin）→ retired")
    retire.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    retire.add_argument("--id", required=True)
    retire.add_argument("--actor", default="maintainer")
    retire.add_argument("--reason", default="")
    retire.set_defaults(func=cmd_sample_retire)

    set_purpose = sample_sub.add_parser("set-purpose", help="active 样本改 purpose")
    set_purpose.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    set_purpose.add_argument("--id", required=True)
    set_purpose.add_argument("--purpose", required=True, choices=PURPOSES)
    set_purpose.add_argument("--actor", default="maintainer")
    set_purpose.add_argument("--reason", default="")
    set_purpose.set_defaults(func=cmd_sample_set_purpose)

    absorb = sample_sub.add_parser("absorb", help="答案进库：转 regression 或使 test 退休")
    absorb.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    absorb.add_argument("--id", required=True)
    absorb.add_argument("--actor", default="maintainer")
    absorb.add_argument("--reason", default="")
    absorb.set_defaults(func=cmd_sample_absorb)

    draw = sample_sub.add_parser("draw-test", help="从 active/core/evaluation 抽 test")
    draw.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    draw.add_argument("--size", type=int, default=None,
                      help="抽几条（默认读 policy.samples.test）")
    draw.add_argument("--policy", default=None, help="策略文件路径（默认 sleuth.config.yaml 的 evolution.policy）")
    draw.add_argument("--actor", default="maintainer")
    draw.add_argument("--reason", default="")
    draw.set_defaults(func=cmd_sample_draw_test)
