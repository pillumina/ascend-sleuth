# -*- coding: utf-8 -*-
"""report_html.py — 单文件离线 HTML 报告渲染 (仅标准库, 全中文, 深色专业风格, inline SVG)
由 report.generate_reports 调用:
    render_html(m, diag, svg_bar_chart_fn, svg_line_chart_fn, esc_fn, sev_color, sev_cn, status_cn)
"""
import io
import re
from .metrics import METRIC_EXPLANATIONS, EVENT_EXPLANATIONS, _explain_irq_name, freq_to_mhz, _pid_disp
from .diagnosis import THRESHOLDS


def _cs_limit(n_cpus):
    """全机上下文切换率判定上限: THRESHOLDS['cs_rate_high'] (单核基线) × 核数"""
    return THRESHOLDS["cs_rate_high"] * max(n_cpus or 1, 1)


_CSS = """
:root{--bg:#0d1117;--panel:#161b22;--panel2:#1c2129;--border:#2d3742;--txt:#c9d1d9;
--muted:#8b949e;--blue:#4a9eff;--red:#d64545;--orange:#d98f00;--green:#2e9e5b;--gray:#6b7280}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font-family:"Segoe UI","PingFang SC","Microsoft YaHei",
"Noto Sans CJK SC",sans-serif;font-size:14px;line-height:1.7;padding:0 0 60px}
.wrap{max-width:900px;margin:0 auto;padding:0 20px}
header{background:linear-gradient(135deg,#10161f,#141d2a);border-bottom:1px solid var(--border);
padding:26px 0 18px;margin-bottom:22px}
h1{font-size:22px;font-weight:600;letter-spacing:.5px}
.meta{color:var(--muted);font-size:12.5px;margin-top:6px}
h2{font-size:17px;font-weight:600;margin:34px 0 12px;padding-left:10px;
border-left:3px solid var(--blue)}
h3{font-size:14.5px;font-weight:600;margin:16px 0 8px;color:#dce3ea}
p{margin:6px 0}
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:16px 18px;margin:12px 0}
.kpis{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}
.kpi{flex:1 1 130px;min-width:130px;background:var(--panel);border:1px solid var(--border);
border-radius:10px;padding:12px 14px}
.kpi .v{font-size:22px;font-weight:600;font-family:Consolas,monospace}
.kpi .n{font-size:12px;color:var(--muted);margin-top:2px}
.badge{display:inline-block;padding:3px 12px;border-radius:20px;font-size:12.5px;font-weight:600;color:#fff}
.status-hero{background:var(--panel);border:1px solid var(--border);border-radius:12px;
padding:20px 22px;margin:16px 0}
.status-hero .big{font-size:26px;font-weight:700;margin:4px 0 10px}
table{width:100%;border-collapse:collapse;margin:8px 0;font-size:13px}
th{background:var(--panel2);color:var(--muted);text-align:left;padding:7px 10px;
border:1px solid var(--border);font-weight:600;white-space:nowrap}
td{padding:7px 10px;border:1px solid var(--border);vertical-align:top}
td.num,th.num{text-align:right;font-family:Consolas,monospace}
.finding{background:var(--panel);border:1px solid var(--border);border-left:4px solid var(--gray);
border-radius:8px;padding:14px 18px;margin:12px 0}
.finding h3{margin:0 0 8px}
.finding .tagline{font-size:12px;color:var(--muted);margin-bottom:8px}
.finding .lbl{color:var(--muted)}
.finding ol{margin:4px 0 0 22px}
.finding li{margin:3px 0}
.evt{background:var(--panel2);border-radius:6px;padding:2px 6px;font-family:Consolas,monospace;font-size:12.5px}
.chart{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:14px;margin:12px 0;overflow-x:auto}
.legend{font-size:12px;color:var(--muted);margin:6px 0 2px}
.note{color:var(--muted);font-size:12.5px}
.warn-box{background:#2a2110;border:1px solid #6b5410;border-radius:8px;padding:10px 14px;margin:10px 0;font-size:13px}
ol.pri{margin:8px 0 0 22px}ol.pri li{margin:5px 0}
.footer{color:var(--muted);font-size:12px;margin-top:40px;text-align:center}
@media print{body{background:#fff;color:#111}.card,.kpi,.finding,.chart,.status-hero{border-color:#ccc}}
/* ---- 左侧固定导航目录 ---- */
:root{--tocpad:216px}
html{scroll-behavior:smooth}
body{padding-left:var(--tocpad)}
h2{scroll-margin-top:14px}
header{margin-left:calc(-1 * var(--tocpad));padding-left:var(--tocpad)}
nav#toc{position:fixed;left:0;top:0;bottom:0;width:200px;overflow-y:auto;z-index:99;
background:#0a0f16;border-right:1px solid var(--border);padding:18px 10px}
nav#toc .toc-title{color:var(--muted);font-size:12px;font-weight:600;letter-spacing:2px;
padding:0 8px 10px;border-bottom:1px solid var(--border);margin-bottom:8px}
nav#toc a{display:block;color:#9aa7b4;text-decoration:none;font-size:12.8px;
padding:6px 8px;border-radius:6px;line-height:1.45}
nav#toc a:hover{background:#161f2c;color:#e6edf3}
nav#toc a.active{background:#1c3252;color:#4a9eff}
nav#toc .toc-foot{color:#4a5568;font-size:10.5px;padding:12px 8px 0;margin-top:10px;
border-top:1px solid var(--border)}
@media (max-width:1024px){body{padding-left:0}header{margin-left:0;padding-left:0}nav#toc{display:none}}
@media print{body{padding-left:0}header{margin-left:0;padding-left:0}nav#toc{display:none}}
"""

