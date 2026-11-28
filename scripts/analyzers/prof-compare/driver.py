#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调用上游 prof-compare 的单卡 Host/Device 热点对比实现。

只使用上游的标准库实现（cross_trace / npu_source / kernel_execution / host_kernel），
不调用会在线安装 msprof-analyze 的 run_compare.py，也不生成 xlsx。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE / "scripts"
sys.path.insert(0, str(SCRIPTS))


def main() -> int:
    parser = argparse.ArgumentParser(description="单卡 Prof Host/Device 热点对比")
    parser.add_argument("--baseline", required=True, help="基准侧（A）")
    parser.add_argument("--compare", required=True, help="对比侧（B）")
    parser.add_argument("--output", required=True, help="输出 JSON")
    args = parser.parse_args()

    try:
        from cross_trace import gpu_file
        from host_kernel import compare_gpu, compare_npus
        from npu_source import npu_source
        from profile_identity import comparison_identity, read_profile_identity

        baseline = Path(args.baseline)
        compare = Path(args.compare)
        base_folder = npu_source(baseline)
        comp_folder = npu_source(compare)
        gpu = None
        if base_folder is not None and comp_folder is not None:
            detail = compare_npus(compare, baseline)
        elif comp_folder is not None:
            gpu = gpu_file(baseline)
            if gpu is None:
                raise ValueError(
                    f"未识别到 {baseline} 的 GPU trace；混合对比的 A 侧需要 "
                    "*.pt.trace.json 或只含一个 rank trace 的目录"
                )
            detail = compare_gpu(compare, gpu)
        elif base_folder is not None:
            raise ValueError("混合对比需要按顺序传入 A（GPU trace 基准）和 B（NPU 对比）。")
        else:
            raise ValueError(
                "两侧都不是可识别的单卡 NPU profiler 主库/文本导出，也不是 GPU trace；"
                "集群多卡请用 cluster-compare"
            )
        detail["identity"] = comparison_identity(
            read_profile_identity(baseline, base_folder, gpu),
            read_profile_identity(compare, comp_folder, None),
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"prof-compare 失败：{exc}", file=sys.stderr)
        return 1
    if not isinstance(detail, dict):
        print("prof-compare 失败：上游没有返回结果对象", file=sys.stderr)
        return 1
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(detail, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "mode": detail.get("mode"),
                "device_rows": len(detail.get("device") or []),
                "host_rows": len(detail.get("host") or []),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
