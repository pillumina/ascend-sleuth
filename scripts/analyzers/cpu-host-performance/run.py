#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Host/CPU trace 离线分析适配器。

上游实现：scripts/analyzers/cpu-host-performance/analyzer/analyze_cpu_trace.py
只做离线解析；采集脚本、绑核执行入口不在本适配器调用范围内。
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

ANALYZER = "cpu-host-performance"
VERSION = UPSTREAM_COMMIT
TOOL_DIR = HERE
ENTRY = TOOL_DIR / "analyzer" / "analyze_cpu_trace.py"


def analyze(inputs, out_dir: Path, args) -> dict:
    if not ENTRY.is_file():
        raise AnalyzerError("analyzer-not-installed", f"缺上游入口：{ENTRY}", status="failed")
    if len(inputs) != 1:
        raise AnalyzerError("bad-input", "一次只接受一份 trace 采集包/目录/文件。")
    target = inputs[0]["path"]

    data_path = out_dir / "report_data.json"
    before = file_signature(data_path)
    optional_before = {
        path: file_signature(path)
        for path in (
            out_dir / "hostbound_report.html",
            out_dir / "cpu_binder_simple.py",
            out_dir / "bind_design.json",
        )
    }
    proc = run_process(
        [sys.executable, str(ENTRY), target, "-o", str(out_dir), "-q"],
        cwd=TOOL_DIR,
        timeout=args.timeout,
        log_path=out_dir / "vendor.log",
    )
    if proc.get("timed_out"):
        raise AnalyzerError("timeout", f"超过 {args.timeout}s", status="failed")
    if not is_fresh(data_path, before):
        detail = tail((proc.get("stderr") or "") + "\n" + (proc.get("stdout") or ""), 800)
        reason = "bad-input" if proc.get("exit_code") == 3 else "analyzer-failed"
        raise AnalyzerError(
            reason,
            "没有生成新的 report_data.json"
            f"（复用输出目录时不会沿用上一次结果；退出码 {proc.get('exit_code')}）。"
            f"{detail or '上游没有写出结果文件'}",
            status="failed",
        )

    data = read_json(data_path)
    diag = data.get("diagnosis") or {}
    findings_data = diag.get("findings") or []
    primary = diag.get("primary") or {}
    findings = []
    if primary:
        evidence = primary.get("evidence") or []
        evidence_text = "；".join(
            f"{item.get('metric')}={item.get('value')}" for item in evidence[:3] if isinstance(item, dict)
        )
        findings.append(
            {
                "claim": (
                    f"{primary.get('title')}｜{primary.get('severity')}｜"
                    f"置信度 {primary.get('confidence')}｜{clip(evidence_text, 180)}"
                ),
                "evidence": "report_data.json diagnosis.primary",
                "kind": "fact",
            }
        )
        if primary.get("possible_root_cause"):
            findings.append(
                {
                    "claim": f"候选根因：{primary.get('possible_root_cause')}",
                    "evidence": "report_data.json diagnosis.primary.possible_root_cause",
                    "kind": "candidate",
                }
            )
    for item in findings_data[:3]:
        if not isinstance(item, dict) or item.get("title") == primary.get("title"):
            continue
        findings.append(
            {
                "claim": f"{item.get('title')}｜{item.get('severity')}｜{item.get('confidence')}",
                "evidence": "report_data.json diagnosis.findings",
                "kind": "fact",
            }
        )
    bind_design = out_dir / "bind_design.json"
    if is_fresh(bind_design, optional_before[bind_design]):
        findings.append(
            {
                "claim": "绑核建议位于 bind_design.json，配套执行脚本为 cpu_binder_simple.py。现场执行需要核对目标进程和变更授权。",
                "evidence": str(bind_design),
                "kind": "fact",
            }
        )

    missing = []
    if not findings_data and not primary:
        missing.append("诊断没有给出任何问题项；可能事件不足或 trace 格式不受支持")
    if primary.get("causality") == "UNPROVEN":
        missing.append("Host 侧风险已观测，但 NPU 因果未证明；不能单独当作根因")
    if not is_fresh(bind_design, optional_before[bind_design]):
        missing.append("本次没有生成 bind_design.json，绑核建议不可用")
    html = out_dir / "hostbound_report.html"
    html_fresh = is_fresh(html, optional_before[html])
    if not html_fresh:
        missing.append("本次没有生成 hostbound_report.html，HTML 报告不可用")
    summary = (
        f"Host 状态 {diag.get('host_status', 'UNKNOWN')}；"
        f"核心问题：{primary.get('title') if primary else '未发现明显问题'}。"
        + (f"报告：{html}" if html_fresh else "报告：本次未生成")
    )

    artifacts = [str(data_path)]
    artifacts.extend(
        str(path)
        for path, signature in optional_before.items()
        if is_fresh(path, signature)
    )
    return {
        "status": "ok",
        "summary": clip(summary, 500),
        "findings": findings[:5],
        "missing": missing[:8],
        "artifacts": artifacts,
    }


if __name__ == "__main__":
    sys.exit(run_adapter(ANALYZER, VERSION, analyze, "Host/CPU trace 离线分析"))
