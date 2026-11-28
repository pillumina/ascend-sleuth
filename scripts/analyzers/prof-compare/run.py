#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单卡 Prof 对比适配器：Host 算子与 Device kernel 热点。

上游实现：scripts/analyzers/prof-compare/scripts/（cross_trace / npu_source /
kernel_execution / host_kernel）。只走上游的标准库路径，不调用会在线安装 msprof-analyze
的 run_compare.py，也不生成需要 openpyxl 的 xlsx 报告。
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

ANALYZER = "prof-compare"
VERSION = UPSTREAM_COMMIT
TOOL_DIR = HERE
DRIVER = HERE / "driver.py"
MODE_LABELS = {
    "npu_npu": ("对比 NPU", "基准 NPU"),
    "npu_gpu": ("NPU", "GPU"),
}


def _ms(value) -> str:
    return "—" if value is None else f"{float(value):.3f}"


def _ratio(value) -> str:
    return "—" if value is None else f"{float(value):.3f}"


def _cell(value) -> str:
    return str(value or "—").replace("|", "\\|").replace("\n", " ")


def _device_rows(detail: dict) -> list[dict]:
    rows = []
    for row in detail.get("device") or []:
        if not isinstance(row, dict):
            continue
        diff = row.get("diff") or {}
        full = row.get("npu") or {}
        matched = row.get("matched_npu")
        rows.append(
            {
                "op": row.get("op") or "unknown",
                "core": row.get("core") or "unknown",
                "compare": matched or full,
                "full_calls": full.get("calls"),
                "partial": bool(matched) and matched.get("calls") != full.get("calls"),
                "base": row.get("base") or row.get("gpu") or {},
                "delta_ms": diff.get("delta_ms"),
                "ratio": diff.get("ratio"),
                "status": row.get("status") or "",
                "note": row.get("note") or "",
            }
        )
    return rows


def _host_rows(detail: dict) -> list[dict]:
    rows = []
    for row in detail.get("host") or []:
        if not isinstance(row, dict):
            continue
        compare_self = row.get("npu_self_ms")
        base_self = row.get("base_self_ms")
        if base_self is None:
            base_self = row.get("gpu_self_ms")
        delta = (
            float(compare_self) - float(base_self)
            if compare_self is not None and base_self is not None
            else None
        )
        peer = row.get("base") or row.get("gpu") or {}
        rows.append(
            {
                "name": row.get("npu_name") or "unknown",
                "compare_self_ms": compare_self,
                "base_self_ms": base_self,
                "delta_ms": delta,
                "compare_total_ms": (row.get("npu") or {}).get("total_ms"),
                "base_total_ms": peer.get("total_ms"),
                "compare_calls": (row.get("npu") or {}).get("calls"),
                "base_calls": peer.get("calls"),
            }
        )
    return rows


