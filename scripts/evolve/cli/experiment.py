"""``experiment`` 命令组：算法适配器、提案、门禁与实验记录。"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from ..adapters import AdapterError
from ..algorithms.registry import algorithm_ids, get_algorithm
from ..contracts import ContractError, now_iso
from ..evaluations.gates import GateRequest, gate_for
from ..experiments import ExperimentError, validate_experiment
from ..flow import FlowError, run_proposal
from ..pilot import PilotError
from ..policy import PolicyError, resolve_autonomy
from ..proposal_engine import (BestPolicy, GepaPolicy, ParetoPolicy,
                               ProposalArchive, ProposalEngine)
from ..proposals import ProposalError, request as proposal_request, validate_draft
from ..readback import latest_by_proposal
from ..records import ExperimentStore, RecordError
from ..samples import StoreError
from ..scoring import RubricError
from ..stage_runner import (load_argv as stage_load_argv, run as stage_run)
from ..store import RSIStore
from ..targets.base import DEFAULT_TARGET
from ..targets.registry import (get_target, resolve_evaluator, resolve_optimizer,
                                target_ids)
from .common import (CliError, evolve_base, json_object_arg, policy_for,
                     sample_store, yaml_or_json_object)


def cmd_experiment_list(args: argparse.Namespace) -> int:
    try:
        policy = policy_for(args)
    except PolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    experiment = policy.get("experiment") or {}
    configured_target = experiment.get("target", DEFAULT_TARGET)
    configured = experiment.get("algorithm", "baseline")
    print(f"configured_target: {configured_target}")
    for tid in target_ids():
        spec = get_target(tid)
        profile = resolve_evaluator(tid)[1]
        marker = "*" if tid == configured_target else " "
        print(
            f"{marker} target {tid}\t{spec.eval_profile_id}\t"
            f"eval_ready={profile.implemented}\t{spec.authority}\t{spec.allowed_algorithms}"
        )
    for name in algorithm_ids():
        algorithm = get_algorithm(name)
        marker = "*" if name == configured else " "
        print(f"{marker} {name}\t{getattr(algorithm, 'version', '')}\t{getattr(algorithm, 'scope', '')}")
    return 0


def _agent_draft_patch(path: str, target_override=None, component_override=None,
                       summary_override=None, seed: int = 0) -> "Patch":
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ProposalError("draft must be an object")
    if component_override:
        data["target_component"] = component_override
    if summary_override:
        data["summary"] = summary_override
    patch = validate_draft(data, target_override=target_override)
    patch.seed = seed
    return patch


def cmd_experiment_flow(args: argparse.Namespace) -> int:
    try:
        policy = policy_for(args)
        draft = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
        archive_path = Path(args.archive) if args.archive else evolve_base(args) / "proposals.jsonl"
        archive = ProposalArchive(archive_path)
        engine = ProposalEngine(archive)
        proposal = engine.add(draft)
        if proposal.status == "invalid":
            raise FlowError("; ".join(proposal.errors))
        if not args.dry_run and not args.judge:
            raise FlowError("--judge is required unless --dry-run")
        command = stage_load_argv(args.runner_command) if args.runner_command else None
        result = run_proposal(
            Path(args.root), proposal, args.samples, Path(args.output), policy,
            Path(args.judge) if args.judge else None, archive,
            runner=(lambda tasks: stage_run(Path(args.output), command))
            if command else None,
            baseline_traces=Path(args.baseline_traces) if args.baseline_traces else None,
            reuse_index=args.reuse_index,
            exploratory=args.exploratory,
            card=args.card,
            dry_run=args.dry_run,
        )
    except (FlowError, ProposalError, OSError, ValueError, PolicyError, PilotError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        payload = {"proposal": proposal.id, "archive": str(archive_path)}
        payload.update(result)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps({
        "proposal": proposal.id,
        "decision": result["decision"],
        "conclusion": result["conclusion"],
        "archive": str(archive_path),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_experiment_search(args: argparse.Namespace) -> int:
    try:
        scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
        if not isinstance(scenario, dict):
            raise ProposalError("scenario must be an object")
        target = str(scenario.get("target_kind") or "")
        component = str(scenario.get("target_component") or "")
        samples = scenario.get("samples")
        if not isinstance(samples, list) or not samples:
            raise ProposalError("scenario.samples must be a non-empty list")
        candidates = scenario.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ProposalError("scenario.candidates must be a non-empty list")
        policy = {"best": BestPolicy, "pareto": ParetoPolicy, "gepa": GepaPolicy}[args.policy]()
        archive = ProposalArchive(Path(args.archive) if args.archive
                                  else evolve_base(args) / "proposals.jsonl")
        engine = ProposalEngine(archive)
        for item in candidates:
            draft = item.get("draft") if isinstance(item, dict) else None
            if not isinstance(draft, dict):
                raise ProposalError("candidate.draft is required")
            if draft.get("target_kind") and draft["target_kind"] != target:
                raise ProposalError("draft target_kind does not match scenario")
            draft.setdefault("target_kind", target)
            draft.setdefault("target_component", component)
            proposal = engine.add(draft)
            if proposal.status != "invalid" and isinstance(item.get("scores"), dict):
                engine.evaluate(proposal, item["scores"], item.get("feedback"))
        selected = policy.choose(engine.proposals, list(samples), [])
    except (ProposalError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "policy": policy.id,
        "proposals": [p.to_dict() for p in engine.proposals],
        "selected": selected.to_dict() if selected else None,
        "archive": str(archive.path),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_experiment_request(args: argparse.Namespace) -> int:
    try:
        policy = policy_for(args)
        target = args.target or ((policy.get("experiment") or {}).get("target") or DEFAULT_TARGET)
        evidence = None
        if args.evidence:
            evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
        constraints = json_object_arg(args.constraints, "constraints") or {}
        failures = None
        if args.failures_file:
            failures = json.loads(Path(args.failures_file).read_text(encoding="utf-8"))
            if not isinstance(failures, list):
                raise ProposalError("failures file must contain a JSON array")
        digest = None
        if args.digest_file:
            digest = json.loads(Path(args.digest_file).read_text(encoding="utf-8"))
            if not isinstance(digest, dict):
                raise ProposalError("digest file must contain a JSON object")
        result = proposal_request(target, args.component, evidence=evidence,
                                  constraints=constraints, failures=failures,
                                  digest=digest)
    except (ProposalError, OSError, ValueError, json.JSONDecodeError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_experiment_propose(args: argparse.Namespace) -> int:
    try:
        policy = policy_for(args)
        experiment = policy.get("experiment") or {}
        target = args.target or experiment.get("target", DEFAULT_TARGET)
        algorithm = args.algorithm or experiment.get("algorithm", "baseline")
        budget = json_object_arg(args.budget, "budget")
        if budget is None:
            budget = experiment.get("budget") or {}
        seed = args.seed if args.seed is not None else experiment.get("seed", 0)
        if args.draft:
            patch = _agent_draft_patch(args.draft, target_override=args.target,
                                       component_override=args.component,
                                       summary_override=args.summary, seed=seed)
            patch.validate()
            execution = "subagent"
        else:
            spec, optimizer = resolve_optimizer(target, algorithm)
            patch = optimizer.propose(target, [], None, budget)
            if args.component:
                patch.target_component = args.component
            if args.summary:
                patch.summary = args.summary
            patch.seed = seed
            patch.validate()
            execution = getattr(optimizer, "execution", "manual")
        profile = resolve_evaluator(patch.target_kind)[1]
        record = asdict(patch)
        record["execution"] = execution
        record["source"] = "agent_draft" if args.draft else "algorithm"
        record["eval_profile_id"] = profile.id
        record["eval_gate"] = profile.gate
        record["eval_ready"] = profile.implemented
        record["autonomy"] = resolve_autonomy(policy, patch.target_component)
        record["at"] = now_iso()
        ExperimentStore.for_base(evolve_base(args)).append(record)
    except (PolicyError, AdapterError, StoreError, RecordError, ContractError, ValueError, TypeError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: cannot write experiment record: {exc}", file=sys.stderr)
        return 1
    print(f"target: {patch.target_kind}")
    print(f"component: {patch.target_component}")
    print(f"autonomy: {record['autonomy']}")
    print(f"algorithm: {patch.algorithm}")
    print(f"summary: {patch.summary}")
    eval_ready = resolve_evaluator(patch.target_kind)[1].implemented
    print(f"eval_profile_id: {resolve_evaluator(target)[1].id}")
    print(f"eval_ready: {eval_ready}")
    if not eval_ready:
        print(
            "warning: target evaluator is not implemented; Patch recorded but not gate-ready",
            file=sys.stderr,
        )
    print(f"recorded: {ExperimentStore.for_base(evolve_base(args)).path}")
    return 0


def cmd_experiment_record(args: argparse.Namespace) -> int:
    try:
        raw = yaml_or_json_object(args.file, "--file")
        if raw is None:
            raise ExperimentError("--file is required")
        record = validate_experiment(raw)
        record["at"] = now_iso()
        ExperimentStore.for_base(evolve_base(args)).append(record)
    except (ExperimentError, PolicyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (RecordError, OSError) as exc:
        print(f"error: cannot write experiment record: {exc}", file=sys.stderr)
        return 1
    print(f"recorded: {record['target_kind']} {record['target_component']}")
    print(f"decision: {record['decision']}")
    print(f"baseline: {record['baseline']['score']:.4f}")
    print(f"candidate: {record['candidate']['score']:.4f}")
    return 0


def cmd_experiment_show(args: argparse.Namespace) -> int:
    try:
        base = evolve_base(args)
        rows = [row for row in ExperimentStore.for_base(base).read()
                if row.get("proposal") == args.proposal]
        events = RSIStore(base).history(proposal_id=args.proposal)
        proposal = ProposalArchive(base / "proposals.jsonl").latest(args.proposal)
        conclusion = latest_by_proposal(args.proposal, base)
        if proposal is None:
            for event in events:
                if event.get("kind") == "proposal":
                    proposal = (event.get("data") or {}).get("proposal")
                    break
                if event.get("kind") == "experiment":
                    proposal = (event.get("data") or {}).get("proposal")
                    if proposal:
                        break
        if conclusion is None:
            for event in events:
                if event.get("kind") == "decision":
                    conclusion = (event.get("data") or {}).get("conclusion")
                    break
                if event.get("kind") == "experiment":
                    conclusion = (event.get("data") or {}).get("conclusion")
                    if conclusion:
                        break
        if not rows:
            rows = [(event.get("data") or {}).get("experiment") for event in events
                    if event.get("kind") == "experiment"]
            rows = [row for row in rows if row]
        if proposal is None:
            print(f"error: no proposal {args.proposal}", file=sys.stderr)
            return 1
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "proposal": proposal,
        "conclusion": conclusion,
        "experiments": rows,
        "history": events,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_experiment_records(args: argparse.Namespace) -> int:
    try:
        records = ExperimentStore.for_base(evolve_base(args)).read()
    except RecordError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    limit = args.limit if args.limit and args.limit > 0 else 10
    print(f"experiments: {len(records)}")
    for record in records[-limit:]:
        scores = ""
        if isinstance(record.get("baseline"), dict) and isinstance(record.get("candidate"), dict):
            scores = (
                f" baseline={record['baseline'].get('score')} "
                f"candidate={record['candidate'].get('score')} "
                f"decision={record.get('decision')}"
            )
        print(
            f"{record.get('at', '')} {record.get('target_kind', '')} "
            f"{record.get('target_component', '')} {record.get('algorithm', '')} "
            f"execution={record.get('execution')} "
            f"eval_ready={record.get('eval_ready')} "
            f"profile={record.get('eval_profile_id')} "
            f"proposal={record.get('proposal') or ''}{scores}"
        )
    return 0


def cmd_experiment_gate(args: argparse.Namespace) -> int:
    """按评测面执行门禁；参数整理与打印在这里，执行在 ``evaluations/gates``。"""
    try:
        spec, profile = resolve_evaluator(args.target)
        if not profile.implemented:
            raise ValueError(
                f"target {args.target!r} has no implemented evaluator ({profile.id})"
            )
        adapter = gate_for(profile.gate)
        sample = threshold = None
        if adapter.needs_sample:
            if not args.sample or not args.scores:
                raise ValueError(f"{adapter.label} gate requires --sample and --scores")
            sample = sample_store(args).require(args.sample)
            threshold = (policy_for(args).get("rubrics") or {}).get("threshold")
        request = GateRequest(
            root=Path(args.root or "."), profile_id=profile.id,
            target=spec.id,
            baseline=args.baseline, candidate=args.candidate,
            component=args.component, candidate_ref=args.candidate_ref,
            note=args.note, alpha=args.alpha,
            object_types=profile.object_types,
            sample=sample, scores_text=args.scores, threshold=threshold,
        )
        outcome = adapter.run(request)
    except (ValueError, RubricError, CliError, StoreError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if outcome.passthrough:
        return outcome.code
    for line in outcome.lines:
        print(line)
    return outcome.code


def cmd_experiment_resolve(args: argparse.Namespace) -> int:
    try:
        spec, optimizer = resolve_optimizer(args.target, args.algorithm)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"target: {spec.id}")
    print(f"algorithm: {getattr(optimizer, 'id', args.algorithm or spec.default_algorithm)}")
    print(f"version: {getattr(optimizer, 'version', '')}")
    print(f"scope: {getattr(optimizer, 'scope', '')}")
    profile = resolve_evaluator(spec.id)[1]
    print(f"eval_profile: {spec.eval_profile}")
    print(f"eval_profile_id: {profile.id}")
    print(f"eval_label: {profile.label}")
    print(f"eval_gate: {profile.gate}")
    print(f"eval_object_types: {', '.join(profile.object_types)}")
    print(f"eval_ready: {profile.implemented}")
    print(f"authority: {spec.authority}")
    return 0


def register(subparsers) -> None:
    experiment = subparsers.add_parser("experiment", help="算法适配器")
    experiment_sub = experiment.add_subparsers(dest="experiment_command", required=True)
    exp_list = experiment_sub.add_parser("list", help="列出注册算法与 policy 选择")
    exp_list.add_argument("--root", default=".", help="策略根目录")
    exp_list.add_argument("--policy", default=None, help="策略路径")
    exp_list.set_defaults(func=cmd_experiment_list)
    exp_resolve = experiment_sub.add_parser("resolve", help="按 target/algorithm 解析适配器")
    exp_resolve.add_argument("--target", required=True)
    exp_resolve.add_argument("--algorithm", default=None)
    exp_resolve.set_defaults(func=cmd_experiment_resolve)
    exp_show = experiment_sub.add_parser(
        "show", help="按提案编号合并 proposal / conclusion / experiment 记录")
    exp_show.add_argument("--root", default=None)
    exp_show.add_argument("--proposal", required=True)
    exp_show.set_defaults(func=cmd_experiment_show)

    exp_records = experiment_sub.add_parser("records", help="列出本地实验记录")
    exp_records.add_argument("--root", default=None)
    exp_records.add_argument("--limit", type=int, default=10)
    exp_records.set_defaults(func=cmd_experiment_records)
    exp_record = experiment_sub.add_parser("record", help="记录一份外部 baseline/candidate 实验结果")
    exp_record.add_argument("--root", default=None)
    exp_record.add_argument("--file", required=True, help="结果 JSON/YAML 路径或内联")
    exp_record.set_defaults(func=cmd_experiment_record)
    exp_gate = experiment_sub.add_parser("gate", help="按 target evaluator 判一个 rubric 样本")
    exp_gate.add_argument("--root", default=None)
    exp_gate.add_argument("--target", required=True)
    exp_gate.add_argument("--sample", default=None)
    exp_gate.add_argument("--scores", default=None, help="JSON 对象：维度 → 0/1/2")
    exp_gate.add_argument("--baseline", default=None, help="tooling gate：基线 tool usage JSON")
    exp_gate.add_argument("--candidate", default=None, help="tooling gate：候选 tool usage JSON")
    exp_gate.add_argument("--component", default=None, help="arena gate：目标组件")
    exp_gate.add_argument("--candidate-ref", default=None, help="arena gate：候选引用")
    exp_gate.add_argument("--note", default=None, help="arena gate：备注")
    exp_gate.add_argument("--alpha", type=float, default=0.1, help="arena gate：alpha")
    exp_gate.set_defaults(func=cmd_experiment_gate)
    exp_flow = experiment_sub.add_parser(
        "flow", help="提案 → candidate → pilot → runner → judge → gate → archive")
    exp_flow.add_argument("--root", required=True)
    exp_flow.add_argument("--proposal", required=True)
    exp_flow.add_argument("--samples", nargs="+", required=True)
    exp_flow.add_argument("--output", required=True)
    exp_flow.add_argument("--judge", default=None)
    exp_flow.add_argument("--runner-command", default=None, help="JSON argv")
    exp_flow.add_argument("--card", default=None, help="绑定 EV 卡号（行为面实验）")
    exp_flow.add_argument("--exploratory", action="store_true",
                          help="降级验收：允许 insufficient usage 与成本改善；不作为生产通过")
    exp_flow.add_argument("--dry-run", action="store_true",
                          help="只准备 candidate/pilot tasks，不跑 runner/judge")
    exp_flow.add_argument("--baseline-traces", default=None)
    exp_flow.add_argument("--archive", default=None)
    exp_flow.add_argument("--policy", default=None)
    exp_flow.add_argument("--profile", default=None, help="sleuth.config.yaml 的成本 profile")
    exp_flow.add_argument("--pipeline", default=None,
                          help="流水线预设名（config/rsi/pipelines.yaml），优先于全局默认与 profile")
    exp_flow.add_argument("--reuse-index", type=int, default=None)
    exp_flow.set_defaults(func=cmd_experiment_flow)

    exp_search = experiment_sub.add_parser(
        "search", help="用已产出的候选做校验、评分、策略选择并归档")
    exp_search.add_argument("--root", default=None)
    exp_search.add_argument("--scenario", required=True)
    exp_search.add_argument("--policy", choices=("best", "pareto", "gepa"), default="gepa")
    exp_search.add_argument("--archive", default=None)
    exp_search.set_defaults(func=cmd_experiment_search)

    exp_request = experiment_sub.add_parser(
        "request", help="为 agent 生成 target-specific 提案请求与 prompt")
    exp_request.add_argument("--root", default=None)
    exp_request.add_argument("--target", default=None)
    exp_request.add_argument("--component", required=True)
    exp_request.add_argument("--evidence", default=None, help="JSON 文件")
    exp_request.add_argument("--failures-file", default=None,
                             help="JSON 数组：逐样例的 sample_id/expected/actual/feedback（定向批评输入）")
    exp_request.add_argument("--digest-file", default=None,
                             help="JSON 对象：data_digest/program_digest（提案上下文摘要）")
    exp_request.add_argument("--constraints", default=None, help="JSON 对象")
    exp_request.add_argument("--policy", default=None)
    exp_request.set_defaults(func=cmd_experiment_request)

    exp_propose = experiment_sub.add_parser(
        "propose", help="记录对照包络，或接收 agent 的 target-specific 提案草案")
    exp_propose.add_argument("--root", default=None)
    exp_propose.add_argument("--policy", default=None)
    exp_propose.add_argument("--target", default=None)
    exp_propose.add_argument("--algorithm", default=None)
    exp_propose.add_argument("--component", default=None)
    exp_propose.add_argument("--summary", default=None)
    exp_propose.add_argument("--budget", default=None, help="JSON 对象")
    exp_propose.add_argument("--seed", type=int, default=None)
    exp_propose.add_argument("--draft", default=None,
                             help="agent 写好的 target-specific 草案 JSON；不调用模型")
    exp_propose.set_defaults(func=cmd_experiment_propose)
