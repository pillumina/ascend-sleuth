#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""现网问题日志取证适配器。

上游实现：scripts/analyzers/issue-analyzer/scripts/log_analyzer.py
本文件按 L0 清单 → L1 提取 → L2 聚合跑一遍，结果摘要取自上游 JSON，不改判据。
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
)

ANALYZER = "issue-analyzer"
VERSION = UPSTREAM_COMMIT
TOOL_DIR = HERE
ENTRY = TOOL_DIR / "scripts" / "log_analyzer.py"
ARCHIVE_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".zip", ".7z", ".rar")


def _run(args, out_dir: Path, timeout: int, name: str) -> dict:
    cmd = [sys.executable, str(ENTRY), *args]
    return run_process(cmd, cwd=TOOL_DIR, timeout=timeout, log_path=out_dir / f"{name}.log")


def analyze(inputs, out_dir: Path, args) -> dict:
    if not ENTRY.is_file():
        raise AnalyzerError("analyzer-not-installed", f"缺上游入口：{ENTRY}", status="failed")

    dirs = [item["path"] for item in inputs if item["kind"] == "dir"]
    files = [item["path"] for item in inputs if item["kind"] == "file"]
    archives = [Path(path).name for path in files if path.lower().endswith(ARCHIVE_SUFFIXES)]
    if archives:
        raise AnalyzerError(
            "bad-input",
            "请先解包，再传一个日志目录或日志文件。待解包文件：" + "、".join(archives),
        )
    if len(dirs) > 1:
        raise AnalyzerError("bad-input", "请传一个包含各节点日志的目录，或传一个或多个日志文件。")

    logs = out_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    manifest_json = logs / "manifest.json"
    hits_json = logs / "hits.json"
    stats_json = logs / "stats.json"
    manifest_before = file_signature(manifest_json)
    hits_before = file_signature(hits_json)
    stats_before = file_signature(stats_json)

    problems = []

    if dirs and len(dirs) == 1 and not files:
        proc = _run(
            ["scan", "--dir", dirs[0], "--out", str(manifest_json), "--md", str(logs / "manifest.md")],
            out_dir,
            args.timeout,
            "scan",
        )
        if (
            proc.get("timed_out")
            or proc.get("exit_code") not in (0, None)
            or not is_fresh(manifest_json, manifest_before)
        ):
            problems.append(f"scan 失败：{tail(proc.get('stderr'), 300)}")

    extract_args = ["extract"]
    if dirs and len(dirs) == 1:
        extract_args += ["--dir", dirs[0]]
    if files:
        extract_args += ["--files", *files]
    extract_args += ["--out", str(hits_json), "--md", str(logs / "hits.md")]
    proc = _run(extract_args, out_dir, args.timeout, "extract")
    if proc.get("timed_out"):
        raise AnalyzerError("timeout", f"错误提取超过 {args.timeout}s", status="failed")
    fresh = is_fresh(hits_json, hits_before)
    if proc.get("exit_code") not in (0, None) or not fresh:
        raise AnalyzerError(
            "analyzer-failed",
            ("没有生成新的 hits.json（复用输出目录时不会沿用上一次结果）。" if not fresh else "")
            + "退出码 {code}；stderr：{err}".format(
                code=proc.get("exit_code"), err=tail(proc.get("stderr"), 600)
            ),
            status="failed",
        )

    if hits_json.is_file():
        proc = _run(
            ["stats", "--hits", str(hits_json), "--out", str(stats_json), "--md", str(logs / "stats.md")],
            out_dir,
            args.timeout,
            "stats",
        )
        if (
            proc.get("timed_out")
            or proc.get("exit_code") not in (0, None)
            or not is_fresh(stats_json, stats_before)
        ):
            problems.append(f"stats 失败：{tail(proc.get('stderr'), 300)}")

    hits = read_json(hits_json)
    stats = (
        read_json(stats_json)
        if stats_json.is_file() and is_fresh(stats_json, stats_before)
        else {}
    )
    total = int(stats.get("total") or hits.get("total_hits") or 0)
    by_pattern = stats.get("by_pattern") or {}
    by_file = stats.get("by_file") or {}
    pattern_text = "、".join(f"{key}×{value}" for key, value in list(by_pattern.items())[:6]) or "无"

    findings = []
    for hit in (hits.get("hits") or [])[:3]:
        location = f"{hit.get('file')}:{hit.get('line')}"
        findings.append(
            {
                "claim": f"{location}｜{'/'.join(hit.get('patterns') or [])}｜{clip(hit.get('text'), 200)}",
                "evidence": location,
                "kind": "fact",
            }
        )
    if not findings and hits.get("files_scanned"):
        findings.append(
            {
                "claim": f"扫描 {hits.get('files_scanned', 0)} 个文件，未命中预置错误模式；"
                f"这不等于没有异常，只说明默认词表未覆盖。",
                "evidence": str(hits_json),
                "kind": "fact",
            }
        )

    missing = []
    if not hits.get("files_scanned"):
        missing.append("没有可读的日志文件（检查目录或文件路径）")
    if problems:
        missing.extend(problems)

    status = "partial" if missing else "ok"
    summary = (
        f"扫描 {hits.get('files_scanned', 0)} 个文件（{hits.get('files_with_hits', 0)} 个有命中），"
        f"命中 {total} 条。按模式：{pattern_text}。"
        f"清单、命中与聚合结果在 {logs}。"
    )
    if by_file:
        top_files = "、".join(f"{key}×{value}" for key, value in list(by_file.items())[:3])
        summary += f" 命中最多：{top_files}。"

    artifacts = []
    if is_fresh(hits_json, hits_before):
        artifacts.append(str(hits_json))
        if (logs / "hits.md").is_file():
            artifacts.append(str(logs / "hits.md"))
    if stats_json.is_file() and is_fresh(stats_json, stats_before):
        artifacts.append(str(stats_json))
        if (logs / "stats.md").is_file():
            artifacts.append(str(logs / "stats.md"))
    if manifest_json.is_file() and is_fresh(manifest_json, manifest_before):
        artifacts.append(str(manifest_json))
        if (logs / "manifest.md").is_file():
            artifacts.append(str(logs / "manifest.md"))
    return {
        "status": status,
        "summary": clip(summary, 500),
        "findings": findings[:5],
        "missing": missing[:8],
        "artifacts": artifacts,
    }


if __name__ == "__main__":
    sys.exit(run_adapter(ANALYZER, VERSION, analyze, "日志清单 / 错误提取 / 聚合 / 证据回验"))
