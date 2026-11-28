#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ascend 环境快照分析适配器：单份看版本配套，多份看配置漂移。

上游实现：
- 单份：scripts/analyzers/ascend-dump-analyzer/references/check_compatibility.py
- 多份：scripts/analyzers/ascend-dump-analyzer/references/compare_dumps.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from _lib import (  # noqa: E402
    AnalyzerError,
    UPSTREAM_COMMIT,
    clip,
    file_signature,
    is_fresh,
    read_json,
    run_adapter,
    run_process,
    tail,
    write_json,
)

ANALYZER = "ascend-dump-analyzer"
VERSION = UPSTREAM_COMMIT
TOOL_DIR = HERE
REFERENCES = TOOL_DIR / "references"
COMPARE = REFERENCES / "compare_dumps.py"
COMPATIBILITY = REFERENCES / "check_compatibility.py"
SNAPSHOT_SUFFIXES = {".json", ".log", ".txt"}
COMPONENT_ORDER = (
    "cann",
    "hdk",
    "python",
    "torch",
    "torch_npu",
    "vllm",
    "vllm_ascend",
    "mindspeed_llm",
    "mindie",
)


def _snapshot_paths(inputs) -> list[str]:
    paths = []
    for item in inputs:
        path = item["path"]
        if item["kind"] != "file" or Path(path).suffix.lower() not in SNAPSHOT_SUFFIXES:
            raise AnalyzerError("bad-input", f"{path} 不是环境快照文件。输入须包含 JSON 文本。")
        paths.append(path)
    return paths


def _versions(observed: dict) -> list[dict]:
    rows = []
    for name, entry in (observed or {}).items():
        if not isinstance(entry, dict):
            continue
        evidence = entry.get("evidence") or []
        raw_version = next(
            (str(item.get("version")) for item in evidence if item.get("version")),
            None,
        )
        rows.append(
            {
                "component": name,
                "version": entry.get("version"),
                "raw_version": raw_version,
                "conflict": bool(entry.get("conflict")),
                "sources": sorted({str(item.get("source")) for item in evidence if item.get("source")}),
            }
        )
    order = {name: index for index, name in enumerate(COMPONENT_ORDER)}
    rows.sort(key=lambda row: (order.get(row["component"], len(order)), row["component"]))
    return rows


def _attach_snapshot_evidence(data: dict, snapshot: dict, path: str) -> list[str]:
    meta = snapshot.get("_meta") or {}
    collection = meta.get("collection") or {}
    workload = snapshot.get("workload")
    targets = (workload.get("targets") or {}) if isinstance(workload, dict) else {}
    data["snapshot_evidence"] = {
        "source": path,
        "hostname": meta.get("hostname"),
        "timestamp": meta.get("timestamp"),
        "collection_status": meta.get("status"),
        "collection": collection,
        "software_scope": "collector_environment",
        "targets": {
            role: {
                key: target[key]
                for key in ("pid", "start_time_ticks", "collection_status", "reason", "libraries")
                if key in target
            }
            for role, target in targets.items()
            if isinstance(target, dict)
        },
    }

    gaps = []
    for section, entry in collection.items():
        if not isinstance(entry, dict):
            continue
        status = entry.get("status")
        if status in {"failed", "partial", "unavailable"}:
            reason = entry.get("reason") or next(iter(entry.get("errors") or []), "")
            gaps.append(f"{section} 采集状态为 {status}" + (f"，{reason}" if reason else ""))
    if not gaps and meta.get("status") in {"failed", "partial", "unavailable"}:
        gaps.append(f"快照采集状态为 {meta['status']}")
    if targets:
        gaps.append("业务进程配套未核对，已加载库路径和采集状态见 compatibility JSON")
    return gaps


