#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内置分析器清单（名称、适配器、上游入口、输入形态）。

新增分析器只改这里与 `scripts/analyzers/`、适配器目录；CLI 不写死名字。
"""
from __future__ import annotations

ANALYZERS = [
    {
        "name": "ibmc_analyzer",
        "adapter": "ibmc_analyzer/run.py",
        "entry": "scripts/run_bmc_report.py",
        "inputs": "一个或多个 dump_info 目录、机器目录，或 iBMC 一键收集压缩包（.zip/.tar.gz/.tgz/.tar）",
        "purpose": "解析 iBMC 一键收集日志，判断服务器硬件健康，输出每机 JSON 与 HTML 报告",
    },
    {
        "name": "issue-analyzer",
        "adapter": "issue-analyzer/run.py",
        "entry": "scripts/log_analyzer.py",
        "inputs": "日志归档先解包。传入一个日志目录或一个或多个日志文件。",
        "purpose": "对 plog/slog/host/device/framework/dmesg 日志做清单、错误提取、聚合与回验",
    },
    {
        "name": "ascend-dump-analyzer",
        "adapter": "ascend-dump-analyzer/run.py",
        "entry": "references/check_compatibility.py",
        "inputs": "一份环境快照 JSON（看版本配套），或至少两份含 JSON 内容的环境快照（看配置漂移）",
        "purpose": "单份核对采集环境的版本配套并保留采集缺项，多份按字段比对配置漂移",
    },
    {
        "name": "cluster-analysis",
        "adapter": "cluster-analysis/run.py",
        "entry": "scripts/run_workflow.py",
        "inputs": "一份 prof 目录（单卡目录或多卡根目录），或已生成的 cluster_analysis_output",
        "purpose": "单份 prof 的端到端性能分析：advisor、泳道、瓶颈定位与 HTML 报告",
    },
    {
        "name": "cluster-compare",
        "adapter": "cluster-compare/run.py",
        "entry": "scripts/generate_cluster_report.py",
        "inputs": "两份集群数据目录（各含 cluster_analysis_output 的 DB 或 TEXT），A 基准、B 对比",
        "purpose": "比对两个集群的 profiling 数据，输出劣化归因 HTML 与 Markdown 报告",
    },
    {
        "name": "prof-compare",
        "adapter": "prof-compare/run.py",
        "entry": "scripts/host_kernel.py",
        "inputs": "两份单卡 Prof（A 基准、B 对比）。混合对比时 A 为 GPU trace 基准，B 为 NPU 对比。",
        "purpose": "比对单卡 Prof 的 Host 算子与 Device kernel 热点，输出逐组耗时差与单次执行序列",
    },
    {
        "name": "cpu-host-performance",
        "adapter": "cpu-host-performance/run.py",
        "entry": "analyzer/analyze_cpu_trace.py",
        "inputs": "一份 ftrace/Host 采集包（cpu_trace_*.tar.gz、zip、解包目录、trace 文本或 Chrome JSON）",
        "purpose": "离线解析 Host/CPU trace，输出调度、中断、频率与绑核建议报告",
    },
]

BY_NAME = {item["name"]: item for item in ANALYZERS}


def find(name: str) -> dict | None:
    return BY_NAME.get(name)


def names() -> list[str]:
    return [item["name"] for item in ANALYZERS]
