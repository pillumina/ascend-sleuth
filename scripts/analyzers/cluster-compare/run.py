#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""两个集群 profiling 数据的比对适配器。

上游实现：scripts/analyzers/cluster-compare/scripts/{cluster_data_extractor,generate_cluster_report,generate_cluster_md}.py
输入按 A（基准）、B（对比）顺序给两份集群数据目录；只接受已有 cluster_analysis_output（DB/TEXT），
不在诊断里安装 msprof-analyze、也不从原始采集数据自动生成。
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

ANALYZER = "cluster-compare"
VERSION = UPSTREAM_COMMIT
TOOL_DIR = HERE
EXTRACT = TOOL_DIR / "scripts" / "cluster_data_extractor.py"
REPORT = TOOL_DIR / "scripts" / "generate_cluster_report.py"
REPORT_MD = TOOL_DIR / "scripts" / "generate_cluster_md.py"


def _extract(path: str, output: Path, args) -> dict:
    before = file_signature(output)
    proc = run_process(
        [sys.executable, str(EXTRACT), "--data-dir", path, "--output", str(output), "--no-advanced"],
        cwd=TOOL_DIR,
        timeout=args.timeout,
        log_path=output.with_suffix(".log"),
    )
    if proc.get("timed_out"):
        raise AnalyzerError("timeout", f"数据提取超过 {args.timeout}s", status="failed")
    fresh = is_fresh(output, before)
    if proc.get("exit_code") not in (0, None) or not fresh:
        raise AnalyzerError(
            "bad-input",
            f"{path} 不是可用的集群数据目录（需 cluster_analysis_output 下 DB 或 "
            f"cluster_step_trace_time.csv + communication_group.json）。"
            + ("没有生成新的提取结果；" if not fresh else "")
            + f"退出码 {proc.get('exit_code')}；stderr：{tail(proc.get('stderr'), 500)}",
        )
    return read_json(output)


def _step_diff(data_a: dict, data_b: dict) -> dict:
    steps_a = data_a.get("step_summary") or {}
    steps_b = data_b.get("step_summary") or {}
    common = [step for step in steps_a if step in steps_b]
    pairs = [(step, step) for step in common]
    shape_only = False
    if not pairs:
        sys.path.insert(0, str(TOOL_DIR / "scripts"))
        from compare_metrics import ordinal_step_pairs

        ordered, _ = ordinal_step_pairs(steps_a, steps_b)
        pairs = [(a, b) for _, a, b in ordered if a is not None and b is not None]
        shape_only = True
    if not pairs:
        return {}
    def mean(key):
        values = []
        for step_a, step_b in pairs:
            a = (steps_a.get(step_a) or {}).get(key)
            b = (steps_b.get(step_b) or {}).get(key)
            if a is not None and b is not None:
                values.append((float(b) - float(a)) / 1000.0)
        return sum(values) / len(values) if values else None
    return {
        "steps": len(pairs),
        "shape_only": shape_only,
        "stage_ms": mean("avg_stage"),
        "compute_ms": mean("avg_compute"),
        "comm_ms": mean("avg_comm"),
        "free_ms": mean("avg_free"),
    }


def _delta(value) -> str:
    return "未采到" if value is None else f"{value:+.3f}"


