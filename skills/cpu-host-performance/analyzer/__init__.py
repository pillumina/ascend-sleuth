# -*- coding: utf-8 -*-
"""analyzer — CPU Host 性能分析包（解析 / 指标 / 诊断 / 报告 / CLI 入口）

模块职责：
- parser            多格式输入解析（tar.gz / zip / 目录 / ftrace 文本 / trace-cmd / Chrome JSON）
- metrics           指标计算 + 中文指标释义表
- diagnosis         13 类诊断规则引擎（组合判断 + 置信度）
- report            Markdown 报告 + inline SVG 图表
- report_html       单文件离线 HTML 报告渲染
- analyze_cpu_trace CLI 入口（run_analysis / main）

用法（在 Skill 根目录执行）：
  python3 -m analyzer analyze <trace> [-o 输出目录]
  python3 analyzer/analyze_cpu_trace.py <trace> [-o 输出目录]   # 任意目录均可
"""
__version__ = "1.0.0"
__all__ = ["parser", "metrics", "diagnosis", "report", "report_html", "analyze_cpu_trace"]