def _single_snapshot(path: str, out_dir: Path, args) -> dict:
    if not COMPATIBILITY.is_file():
        raise AnalyzerError("analyzer-not-installed", f"缺上游入口：{COMPATIBILITY}", status="failed")
    try:
        snapshot = read_json(path)
    except (OSError, ValueError) as exc:
        raise AnalyzerError("bad-input", f"{path} 不是可读的 JSON 环境快照：{exc}") from exc
    if not snapshot:
        raise AnalyzerError("bad-input", f"{path} 是空 JSON 或不是对象，无法做版本配套检查。")
    output = out_dir / "compatibility.json"
    before = file_signature(output)
    proc = run_process(
        [sys.executable, str(COMPATIBILITY), path, "--output", str(output)],
        cwd=REFERENCES,
        timeout=args.timeout,
        log_path=out_dir / "vendor.log",
    )
    if proc.get("timed_out"):
        raise AnalyzerError("timeout", f"超过 {args.timeout}s", status="failed")
    if not is_fresh(output, before):
        detail = tail(proc.get("stderr"), 900) or tail(proc.get("stdout"), 900)
        raise AnalyzerError(
            "analyzer-failed",
            "没有生成新的 compatibility.json（复用输出目录时不会沿用上一次结果）。"
            "退出码 {code}；{detail}".format(
                code=proc.get("exit_code"), detail=detail
            ),
            status="failed",
        )

    data = read_json(output)
    collection_gaps = _attach_snapshot_evidence(data, snapshot, path)
    write_json(output, data)
    observed = data.get("observed") or {}
    software = data.get("software") or {}
    host = data.get("host") or {}
    recommendations = data.get("recommendations") or []
    boards = data.get("boards") or []
    versions = _versions(observed)
    known_versions = [row for row in versions if row["version"]]

    findings: list[dict] = []
    component_findings: list[dict] = []
    raw_by_component = {row["component"]: row.get("raw_version") for row in versions}
    for row in known_versions[:8]:
        sources = "、".join(row["sources"][:3]) or "来源未记录"
        component_findings.append(
            {
                "claim": f"组件 {row['component']} = {row.get('raw_version') or row['version']}（来源：{sources}）",
                "evidence": f"compatibility.json observed.{row['component']}",
                "kind": "fact",
            }
        )

    software_status = software.get("status") or "unknown"
    rule = software.get("rule")
    if software_status == "matched":
        source = (software.get("source") or "").strip()
        findings.append(
            {
                "claim": f"采集环境的软件配套匹配规则 {rule or 'unknown'}"
                + (f"（来源：{clip(source, 120)}）" if source else ""),
                "evidence": "compatibility.json software",
                "kind": "fact",
            }
        )
    elif software_status == "deviation":
        for name, check in (software.get("checks") or {}).items():
            if check.get("status") != "deviation":
                continue
            expected = "、".join(str(value) for value in (check.get("expected") or []))
            observed = raw_by_component.get(name) or check.get("observed")
            findings.append(
                {
                    "claim": (
                        f"采集环境的软件配套偏离：{name} 实测 {observed}，"
                        f"规则 {rule or 'unknown'} 期望 {expected or '未记录'}"
                    ),
                    "evidence": f"compatibility.json software.checks.{name}",
                    "kind": "fact",
                }
            )
    else:
        findings.append(
            {
                "claim": "采集环境的软件配套未判定：" + clip(software.get("reason") or "缺少可匹配的规则或版本", 240),
                "evidence": "compatibility.json software",
                "kind": "fact",
            }
        )

    for plan in recommendations[:3]:
        changes = plan.get("changes") or {}
        if changes:
            detail = "；".join(
                f"{name} {raw_by_component.get(name) or item.get('observed')}"
                f"→{'/'.join(str(v) for v in (item.get('expected') or []))}"
                for name, item in changes.items()
            )
        else:
            detail = "保持现版本"
        findings.append(
            {
                "claim": f"采集环境的配套候选 {plan.get('rule') or 'unknown'}（{plan.get('release') or 'release 未知'}）：{detail}",
                "evidence": "compatibility.json recommendations",
                "kind": "candidate",
            }
        )

    for board in boards:
        if board.get("status") == "incompatible":
            findings.append(
                {
                    "claim": (
                        f"板卡兼容性异常：device {board.get('device_id')} "
                        f"{board.get('model') or ''} 读到 {board.get('observed')}"
                    ),
                    "evidence": board.get("evidence") or "compatibility.json boards",
                    "kind": "fact",
                }
            )

    findings.extend(component_findings[-8:])

    missing = list(collection_gaps)
    catalog = data.get("catalog") or {}
    if catalog:
        findings.insert(0, {
            "claim": f"兼容性目录核对结果为 {catalog.get('label') or catalog.get('status')}，适用范围 {catalog.get('scope') or {}}",
            "evidence": "compatibility.json catalog",
            "kind": "candidate" if catalog.get("status") == "incompatible" else "fact",
        })
        for check in catalog.get("checks") or []:
            if check.get("missing"):
                missing.append("兼容性目录缺项：" + "、".join(check["missing"]))
    required = set((software.get("checks") or {}).keys())
    anchor = {
        "torch": "torch_npu",
        "vllm": "vllm_ascend",
        "mindspeed": "mindspeed_llm",
        "modelink": "modellink",
        "mindie": "mindie",
    }.get(str(data.get("scene") or ""), "")
    if anchor:
        required.add(anchor)
    for row in versions:
        if row["conflict"]:
            missing.append(f"组件 {row['component']} 的版本来源冲突，未取单一版本")
        elif not row["version"] and row["component"] in required:
            missing.append(f"组件 {row['component']} 未取到版本")
    if software_status == "unknown" and software.get("reason"):
        missing.append("软件配套：" + str(software["reason"]))
    for name, check in host.items():
        if isinstance(check, dict) and check.get("status") == "unknown" and check.get("reason"):
            missing.append(f"{name} 未核对：{check['reason']}")
    unknown_boards = [board for board in boards if board.get("status") == "unknown"]
    if unknown_boards:
        missing.append(f"板卡兼容性未核对：{len(unknown_boards)} 个设备")

    scene = data.get("scene") or "unknown"
    scene_source = data.get("scene_source") or "unknown"
    deviation_count = sum(check.get("status") == "deviation" for check in (software.get("checks") or {}).values())
    text = (
        f"单份环境快照：场景 {scene}（{scene_source}）；采集环境的软件配套 {software_status}"
        f"（规则 {rule or 'unknown'}）；读取 {len(known_versions)} 个组件版本；"
        f"{deviation_count} 处偏离；{len(recommendations)} 条推荐组合。"
    )
    return {
        "status": "partial" if collection_gaps else "ok",
        "summary": clip(text, 500),
        "findings": findings[:10],
        "missing": missing[:8],
        "artifacts": [str(output)],
        "observations": [
            {
                "topic": f"组件版本 {row['component']}",
                "detail": (
                    f"{row.get('raw_version') or row['version'] or '未取到'}；"
                    f"来源 {('、'.join(row['sources'][:3]) or '未记录')}"
                ),
                "level": "info",
                "evidence": f"compatibility.json observed.{row['component']}",
            }
            for row in versions
            if row["version"]
        ][:12],
    }


