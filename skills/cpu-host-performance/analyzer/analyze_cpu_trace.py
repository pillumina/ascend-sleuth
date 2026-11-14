# -*- coding: utf-8 -*-
"""analyze_cpu_trace.py — CPU Host 性能分析命令行入口

用法（任选其一）：
  python3 -m analyzer analyze <trace> [-o 输出目录]            # 在 Skill 根目录执行
  python3 analyzer/analyze_cpu_trace.py <trace> [-o 输出目录]  # 任意目录均可

支持输入：
  - 采集脚本产物 cpu_trace_*.tar.gz
  - 同结构 zip 压缩包
  - 解包后的目录
  - 裸 ftrace 文本（trace_pipe / per_cpu trace 文件）
  - trace-cmd report 文本
  - Chrome/Perfetto JSON (traceEvents)

输出：<输出目录>/report.md 与 hostbound_report.html（固定名称、单文件离线 HTML、全中文）。
仅依赖 Python 标准库。
"""
import argparse
import os
import sys
import time

if __package__ in (None, ""):  # 直接以脚本运行
    # 本文件位于 <Skill根>/analyzer/ 下, 向上两级即 Skill 根; 加入 sys.path 后
    # 按包名 analyzer 绝对导入 —— 包名与外层目录名解耦, 外层目录改名不受影响
    _PKG_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _PKG_PARENT not in sys.path:
        sys.path.insert(0, _PKG_PARENT)
    from analyzer.parser import load_input, cleanup_temp
    from analyzer.metrics import compute_metrics
    from analyzer.diagnosis import diagnose
    from analyzer.report import generate_reports
else:  # 以包模块运行 (python -m analyzer)
    from .parser import load_input, cleanup_temp
    from .metrics import compute_metrics
    from .diagnosis import diagnose
    from .report import generate_reports


def run_analysis(input_path, out_dir=None, quiet=False):
    """执行完整分析流程，返回 (diag, out_dir)。"""
    input_path = os.path.abspath(input_path)
    if not os.path.exists(input_path):
        raise FileNotFoundError("输入不存在：%s" % input_path)
    if out_dir is None:
        base = os.path.dirname(input_path) or "."
        out_dir = os.path.join(base, "cpu_analysis_" + time.strftime("%Y%m%d_%H%M%S"))
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    def say(msg):
        if not quiet:
            print(msg)

    say("[1/4] 解析 trace：%s" % input_path)
    td = load_input(input_path)
    try:
        if not td.events:
            raise ValueError(
                "未能从输入中解析出任何事件。当前识别格式：%s。"
                "支持的格式：采集脚本 tar.gz/zip、解包目录、裸 ftrace 文本、"
                "trace-cmd 文本、Chrome/Perfetto JSON；Perfetto protobuf 二进制请先用"
                " trace_processor 导出 JSON 后重试。" % (td.format_name or "未知"))
        say("      格式：%s ｜ 事件 %s 条 ｜ 数据告警 %d 项" % (
            td.format_name, format(len(td.events), ","), len(td.warnings)))

        say("[2/4] 计算指标 ...")
        m = compute_metrics(td)

        say("[3/4] 诊断分析（13 类规则 + 组合判断）...")
        diag = diagnose(m)

        say("[4/4] 生成报告 ...")
        md_path, html_path = generate_reports(m, diag, out_dir)
        say("")
        say("Host 状态：%s" % diag["host_status"])
        p = diag.get("primary")
        say("核心问题：%s" % (p["title"] if p else "未发现明显问题"))
        say("")
        say("报告已生成：")
        say("  Markdown: %s" % md_path)
        say("  HTML    : %s" % html_path)
        return diag, out_dir
    finally:
        cleanup_temp(td)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="analyzer",
        description="CPU Host 性能分析：解析 ftrace/trace-cmd/Perfetto JSON 等多格式 trace，"
                    "输出全中文 Markdown + 离线 HTML 诊断报告（仅标准库）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python3 -m analyzer analyze cpu_trace_20240101_120000.tar.gz\n"
               "  python3 -m analyzer analyze trace.txt -o ./out\n")
    ap.add_argument("command", nargs="?", default="analyze", choices=["analyze"],
                    help="子命令（当前仅支持 analyze，可省略）")
    ap.add_argument("trace", help="trace 输入路径（tar.gz/zip/目录/文本/JSON）")
    ap.add_argument("-o", "--output-dir", default=None,
                    help="报告输出目录（默认：输入同目录下 cpu_analysis_时间戳/）")
    ap.add_argument("-q", "--quiet", action="store_true", help="静默模式，仅输出错误")
    args = ap.parse_args(argv)
    try:
        run_analysis(args.trace, args.output_dir, args.quiet)
        return 0
    except FileNotFoundError as e:
        print("错误：%s" % e, file=sys.stderr)
        return 2
    except ValueError as e:
        print("错误：%s" % e, file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
