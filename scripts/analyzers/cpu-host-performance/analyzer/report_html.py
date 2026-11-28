# -*- coding: utf-8 -*-
"""report_html.py — 单文件离线 HTML 报告渲染 (仅标准库, 全中文, 深色专业风格, inline SVG)
由 report.generate_reports 调用:
    render_html(m, diag, svg_bar_chart_fn, svg_line_chart_fn, esc_fn, sev_color, sev_cn, status_cn)
"""
import re
from .diagnosis import THRESHOLDS
from .npu_report import affinity_html, binding_html
from .report_explanation import collection_integrity_html, explanations_html, fmt
from .report_tables import enhance_long_tables, table_script
from .report_findings import diagnosis_overview
from .report_sections import core_table, environment_section, resource_section
from .core_balance import render_core_balance


def _cs_limit(n_cpus):
    """全机上下文切换率判定上限: THRESHOLDS['cs_rate_high'] (单核基线) × 核数"""
    return THRESHOLDS["cs_rate_high"] * max(n_cpus or 1, 1)


_CSS = """
:root{--bg:#0d1117;--panel:#161b22;--panel2:#1c2129;--border:#2d3742;--txt:#c9d1d9;
--muted:#8b949e;--blue:#4a9eff;--red:#d64545;--orange:#d98f00;--green:#2e9e5b;--gray:#6b7280}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font-family:"Segoe UI","PingFang SC","Microsoft YaHei",
"Noto Sans CJK SC",sans-serif;font-size:14px;line-height:1.7;padding:0 0 60px}
.wrap{max-width:1120px;margin:0 auto;padding:0 24px}
header{background:linear-gradient(135deg,#10161f,#141d2a);border-bottom:1px solid var(--border);
padding:26px 0 18px;margin-bottom:22px}
h1{font-size:22px;font-weight:600;letter-spacing:.5px}
.meta{color:var(--muted);font-size:12.5px;margin-top:6px}
h2{font-size:17px;font-weight:600;margin:34px 0 12px;padding-left:10px;
border-left:3px solid var(--blue)}
h3{font-size:14.5px;font-weight:600;margin:16px 0 8px;color:#dce3ea}
p{margin:6px 0}
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:16px 18px;margin:12px 0}
.diagnosis-item h4{margin:0 0 6px;font-size:14.5px;color:#dce3ea}
.diagnosis-item b{color:#dce3ea}
.diagnosis-status{display:inline-block;color:#abd2ff;background:#1b2d42;border-radius:4px;
font-size:12px;padding:1px 6px;margin-right:5px}
.diagnosis-critical{color:#ffb1b1;background:#442324}
.diagnosis-warning{color:#ffda92;background:#3c2b17}
.diagnosis-item{overflow-wrap:anywhere}
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
table{display:block;max-width:100%;overflow-x:auto}p,li{overflow-wrap:anywhere}
.wrap,.card,.finding,.numa-group,.npu-card{min-width:0;max-width:100%}
th{background:var(--panel2);color:var(--muted);text-align:left;padding:7px 10px;
border:1px solid var(--border);font-weight:600;white-space:nowrap}
td{padding:7px 10px;border:1px solid var(--border);vertical-align:top;overflow-wrap:normal;word-break:normal;min-width:4.5em}
td.num,th.num{text-align:right;font-family:Consolas,monospace}
.evt{background:var(--panel2);border-radius:6px;padding:2px 6px;font-family:Consolas,monospace;font-size:12.5px}
.chart{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:14px;margin:12px 0;overflow-x:auto}
.legend{font-size:12px;color:var(--muted);margin:6px 0 2px}
.note{color:var(--muted);font-size:12.5px}
.warn-box{background:#2a2110;border:1px solid #6b5410;border-radius:8px;padding:10px 14px;margin:10px 0;font-size:13px}
ol.pri{margin:8px 0 0 22px}ol.pri li{margin:5px 0}
.footer{color:var(--muted);font-size:12px;margin-top:40px;text-align:center}
.numa-group{margin:16px 0;background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px}
.numa-title{font-size:16px;font-weight:650;margin-bottom:12px;color:#e6edf3}
.numa-title span{font-size:12px;font-weight:400;color:var(--muted);margin-left:10px}
.npu-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:12px}
.npu-card{min-width:0;border:1px solid var(--border);border-top:3px solid var(--orange);border-radius:9px;background:var(--bg);padding:14px}
.npu-card.good{border-top-color:var(--green)}.npu-card.danger{border-top-color:var(--red)}
.npu-heading{display:flex;gap:8px;justify-content:space-between;align-items:start;flex-wrap:wrap}
.aff-state{font-size:11px;padding:2px 7px;border-radius:12px;background:#342a15;color:#efc36a}
.good .aff-state{background:#143224;color:#6dd69a}.danger .aff-state{background:#3a2025;color:#f39a9a}
.npu-process{margin:12px 0;font-size:14px}.npu-process strong{margin-left:8px;color:#e6edf3}
.npu-process small{display:block;color:var(--muted);font-size:11px;margin-top:3px}
.npu-process-entry{margin-top:10px}.npu-process-entry+.npu-process-entry{border-top:1px solid var(--border);padding-top:12px}
.numa-verdict{font-size:12px;color:#f39a9a;margin:8px 0}.numa-verdict.local-numa{color:#6dd69a}
.numa-verdict.unknown-numa{color:#efc36a}
.aff-line{display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;font-size:12px;margin:6px 0}
.aff-line span{color:var(--muted)}code{font-family:Consolas,monospace;overflow-wrap:anywhere}
pre{white-space:pre;overflow:auto;background:#090e15;border:1px solid var(--border);border-radius:8px;padding:16px;font-size:12px;line-height:1.6;margin:10px 0}
.code-panel{position:relative;padding-top:30px}.copy-code{position:absolute;right:0;top:0;background:#1c3252;border:1px solid #315379;border-radius:6px;color:#a9d1ff;padding:4px 10px;cursor:pointer}
.code-panel pre{max-height:440px}
@media(max-width:700px){.npu-grid{grid-template-columns:1fr}.wrap{padding:0 12px}}
@media print{body{background:#fff;color:#111}.card,.kpi,.finding,.chart,.status-hero{border-color:#ccc}}

.data-details{margin:12px 0;border:1px solid var(--border);border-radius:8px;background:var(--panel)}
.data-details>summary{cursor:pointer;padding:10px 12px;color:#a9d1ff;font-weight:600}
.data-details[open]>summary{border-bottom:1px solid var(--border)}
.table-tools{display:flex;flex-wrap:wrap;align-items:center;gap:12px;padding:10px;font-size:12px}
.table-tools input,.table-tools select,.table-tools button{background:#182333;color:#dce3ea;border:1px solid #40516a;border-radius:5px;padding:6px;max-width:100%}
.table-tools input{min-width:170px}.table-tools select{max-width:190px}
.data-details table{margin:0}.data-details tbody tr[hidden]{display:none!important}
.data-details .core-table-scroll{max-height:650px;overflow:auto}
@media print{.table-tools{display:none}.data-details{break-inside:avoid}}

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
@media print{body{padding-left:0}header{margin-left:0;padding-left:0}nav#toc{display:none}table{display:table;table-layout:fixed;font-size:8px;overflow:visible}th,td{white-space:normal;word-break:break-word}.core-table-scroll{overflow:visible}.chart{break-inside:avoid}#core-balance svg{min-width:0}}
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
function copyBinding(button){
var text=button.parentNode.querySelector('code').textContent;
function done(){button.textContent='已复制';setTimeout(function(){button.textContent='复制执行命令'},1800)}
function fallback(){var a=document.createElement('textarea');a.value=text;document.body.appendChild(a);a.select();
try{if(document.execCommand('copy'))done();else button.textContent='请手动选择代码复制'}finally{a.remove()}}
if(navigator.clipboard&&window.isSecureContext)navigator.clipboard.writeText(text).then(done,fallback);else fallback();
}
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
    if m.get("metadata",{}).get("data_origin")=="SYNTHETIC_TEST_DATA":
        A("<div class='warn-box'><b>合成测试数据 / SYNTHETIC TEST DATA</b>：此报告用于功能验证，不代表真实Kunpeng/Ascend服务器测量。</div>")
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
    A(_kpi(fmt(irq.get("total_ratio"),"%"), "硬中断总占比", (irq.get('max_cpu_ratio') or 0)>=15))
    soft = m.get("softirq", {})
    A(_kpi(fmt(soft.get("total_ratio"),"%"), "软中断总占比", (soft.get('max_cpu_ratio') or 0)>=20))
    A("</div>")
    p = diag.get("primary")
    resource_types = {'CPU_RESOURCE_PRESSURE','MEMORY_PRESSURE','DISK_CAPACITY','IO_PRESSURE','CGROUP_RESOURCE_LIMIT'}
    resource_types.update(r['type'] for r in m.get('resources', {}).get('risks', []))
    primary_resource = bool(p and p['type'] in resource_types)
    A(diagnosis_overview(m, diag, sev_cn, primary_resource))
    A(collection_integrity_html(m.get("collection_integrity", {})))
    if m.get("warnings"):
        A("<div class='warn-box'>⚠ <b>数据告警</b>：%s</div>" % esc("；".join(m["warnings"])))
    # ---------- 2. 证据总表 ----------
    A("<h2>2. 问题证据总表与根因判断</h2>")
    A("<h3>2.1 关键指标证据与解释</h3>")
    A(explanations_html(m,diag))
    # ---------- 2.2 根因 ----------
    A("<h3>2.2 根因判断与证据链</h3>")
    if p and not primary_resource:
        A("<div class='card'><p><span class='lbl'>现象</span> → %s</p>" % esc(p["title"]))
        A("<p><span class='lbl'>证据</span> → %s</p>" % esc(
            "；".join("%s=%s（阈值 %s）" % (e["metric"], e["value"], e["threshold"]) for e in p["evidence"])))
        A("<p><span class='lbl'>推断</span> → %s</p>" % esc(p["possible_root_cause"]))
        A("<p><span class='lbl'>候选判断</span> → <span class='evt'>%s</span>（%s）</p></div>" % (
            esc(p["type"]), esc(p.get("explanation", ""))))
    elif primary_resource:
        A("<p>机器资源可能限制性能；<a href='#sec-4'>详见第4节</a>。</p>")
    else:
        A("<p>未发现需要根因判断的问题。</p>")
    A(affinity_html(m.get("npu_affinity", {}), m.get("collection_integrity", {})))
    # ---------- 3. 建议 ----------
    A("<h2>3. 优化建议</h2>")
    A(binding_html(m.get("npu_affinity", {}), m.get("collection_integrity", {}),
                   m.get("binding_plan", {}), rankings=m.get("ai_rankings"), product=m.get("product_identity")))
    # ---------- 4. 总体状态 ----------
    A("<h2>4. 机器资源与 CPU 总体状态</h2>")
    A(resource_section(m, True))
    # ---------- 5. Core Balance ----------
    A("<h2>5. CPU Core Balance（各核心负载）</h2>")
    A(render_core_balance(m))
    A(core_table(m,True))
    A("<h2>6. 采集环境与软件栈</h2>")
    A(environment_section(m.get("environment", {})))
    A("<div class='footer'>HostBound 性能诊断 Skill 生成 ｜ 仅标准库渲染，可离线打开</div>")
    A("</div></body></html>")
    return _inject_toc(enhance_long_tables("\n".join(L))).replace("</body>", table_script()+"</body>", 1)

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

def _now():
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S")