def _compatibility_facts(
    path: str, index: int, out_dir: Path, timeout: int
) -> tuple[dict | None, list[str], str | None, bool]:
    """对一份能读取的快照做版本配套检查；失败只记缺项，不中断比对。"""
    if not COMPATIBILITY.is_file():
        return None, ["配套检查脚本缺失，未核对版本配套"], None, True
    try:
        snapshot = read_json(path)
    except (OSError, ValueError):
        return None, [], None, True
    name = Path(path).name
    output = out_dir / f"compatibility-{index:02d}-{Path(path).stem}.json"
    before = file_signature(output)
    proc = run_process(
        [sys.executable, str(COMPATIBILITY), path, "--output", str(output)],
        cwd=REFERENCES,
        timeout=timeout,
        log_path=out_dir / f"compatibility-{index:02d}.log",
    )
    if proc.get("timed_out") or not is_fresh(output, before):
        detail = tail(proc.get("stderr"), 300) or "未生成新的 compatibility.json"
        return None, [f"配套检查未执行（{name}）：{detail}"], None, True
    data = read_json(output)
    collection_gaps = _attach_snapshot_evidence(data, snapshot, path)
    write_json(output, data)
    software = data.get("software") or {}
    observed = data.get("observed") or {}
    raw_versions = {
        component: next(
            (
                str(item.get("version"))
                for item in (entry.get("evidence") or [])
                if item.get("version")
            ),
            None,
        )
        for component, entry in observed.items()
        if isinstance(entry, dict)
    }
    status = software.get("status") or "unknown"
    missing = [f"{name}：{gap}" for gap in collection_gaps]
    if status == "unknown":
        missing.append(f"配套未判定（{name}）：{software.get('reason') or '缺少可匹配的规则或版本'}")
    claim = None
    if status == "deviation":
        changes = []
        for component, check in (software.get("checks") or {}).items():
            if check.get("status") == "deviation":
                expected = "/".join(str(value) for value in (check.get("expected") or []))
                actual = raw_versions.get(component) or check.get("observed")
                changes.append(f"{component} {actual}→{expected or '未记录'}")
        if changes:
            claim = f"采集环境的软件配套偏离（{name}，规则 {software.get('rule') or 'unknown'}）：" + "；".join(changes)
    boards = [
        board
        for board in (data.get("boards") or [])
        if board.get("status") == "incompatible"
    ]
    if boards:
        board_text = "板卡兼容性异常：" + "；".join(
            f"device {board.get('device_id')} 读到 {board.get('observed')}"
            for board in boards[:3]
        )
        claim = f"{claim}；{board_text}" if claim else f"配套异常（{name}）：{board_text}"
    fact = (
        {"claim": claim, "evidence": f"{output.name} software/boards", "kind": "fact"}
        if claim
        else None
    )
    return fact, missing, str(output), bool(collection_gaps)