_SPY_JS = """
<script>
(function(){
var links=[].slice.call(document.querySelectorAll('nav#toc a'));
var secs=links.map(function(a){return document.getElementById(a.getAttribute('data-sec'))});
function upd(){
  var y=window.scrollY+90,cur=0;
  for(var i=0;i<secs.length;i++){if(secs[i]&&secs[i].offsetTop<=y)cur=i;}
  links.forEach(function(a,i){a.className=(i===cur)?'active':'';});
}
window.addEventListener('scroll',upd,{passive:true});
window.addEventListener('resize',upd);upd();
})();
</script>
"""

_H2_RE = re.compile(r"<h2>(\d+)\.\s*([^<]*)</h2>")

def _inject_toc(html):
    """为各节 <h2> 注入锚点 id, 在 body 开头插入固定左侧导航目录, 末尾追加滚动高亮脚本。

    导航为纯 CSS/原生 JS 实现, 保持单文件离线零依赖; 窄屏与打印时自动隐藏。
    """
    entries = []

    def _repl(m):
        num, title = m.group(1), m.group(2).strip()
        entries.append((num, title))
        return "<h2 id='sec-%s'>%s. %s</h2>" % (num, num, title)

    html = _H2_RE.sub(_repl, html)
    if not entries:
        return html
    items = "".join(
        "<a href='#sec-%s' data-sec='sec-%s'>%s. %s</a>" % (n, n, n, t)
        for n, t in entries)
    nav = ("<nav id='toc'><div class='toc-title'>报告目录</div>%s"
           "<div class='toc-foot'>cpu-host-performance</div></nav>" % items)
    html = html.replace("<body>", "<body>" + nav, 1)
    html = html.replace("</body>", _SPY_JS + "</body>", 1)
    return html

