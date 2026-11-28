# -*- coding: utf-8 -*-
"""report.py — HTML / JSON / 绑核脚本输出与 inline SVG 图表工具
HTML 渲染见 report_html.py
"""
import os
import io
import json
from .report_html import render_html
from hostbind.delivery import write_delivery

SEV_COLOR = {"CRITICAL": "#d64545", "WARNING": "#d98f00", "INFO": "#6b7280", "OK": "#2e9e5b"}
SEV_CN = {"CRITICAL": "严重", "WARNING": "警告", "INFO": "提示", "OK": "健康"}
STATUS_CN = {"CRITICAL": "CRITICAL（严重异常）", "WARNING": "WARNING（存在风险）",
             "DEGRADED": "DEGRADED（部分受限）", "HEALTHY": "HEALTHY（健康）",
             "UNKNOWN": "UNKNOWN（无法判定）"}

# ================================================================
# SVG 图表工具
# ================================================================
def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#x27;"))

def svg_bar_chart(items, width=760, bar_h=16, gap=6, unit="%", color="#4a9eff", fmt=None):
    """横向条形图: items=[(label, value, color?)]"""
    if not items:
        return "<svg width='%d' height='40'><text x='10' y='25' fill='#888'>无数据</text></svg>" % width
    maxv = max(v for _l, v, *_ in items) or 1.0
    label_w = 110
    val_w = 90
    plot_w = width - label_w - val_w - 10
    h = len(items) * (bar_h + gap) + 10
    parts = ["<svg xmlns='http://www.w3.org/2000/svg' width='%d' height='%d' font-family='sans-serif'>" % (width, h)]
    y = 5
    for it in items:
        label, v = it[0], it[1]
        c = it[2] if len(it) > 2 and it[2] else color
        w = max(plot_w * float(v) / maxv, 1.5) if maxv else 1
        parts.append("<text x='0' y='%d' font-size='11' fill='#c9d1d9' text-anchor='start'>%s</text>"
                     % (y + bar_h - 3, _esc(label)[:14]))
        parts.append("<rect x='%d' y='%d' width='%d' height='%d' rx='3' fill='%s'/>"
                     % (label_w, y, plot_w, bar_h, "#22303c"))
        parts.append("<rect x='%d' y='%d' width='%.1f' height='%d' rx='3' fill='%s'/>"
                     % (label_w, y, w, bar_h, c))
        txt = fmt(v) if fmt else ("%.1f%s" % (v, unit))
        parts.append("<text x='%d' y='%d' font-size='11' fill='#c9d1d9'>%s</text>"
                     % (width - 2, y + bar_h - 3, _esc(txt)))
        y += bar_h + gap
    parts.append("</svg>")
    return "".join(parts)

def svg_line_chart(series, width=760, height=200, y_max=None, y_label="%"):
    """折线图: series=[(name, color, [values]), ...] values 可含 None (断点)"""
    n = max(len(s[2]) for s in series) if series else 0
    if n == 0:
        return "<svg width='%d' height='40'><text x='10' y='25' fill='#888'>无数据</text></svg>" % width
    pad_l, pad_b, pad_t = 46, 22, 10
    plot_w, plot_h = width - pad_l - 10, height - pad_b - pad_t
    gmax = y_max
    if gmax is None:
        vals = [v for _n, _c, arr in series for v in arr if v is not None]
        gmax = max(vals) if vals else 1.0
        gmax = gmax * 1.15 or 1.0
    parts = ["<svg xmlns='http://www.w3.org/2000/svg' width='%d' height='%d' font-family='sans-serif'>" % (width, height)]
    # 网格与 Y 轴刻度
    for i in range(5):
        fy = pad_t + plot_h * i / 4.0
        yv = gmax * (1 - i / 4.0)
        parts.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#22303c' stroke-width='1'/>"
                     % (pad_l, fy, pad_l + plot_w, fy))
        parts.append("<text x='%d' y='%.1f' font-size='10' fill='#8b949e' text-anchor='end'>%.1f</text>"
                     % (pad_l - 4, fy + 3, yv))
    x0 = pad_l
    for name, color, arr in series:
        pts = []
        for i, v in enumerate(arr):
            if v is None:
                continue
            px = x0 + plot_w * i / max(n - 1, 1)
            py = pad_t + plot_h * (1 - min(float(v) / gmax, 1.0))
            pts.append("%.1f,%.1f" % (px, py))
        if len(pts) >= 2:
            parts.append("<polyline points='%s' fill='none' stroke='%s' stroke-width='1.6'/>" % (" ".join(pts), color))
        elif pts:
            x, y = pts[0].split(",")
            parts.append("<circle cx='%s' cy='%s' r='2' fill='%s'/>" % (x, y, color))
    # X 轴时间刻度 (首/中/尾)
    for i, lab in ((0, "0"), (n // 2, "50%"), (n - 1, "100%")):
        px = x0 + plot_w * i / max(n - 1, 1)
        parts.append("<text x='%.1f' y='%d' font-size='10' fill='#8b949e' text-anchor='middle'>%s</text>"
                     % (px, height - 6, lab))
    parts.append("<text x='%d' y='%.1f' font-size='10' fill='#8b949e' text-anchor='end'>%s</text>"
                 % (pad_l - 4, pad_t - 2, y_label))
    parts.append("</svg>")
    return "".join(parts)

def generate_reports(m, diag, out_dir):
    """HTML and JSON are generated directly; Markdown is not an intermediate."""
    os.makedirs(out_dir, exist_ok=True)
    html = render_html(m, diag, svg_bar_chart, svg_line_chart, _esc, SEV_COLOR, SEV_CN, STATUS_CN)
    html_path = os.path.join(out_dir, 'hostbound_report.html')
    with io.open(html_path, 'w', encoding='utf-8') as stream:
        stream.write(html)
    with io.open(os.path.join(out_dir, 'report_data.json'), 'w', encoding='utf-8') as stream:
        json.dump({'schema_version':2,'units':{'time':'s','latency':'ms','frequency':'MHz','ratio':'percent','rate':'events/s'},'metrics':m,'diagnosis':diag},stream,ensure_ascii=False,indent=2,allow_nan=False,default=lambda x:sorted(x) if isinstance(x,set) else str(x))
    write_delivery(out_dir, m.get('binding_plan', {}).get('design', {'custom_bind': []}))
    # Retire only the generated preview if this directory was used by an older release.
    legacy = os.path.join(out_dir, 'bind_cpu.sh')
    if os.path.isfile(legacy):
        with io.open(legacy, encoding='utf-8', errors='replace') as stream:
            header = [stream.readline().rstrip() for _ in range(3)]
        if header == ['#!/usr/bin/env bash', 'set -euo pipefail',
                      '# 默认只读预检/预览；执行与回滚委托给带 journal 的闭环入口。']:
            os.remove(legacy)
    # Remove only a recognizable report from this generator when reusing an old output directory.
    old_md = os.path.join(out_dir, 'report.md')
    if os.path.isfile(old_md):
        with io.open(old_md, encoding='utf-8', errors='replace') as stream:
            owned = stream.readline().strip() == '# HostBound 性能诊断报告'
        if owned:
            os.remove(old_md)
    return html_path