def _compare(paths: list[str], out_dir: Path, args) -> dict:
    output = out_dir / "diff.json"
    html = out_dir / "diff.html"
    output_before = file_signature(output)
    html_before = file_signature(html)
    proc = run_process(
        [sys.executable, str(COMPARE), *paths, "--json", str(output), "--html", str(html)],
        cwd=TOOL_DIR,
        timeout=args.timeout,
        log_path=out_dir / "vendor.log",
    )
    if proc.get("timed_out"):
        raise AnalyzerError("timeout", f"超过 {args.timeout}s", status="failed")
    if not is_fresh(output, output_before):
        raise AnalyzerError(
            "analyzer-failed",
            "没有生成新的 diff.json（复用输出目录时不会沿用上一次结果）。退出码 {code}；stderr：{err}".format(
                code=proc.get("exit_code"), err=tail(proc.get("stderr"), 900)
            ),
            status="failed",
        )
    data = read_json(output)
    upstream_status = data.get("status")
    if upstream_status not in {"success", "partial"}:
        raise AnalyzerError("bad-input", f"比对未成功：{data.get('status')}；{data.get('error', '')}")
    summary = data.get("summary") or {}
    diff_count = int(summary.get("diff_count") or 0)
    similarity = summary.get("similarity")
    compared_count = len(data.get("files") or paths)
    findings = []
    for section, diffs in (data.get("diffs") or {}).items():
        if not isinstance(diffs, dict):
            continue
        for item in (diffs.get("modified") or [])[:2]:
            values = item.get("values") or {}
            pairs = "；".join(f"{Path(name).name}={value}" for name, value in values.items())
            findings.append(
                {
                    "claim": f"{section}｜{item.get('path')}｜{clip(pairs, 200)}",
                    "evidence": "diff.json diffs",
                    "kind": "fact",
                }
            )
        for item in (diffs.get("only_in") or [])[:1]:
            present = "、".join(str(name) for name in (item.get("present_in") or []))
            findings.append(
                {
                    "claim": f"{section}｜仅存在于 {present or '部分文件'}：{item.get('path')}",
                    "evidence": "diff.json diffs.only_in",
                    "kind": "fact",
                }
            )
    if not findings:
        findings.append(
            {
                "claim": f"{compared_count} 份已比对的快照未发现差异（相似度 {similarity}%）。",
                "evidence": "diff.json summary",
                "kind": "fact",
            }
        )
    skipped = data.get("skipped_files") or []
    status = "partial" if upstream_status == "partial" else "ok"
    compat_findings: list[dict] = []
    compat_missing: list[str] = []
    compat_artifacts: list[str] = []
    for index, path in enumerate(paths, 1):
        fact, missing_items, artifact, partial = _compatibility_facts(path, index, out_dir, args.timeout)
        if partial:
            status = "partial"
        if fact:
            compat_findings.append(fact)
        compat_missing.extend(missing_items)
        if artifact:
            compat_artifacts.append(artifact)
    findings.extend(compat_findings)
    text = (
        f"比对 {compared_count} 份快照：总路径 {summary.get('total_paths', 0)}，"
        f"一致 {summary.get('identical_paths', 0)}，差异 {diff_count}，相似度 {similarity}%。"
        f" 另对 {len(compat_artifacts)}/{len(paths)} 份快照做了版本配套检查。"
    )
    if skipped:
        text += f" 跳过 {len(skipped)} 个文件（见 missing）。"
    artifacts = [str(output)]
    if is_fresh(html, html_before):
        artifacts.append(str(html))
    artifacts.extend(compat_artifacts)
    missing = [f"跳过：{item}" for item in skipped] + compat_missing
    if not is_fresh(html, html_before):
        missing.append("HTML 报告未生成，JSON 差异结果仍可用")
    return {
        "status": status,
        "summary": clip(text, 500),
        "findings": findings[:8],
        "missing": missing[:10],
        "artifacts": artifacts,
    }


def analyze(inputs, out_dir: Path, args) -> dict:
    paths = _snapshot_paths(inputs)
    if len(paths) == 1:
        return _single_snapshot(paths[0], out_dir, args)
    if len(paths) < 2:
        raise AnalyzerError("bad-input", "环境快照分析需要一份（看版本配套）或至少两份（看配置漂移）。")
    if not COMPARE.is_file():
        raise AnalyzerError("analyzer-not-installed", f"缺上游入口：{COMPARE}", status="failed")
    return _compare(paths, out_dir, args)


if __name__ == "__main__":
    sys.exit(run_adapter(ANALYZER, VERSION, analyze, "Ascend 环境快照分析"))