def analyze(inputs, out_dir: Path, args) -> dict:
    for entry in (EXTRACT, REPORT, REPORT_MD):
        if not entry.is_file():
            raise AnalyzerError("analyzer-not-installed", f"缺上游入口：{entry}", status="failed")
    if len(inputs) != 2 or any(item["kind"] != "dir" for item in inputs):
        raise AnalyzerError(
            "bad-input",
            "接受两份集群数据目录，顺序为 A（基准）、B（对比）；每份需含 cluster_analysis_output 的 DB 或 TEXT。",
        )

    data_a_path = out_dir / "data_a.json"
    data_b_path = out_dir / "data_b.json"
    data_a = _extract(inputs[0]["path"], data_a_path, args)
    data_b = _extract(inputs[1]["path"], data_b_path, args)

    html = out_dir / "cluster_compare_report.html"
    md = out_dir / "cluster_compare_report.md"
    html_before = file_signature(html)
    proc = run_process(
        [sys.executable, str(REPORT), "--data-a", str(data_a_path), "--data-b", str(data_b_path),
         "--output", str(html)],
        cwd=TOOL_DIR,
        timeout=args.timeout,
        log_path=out_dir / "report.log",
    )
    if proc.get("timed_out"):
        raise AnalyzerError("timeout", f"报告生成超过 {args.timeout}s", status="failed")
    if not is_fresh(html, html_before):
        raise AnalyzerError(
            "analyzer-failed",
            "没有生成新的 HTML 报告（复用输出目录时不会沿用上一次结果）："
            f"退出码 {proc.get('exit_code')}；{tail(proc.get('stderr'), 600)}",
            status="failed",
        )

    md_before = file_signature(md)
    proc_md = run_process(
        [sys.executable, str(REPORT_MD), "--data-a", str(data_a_path), "--data-b", str(data_b_path),
         "--output", str(md)],
        cwd=TOOL_DIR,
        timeout=args.timeout,
        log_path=out_dir / "report_md.log",
    )
    if proc_md.get("timed_out"):
        raise AnalyzerError("timeout", f"Markdown 报告生成超过 {args.timeout}s", status="failed")

    diff = _step_diff(data_a, data_b)
    if not diff:
        raise AnalyzerError("bad-input", "两份数据没有共同的 Step，无法比对；先确认两次采集的 step 范围。")

    pairing = "按采集顺序配对" if diff["shape_only"] else "共同"
    findings = [
        {
            "claim": (
                "{pairing} {steps} 个 Step：Stage 平均差 {stage} ms，计算 {compute} ms，"
                "通信 {comm} ms，空闲 {free} ms（B−A）"
            ).format(
                steps=diff["steps"],
                pairing=pairing,
                stage=_delta(diff.get("stage_ms")),
                compute=_delta(diff.get("compute_ms")),
                comm=_delta(diff.get("comm_ms")),
                free=_delta(diff.get("free_ms")),
            ),
            "evidence": "data_a.json / data_b.json step_summary",
            "kind": "candidate" if diff["shape_only"] else "fact",
        }
    ]
    tables_empty = sorted(set(data_a.get("tables_empty") or []) | set(data_b.get("tables_empty") or []))
    if tables_empty:
        findings.append(
            {
                "claim": "缺失的可选数据：" + "、".join(tables_empty) + "；通信带宽/矩阵相关结论不可用。",
                "evidence": "data_a.json tables_empty",
                "kind": "fact",
            }
        )
    findings.append(
        {
            "claim": "差异、慢卡与通信算子排行见 HTML/Markdown 报告，摘要给出配对 Step 的均值差。",
            "evidence": str(html),
            "kind": "fact",
        }
    )

    summary = (
        f"集群比对（A 基准 → B 对比）：{pairing} {diff['steps']} 个 Step，"
        f"Stage 平均差 {_delta(diff.get('stage_ms'))} ms（正值为 B 更慢）。"
        f"报告：{html}"
    )
    artifacts = [str(item) for item in (html, md, data_a_path, data_b_path) if item.is_file()]
    missing = [f"缺可选表：{item}" for item in tables_empty]
    if not is_fresh(md, md_before):
        missing.append("Markdown 报告未生成，HTML 报告仍可用")
        artifacts = [item for item in artifacts if item != str(md)]
    if diff["shape_only"]:
        missing.append("两侧 Step 编号不重叠，按采集顺序配对，仅用于形态比较。需要同一迭代的证据才能判断逐步性能。")
    return {
        "status": "partial" if missing else "ok",
        "summary": clip(summary, 500),
        "findings": findings[:5],
        "missing": missing[:8],
        "artifacts": artifacts,
    }


if __name__ == "__main__":
    sys.exit(run_adapter(ANALYZER, VERSION, analyze, "两个集群 profiling 数据的劣化归因比对"))
