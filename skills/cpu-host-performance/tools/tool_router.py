#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据已有证据生成 HostBound 补采集计划；不执行采集或修改系统状态。"""
import argparse
import json
import os
import shutil


def exists_tool(name):
    return bool(shutil.which(name))


def route(args):
    signals = {s.strip().lower() for s in (args.signals or "").split(",") if s.strip()}
    plan = [{
        "tool": "ftrace",
        "required": True,
        "reason": "所有 HostBound 结论的基础证据：调度、抢占、IRQ/SoftIRQ、迁移与 CPU idle。",
        "action": "使用 scripts/cpu_trace_collect.sh；默认全量模式；需要进程/线程证据时追加 --pid <PID>。",
    }]
    if signals & {"python", "gil", "thread", "thread-contention"}:
        plan.append({
            "tool": "gil_tracer",
            "required": "conditional",
            "reason": "Python 多线程/GIL 争用是候选根因；需与 ftrace 同窗口对齐。",
            "preconditions": ["Linux", "root", "sysTrace_cli 在 PATH", "目标 PID 已确认"],
            "action": "使用官方 misc/gil_tracer/gil_trace_record.py；仅限目标 PID 和短窗口。",
        })
    if signals & {"function", "pmu", "cache", "page-fault", "operator-gap"}:
        plan.append({
            "tool": "function_monitor",
            "required": "conditional",
            "reason": "需要把业务函数耗时、Cache Miss/Page Fault 与 ftrace 空泡进行关联。",
            "preconditions": ["Python + PyTorch", "用户允许插桩", "PMU 模式还需 libkperf 与权限"],
            "action": "使用官方 misc/function_monitor；只标注粗粒度业务函数或代码段。",
        })
    if signals & {"device-gap", "overlap", "runtime", "cann", "ascend"}:
        plan.append({
            "tool": "msprof",
            "required": "conditional",
            "reason": "需要确认 Host 下发、Runtime API 与 Device task 的重叠/空泡关系。",
            "preconditions": ["已有 CANN Profiling collection-dir，或客户按其版本官方流程采集"],
            "action": "只导入/导出 collection-dir；不得修改官方 msProf 源码。",
        })
    if signals & {"irq", "affinity", "numa", "cache", "preemption"}:
        plan.append({
            "tool": "host_analyzer",
            "required": "after-diagnosis-only",
            "reason": "用于验证已证实的 CPU/IRQ/NUMA 资源争用优化，不用于发现根因。",
            "preconditions": ["Ascend npu-smi 可用", "已保存当前 affinity/IRQ 配置", "用户确认变更窗口"],
            "action": "先生成/审阅 JSON；禁止自动执行绑核或停止 irqbalance。",
        })
    return {
        "mode": "evidence-first",
        "detected_environment": {"sysTrace_cli": exists_tool("sysTrace_cli"), "npu-smi": exists_tool("npu-smi")},
        "input_signals": sorted(signals),
        "collection_plan": plan,
        "rule": "任何优化建议均需至少两类独立证据支持；无证据时返回 INSUFFICIENT_EVIDENCE。",
    }


def main():
    parser = argparse.ArgumentParser(description="生成 HostBound 工具选择计划（只读、不采集）。")
    parser.add_argument("--signals", default="", help="逗号分隔：python,gil,pmu,irq,numa,device-gap 等")
    parser.add_argument("--output", default="", help="可选 JSON 输出路径")
    args = parser.parse_args()
    result = route(args)
    data = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output = os.path.abspath(args.output)
        with open(output, "w", encoding="utf-8") as fp:
            fp.write(data + "\n")
    print(data)


if __name__ == "__main__":
    main()