def render_html(m, diag, bar_fn, line_fn, esc, sev_color, sev_cn, status_cn):
    st = diag["stats"]
    L = []
    A = L.append
    A("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    A("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    A("<title>HostBound 性能诊断报告</title><style>%s</style></head><body>" % _CSS)
    # ---------- 头部 ----------
    A("<header><div class='wrap'><h1>HostBound 性能诊断报告</h1>")
    A("<div class='meta'>数据格式：%s ｜ 采集时长：%.1f 秒 ｜ 核心数：%d ｜ 分析时间：%s</div></div></header>"
      % (esc(m.get("format_name", "-")), st["duration"], st["n_cpus"], _now()))
    A("<div class='wrap'>")
    # ---------- 1. 摘要：状态 + KPI ----------
    A("<h2>1. Executive Summary（结论摘要）</h2>")
    sc = sev_color.get(diag["host_status"], "#6b7280")
    A("<div class='status-hero'><div class='lbl'>Host 健康状态</div>")
    A("<div class='big' style='color:%s'>%s</div></div>" % (sc, esc(status_cn.get(diag["host_status"], diag["host_status"]))))
    A("<div class='kpis'>")
    if st.get("avg_util") is not None:
        A(_kpi("%.1f%%" % st["avg_util"], "CPU 平均利用率", st["avg_util"] >= 90, 70))
    if st.get("max_util") is not None:
        A(_kpi("%.1f%%" % st["max_util"], "单核最高利用率", st["max_util"] >= 90, 70))
    sch = m.get("sched", {})
    if sch.get("cs_rate") is not None:
        A(_kpi("%.0f/s" % sch["cs_rate"], "上下文切换率", sch["cs_rate"] > _cs_limit(st["n_cpus"])))
    if sch.get("lat_p99") is not None:
        A(_kpi("%.2f ms" % sch["lat_p99"], "调度延迟 P99", sch["lat_p99"] >= 20, 5))
    irq = m.get("irq", {})
    A(_kpi("%.2f%%" % irq.get("total_ratio", 0), "硬中断总占比",
           max([pc.get("irq_ratio", 0) for pc in m["per_cpu"].values()] or [0]) >= 15))
    soft = m.get("softirq", {})
    A(_kpi("%.2f%%" % soft.get("total_ratio", 0), "软中断总占比",
           max([pc.get("softirq_ratio", 0) for pc in m["per_cpu"].values()] or [0]) >= 20))
    A("</div>")
    p = diag.get("primary")
    if p:
        A("<div class='card' style='border-left:4px solid %s'>" % sev_color.get(p["severity"], "#6b7280"))
        A("<h3>核心问题：%s</h3>" % esc(p["title"]))
        A("<p><span class='lbl'>置信度：</span><span class='evt'>%s</span> ｜ <span class='lbl'>类别：</span>"
          "<span class='evt'>%s</span></p>" % (esc(p["confidence"]), esc(p["type"])))
        A("<p><span class='lbl'>影响：</span>%s</p>" % esc(p["impact"]))
        A("<p class='lbl' style='margin-top:10px'>解决方案（按优先级）：</p><ol class='pri'>")
        for r in p["recommendation"][:5]:
            A("<li>%s</li>" % esc(r))
        A("</ol></div>")
    else:
        A("<div class='card'><p>未发现明显的 CPU Host 侧问题。若业务性能仍异常，建议从 NPU/IO/框架侧继续排查。</p></div>")
    if m.get("warnings"):
        A("<div class='warn-box'>⚠ <b>数据告警</b>：%s</div>" % esc("；".join(m["warnings"])))
    # ---------- 2. 证据总表 ----------
    A("<h2>2. 问题证据总表</h2>")
    A("<table><tr><th>指标</th><th class='num'>当前值</th><th>基线/阈值</th><th>状态</th></tr>")
    if st.get("avg_util") is not None:
        A(_row("CPU 平均利用率", "%.1f%%" % st["avg_util"], "&lt;70% 健康",
               "偏高" if st["avg_util"] >= 70 else "正常", st["avg_util"] >= 70))
    if st.get("max_util") is not None:
        A(_row("单核最高利用率", "%.1f%%" % st["max_util"], "&lt;90% 健康",
               "饱和" if st["max_util"] >= 90 else "正常", st["max_util"] >= 90))
    if sch.get("cs_rate") is not None:
        A(_row("上下文切换率", "%.0f 次/秒" % sch["cs_rate"],
               "全机 &gt; %.0f×核数/s 偏高" % THRESHOLDS["cs_rate_high"],
               "偏高" if sch["cs_rate"] > _cs_limit(st["n_cpus"]) else "正常",
               sch["cs_rate"] > _cs_limit(st["n_cpus"])))
    if sch.get("lat_p99") is not None:
        A(_row("调度延迟 P99", "%.2f ms" % sch["lat_p99"], "≥5ms 警告 / ≥20ms 严重",
               "异常" if sch["lat_p99"] >= 5 else "正常", sch["lat_p99"] >= 5))
    else:
        A(_row("调度延迟 P99", "无法计算", "-", "数据缺失", False))
    A(_row("硬中断总占比", "%.2f%%" % irq.get("total_ratio", 0), "单核≥15% 关注热点",
           "关注" if max([pc.get("irq_ratio", 0) for pc in m["per_cpu"].values()] or [0]) >= 15 else "正常", False))
    A(_row("软中断总占比", "%.2f%%" % soft.get("total_ratio", 0), "单核≥20% 关注热点",
           "关注" if max([pc.get("softirq_ratio", 0) for pc in m["per_cpu"].values()] or [0]) >= 20 else "正常", False))
    A("</table><p class='note'>指标含义见第 14 节「指标与事件说明」。</p>")
    # ---------- 3. 问题详情 ----------
    A("<h2>3. 问题详情</h2>")
    if diag["findings"]:
        for f in diag["findings"]:
            A(_finding_html(f, esc, sev_color, sev_cn))
    else:
        A("<p>未发现问题。</p>")
    # ---------- 4. 总体状态 ----------
    A("<h2>4. CPU 总体状态</h2>")
    ps = m.get("proc_stat") or {}
    if ps:
        A("<div class='card'><p>/proc/stat 快照（开机以来累计）：user %.1f%%、system %.1f%%、iowait %.1f%%、"
          "irq %.1f%%、softirq %.1f%%、idle %.1f%%、steal %.1f%%。</p>" % (
              ps.get("user", 0), ps.get("system", 0), ps.get("iowait", 0),
              ps.get("irq", 0), ps.get("softirq", 0), ps.get("idle", 0), ps.get("steal", 0)))
        A("<p class='note'>注意：trace 只能区分 busy/idle；user/system/iowait 为开机累计值，仅供参考。</p></div>")
    else:
        A("<p>无 /proc/stat 快照，总体占用以 trace 计算为准。</p>")
    # ---------- 5. Core Balance ----------
    A("<h2>5. CPU Core Balance（各核心负载）</h2>")
    A("<div class='chart'>")
    if m["per_cpu"]:
        _known = [(c, pc) for c, pc in sorted(m["per_cpu"].items(), key=lambda kv: int(str(kv[0])) if str(kv[0]).isdigit() else 0)
                  if pc.get("util_known", True)]
        items = [("CPU %s" % c, pc["util"],
                  "#d64545" if pc["util"] >= 90 else ("#d98f00" if pc["util"] >= 70 else "#4a9eff"))
                 for c, pc in _known][:64]
        if items:
            A(bar_fn(items, fmt=lambda v: "%.1f%%" % v))
        n_unk = len(m["per_cpu"]) - len(_known)
        if n_unk:
            A("<p class='note'>%d 个核心无 idle 证据（静默核），利用率记为 N/A。</p>" % n_unk)
    A("</div>")
    A("<table><tr><th>核心</th><th class='num'>利用率</th><th class='num'>空闲比</th>"
      "<th class='num'>上下文切换/s</th><th class='num'>硬中断占比</th><th class='num'>软中断占比</th></tr>")
    for c in sorted(m["per_cpu"].keys()):
        pc = m["per_cpu"][c]
        _k = pc.get("util_known", True)
        util_s = ("%.1f%%" % pc["util"]) if _k else "N/A"
        idle_s = ("%.1f%%" % pc["idle_ratio"]) if _k else "N/A"
        A("<tr><td class='evt'>CPU %s</td><td class='num'>%s</td><td class='num'>%s</td>"
          "<td class='num'>%.0f</td><td class='num'>%.1f%%</td><td class='num'>%.1f%%</td></tr>"
          % (esc(c), util_s, idle_s, pc["cs_rate"], pc["irq_ratio"], pc["softirq_ratio"]))
    A("</table>")
    known_pcs = {c: pc for c, pc in m["per_cpu"].items() if pc.get("util_known", True)}
    hot = max(known_pcs.items(), key=lambda kv: kv[1]["util"]) if known_pcs else (None, None)
    if hot[1]:
        cold = min(known_pcs.items(), key=lambda kv: kv[1]["util"])
        A("<p>最高负载：%s（%.1f%%），最低：%s（%.1f%%）。%s</p>" % (
            esc(hot[0]), hot[1]["util"], esc(cold[0]), cold[1]["util"],
            "<b style='color:#d98f00'>存在明显不均衡，详见问题详情。</b>"
            if hot[1]["util"] - cold[1]["util"] >= 40 else "负载分布尚可。"))
    # ---------- 6. Scheduler ----------
    A("<h2>6. Scheduler 调度分析</h2>")
    A("<div class='card'>")
    A("<p>上下文切换总计 <b>%s</b> 次（%.0f 次/秒）%s</p>" % (
        format(sch.get("cs_total", 0), ","), sch.get("cs_rate", 0) or 0,
        "— 上下文切换率过高会增加调度开销，任务碎片化明显。"
        if (sch.get("cs_rate") or 0) > _cs_limit(st["n_cpus"]) else ""))
    A("<p>唤醒总计 <b>%s</b> 次（%.0f 次/秒）— 唤醒率反映任务碎片化程度。</p>" % (
        format(sch.get("wakeup_total", 0), ","), sch.get("wakeup_rate", 0) or 0))
    if sch.get("lat_avg") is not None:
        A("<p>调度延迟：平均 %.3f ms，P50 %.3f ms，P95 %.2f ms，P99 %.2f ms，最大 %.2f ms（共 %s 次可配对样本）。</p>" % (
            sch["lat_avg"], sch["lat_p50"], sch["lat_p95"], sch["lat_p99"], sch["lat_max"],
            format(sch["lat_count"], ",")))
        A("<p class='note'>调度延迟含义：%s</p>" % esc(METRIC_EXPLANATIONS["sched_latency"]))
    else:
        A("<p>调度延迟：%s</p>" % esc(sch.get("lat_note") or "无数据。"))
    if sch.get("runnable_avg") is not None:
        A("<p>平均可运行任务数 %.1f — %s</p>" % (sch["runnable_avg"], esc(METRIC_EXPLANATIONS["runnable_avg"])))
    A("</div>")
    if sch.get("top_lat_tasks"):
        A("<table><tr><th>任务</th><th class='num'>最大延迟 ms</th><th class='num'>平均 ms</th><th class='num'>次数</th></tr>")
        for pid, comm, mx, avg, n in sch["top_lat_tasks"]:
            A("<tr><td>%s</td><td class='num'>%.2f</td><td class='num'>%.3f</td><td class='num'>%d</td></tr>"
              % (esc(_pid_disp(comm, pid)), mx * 1000, avg * 1000, n))
        A("</table>")
    # ---------- 7. IRQ / SoftIRQ ----------
    A("<h2>7. IRQ / SoftIRQ 分析</h2>")
    A("<h3>7.1 硬中断</h3>")
    A("<p>硬中断总 CPU 占比 <b>%.2f%%</b>（%s 次）。</p>" % (irq.get("total_ratio", 0), format(irq.get("total_count", 0), ",")))
    if irq.get("top_names"):
        A("<table><tr><th>中断源</th><th class='num'>次数</th><th class='num'>累计耗时 ms</th><th>说明</th></tr>")
        for n, cnt, t in irq["top_names"]:
            A("<tr><td class='evt'>%s</td><td class='num'>%s</td><td class='num'>%.1f</td><td>%s</td></tr>"
              % (esc(n), format(cnt, ","), t * 1000, esc(_explain_irq_name(n))))
        A("</table>")
    A("<h3>7.2 软中断</h3>")
    A("<p>软中断总 CPU 占比 <b>%.2f%%</b>（%s 次）。</p>" % (soft.get("total_ratio", 0), format(soft.get("total_count", 0), ",")))
    if soft.get("top_actions"):
        A("<table><tr><th>软中断类型</th><th class='num'>次数</th><th class='num'>累计耗时 ms</th><th>说明</th></tr>")
        for n, cnt, t in soft["top_actions"]:
            A("<tr><td class='evt'>%s</td><td class='num'>%s</td><td class='num'>%.1f</td><td>%s</td></tr>"
              % (esc(n), format(cnt, ","), t * 1000,
                 esc(EVENT_EXPLANATIONS.get(n, "未收录软中断类型，参考内核文档。"))))
        A("</table>")
    A("<p class='note'>各核中断分布见第 5 节表格与上方图表。</p>")
    # ---------- 8. Freq / Idle ----------
    A("<h2>8. CPU Frequency / Idle 分析</h2>")
    freq = m.get("freq", {})
    if freq.get("available"):
        rows = sorted(freq["per_cpu"].items())
        if rows:
            A("<table><tr><th>核心</th><th class='num'>最低 MHz</th><th class='num'>平均 MHz</th>"
              "<th class='num'>最高 MHz</th><th class='num'>低频样本占比</th></tr>")
            for c, fv in rows[:32]:
                A("<tr><td class='evt'>CPU %s</td><td class='num'>%.0f</td><td class='num'>%.0f</td>"
                  "<td class='num'>%.0f</td><td class='num'>%.0f%%</td></tr>" % (
                      esc(c), freq_to_mhz(fv["min"]), freq_to_mhz(fv["avg"]),
                      freq_to_mhz(fv["max"]), fv["low_ratio"]))
            A("</table>")
        A("<p>governor：%s。</p>" % esc(m.get("governor") or "快照未提供"))
        A("<p class='note'>频率单位由 trace 原始值换算（常见 kHz/Hz，已自动识别）；仅凭 trace 不判定硬件故障。</p>")
    else:
        A("<p>trace 中无 cpu_frequency 事件，频率分析不可用（Available: Unavailable）。</p>")
    idle = m.get("idle", {})
    if idle.get("available"):
        avgs = idle.get("per_cpu_ratio") or {}
        if avgs:
            A("<p>各核空闲占比：平均 %.1f%%，最高 %.1f%%（%s），最低 %.1f%%（%s）。%s</p>" % (
                sum(avgs.values()) / len(avgs), max(avgs.values()), esc(max(avgs, key=avgs.get)),
                min(avgs.values()), esc(min(avgs, key=avgs.get)),
                "多数核心大量空闲，负载分布问题见问题详情。" if (sum(avgs.values()) / len(avgs)) >= 70 else ""))
    else:
        A("<p>trace 中无 cpu_idle 事件，空闲比基于 swapper 任务近似。</p>")
    # ---------- 9. Task ----------
    A("<h2>9. Task / Thread 分析</h2>")
    tk = m.get("tasks", {})
    if tk.get("top_runtime"):
        A("<table><tr><th>Top 运行时间任务</th><th class='num'>累计运行 ms</th><th>说明</th></tr>")
        for pid, comm, v in tk["top_runtime"]:
            from .metrics import _explain_task
            A("<tr><td>%s</td><td class='num'>%.0f</td><td>%s</td></tr>" % (
                esc(_pid_disp(comm, pid)), v * 1000, esc(_explain_task(comm or "") or "普通任务")))
        A("</table>")
    if tk.get("top_cs"):
        A("<table><tr><th>Top 切出次数任务</th><th class='num'>次数</th></tr>")
        for pid, comm, v in tk["top_cs"]:
            A("<tr><td>%s</td><td class='num'>%s</td></tr>" % (
                esc(_pid_disp(comm, pid)), format(v, ",")))
        A("</table>")
    if tk.get("top_wakeup"):
        A("<table><tr><th>Top 被唤醒任务</th><th class='num'>次数</th></tr>")
        for comm, n in tk["top_wakeup"]:
            A("<tr><td>%s</td><td class='num'>%s</td></tr>" % (esc(comm or "?"), format(n, ",")))
        A("</table>")
    if tk.get("top_migration"):
        A("<table><tr><th>Top 迁移任务</th><th class='num'>次数</th></tr>")
        for pid, comm, n in tk["top_migration"]:
            A("<tr><td>%s</td><td class='num'>%d</td></tr>" % (esc(_pid_disp(comm, pid)), n))
        A("</table>")
    # ---------- 10. Affinity / NUMA ----------
    A("<h2>10. Affinity / NUMA 分析</h2>")
    numa_txt = (m.get("snapshot", {}) or {}).get("numa.txt", "")
    if numa_txt and "node" in numa_txt:
        nn = numa_txt.count("== /sys/devices/system/node/node") if "== " in numa_txt else None
        A("<p>快照包含 NUMA 拓扑信息（%s 个节点可见）。</p>" % (nn if nn else "多"))
    if tk.get("top_runtime"):
        A("<p>Top 任务运行分布与各核利用率见第 5 节；任务集中在少数核时可结合绑核配置判断。</p>")
    A("<p class='note'><b>证据说明</b>：当前 trace 未包含跨 NUMA 访问的直接证据，NUMA 结论置信度为低"
      "（Evidence insufficient），如需精确判断请补充 <span class='evt'>numactl -H</span> 与 "
      "<span class='evt'>numastat</span> 快照。</p>")
    # ---------- 11. 时间窗口 ----------
    A("<h2>11. 时间窗口分析</h2>")
    A(_time_window_html(m, esc))
    # ---------- 12. 根因 ----------
    A("<h2>12. 根因判断</h2>")
    if p:
        A("<div class='card'><p><span class='lbl'>现象</span> → %s</p>" % esc(p["title"]))
        A("<p><span class='lbl'>证据</span> → %s</p>" % esc(
            "；".join("%s=%s（阈值 %s）" % (e["metric"], e["value"], e["threshold"]) for e in p["evidence"])))
        A("<p><span class='lbl'>推断</span> → %s</p>" % esc(p["possible_root_cause"]))
        A("<p><span class='lbl'>根因</span> → <span class='evt'>%s</span>（%s）</p></div>" % (
            esc(p["type"]), esc(p.get("explanation", ""))))
    else:
        A("<p>未发现需要根因判断的问题。</p>")
    # ---------- 13. 建议 ----------
    A("<h2>13. 优化建议</h2>")
    pri = {"CRITICAL": "P0（立即处理）", "WARNING": "P1（尽快处理）", "INFO": "P2（择机处理）", "OK": "—"}
    shown = False
    for f in diag["findings"]:
        if f["severity"] in ("INFO", "OK"):
            continue
        shown = True
        A("<div class='finding' style='border-left-color:%s'>" % sev_color.get(f["severity"], "#6b7280"))
        A("<h3>%s — %s</h3><ol class='pri'>" % (pri[f["severity"]], esc(f["title"])))
        for r in f["recommendation"]:
            A("<li>%s</li>" % esc(r))
        A("</ol></div>")
    if not shown:
        A("<p>当前无需紧急优化动作；保持对 NPU 侧性能的持续观察即可。</p>")
    # ---------- 14. 数据说明与指标解释 ----------
    A("<h2>14. 数据说明与指标解释</h2>")
    A("<h3>数据概况</h3><div class='card'>")
    A("<p>trace 时间范围：%.3f ~ %.3f（相对秒），时长 %.1f 秒</p>" % (m.get("t_start", 0), m.get("t_end", 0), st["duration"]))
    A("<p>CPU 数量（参与统计）：%d；报告核数（nproc）：%s</p>" % (st["n_cpus"], esc(m.get("n_cpus_report") or "-")))
    A("<p>内核版本：%s ｜ 主机名：%s</p>" % (
        esc(m["metadata"].get("kernel", "未知")), esc(m["metadata"].get("hostname", "未知"))))
    A("<p>可用事件：%s</p>" % esc(", ".join(sorted(m.get("available", [])) or ["无"])))
    A("<p>解析统计：总行 %s，成功 %s，失败 %s（失败行已自动跳过）</p>" % (
        format(m["parse_stats"]["total"], ","), format(m["parse_stats"]["parsed"], ","),
        format(m["parse_stats"]["failed"], ",")))
    A("<p>buffer 溢出：%s</p></div>" % esc(m.get("buffer_overrun") or "0（未检测到溢出）"))
    A("<h3>分析限制</h3><div class='card'><ul style='margin-left:20px'>"
      "<li>trace 仅覆盖采集窗口，不代表长期行为。</li>"
      "<li>利用率基于 idle 事件/swapper 近似；user/system 区分依赖 /proc/stat（开机累计）。</li>"
      "<li>调度延迟为 wakeup→switch 配对估算；中断耗时为 entry→exit 配对。</li>"
      "<li>频率单位自动换算可能存在平台差异，仅作相对比较。</li></ul></div>")
    A("<h3>指标解释（每个指标是什么）</h3>")
    A("<table><tr><th>指标</th><th>解释</th></tr>")
    for k, v in METRIC_EXPLANATIONS.items():
        A("<tr><td class='evt'>%s</td><td>%s</td></tr>" % (esc(k), esc(v)))
    A("</table>")
    A("<h3>事件/术语解释</h3>")
    A("<table><tr><th>术语</th><th>解释</th></tr>")
    for k, v in EVENT_EXPLANATIONS.items():
        A("<tr><td class='evt'>%s</td><td>%s</td></tr>" % (esc(k), esc(v)))
    A("</table>")
    # ---------- 图表：时间序列 ----------
    ts = m.get("timeseries") or {}
    util = ts.get("util") or []
    if util:
        A("<h2>附录图 1：利用率 / 中断占比时间序列</h2><div class='chart'>")
        A("<div class='legend'><span style='color:#4a9eff'>■</span> CPU 利用率　"
          "<span style='color:#d98f00'>■</span> 硬中断占比　"
          "<span style='color:#2e9e5b'>■</span> 软中断占比</div>")
        A(line_fn([("util", "#4a9eff", util),
                   ("irq", "#d98f00", ts.get("irq_ratio") or []),
                   ("softirq", "#2e9e5b", ts.get("softirq_ratio") or [])],
                  y_max=100, y_label="%"))
        A("</div>")
        lat = ts.get("lat_p99") or []
        if any(v is not None for v in lat):
            A("<h2>附录图 2：调度延迟 P99 时间序列</h2><div class='chart'>")
            A("<div class='legend'><span style='color:#d64545'>■</span> 调度延迟 P99 (ms)</div>")
            A(line_fn([("lat_p99", "#d64545", lat)], y_label="ms"))
            A("</div>")
    A("<div class='footer'>HostBound 性能诊断 Skill 生成 ｜ 仅标准库渲染，可离线打开</div>")
    A("</div></body></html>")
    return _inject_toc("\n".join(L))

# ---------- 小工具 ----------
def _kpi(value, name, bad=False, warn_level=None):
    color = "#d64545" if bad else ("#d98f00" if warn_level is not None and value_bad(value, warn_level) else "#c9d1d9")
    return "<div class='kpi'><div class='v' style='color:%s'>%s</div><div class='n'>%s</div></div>" % (color, value, name)

def value_bad(v, level):
    """判断 KPI 是否达到 warn 阈值。
    v 可为数值，或带单位/百分号的格式化字符串（如 "12.3%"、"8.50 ms"、"1234/s"）：
    去掉 % 与单位后缀，取前导数字比较；解析失败视为未超标。"""
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return v >= level
    s = str(v).strip().rstrip("%")
    m = re.match(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", s)
    if not m:
        return False
    try:
        return float(m.group()) >= level
    except Exception:
        return False

def _row(name, value, threshold, status, warn):
    color = "#d98f00" if warn else "#2e9e5b"
    return ("<tr><td>%s</td><td class='num'>%s</td><td>%s</td>"
            "<td style='color:%s;font-weight:600'>%s</td></tr>" % (name, value, threshold, color, status))

def _finding_html(f, esc, sev_color, sev_cn):
    color = sev_color.get(f["severity"], "#6b7280")
    parts = ["<div class='finding' style='border-left-color:%s'>" % color]
    parts.append("<h3>%s <span class='badge' style='background:%s'>%s</span> "
                 "<span class='evt'>置信度 %s</span></h3>" % (
                     esc(f["title"]), color, esc(sev_cn.get(f["severity"], f["severity"])), esc(f["confidence"])))
    parts.append("<div class='tagline'>类别：<span class='evt'>%s</span> — %s</div>" % (
        esc(f["type"]), esc(f.get("explanation", ""))))
    parts.append("<p><span class='lbl'>证据：</span></p><table><tr><th>指标</th><th>当前值</th><th>判定阈值</th></tr>")
    for e in f["evidence"]:
        parts.append("<tr><td class='evt'>%s</td><td><b>%s</b></td><td>%s</td></tr>" % (
            esc(e["metric"]), esc(e["value"]), esc(e["threshold"])))
    parts.append("</table>")
    parts.append("<p><span class='lbl'>影响：</span>%s</p>" % esc(f["impact"]))
    parts.append("<p><span class='lbl'>可能根因：</span>%s</p>" % esc(f["possible_root_cause"]))
    parts.append("<p class='lbl'>建议措施：</p><ol class='pri'>")
    for r in f["recommendation"]:
        parts.append("<li>%s</li>" % esc(r))
    parts.append("</ol></div>")
    return "".join(parts)

def _time_window_html(m, esc):
    ts = m.get("timeseries") or {}
    util = ts.get("util") or []
    if not util:
        return "<p>时间序列数据不足，无法进行时间窗口分析。</p>"
    b = ts.get("bucket_sec", 1)
    vals = [(i, v) for i, v in enumerate(util) if v is not None]
    if not vals:
        return "<p>时间序列数据不足，无法进行时间窗口分析。</p>"
    top3 = sorted(sorted(vals, key=lambda x: -x[1])[:3])
    parts = ["<p>以下为利用率最高的时间窗口（桶 = %.2f 秒）：</p><ul style='margin-left:22px'>" % b]
    cs = ts.get("cs_rate") or []
    lat = ts.get("lat_p99") or []
    soft = ts.get("softirq_ratio") or []
    for i, v in top3:
        seg = "窗口 %.1f~%.1f 秒：利用率峰值 <b>%.1f%%</b>" % (i * b, (i + 1) * b, v)
        extra = []
        if cs:
            extra.append("上下文切换 %.0f 次/秒" % cs[i])
        if soft:
            extra.append("软中断占比 %.1f%%" % soft[i])
        if lat and lat[i] is not None:
            extra.append("调度延迟 P99 %.2f ms" % lat[i])
        if extra:
            seg += "，同期 " + "、".join(extra)
        parts.append("<li>%s</li>" % seg)
    parts.append("</ul>")
    parts.append("<p class='note'>若峰值窗口内同步出现中断/调度延迟上升，可建立「负载升高 → 中断增加 → 调度延迟上升 → "
                 "worker 运行时间下降 → NPU 等待 Host」的关联链；仅当上述同期证据存在时成立。</p>")
    return "".join(parts)

def _now():
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S")