def _markdown(detail: dict, device: list[dict], host: list[dict]) -> str:
    mode = detail.get("mode") or ("npu_gpu" if detail.get("gpu_path") else "npu_npu")
    left, right = MODE_LABELS.get(mode, ("对比侧", "基准侧"))
    lines = [
        "# 单卡 Prof 对比",
        "",
        f"- 对比侧（{left}）：{detail.get('npu_path') or '未记录'}",
        (
            f"- 基准侧（{right}）：{detail.get('base_path') or detail.get('gpu_path') or '未记录'}"
        ),
        "- 差值统一为「对比侧 − 基准侧」；Device 耗时单位 ms，Host self 单位 ms。",
        "",
        "## Device Top 15",
        "",
        f"| 算子 | 核心 | {left} 总耗时(ms) | {right} 总耗时(ms) | 差(ms) | 比率 | {left} 次数 | 状态 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in device[:15]:
        calls = row["compare"].get("calls", "—")
        if row["partial"]:
            calls = f"{calls}（部分，完整 {row['full_calls']}）"
        lines.append(
            f"| {_cell(row['op'])} | {_cell(row['core'])} | {_ms(row['compare'].get('total_ms'))} | "
            f"{_ms(row['base'].get('total_ms'))} | {_ms(row['delta_ms'])} | {_ratio(row['ratio'])} | "
            f"{calls} | {_cell(row['status'])} |"
        )
    lines += [
        "",
        "## Host 算子",
        "",
        f"| 算子 | {left} self(ms) | {right} self(ms) | 差(ms) | {left} 总耗时(ms) | {right} 总耗时(ms) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in host[:10]:
        lines.append(
            f"| {_cell(row['name'])} | {_ms(row['compare_self_ms'])} | {_ms(row['base_self_ms'])} | "
            f"{_ms(row['delta_ms'])} | {_ms(row['compare_total_ms'])} | {_ms(row['base_total_ms'])} |"
        )
    notes = detail.get("notes") or []
    if notes:
        lines += ["", "## 覆盖限制", ""] + [f"- {note}" for note in notes]
    return "\n".join(lines) + "\n"


def analyze(inputs, out_dir: Path, args) -> dict:
    if len(inputs) != 2:
        raise AnalyzerError(
            "bad-input",
            "单卡 Prof 对比需要两份输入（A 基准、B 对比）。混合对比时 A 为 GPU trace，B 为 NPU。",
        )
    if not DRIVER.is_file() or not TOOL_DIR.is_dir():
        raise AnalyzerError("analyzer-not-installed", f"缺上游实现：{TOOL_DIR}", status="failed")
    baseline, compare = inputs[0]["path"], inputs[1]["path"]
    output = out_dir / "prof_compare.json"
    before = file_signature(output)
    proc = run_process(
        [
            sys.executable,
            str(DRIVER),
            "--baseline",
            baseline,
            "--compare",
            compare,
            "--output",
            str(output),
        ],
        timeout=args.timeout,
        log_path=out_dir / "vendor.log",
    )
    if proc.get("timed_out"):
        raise AnalyzerError("timeout", f"超过 {args.timeout}s", status="failed")
    fresh = is_fresh(output, before)
    if proc.get("exit_code") not in (0, None) or not fresh:
        detail = tail(proc.get("stderr"), 900) or tail(proc.get("stdout"), 900)
        reason = "bad-input" if any(
            key in detail
            for key in ("多卡", "单卡", "未识别", "不是可识别", "需要", "缺少列", "无效的耗时")
        ) else "analyzer-failed"
        prefix = (
            "没有生成新的 prof_compare.json（复用输出目录时不会沿用上一次结果）。"
            if not fresh
            else ""
        )
        raise AnalyzerError(
            reason,
            prefix
            + "退出码 {code}；{detail}".format(
                code=proc.get("exit_code"), detail=detail or "上游没有写出结果文件"
            ),
            status="blocked" if reason == "bad-input" else "failed",
        )

    data = read_json(output)
    mode = data.get("mode") or ("npu_gpu" if data.get("gpu_path") else "npu_npu")
    left, right = MODE_LABELS.get(mode, ("对比侧", "基准侧"))
    device = _device_rows(data)
    host = _host_rows(data)
    notes = [str(item) for item in (data.get("notes") or [])]
    execution = data.get("execution") or {}

    degraded = sorted(
        [row for row in device if row["delta_ms"] is not None and row["delta_ms"] > 0],
        key=lambda row: -row["delta_ms"],
    )
    improved = sorted(
        [row for row in device if row["delta_ms"] is not None and row["delta_ms"] < 0],
        key=lambda row: row["delta_ms"],
    )
    findings: list[dict] = []
    for row in degraded[:5]:
        partial = (
            f"；部分覆盖（完整 calls={row['full_calls']}）" if row["partial"] else ""
        )
        findings.append(
            {
                "claim": (
                    f"Device {row['op']}/{row['core']}：{left} {_ms(row['compare'].get('total_ms'))} ms，"
                    f"{right} {_ms(row['base'].get('total_ms'))} ms，慢 {_ms(row['delta_ms'])} ms"
                    f"（比率 {_ratio(row['ratio'])}；{row['status'] or '状态未记录'}{partial}）"
                ),
                "evidence": "prof_compare.json device",
                "kind": "fact",
            }
        )
    for row in improved[:2]:
        partial = (
            f"；部分覆盖（完整 calls={row['full_calls']}）" if row["partial"] else ""
        )
        findings.append(
            {
                "claim": (
                    f"Device {row['op']}/{row['core']}：{left} {_ms(row['compare'].get('total_ms'))} ms，"
                    f"{right} {_ms(row['base'].get('total_ms'))} ms，快 {_ms(abs(row['delta_ms']))} ms"
                    f"（比率 {_ratio(row['ratio'])}{partial}）"
                ),
                "evidence": "prof_compare.json device",
                "kind": "fact",
            }
        )
    host_delta = sorted(
        [row for row in host if row["delta_ms"] is not None],
        key=lambda row: -row["delta_ms"],
    )
    for row in host_delta[:3]:
        if row["delta_ms"] == 0:
            continue
        direction = "慢" if row["delta_ms"] > 0 else "快"
        findings.append(
            {
                "claim": (
                    f"Host {row['name']} self：{left} {_ms(row['compare_self_ms'])} ms，"
                    f"{right} {_ms(row['base_self_ms'])} ms，{direction} {_ms(abs(row['delta_ms']))} ms"
                ),
                "evidence": "prof_compare.json host",
                "kind": "fact",
            }
        )
    if not findings:
        findings.append(
            {
                "claim": "两侧都读到了明细，但 Device/Host 的耗时差值都是 0 或缺少可比较的对应分组。",
                "evidence": "prof_compare.json device / host",
                "kind": "fact",
            }
        )

    status = "partial" if notes else "ok"
    summary = (
        f"单卡 Prof 对比（{left} vs {right}）：Device {len(device)} 组，Host {len(host)} 项，"
        f"单次执行 {len((execution.get('series') or {}))} 个序列；"
        f"劣化 {len(degraded)} 组，改善 {len(improved)} 组。"
    )
    md = out_dir / "prof_compare.md"
    md.write_text(_markdown(data, device, host), encoding="utf-8")

    observations = [
        {
            "topic": f"Device {row['op']}/{row['core']}",
            "detail": (
                f"{left} calls={row['compare'].get('calls')} total={_ms(row['compare'].get('total_ms'))}ms"
                + (f"（部分，完整 {row['full_calls']}）" if row["partial"] else "")
                + f"；{right} calls={row['base'].get('calls')} total={_ms(row['base'].get('total_ms'))}ms；"
                f"差 {_ms(row['delta_ms'])}ms"
            ),
            "level": "info",
            "evidence": f"prof_compare.json device[{index}]",
        }
        for index, row in enumerate(device[:15])
    ]
    return {
        "status": status,
        "summary": clip(summary, 500),
        "findings": findings[:10],
        "missing": notes[:8],
        "artifacts": [str(output), str(md)],
        "observations": observations,
    }


if __name__ == "__main__":
    sys.exit(run_adapter(ANALYZER, VERSION, analyze, "单卡 Prof 对比（Host/Device 热点）"))
