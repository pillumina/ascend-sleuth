#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_bmc_report.py — 基于 parse_bmc_collect.py 生成的 JSON，生成精美 HTML 报告。

两套模板：
- 单机分析模板 build_single_report(): 左侧固定导航，分析先行（判定卡 + 关键指标
  速览 + 置顶问题清单），随后逐维度详细展开（身份版本/告警/指示灯/电源/CPU内存/
  NPU与ECC/光模块/温度风扇/RAID/网络/BMC系统与环境/利用率/SEL/日志OS）。
- 多机对比模板 build_cluster_report(): 分析先行（集群总结论 + 判定对比表 +
  问题分布 + 健康分），随后逐维度横向对比矩阵 + 每台机器详情区块。

用法：
  python generate_bmc_report.py <json1> [json2 ...] -o <out.html>
  或传入一个 all_machines_bmc.json（自动识别多机并走集群模板）
"""

import argparse
import html
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# 前端样式（深色/现代/专业）
# ---------------------------------------------------------------------------
CSS = """
/* ================= 深空控制台 Deep-Space Console ================= */
:root{
  --bg:#090D15; --panel:#0F1524; --panel2:#141C30; --panel3:#182238;
  --line:rgba(122,144,183,.13); --line2:rgba(122,144,183,.26);
  --txt:#E7EEF9; --mut:#8494B0; --dim:#5A6A88;
  --acc:#2DD4BF; --acc2:#22B8A6;
  --ok:#34D399; --warn:#FBBF24; --bad:#F87171; --info:#60A5FA;
  --p0:#F87171; --p1:#FBBF24; --p2:#FDE047; --p3:#94A3B8;
  --mono:'JetBrains Mono','Cascadia Code',Consolas,'Courier New',monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{
  font-family:'Segoe UI Variable','Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;
  background:var(--bg);color:var(--txt);font-size:14px;line-height:1.65;overflow-x:hidden;
  background-image:
    radial-gradient(1100px 520px at 78% -8%, rgba(45,212,191,.075), transparent 62%),
    radial-gradient(900px 460px at -10% 105%, rgba(96,165,250,.055), transparent 60%),
    repeating-linear-gradient(0deg, transparent 0 47px, rgba(122,144,183,.045) 47px 48px),
    repeating-linear-gradient(90deg, transparent 0 47px, rgba(122,144,183,.045) 47px 48px);
  background-attachment:fixed;
}
/* ---------- 侧边导航 ---------- */
.layout{display:flex;min-height:100vh;align-items:flex-start}
nav{width:248px;position:fixed;top:0;left:0;bottom:0;overflow-y:auto;
  background:linear-gradient(180deg,rgba(15,21,36,.92),rgba(11,16,28,.92));
  border-right:1px solid var(--line);backdrop-filter:blur(8px);padding:22px 14px;z-index:50}
.brand{display:flex;align-items:center;gap:10px;padding:2px 8px 20px}
.brand .sig{width:30px;height:30px;border-radius:8px;flex:none;
  background:linear-gradient(135deg,var(--acc),#0EA5E9);display:flex;align-items:center;justify-content:center;
  font-weight:800;font-size:13px;color:#04201C;box-shadow:0 0 18px rgba(45,212,191,.4)}
.brand b{font-size:14.5px;letter-spacing:.4px}
.brand small{display:block;font-size:10.5px;color:var(--dim);letter-spacing:1.5px}
nav .grp{font-size:10.5px;color:var(--dim);letter-spacing:2px;padding:16px 10px 6px}
nav a{display:flex;align-items:center;gap:9px;color:var(--mut);text-decoration:none;
  padding:7.5px 10px;border-radius:8px;font-size:13px;margin:1px 0;border-left:2px solid transparent;transition:.15s;word-break:break-all}
nav a .ic{width:16px;text-align:center;opacity:.75;font-size:12px}
nav a:hover{background:rgba(122,144,183,.08);color:var(--txt)}
nav a.active{background:linear-gradient(90deg,rgba(45,212,191,.14),transparent);
  color:#A7F3EB;border-left-color:var(--acc)}
nav a .cnt{margin-left:auto;font-family:var(--mono);font-size:10.5px;color:#FCD34D}
nav .foot{margin-top:22px;padding:12px 10px;border-top:1px dashed var(--line2);font-size:11px;color:var(--dim)}
main{margin-left:248px;padding:30px 40px 90px;max-width:1320px;min-width:0;width:calc(100% - 248px)}
main .content-wrap{max-width:1280px;margin:0 auto}
/* ---------- 顶部识别条 ---------- */
.crumb{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:12.5px;color:var(--mut);margin-bottom:14px}
.crumb .chip{font-family:var(--mono);font-size:11.5px;background:var(--panel);border:1px solid var(--line);
  border-radius:6px;padding:3px 9px;color:var(--txt)}
.crumb .chip .k{color:var(--dim);margin-right:6px;font-family:inherit}
/* ---------- 判定 HERO ---------- */
.hero{display:grid;grid-template-columns:1fr 210px;gap:18px;margin-bottom:20px}
.verdict{background:linear-gradient(135deg,rgba(45,212,191,.09),rgba(15,21,36,.6) 55%);
  border:1px solid rgba(45,212,191,.28);border-radius:16px;padding:22px 26px;position:relative;overflow:hidden}
.verdict::before{content:'';position:absolute;inset:0 0 auto 0;height:2px;
  background:linear-gradient(90deg,transparent,var(--acc),transparent);opacity:.7}
.verdict.v-ok{border-color:rgba(52,211,153,.3);
  background:linear-gradient(135deg,rgba(52,211,153,.09),rgba(15,21,36,.6) 55%)}
.verdict.v-ok::before{background:linear-gradient(90deg,transparent,var(--ok),transparent)}
.verdict.v-bad{border-color:rgba(248,113,113,.3);
  background:linear-gradient(135deg,rgba(248,113,113,.09),rgba(15,21,36,.6) 55%)}
.verdict.v-bad::before{background:linear-gradient(90deg,transparent,var(--bad),transparent)}
.v-row{display:flex;align-items:center;gap:14px}
.v-dot{width:14px;height:14px;border-radius:50%;background:var(--warn);flex:none;
  box-shadow:0 0 0 4px rgba(251,191,36,.15),0 0 16px rgba(251,191,36,.6);animation:pulse 2.2s infinite}
.v-ok .v-dot{background:var(--ok);animation-name:pulseOk}
.v-bad .v-dot{background:var(--bad);animation-name:pulseBad}
@keyframes pulse{0%,100%{box-shadow:0 0 0 4px rgba(251,191,36,.12),0 0 12px rgba(251,191,36,.5)}
  50%{box-shadow:0 0 0 7px rgba(251,191,36,.06),0 0 22px rgba(251,191,36,.75)}}
@keyframes pulseOk{0%,100%{box-shadow:0 0 0 4px rgba(52,211,153,.12),0 0 12px rgba(52,211,153,.5)}
  50%{box-shadow:0 0 0 7px rgba(52,211,153,.06),0 0 22px rgba(52,211,153,.75)}}
@keyframes pulseBad{0%,100%{box-shadow:0 0 0 4px rgba(248,113,113,.12),0 0 12px rgba(248,113,113,.5)}
  50%{box-shadow:0 0 0 7px rgba(248,113,113,.06),0 0 22px rgba(248,113,113,.75)}}
.v-txt{font-size:23px;font-weight:700;letter-spacing:.3px}
.v-txt em{font-style:normal;color:var(--warn)}
.v-ok .v-txt em{color:var(--ok)} .v-bad .v-txt em{color:var(--bad)}
.v-sub{color:var(--mut);font-size:13px;margin-top:5px}
.v-sub b{color:#FCD34D;font-weight:600}
/* 维度健康带 */
.dim-strip{margin-top:16px;display:grid;grid-template-columns:repeat(10,1fr);gap:6px}
.dim{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:8px 6px 7px;text-align:center}
.dim .bar{height:5px;border-radius:3px;background:rgba(122,144,183,.15);overflow:hidden;margin-bottom:6px}
.dim .bar i{display:block;height:100%;border-radius:3px}
.dim .n{font-size:10.5px;color:var(--mut);letter-spacing:.3px;white-space:nowrap}
.dim.ok .bar i{background:linear-gradient(90deg,#0EA371,var(--ok))}
.dim.warn .bar i{background:linear-gradient(90deg,#D97706,var(--warn))}
.dim.bad .bar i{background:linear-gradient(90deg,#DC2626,var(--bad))}
/* 健康分环 */
.score{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px;
  display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}
.score .num{font-family:var(--mono);font-size:44px;font-weight:700;line-height:1;color:var(--acc);
  text-shadow:0 0 24px rgba(45,212,191,.35)}
.score .num small{font-size:16px;color:var(--dim);font-weight:400}
.score .lb{font-size:12px;color:var(--mut);margin-top:8px;letter-spacing:2px}
.score .hint{font-size:11.5px;color:var(--dim);margin-top:10px;line-height:1.5}
/* ---------- KPI ---------- */
.kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:26px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:14px 15px;position:relative}
.kpi:hover{border-color:var(--line2)}
.kpi .l{font-size:11.5px;color:var(--mut);letter-spacing:.5px;margin-bottom:7px}
.kpi .v{font-family:var(--mono);font-size:22px;font-weight:600;letter-spacing:.3px}
.kpi .v small{font-size:12px;color:var(--dim);font-weight:400;margin-left:2px}
.kpi .st{position:absolute;top:13px;right:13px;width:8px;height:8px;border-radius:50%;background:var(--dim);opacity:.45}
.kpi.ok .st{background:var(--ok);opacity:1;box-shadow:0 0 10px rgba(52,211,153,.7)}
.kpi.warn .st{background:var(--warn);opacity:1;box-shadow:0 0 10px rgba(251,191,36,.7)}
.kpi.bad .st{background:var(--bad);opacity:1;box-shadow:0 0 10px rgba(248,113,113,.7)}
/* ---------- 区块标题 ---------- */
h1{font-size:24px;margin-bottom:6px}
h2.sec{display:flex;align-items:center;gap:12px;font-size:17px;font-weight:700;margin:38px 0 16px;letter-spacing:.5px}
h2.sec .no{font-family:var(--mono);font-size:12px;color:var(--acc);border:1px solid rgba(45,212,191,.35);
  border-radius:6px;padding:2px 8px;background:rgba(45,212,191,.07)}
h2.sec::after{content:'';flex:1;height:1px;background:linear-gradient(90deg,var(--line2),transparent)}
h2.sec .src{font-size:11px;color:var(--dim);font-family:var(--mono);font-weight:400;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
h3{font-size:14px;font-weight:600;margin:0 0 6px;color:var(--txt)}
h3.collapsible{margin-bottom:10px}
.section{scroll-margin-top:20px}
/* ---------- 问题卡 ---------- */
.issues{display:flex;flex-direction:column;gap:10px}
.issue{display:grid;grid-template-columns:64px 1fr auto;gap:14px;align-items:start;
  background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 18px;position:relative;overflow:hidden}
.issue::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px}
.issue.lv-p0::before{background:var(--p0)}
.issue.lv-p1::before{background:var(--p1)}
.issue.lv-p2::before{background:var(--p2)}
.issue.lv-p3::before{background:var(--p3)}
.lv{font-family:var(--mono);font-weight:700;font-size:12px;border-radius:7px;text-align:center;padding:6px 0;height:fit-content;letter-spacing:1px}
.lv-p0{color:#FCA5A5;background:rgba(248,113,113,.1);border:1px solid rgba(248,113,113,.35)}
.lv-p1{color:#FCD34D;background:rgba(251,191,36,.1);border:1px solid rgba(251,191,36,.35)}
.lv-p2{color:#FDE047;background:rgba(253,224,71,.07);border:1px solid rgba(234,179,8,.3)}
.lv-p3{color:#B7C3D8;background:rgba(148,163,184,.09);border:1px solid rgba(148,163,184,.28)}
.issue .t{font-weight:600;font-size:14px}
.issue .d{color:var(--mut);font-size:12.8px;margin-top:3px}
.evi{display:inline-flex;align-items:center;gap:6px;margin-top:8px;font-family:var(--mono);font-size:11px;
  color:#9DB2D6;background:rgba(9,13,21,.65);border:1px solid var(--line);border-radius:6px;padding:4px 10px}
.evi::before{content:'▣';color:var(--acc);font-size:10px}
.issue .act{font-size:12.5px;color:#A7F3EB;background:rgba(45,212,191,.06);border:1px dashed rgba(45,212,191,.3);
  border-radius:8px;padding:8px 12px;margin-top:10px}
.issue .act b{color:var(--acc);font-weight:600;margin-right:6px}
.issue .dim-tag{font-family:var(--mono);font-size:11px;color:var(--dim);border:1px solid var(--line);
  border-radius:6px;padding:3px 8px;white-space:nowrap;height:fit-content}
/* ---------- 卡片与表格 ---------- */
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px 22px;margin-bottom:14px;overflow-x:auto}
.card h3{font-size:14px}
.card .note{font-size:11.5px;color:var(--dim);margin-bottom:14px}
.card-body{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:14px;margin-top:12px}
.sub{color:var(--mut);font-size:13px;margin-bottom:14px}
.grid{display:grid;gap:12px}
.grid-2{grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.grid-3{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.grid-4{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.card .table-scroll{overflow-x:auto}
.overflow-table-wrap{overflow-x:auto;max-width:100%}
table{width:100%;border-collapse:collapse;font-size:13px;min-width:0}
table th{font-size:11px;letter-spacing:1.2px;color:var(--dim);text-align:left;font-weight:600;
  padding:8px 12px;border-bottom:1px solid var(--line2);white-space:nowrap;background:transparent}
tbody td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:middle}
tbody tr:last-child td{border-bottom:none}
tbody tr{transition:.12s}
tbody tr:hover{background:rgba(122,144,183,.05)}
td.mono{font-family:var(--mono);font-size:12.5px}
.mono{font-family:var(--mono);font-size:12.5px}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:600;border-radius:20px;
  padding:2.5px 10px;border:1px solid var(--line2);white-space:nowrap}
.pill i{width:6px;height:6px;border-radius:50%;display:inline-block;background:var(--dim)}
.pill.ok{color:#86EFAC;background:rgba(52,211,153,.1);border-color:rgba(52,211,153,.3)}
.pill.ok i{background:var(--ok)}
.pill.warn{color:#FCD34D;background:rgba(251,191,36,.09);border-color:rgba(251,191,36,.3)}
.pill.warn i{background:var(--warn)}
.pill.bad,.pill.p0{color:#FCA5A5;background:rgba(248,113,113,.1);border-color:rgba(248,113,113,.3)}
.pill.bad i,.pill.p0 i{background:var(--bad)}
.pill.p1{color:#FCD34D;background:rgba(251,191,36,.09);border-color:rgba(251,191,36,.3)}
.pill.p1 i{background:var(--warn)}
.pill.p2{color:#FDE047;background:rgba(253,224,71,.07);border-color:rgba(234,179,8,.3)}
.pill.p2 i{background:var(--p2)}
.pill.info,.pill.p3{color:#93C5FD;background:rgba(96,165,250,.1);border-color:rgba(96,165,250,.3)}
.pill.info i,.pill.p3 i{background:var(--info)}
/* 旧标记样式兼容（level_tag 生成 .tag p0/p1/...） */
.tag{display:inline-flex;align-items:center;gap:6px;padding:2.5px 10px;border-radius:20px;font-size:11px;
  font-weight:600;white-space:nowrap;border:1px solid var(--line2)}
.tag::before{content:'';width:6px;height:6px;border-radius:50%;background:currentColor;flex:none}
.tag.p0{color:#FCA5A5;background:rgba(248,113,113,.12);border-color:rgba(248,113,113,.35)}
.tag.p1{color:#FCD34D;background:rgba(251,191,36,.09);border-color:rgba(251,191,36,.3)}
.tag.p2{color:#FDE047;background:rgba(253,224,71,.07);border-color:rgba(234,179,8,.3)}
.tag.p3{color:#B7C3D8;background:rgba(148,163,184,.09);border-color:rgba(148,163,184,.28)}
.tag.ok{color:#86EFAC;background:rgba(52,211,153,.1);border-color:rgba(52,211,153,.3)}
.tag.info{color:#93C5FD;background:rgba(96,165,250,.1);border-color:rgba(96,165,250,.3)}
.ok{color:var(--ok)} .warn{color:var(--warn)} .bad{color:var(--bad)} .info{color:var(--info)}
.bar{height:10px;border-radius:6px;background:rgba(122,144,183,.15);overflow:hidden}
.bar>i{display:block;height:100%;border-radius:6px}
.badge{display:inline-block;padding:1px 8px;border-radius:12px;font-size:11px;background:var(--panel2);color:var(--mut);border:1px solid var(--line)}
pre{background:rgba(9,13,21,.7);border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto;
  font-size:12px;font-family:var(--mono);color:#9DB2D6;white-space:pre-wrap;word-break:break-word}
ul.plist{list-style:none}
ul.plist li{padding:9px 12px;border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:flex-start}
ul.plist li:last-child{border-bottom:none}
ul.plist .d{color:var(--txt)}
ul.plist .s{color:var(--mut);font-size:12px}
.hl{color:#FDE047}
/* ---------- NPU 瓦片 ---------- */
.npu-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:6px}
.npu{background:var(--panel2);border:1px solid var(--line);border-radius:11px;padding:13px 15px;position:relative}
.npu .id{font-family:var(--mono);font-size:11px;color:var(--dim);letter-spacing:1px}
.npu .pw{font-family:var(--mono);font-size:19px;font-weight:600;margin:5px 0 2px}
.npu .pw small{font-size:11px;color:var(--dim)}
.npu .ecc{font-family:var(--mono);font-size:11px;color:var(--mut);margin-top:3px}
.npu .ecc b{color:#86EFAC;font-weight:600}
.npu .corner{position:absolute;top:11px;right:12px;font-size:10px;font-family:var(--mono);color:var(--dim)}
.npu .corner.ok{color:var(--ok)}
.npu.hot{border-color:rgba(251,191,36,.35);background:linear-gradient(135deg,rgba(251,191,36,.05),var(--panel2) 60%)}
.npu.hot .corner{color:var(--warn)}
/* ---------- 图表 ---------- */
.chart-wrap{position:relative}
.chart-box{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:14px;margin-top:12px}
.chart-box .chart-title{font-size:13px;font-weight:600;margin-bottom:8px}
.chart-box .chart-sub{font-size:11px;color:var(--mut);margin-bottom:6px}
.chart-box svg{width:100%;height:auto;display:block}
.chart-legend{display:flex;gap:16px;flex-wrap:wrap;font-size:11.5px;color:var(--mut);margin-top:10px}
.chart-legend .lg{display:inline-flex;align-items:center;gap:6px}
.legend{display:flex;gap:18px;font-size:11.5px;color:var(--mut);margin-top:12px;flex-wrap:wrap}
.legend .li{display:inline-flex;align-items:center;gap:7px}
.chart-legend .sw,.legend .sw{width:16px;height:3px;border-radius:2px;display:inline-block}
/* ---------- 集群兼容 ---------- */
.cluster-strip{display:flex;align-items:center;gap:10px;padding:8px 0}
.cluster-strip .name{width:200px;font-size:12px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cmp-table td{vertical-align:top}
.diff-hi{color:#FDE047;font-weight:600}
.collapsible{cursor:pointer;user-select:none}
.collapsible::after{content:' ▾';opacity:.55;color:var(--dim)}
.collapsible.collapsed::after{content:' ▸';opacity:.55;color:var(--dim)}
/* ---------- 建议 ---------- */
.actions{background:linear-gradient(135deg,rgba(96,165,250,.07),var(--panel) 60%);
  border:1px solid rgba(96,165,250,.25);border-radius:14px;padding:20px 24px;margin-bottom:14px}
.actions h3{font-size:14.5px;margin-bottom:12px;color:#BFDBFE}
.actions ol{margin-left:18px;display:flex;flex-direction:column;gap:9px;font-size:13.5px}
.actions ol li::marker{color:var(--info);font-family:var(--mono);font-weight:700}
.actions .tag-hint{color:var(--dim);font-size:12px}
/* ---------- 滚动条 / 响应式 ---------- */
::-webkit-scrollbar{width:9px;height:9px}
::-webkit-scrollbar-thumb{background:#243050;border-radius:6px}
::-webkit-scrollbar-track{background:transparent}
@media (max-width:1150px){
  nav{width:210px}
  main{margin-left:210px;width:calc(100% - 210px);padding:24px 20px 70px}
  .kpis{grid-template-columns:repeat(3,1fr)!important}
  .npu-grid{grid-template-columns:repeat(2,1fr)!important}
}
@media (max-width:900px){
  .layout{display:block}
  nav{position:static;width:100%;height:auto;max-height:38vh;overflow-y:auto;
    border-right:none;border-bottom:1px solid var(--line)}
  main{margin-left:0;width:100%;padding:16px 12px 60px}
  .hero{grid-template-columns:1fr}
  .dim-strip{grid-template-columns:repeat(5,1fr)}
  .issue{grid-template-columns:52px 1fr}
}
@media print{nav{display:none}main{margin-left:0;width:100%}body{background-image:none}}
"""

JS = """
function onNav(){
  const secs=[...document.querySelectorAll('.section')];
  const navs=[...document.querySelectorAll('nav a[data-target]')];
  const off=130;
  let cur=secs[0]&&secs[0].id;
  for(const s of secs){ if(window.scrollY>=s.offsetTop-off) cur=s.id; }
  navs.forEach(a=>a.classList.toggle('active',a.dataset.target===cur));
}
window.addEventListener('scroll',onNav,{passive:true});
window.addEventListener('load',onNav);
document.addEventListener('click',(e)=>{
  const t=e.target.closest('.collapsible');
  if(t){ const body=document.getElementById(t.dataset.target);
    if(body){ const on=body.style.display!=='none'; body.style.display=on?'none':'block'; t.classList.toggle('collapsed',on);} }
});

/* ================= 折线图渲染（无外部依赖，SVG path） ================= */
function renderLineChart(canvasId, series, opts){
  /* series: [ {name, color, points:[[x,y],...]} , ... ]
     opts: {height, yLabel, xLabel, yMin, yMax} */
  const el=document.getElementById(canvasId);
  if(!el) return;
  const W = Math.max(el.clientWidth||780, 320);
  const H = (opts&&opts.height)||220;
  const padL=46, padR=16, padT=14, padB=30;
  let allX=[], allY=[];
  series.forEach(s=>(s.points||[]).forEach(p=>{allX.push(p[0]); allY.push(+(p[1]));}));
  if(!allX.length){ el.innerHTML='<div class="sub" style="padding:12px">无数据点</div>'; return; }
  allX.sort((a,b)=>a-b);
  const xMin=allX[0], xMax=allX[allX.length-1];
  let yMin=Math.min.apply(null,allY), yMax=Math.max.apply(null,allY);
  if(opts&&typeof opts.yMin==='number') yMin=opts.yMin;
  if(opts&&typeof opts.yMax==='number') yMax=opts.yMax;
  if(yMin===yMax){ yMin-=1; yMax+=1; }
  const spanY=yMax-yMin;
  yMin-=spanY*0.06; yMax+=spanY*0.06;
  const X=x=>padL+(x-xMin)/(xMax-xMin||1)*(W-padL-padR);
  const Y=y=>padT+(yMax-y)/(yMax-yMin)*(H-padT-padB);
  // 网格 + Y 轴刻度（5 段）
  let grid='', ticks='';
  for(let i=0;i<=5;i++){
    const gy=yMin+(yMax-yMin)*i/5;
    const yy=Y(gy);
    grid+=`<line x1="${padL}" y1="${yy}" x2="${W-padR}" y2="${yy}" stroke="rgba(122,144,183,.12)" stroke-width="0.7"/>`;
    ticks+=`<text x="${padL-6}" y="${yy+3}" fill="#5A6A88" font-size="9" text-anchor="end">${Math.round(gy)}</text>`;
  }
  // X 轴时间刻度（最多 7 个）—— unix 秒时按全局时间跨度均匀分布
  let xt='';
  if(xMax-xMin>1000000){ // unix 秒
    const nTicks=7;
    for(let i=0;i<nTicks;i++){
      const xv=xMin+(xMax-xMin)*i/(nTicks-1);
      const xx=X(xv);
      const dt=new Date(xv*1000);
      const lbl=(dt.getMonth()+1)+'/'+dt.getDate()+' '+('0'+dt.getHours()).slice(-2)+':'+('0'+dt.getMinutes()).slice(-2);
      xt+=`<text x="${xx}" y="${H-10}" fill="#5A6A88" font-size="8.5" text-anchor="middle">${lbl}</text>`;
      // 网格竖线
      xt+=`<line x1="${xx}" y1="${padT}" x2="${xx}" y2="${H-padB}" stroke="rgba(122,144,183,.08)" stroke-width="0.5" stroke-dasharray="3,3"/>`;
    }
  } else {
    const labels=opts&&opts.labels||[];
    const step=Math.max(1,Math.floor(labels.length/6));
    for(let i=0;i<labels.length;i+=step){
      const xx=padL+i/(labels.length-1||1)*(W-padL-padR);
      xt+=`<text x="${xx}" y="${H-10}" fill="#5A6A88" font-size="8.5" text-anchor="middle">${labels[i]}</text>`;
    }
  }
  // 各序列 path（支持 area 渐变填充 + threshold 阈值线）
  let defs='', paths='';
  const uid='g'+Math.random().toString(36).slice(2,8);
  let gi=0;
  series.forEach(s=>{
    const pts=s.points||[];
    if(!pts.length) return;
    const col=s.color||'#2DD4BF';
    let d='';
    pts.forEach((p,i)=>{
      const cx=X(p[0]), cy=Y(p[1]);
      d+= (i===0?'M':'L')+cx.toFixed(1)+','+cy.toFixed(1)+' ';
    });
    if(s.area){
      const gid=uid+'a'+(gi++);
      defs+=`<linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${col}" stop-opacity=".26"/>
        <stop offset="100%" stop-color="${col}" stop-opacity="0"/>
      </linearGradient>`;
      paths+=`<path d="${d}L${X(pts[pts.length-1][0]).toFixed(1)},${(H-padB)} L${X(pts[0][0]).toFixed(1)},${(H-padB)} Z" fill="url(#${gid})" stroke="none"/>`;
    }
    paths+=`<path d="${d}" fill="none" stroke="${col}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>`;
  });
  // 阈值线
  let thr='';
  if(opts&&opts.threshold&&typeof opts.threshold.value==='number'){
    const tcol=opts.threshold.color||'#F87171';
    const tlab=opts.threshold.label||'';
    const ty=Y(opts.threshold.value);
    thr=`<line x1="${padL}" y1="${ty.toFixed(1)}" x2="${W-padR}" y2="${ty.toFixed(1)}" stroke="${tcol}" stroke-width="1" stroke-dasharray="5,4" opacity=".8"/>`+
        `<text x="${W-padR-4}" y="${(ty-5).toFixed(1)}" fill="${tcol}" font-size="9.5" text-anchor="end">${tlab}</text>`;
  }
  // 图例
  let lg='';
  series.forEach(s=>{
    lg+=`<span class="lg"><span class="sw" style="background:${s.color||'#2DD4BF'}"></span>${s.name}</span>`;
  });
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
    <defs>${defs}</defs>${grid}${ticks}${xt}${paths}${thr}
  </svg><div class="chart-legend">${lg}</div>`;
}
function drawAllCharts(){
  document.querySelectorAll('[data-chart]').forEach(el=>{
    try{
      const spec=JSON.parse(el.getAttribute('data-chart')||'{}');
      renderLineChart(el.id||('c'+Math.random().toString(36).slice(2)), spec.series||[], spec.opts||{});
    }catch(err){}
  });
}
window.addEventListener('load',drawAllCharts);
setTimeout(drawAllCharts, 300);
"""

# ---------------------------------------------------------------------------
def esc(v):
    if v is None:
        return ""
    return html.escape(str(v))


def val(v, default="-"):
    return esc(v) if v not in (None, "", "N/A", "na") else default


def level_tag(lvl):
    l = str(lvl).lower()
    cls = l if l in ("p0", "p1", "p2", "p3", "ok", "info") else "info"
    return f'<span class="tag {cls}">{esc(lvl)}</span>'


def verdict_block(d, dims_html=""):
    v = d.get("health", {}).get("verdict", "未知")
    if v == "正常":
        cls, tip = "ok", "当前无活动告警且各硬件维度均正常"
    elif v.startswith("基本正常"):
        cls, tip = "warn", "存在需关注/加固项（P2/P3），不影响业务但建议处理"
    elif v == "有风险":
        cls, tip = "warn", "存在 P1 风险项，建议尽快排查"
    else:
        cls, tip = "bad", "存在 P0 严重问题，必须立即处理"
    vcls = {"ok": "v-ok", "bad": "v-bad"}.get(cls, "")
    return f'''<div class="verdict {vcls}">
      <div class="v-row">
        <div class="v-dot"></div>
        <div class="v-txt">总体判定：<em>{esc(v)}</em></div>
      </div>
      <div class="v-sub">{tip}</div>{dims_html}
    </div>'''


def kpi_block(items):
    """items: list of (value_html, label_html) 或 (value_html, label_html, status)
    status: ok / warn / bad / ''，渲染 .kpis 网格 + 右上角状态点"""
    n = max(1, min(6, len(items)))
    cells = []
    for it in items:
        v, l = it[0], it[1]
        st = it[2] if len(it) > 2 else ""
        stc = f" {st}" if st in ("ok", "warn", "bad") else ""
        cells.append(f'<div class="kpi{stc}"><div class="st"></div><div class="l">{l}</div><div class="v">{v}</div></div>')
    return f'<div class="kpis" style="grid-template-columns:repeat({n},1fr)">' + "".join(cells) + '</div>'


def issues_section(d):
    issues = d.get("health", {}).get("issues", [])
    counts = d.get("health", {}).get("counts", {})
    real = [i for i in issues if str(i.get("level", "")) in ("P0", "P1", "P2", "P3")]
    cells = []
    for l, c in (("P0", "bad"), ("P1", "warn"), ("P2", "warn"), ("P3", ""), ("OK", "ok")):
        cells.append(f'<div class="kpi {c}"><div class="st"></div><div class="l">{l}</div><div class="v">{counts.get(l,0)}</div></div>')
    total = sum(int(counts.get(l, 0) or 0) for l in ("P0", "P1", "P2", "P3"))
    cells.append(f'<div class="kpi"><div class="st"></div><div class="l">非OK合计</div><div class="v">{total}</div></div>')
    cards = []
    for i in real:
        lvl = str(i.get("level", "P3"))
        evi = i.get("evidence") or i.get("source") or ""
        act = i.get("action") or ""
        evi_html = f'<div class="evi">{esc(evi)}</div>' if evi else ""
        act_html = f'<div class="act"><b>建议</b>{esc(act)}</div>' if act else ""
        cards.append(
            f'<div class="issue lv-{lvl.lower()}"><div class="lv">{esc(lvl)}</div>'
            f'<div><div class="t">{esc(i.get("topic", ""))}</div>'
            f'<div class="d">{esc(i.get("detail", ""))}</div>{evi_html}{act_html}</div></div>')
    if not real:
        return ('<div class="kpis">' + "".join(cells) + '</div>'
                '<div class="card">未发现分级问题，各硬件维度均正常。</div>')
    return ('<div class="kpis">' + "".join(cells) + '</div>'
            '<div class="issues">' + "".join(cards) + '</div>')


# ---------------------------------------------------------------------------
# 单机模板 sections
# ---------------------------------------------------------------------------
def identity_section(d):
    ident = d.get("identity", {})
    ver = d.get("versions", {})
    tc = d.get("time_config", {})
    rows = [
        ("产品名称", ident.get("product_name") or ver.get("product_name")),
        ("产品序列号(SN)", ident.get("product_sn")),
        ("产品型号 Model", ident.get("model")),
        ("制造商", ident.get("product_manufacturer")),
        ("主板型号", ident.get("board_name")),
        ("主板SN", ident.get("board_sn")),
        ("主板制造商", ident.get("board_manufacturer")),
        ("主板生产日期", ident.get("board_mfg_date")),
        ("主板PartNo", ident.get("board_part_number")),
        ("主机名", tc.get("hostname")),
        ("Active iBMC", ver.get("ibmc")),
        ("Backup iBMC", ver.get("backup_ibmc")),
        ("BIOS", ver.get("bios")),
        ("CPLD", ver.get("cpld")),
        ("SDK/RTOS", ver.get("rtos_release")),
        ("iBMC Build", ver.get("ibmc_built")),
        ("build_date", ver.get("build_date")),
        ("baseversion", ver.get("baseversion")),
        ("Extend label", ident.get("extend_label")),
    ]
    rows = [(k, v) for k, v in rows if v]
    t = "".join(f"<tr><td style='width:200px'>{esc(k)}</td><td class='mono'>{esc(v)}</td></tr>" for k, v in rows)
    return f'<div class="card"><table>{t}</table></div>'


def current_event_section(d):
    ce = d.get("current_event", {})
    txt = ce.get("text", "").strip() or "（空 — 当前无活动告警）"
    if ce.get("has_critical"):
        cls = "bad"
    elif ce.get("empty"):
        cls = "ok"
    else:
        cls = "warn"
    status = "有 Critical" if ce.get("has_critical") else ("空" if ce.get("empty") else "有内容")
    return f'''<div class="card">
      <div style="margin-bottom:8px"><span class="tag {cls}">当前告警：{status}</span>
      <span class="badge">sensor_alarm/current_event.txt</span></div>
      <pre>{esc(txt)}</pre>
    </div>'''


def led_section(d):
    leds = d.get("led", {})
    if not leds:
        return '<div class="card">无 LedInfo 数据</div>'
    rows = []
    for name, info in leds.items():
        st = info.get("State", ""); col = info.get("Color", "")
        if "SysHeal" in name:
            cls = "ok" if "GREEN" in col.upper() else ("bad" if "RED" in col.upper() else "warn")
        elif "Fan" in name:
            cls = "ok" if "GREEN" in col.upper() else "bad"
        else:
            cls = "ok"
        rows.append(f"<tr><td>{esc(name)}</td><td>{esc(st)} / {esc(col)}</td><td><span class='tag {cls}'>{cls.upper()}</span></td></tr>")
    return f'<div class="card"><table><tr><th>LED</th><th>State/Color</th><th>判定</th></tr>{"".join(rows)}</table></div>'


def psu_section(d):
    psu = d.get("psu", [])
    if not psu:
        return '<div class="card">无 PSU 数据</div>'
    rows = []
    for p in psu:
        try:
            vin = float(p.get("vin", 0)); vout = float(p.get("vout", 0))
        except ValueError:
            vin = vout = 0
        cls = "ok" if (vin >= 180 and 11.5 <= vout <= 12.6 and p.get("presence") == "present") else "bad"
        rows.append(
            f"<tr><td>PSU{p.get('slot')}</td><td>{val(p.get('presence'))}</td>"
            f"<td>{val(p.get('type'))}</td><td>{val(p.get('rated_power'))}W</td>"
            f"<td>{val(p.get('input_mode'))}</td><td class='mono'>{val(p.get('vin'))}V</td>"
            f"<td class='mono'>{val(p.get('vout'))}V</td><td><span class='tag {cls}'>{cls.upper()}</span></td></tr>")
    return f'''<div class="card"><table>
      <tr><th>槽位</th><th>在位</th><th>型号</th><th>额定功率</th><th>输入模式</th><th>Vin</th><th>Vout</th><th>判定</th></tr>
      {"".join(rows)}</table>
      <div class="sub" style="margin-top:8px">正常标准：4 个全 present；Vin≈220V(180~264V)；Vout≈12V(11.5~12.6V)；InputMode=AC</div></div>'''


def cpu_mem_section(d):
    cpus = d.get("cpu", [])
    mem = d.get("memory", {})
    out = ""
    if cpus:
        rows = "".join(
            f"<tr><td>{esc(c.get('slot'))}</td><td>{esc(c.get('presence'))}</td>"
            f"<td>{esc(c.get('model'))}</td><td>{esc(c.get('cores'))}</td><td>{esc(c.get('threads'))}</td>"
            f"<td>{esc(c.get('l3'))}</td><td class='mono'>{esc(c.get('sn'))}</td></tr>"
            for c in cpus)
        out += f'''<div class="card"><h3 style="margin-top:0">CPU（{len(cpus)}）</h3><table>
          <tr><th>槽位</th><th>在位</th><th>型号</th><th>核数</th><th>线程</th><th>L3</th><th>SN</th></tr>{rows}</table></div>'''
    else:
        out += '<div class="card">无 CPU 数据</div>'
    dimms = mem.get("dimms", [])
    bad = mem.get("bad_dimms", [])
    kpis = kpi_block([
        (str(mem.get("count", 0)), "DIMM 条数"),
        (f'{mem.get("total_gb", 0)}<span style="font-size:12px">GB</span>', "总容量"),
        (f'<span class="{"bad" if mem.get("bad_count") else "ok"}">{mem.get("bad_count", 0)}</span>', "异常条数"),
    ])
    out += f'<div class="card"><h3 style="margin-top:0">内存</h3>{kpis}'
    if bad:
        out += '<div class="card-body"><h3>异常 DIMM</h3><ul class="plist">' + "".join(
            f"<li><div class='d'>{esc(b.get('slot'))} {esc(b.get('name'))}</div><div class='s'>health={esc(b.get('health'))}</div></li>"
            for b in bad) + "</ul></div>"
    if dimms:
        # 只展示前 60 条，其余可折叠
        shown = dimms[:60]
        rows = "".join(
            f"<tr><td>{esc(x.get('slot'))}</td><td>{esc(x.get('name'))}</td><td>{esc(x.get('manufacturer'))}</td>"
            f"<td>{esc(x.get('size'))}</td><td>{esc(x.get('speed'))}</td><td>{esc(x.get('type'))}</td>"
            f"<td><span class='tag {'ok' if str(x.get('health','')).lower() in ('ok','') else 'bad'}'>{esc(x.get('health') or 'ok')}</span></td></tr>"
            for x in shown)
        more = len(dimms) - len(shown)
        coll = f'''<span class="collapsible" data-target="dimm-more">剩余 {more} 条 DIMM 明细</span><div id="dimm-more" style="display:none;margin-top:8px">''' if more > 0 else ""
        coll_rows = "".join(
            f"<tr><td>{esc(x.get('slot'))}</td><td>{esc(x.get('name'))}</td><td>{esc(x.get('manufacturer'))}</td>"
            f"<td>{esc(x.get('size'))}</td><td>{esc(x.get('speed'))}</td><td>{esc(x.get('type'))}</td>"
            f"<td><span class='tag {'ok' if str(x.get('health','')).lower() in ('ok','') else 'bad'}'>{esc(x.get('health') or 'ok')}</span></td></tr>"
            for x in dimms[60:])
        out += f'''<div style="max-height:400px;overflow:auto"><table>
          <tr><th>槽位</th><th>名称</th><th>厂商</th><th>容量</th><th>速率</th><th>类型</th><th>健康</th></tr>{rows}</table></div>
          {coll}{coll_rows}</div>{'</div>' if more else ''}'''
    out += '</div>'
    return out


def _ecc_cell(v, bad):
    """ECC 数值：0/N/A/- 绿色加粗；异常时按 bad 级别红/黄高亮"""
    s = str(v)
    if s in ("0", "N/A", "-"):
        return f"<b>{esc(s)}</b>"
    color = "var(--bad)" if bad else "var(--warn)"
    return f'<span style="color:{color};font-weight:600">{esc(s)}</span>'


def npu_section(d):
    npus = d.get("npu", [])
    ecc = d.get("npu_ecc", {})
    if not npus:
        return '<div class="card">无 NPU 数据（注意：可能存在 NPU 掉卡）</div>'
    tiles = []
    for n in npus:
        name = n.get("name")
        e = ecc.get(name, {})
        sb = str(e.get("single_bit", "-"))
        mb = str(e.get("multi_bit", "-"))
        mb_bad = mb not in ("0", "N/A", "-")
        sb_warn = sb not in ("0", "N/A", "-")
        hot = " hot" if (mb_bad or sb_warn) else ""
        if mb_bad:
            corner, ccls = "故障", ' style="color:var(--bad)"'
        elif sb_warn:
            corner, ccls = "关注", ""
        else:
            corner, ccls = "在位正常", ' class="ok"'
        tiles.append(
            f'''<div class="npu{hot}">
  <div class="corner"{ccls}>{corner}</div>
  <div class="id">{esc(name)} · {esc(n.get('board', '-'))}</div>
  <div class="pw">{esc(n.get('power_w', '-'))}<small> W · {esc(n.get('workmode', '-'))}</small></div>
  <div class="ecc">ECC 单bit {_ecc_cell(sb, False)} · 多bit {_ecc_cell(mb, True)}</div>
  <div class="ecc">固件 <b>{val(n.get('fw_version'))}</b> · 软件 {val(n.get('sw_version'))}</div>
</div>''')
    return f'''<div class="npu-grid">{"".join(tiles)}</div>
  <div class="sub" style="margin-top:10px">共 {len(npus)} 卡；ECC 单/多 bit=0 正常（多 bit &gt;0 = 硬件故障 P0）</div>'''


def optical_section(d):
    opt = d.get("optical", {})
    static = opt.get("static", [])
    events = opt.get("port_events", [])
    out = ""
    if static:
        rows = "".join(
            f"<tr><td>{esc(o.get('OpticalModuleId'))}</td><td>{esc(o.get('VendorName'))}</td>"
            f"<td class='mono'>{esc(o.get('SerialNumber'))}</td><td>{esc(o.get('TransceiverType'))}</td></tr>"
            for o in static)
        out += f'<div class="card"><table><tr><th>模块ID</th><th>厂商</th><th>SN</th><th>类型</th></tr>{rows}</table></div>'
    if events:
        flaps = {}
        for e in events:
            flaps.setdefault(e["port"], {"up": 0, "down": 0, "first": e["time"], "last": e["time"]})
            flaps[e["port"]][e["event"]] += 1
            flaps[e["port"]]["last"] = e["time"]
        rows = "".join(
            f"<tr><td>{esc(p)}</td><td>{c['down']}</td><td>{c['up']}</td>"
            f"<td class='mono'>{esc(c['first'])}</td><td class='mono'>{esc(c['last'])}</td>"
            f"<td><span class='tag {'warn' if c['down']>=5 else 'ok'}'>{'关注' if c['down']>=5 else '正常'}</span></td></tr>"
            for p, c in flaps.items())
        out += f'''<div class="card"><h3 style="margin-top:0">NPU 参数面端口 up/down 历史（port_history_log）</h3>
          <table><tr><th>端口</th><th>down次数</th><th>up次数</th><th>首次</th><th>末次</th><th>判定</th></tr>{rows}</table>
          <div class="sub" style="margin-top:8px">共 {len(events)} 条事件；频繁 up/down 提示光路/模块/PCIe链路不稳定。</div></div>'''
    return out or '<div class="card">无光模块/端口数据</div>'


def temp_fan_section(d):
    sensors = d.get("sensors", [])
    fans = d.get("fan_detail", [])
    if not sensors and not fans:
        return '<div class="card">无传感器/风扇数据</div>'
    temps = [s for s in sensors if "degrees" in s.get("unit", "")]
    # 关键温度单独展示
    key_temps = []
    for kw in ("Inlet", "Outlet", "HBM", "Board Temp", "Core", "AI"):
        for s in temps:
            if kw in s.get("name", "") and s not in key_temps:
                key_temps.append(s)
    rowsT = ""
    shown_t = key_temps or temps[:40]
    for s in shown_t:
        cls = "ok" if s.get("status") == "ok" else "warn"
        rowsT += f"<tr><td>{esc(s.get('name'))}</td><td class='mono'>{esc(s.get('value'))} {esc(s.get('unit'))}</td><td><span class='tag {cls}'>{esc(s.get('status'))}</span></td></tr>"
    rowsF = ""
    for f in fans:
        spd = f.get("speed", "")
        m = re.search(r"(\d+)", spd.split("/")[0] if "/" in spd else spd)
        ok = False
        if m:
            try:
                ok = int(m.group(1)) >= 7000
            except ValueError:
                ok = False
        rowsF += f"<tr><td>{esc(f.get('name'))}</td><td>{esc(f.get('presence'))}</td><td>{esc(f.get('pwm'))}</td><td class='mono'>{esc(spd)} RPM</td><td><span class='tag {'ok' if ok else 'warn'}'>{'OK' if ok else '低'}</span></td></tr>"
    return f'''<div class="grid grid-2">
      <div class="card"><h3 style="margin-top:0">关键温度</h3><div style="max-height:460px;overflow:auto"><table>
        <tr><th>传感器</th><th>值</th><th>状态</th></tr>{rowsT}</table></div></div>
      <div class="card"><h3 style="margin-top:0">风扇详情</h3><div style="max-height:460px;overflow:auto"><table>
        <tr><th>风扇</th><th>在位</th><th>PWM</th><th>转速</th><th>判定(≥7000)</th></tr>{rowsF}</table></div></div>
    </div>'''


def raid_section(d):
    raid = d.get("raid", {})
    if not raid:
        return '<div class="card">无 RAID/存储信息</div>'
    ch = raid.get("controller", {})
    bbu = raid.get("bbu", {})
    out = f'''<div class="card"><h3 style="margin-top:0">RAID 控制器 / BBU</h3>
      <table>
        <tr><td style="width:140px">控制器</td><td>{val(ch.get('name'))}</td><td style="width:120px">模式</td><td>{val(ch.get('mode'))}</td></tr>
        <tr><td>固件</td><td class='mono'>{val(ch.get('fw'))}</td><td>健康</td><td><span class="tag {'ok' if ch.get('health')=='Normal' else 'bad'}">{val(ch.get('health'))}</span></td></tr>
        <tr><td>内存</td><td>{val(ch.get('memory_size'))}</td><td>DDR ECC</td><td class='mono'>{val(ch.get('ddr_ecc'))}</td></tr>
        <tr><td>BBU 状态</td><td>{val(bbu.get('status'))}</td><td>BBU 健康</td><td><span class="tag {'ok' if bbu.get('health')=='Normal' else 'warn'}">{val(bbu.get('health'))}</span></td></tr>
      </table></div>'''
    lds = raid.get("logical_drives", [])
    if lds:
        rows = "".join(
            f"<tr><td>{val(x.get('name'))}</td><td>{val(x.get('type'))}</td><td><span class='tag {'ok' if x.get('state')=='Optimal' else 'bad'}'>{val(x.get('state'))}</span></td><td>{val(x.get('target'))}</td></tr>"
            for x in lds)
        out += f'<div class="card"><h3>逻辑盘({len(lds)})</h3><table><tr><th>名称</th><th>RAID</th><th>状态</th><th>Target</th></tr>{rows}</table></div>'
    pds = raid.get("physical_drives", [])
    if pds:
        rows = "".join(
            f"<tr><td>{val(x.get('Device Name'))}</td><td>{val(x.get('Model'))}</td>"
            f"<td>{val(x.get('Media Type'))}</td><td>{val(x.get('Capacity'))}</td>"
            f"<td><span class='tag {'ok' if 'normal' in (x.get('Health Status') or '').lower() or x.get('Health Status')=='正常' else 'bad'}'>{val(x.get('Health Status'))}</span></td>"
            f"<td class='mono'>{val(x.get('Media Error Count'))}</td><td class='mono'>{esc(x.get('Power-On Hours'))}</td></tr>"
            for x in pds)
        out += f'<div class="card"><h3>物理盘({len(pds)})</h3><div style="max-height:360px;overflow:auto"><table><tr><th>盘</th><th>型号</th><th>介质</th><th>容量</th><th>健康</th><th>MediaErr</th><th>上电小时</th></tr>{rows}</table></div></div>'
    if raid.get("phy_errors"):
        out += f'<div class="card"><h3>PHY 误码文件</h3><div class="sub">{", ".join(esc(k) for k in raid["phy_errors"])}</div></div>'
    return out


def network_section(d):
    net = d.get("network", {})
    net_os = d.get("network_os", {})
    eth = net.get("eth_groups", [])
    out = ""
    if eth:
        rows = ""
        for g in eth:
            vlan = g.get("Dedicated Port VLAN State") or g.get("NCSI Port VLAN State") or "-"
            vlan_cls = "warn" if "enabled" in str(vlan).lower() else "ok"
            rows += f"<tr><td>{esc(g.get('id'))}</td><td>{esc(g.get('Net Type'))}</td><td>{esc(g.get('Net Mode'))}</td>" \
                    f"<td class='mono'>{val(g.get('IP Address'))}</td><td class='mono'>{val(g.get('IPv6 Mode'))}</td>" \
                    f"<td><span class='tag {vlan_cls}'>{esc(vlan)}</span></td></tr>"
        out += f'''<div class="card"><table>
          <tr><th>EthGroup</th><th>类型</th><th>模式</th><th>IPv4</th><th>IPv6</th><th>VLAN使能</th></tr>{rows}</table>
          <div class="sub" style="margin-top:8px">交付要求：序列号配置场景 IPv6=手动配置；Dedicated VLAN 使能应关闭。</div></div>'''
    if net_os.get("ifconfig"):
        rows = "".join(
            f"<tr><td class='mono'>{esc(iface)}</td><td class='mono'>{val(info.get('ip'))}</td>"
            f"<td class='mono'>{val(info.get('mask'))}</td><td>{esc(info.get('flags',''))[:40]}</td></tr>"
            for iface, info in net_os["ifconfig"].items())
        routes = "".join(
            f"<tr><td class='mono'>{esc(r.get('dest'))}</td><td class='mono'>{esc(r.get('gateway'))}</td><td class='mono'>{esc(r.get('iface'))}</td></tr>"
            for r in net_os.get("route", []))
        dns = ", ".join(esc(x) for x in net_os.get("resolv", [])) or "-"
        out += f'''<div class="grid grid-2"><div class="card"><h3 style="margin-top:0">iBMC 网口（ifconfig）</h3><table>
          <tr><th>接口</th><th>IP</th><th>掩码</th><th>Flags</th></tr>{rows}</table></div>
          <div class="card"><h3 style="margin-top:0">路由与DNS</h3>
            <h3 style="font-size:13px">路由</h3><table><tr><th>目标</th><th>网关</th><th>接口</th></tr>{routes or '<tr><td colspan=3 class=sub>-</td></tr>'}</table>
            <h3 style="font-size:13px">DNS</h3><div class="mono">{dns}</div></div></div>'''
    return out or '<div class="card">无网络配置数据</div>'


def bmc_env_section(d):
    """BMC 系统资源 + 环境配置（时区/NTP）+ 寄存器/扣卡/License/SP。"""
    ibmc = d.get("ibmc_sys", {})
    tc = d.get("time_config", {})
    reg = d.get("register", {})
    cards = d.get("cards", {})
    lic = d.get("license", {})
    sp = d.get("sp_asset", {})
    out = ""
    # BMC 系统资源
    mem = ibmc.get("mem", {})
    mem_used_pct = ""
    if mem.get("MemTotal") and mem.get("MemAvailable"):
        mem_used_pct = f'{100*(1-mem["MemAvailable"]/mem["MemTotal"]):.0f}%'
    df_warn = ""
    for drow in ibmc.get("df", []):
        try:
            pct = int(drow.get("use_pct", "0").rstrip("%"))
            if pct >= 80:
                df_warn += f"<span class='tag p1'>{esc(drow.get('mount'))} {pct}%</span> "
        except ValueError:
            pass
    load = ibmc.get("loadavg", "")
    uptime = ibmc.get("uptime", "")
    rows = [
        ("运行时间", uptime),
        ("负载 loadavg", load),
        ("内存", f"{mem.get('MemTotal','?')//1024 if mem.get('MemTotal') else '?'}MB 总 / {mem.get('MemAvailable','?')//1024 if mem.get('MemAvailable') else '?'}MB 可用 ({mem_used_pct})"),
        ("时区", tc.get("timezone")),
        ("NTP", tc.get("ntp") or "-"),
        ("主机名", tc.get("hostname")),
    ]
    rows = [(k, v) for k, v in rows if v]
    t = "".join(f"<tr><td style='width:150px'>{esc(k)}</td><td class='mono'>{esc(v)}</td></tr>" for k, v in rows)
    df_html = f'<div class="sub" style="margin-top:8px">高占用分区：{df_warn or "无"}</div>' if df_warn else ""
    out += f'<div class="card"><h3 style="margin-top:0">iBMC 系统资源</h3><table>{t}</table>{df_html}</div>'
    # 扣卡信息
    if any(cards.values()):
        pcie = cards.get("pcie_cards", [])
        risers = cards.get("risers", [])
        bps = cards.get("backplanes", [])
        card_rows = ""
        for c in pcie:
            card_rows += f"<tr><td>{esc(c.get('slot'))}</td><td>{esc(c.get('desc'))}</td><td>{esc(c.get('product'))}</td></tr>"
        r_rows = "".join(f"<tr><td>{esc(r.get('slot'))}</td><td>{esc(r.get('name'))}</td><td>{esc(r.get('type'))}</td></tr>" for r in risers)
        b_rows = "".join(f"<tr><td>{esc(bp.get('slot'))}</td><td>{esc(bp.get('name'))}</td><td>{esc(bp.get('type'))}</td></tr>" for bp in bps)
        out += f'''<div class="card"><h3 style="margin-top:0">扣卡 / Riser / 背板</h3>
          <div class="grid grid-3">
            <div><h3 style="font-size:13px">PCIe 扣卡({len(pcie)})</h3><table><tr><th>槽</th><th>描述</th><th>产品</th></tr>{card_rows or '<tr><td colspan=3 class=sub>-</td></tr>'}</table></div>
            <div><h3 style="font-size:13px">Riser({len(risers)})</h3><table><tr><th>槽</th><th>名称</th><th>类型</th></tr>{r_rows or '<tr><td colspan=3 class=sub>-</td></tr>'}</table></div>
            <div><h3 style="font-size:13px">硬盘背板({len(bps)})</h3><table><tr><th>槽</th><th>名称</th><th>类型</th></tr>{b_rows or '<tr><td colspan=3 class=sub>-</td></tr>'}</table></div>
          </div></div>'''
    # 寄存器
    if reg:
        reg_rows = "".join(
            f"<tr><td class='mono'>{esc(k)}</td><td>{esc(v.get('size'))} B</td><td class='mono'>{esc(v.get('head',''))}</td></tr>"
            for k, v in reg.items())
        out += f'<div class="card"><h3 style="margin-top:0">寄存器信息（Register）</h3><table><tr><th>文件</th><th>大小</th><th>内容片段</th></tr>{reg_rows}</table></div>'
    # License / SP
    if lic.get("esn") or sp:
        lic_rows = "".join(f"<tr><td style='width:150px'>ESN</td><td class='mono'>{val(lic.get('esn'))}</td></tr>"
                           f"<tr><td>License 状态</td><td>{val(lic.get('license_status'))}</td></tr>"
                           f"<tr><td>SP OS</td><td>{val(sp.get('sp_version',{}).get('OSVersion'))}</td></tr>"
                           f"<tr><td>SP APP</td><td class='mono'>{val(sp.get('sp_version',{}).get('APPVersion'))}</td></tr>"
                           f"<tr><td>SP ReleaseDate</td><td>{val(sp.get('sp_version',{}).get('ReleaseDate'))}</td></tr>")
        out += f'<div class="card"><h3 style="margin-top:0">License / SP 资产</h3><table>{lic_rows}</table></div>'
    return out or '<div class="card">无 BMC 系统数据</div>'


def _json_safe(obj):
    """把对象 JSON 序列化并转义为可内嵌到 HTML attribute 的安全字符串。"""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return html.escape(s, quote=True)


def _parse_power_csv(sample):
    """解析 power_statistics.csv 文本 → {labels:[时间], current:[], avg:[], peak:[]}"""
    cur, avg, peak, labels = [], [], [], []
    for line in (sample or "").splitlines()[1:]:
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 4:
            try:
                labels.append(parts[0])
                cur.append(float(parts[1]))
                avg.append(float(parts[2]))
                peak.append(float(parts[3]))
            except ValueError:
                continue
    return labels, cur, avg, peak


def _parse_tsval(sample):
    """解析 '时间#数值' 文本 → (labels[], values[])"""
    labels, vals = [], []
    for line in (sample or "").splitlines():
        line = line.strip()
        if "#" in line:
            t, _, v = line.partition("#")
            t = t.strip()
            if t and _is_number(v.strip()):
                labels.append(t)
                vals.append(float(v.strip()))
    return labels, vals


def _is_number(s):
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def utilization_section(d):
    ut = d.get("utilization", {})
    pstat = d.get("power_stat", {})
    out = ""

    # ---- 功率曲线（power_statistics.csv）----
    labels, cur, avg, peak = _parse_power_csv(pstat.get("sample", ""))
    if cur:
        series = []
        series.append({"name": "当前功率(W)", "color": "#2DD4BF", "area": True,
                       "points": [[float(i), cur[i]] for i in range(len(cur))]})
        if avg:
            series.append({"name": "平均功率(W)", "color": "#34D399",
                           "points": [[float(i), avg[i]] for i in range(len(avg))]})
        if peak:
            series.append({"name": "峰值功率(W)", "color": "#FBBF24",
                           "points": [[float(i), peak[i]] for i in range(len(peak))]})
        spec = {"series": series,
                "opts": {"height": 240, "labels": labels[-400:]}}
        cid = "ch-power"
        out += f'''<div class="card"><h3 style="margin-top:0">功率曲线（power_statistics.csv）</h3>
          <div class="chart-box"><div class="chart-title">功率趋势（最近 {len(labels)} 个采样点）</div>
          <div class="chart-sub">描点间隔约 10 分钟；峰值突刺可能对应负载/训练任务</div>
          <div id="{cid}" data-chart="{_json_safe(spec)}"></div></div></div>'''

    # ---- 环境温度曲线（env_web_view.dat）----
    env = ut.get("env_temp", [])
    if env:
        labels_t = [x["time"] for x in env]
        vals_t = []
        for x in env:
            try:
                vals_t.append(float(x["value"]))
            except (TypeError, ValueError):
                vals_t.append(None)
        pts = [[float(i), v] for i, v in enumerate(vals_t) if v is not None]
        if pts:
            spec = {"series": [{"name": "环境温度(°C)", "color": "#2DD4BF", "area": True,
                                "points": pts}],
                    "opts": {"height": 220, "labels": labels_t[-400:],
                             "threshold": {"value": 42, "color": "#F87171", "label": "42°C Inlet 上限"}}}
            cid = "ch-env"
            out += f'''<div class="card"><h3 style="margin-top:0">环境温度曲线（env_web_view.dat，{len(env)} 点）</h3>
              <div class="chart-box"><div class="chart-title">进风/环境温度趋势</div>
              <div class="chart-sub">Inlet 标准 &lt;42°C（Minor）/ &lt;46°C（Major）</div>
              <div id="{cid}" data-chart="{_json_safe(spec)}"></div></div></div>'''

    # ---- NPU HBM 温度曲线（NPU-*_hbm_webview.dat）----
    for h in ut.get("hbm_temp", []):
        labels_h, vals_h = _parse_tsval(h.get("sample", ""))
        pts = [[float(i), v] for i, v in enumerate(vals_h) if v is not None]
        if pts:
            cid = "ch-hbm-" + re.sub(r'\W+', '', h.get("file", "hbm"))[-20:]
            spec = {"series": [{"name": "HBM温度(°C)", "color": "#FBBF24", "area": True, "points": pts}],
                    "opts": {"height": 200, "labels": labels_h,
                             "threshold": {"value": 95, "color": "#F87171", "label": "95°C HBM 上限"}}}
            out += f'''<div class="card"><h3 style="margin-top:0">{esc(h["file"])}</h3>
              <div class="chart-box"><div class="chart-title">NPU HBM 温度趋势（标准 &lt;95°C）</div>
              <div id="{cid}" data-chart="{_json_safe(spec)}"></div></div></div>'''

    # ---- 功率趋势（powerview.txt，纯数值序列）----
    raw_power = ut.get("power", "")
    if raw_power:
        nums = []
        for line in raw_power.splitlines():
            line = line.strip()
            if _is_number(line):
                try:
                    nums.append(float(line))
                except ValueError:
                    continue
        if nums:
            first_ts = nums[0] if len(str(nums[0]).split(".")[0]) > 9 else None  # 可能是 unix ts
            vals = nums[1:] if first_ts and first_ts > 1000000000 else nums
            vals = vals[:400]
            spec = {"series": [{"name": "功率(W)", "color": "#FBBF24", "area": True,
                                "points": [[float(i), v] for i, v in enumerate(vals) if v is not None]}],
                    "opts": {"height": 200}}
            out += f'''<div class="card"><h3 style="margin-top:0">功率趋势（powerview.txt）</h3>
              <div class="chart-box"><div class="chart-title">功率值序列（{len(vals)} 点）</div>
              <div id="ch-pv" data-chart="{_json_safe(spec)}"></div></div></div>'''

    # ---- CPU/内存利用率（如存在数据点）----
    cpts, mpts = None, None
    cl, cv = _parse_tsval(ut.get("cpu_utilise", ""))
    if len(cv) > 1:
        cpts = [[float(i), v] for i, v in enumerate(cv)]
    ml, mv = _parse_tsval(ut.get("mem_utilise", ""))
    if len(mv) > 1:
        mpts = [[float(i), v] for i, v in enumerate(mv)]
    if cpts or mpts:
        series = []
        if cpts:
            series.append({"name": "CPU利用率(%)", "color": "#34D399", "points": cpts})
        if mpts:
            series.append({"name": "内存利用率(%)", "color": "#60A5FA", "points": mpts})
        spec = {"series": series, "opts": {"height": 220, "yMin": 0, "yMax": 100}}
        out += f'''<div class="card"><h3 style="margin-top:0">CPU / 内存利用率</h3>
          <div class="chart-box"><div class="chart-title">利用率趋势（0-100%）</div>
          <div id="ch-util" data-chart="{_json_safe(spec)}"></div></div></div>'''

    if not out:
        return '<div class="card">无利用率/功率曲线数据</div>'
    return out


def sel_section(d):
    sel = d.get("sel", {})
    events = sel.get("events", [])
    stats = sel.get("stats", {})
    if not events:
        return '<div class="card">无 SEL 数据或 SEL 为空</div>'
    bl = stats.get("by_level", {})
    level_kpi = {
        "CRITICAL": ("bad", bl.get("CRITICAL", 0)),
        "MAJOR": ("warn", bl.get("MAJOR", 0)),
        "MINOR": ("warn", bl.get("MINOR", 0)),
        "INFO": ("ok", bl.get("INFO", 0)),
    }
    kpis = "".join(
        f'<div class="kpi"><div class="v {c}">{n}</div><div class="l">{lvl}</div></div>'
        for lvl, (c, n) in level_kpi.items())
    kpis += f'<div class="kpi"><div class="v">{len(events)}</div><div class="l">总事件</div></div>'
    important = [e for e in events if e["level"] != "INFO"]
    imp_rows = ""
    for e in important[-80:]:
        cls = e["level"].lower()
        imp_rows += f"<tr><td><span class='tag {cls}'>{e['level']}</span></td><td class='mono'>{esc(e['time'])}</td>" \
                    f"<td>{esc(e['entity'])}:{esc(e['sensor'])}</td><td>{esc(e['record'][:70])}</td><td>{esc(e['status'])}</td></tr>"
    imp_table = f'<div class="card"><h3 style="margin-top:0">非 INFO 事件（最近 {min(80,len(important))} 条）</h3>' \
                f'<div style="max-height:440px;overflow:auto"><table><tr><th>级别</th><th>时间</th><th>对象</th><th>内容</th><th>状态</th></tr>{imp_rows}</table></div></div>'
    return f'''<div class="grid grid-4">{kpis}</div>
      <div class="sub">SEL 时间跨度: {val(stats.get('first_ts'))} ~ {val(stats.get('last_ts'))}；来源 sel.db（{stats.get('count')} 条）</div>
      {imp_table}'''


def logs_section(d):
    ls = d.get("logs_summary", {})
    sizes = ls.get("sizes", {})
    rows = "".join(f"<tr><td class='mono'>{esc(k)}</td><td>{esc(v)} B</td></tr>" for k, v in sorted(sizes.items()))
    osd = d.get("osd_files", [])
    os_rows = "".join(f"<tr><td class='mono'>{esc(x['name'])}</td><td>{esc(x.get('size',''))} B</td></tr>" for x in osd)
    sev = d.get("syslog_events", {})
    npu_ev = sev.get("npu_health", [])
    sys_rows = ""
    if npu_ev:
        rows2 = "".join(
            f"<tr><td class='mono'>{esc(e['time'])}</td><td><span class='tag {'warn' if e['level'] not in ('Normal','Info') else 'ok'}'>{esc(e['level'])}</span></td>"
            f"<td>{esc(e['state'])}</td><td>{esc(e['msg'][:90])}</td></tr>"
            for e in npu_ev[-40:])
        sys_rows = f'''<div class="card" style="margin-top:12px"><h3 style="margin-top:0">NPU 健康事件（syslog remote_log，SEL 补充）</h3>
          <div class="sub">共 {len(npu_ev)} 条；'degraded... Error Code: 非NA' 表示瞬时降级，随后 NA/Deasserted 表示恢复。需结合 OS/npu-smi 确认。</div>
          <div style="max-height:360px;overflow:auto"><table><tr><th>时间</th><th>级别</th><th>状态</th><th>内容</th></tr>{rows2}</table></div></div>'''
    nginx = d.get("nginx", {})
    nginx_rows = ""
    if nginx.get("exists"):
        nginx_rows = "".join(f"<tr><td class='mono'>{esc(k)}</td><td>{esc(v)} B</td></tr>" for k, v in sorted(nginx.get("files", {}).items()))
    return f'''<div class="grid grid-2">
      <div class="card"><h3 style="margin-top:0">LogDump 关键日志</h3><div style="max-height:360px;overflow:auto"><table><tr><th>文件</th><th>大小</th></tr>{rows or '<tr><td colspan=2 class=sub>-</td></tr>'}</table></div>
      {sys_rows}</div>
      <div>
        <div class="card"><h3 style="margin-top:0">OSDump 录像/截图</h3>
          {f'<table><tr><th>文件</th><th>大小</th></tr>{os_rows}</table>' if os_rows else '<div class="sub">无</div>'}</div>
        <div class="card"><h3 style="margin-top:0">3rdDump (Nginx 配置)</h3>
          {f'<table><tr><th>文件</th><th>大小</th></tr>{nginx_rows}</table>' if nginx_rows else '<div class="sub">无</div>'}</div>
      </div>
    </div>'''


def bios_single_section(d):
    """单机模板：BIOS 全量配置展示（带说明列）。"""
    bios = d.get("bios", {})
    items = bios.get("items", []) or []
    if not items:
        return '<div class="card">无 BIOS 配置数据</div>'
    rows = ""
    for it in items:
        disp = it.get("display_name") or ""
        help_txt = it.get("help_text") or ""
        menu = it.get("menu_path") or ""
        doc = " ".join(x for x in (disp, help_txt, f"[菜单: {menu}]" if menu else "") if x)
        rows += (f"<tr><td class='mono'><b>{esc(it.get('name'))}</b></td>"
                 f"<td class='mono'>{esc(it.get('default'))}</td>"
                 f"<td class='mono'>{esc(it.get('value'))}</td>"
                 f"<td class='sub' style='min-width:260px'>{esc(doc)}</td></tr>")
    return f'''<div class="card"><h3 style="margin-top:0">BIOS 配置（{len(items)} 项，含说明）</h3>
      <div class="sub">当前值来自 currentvalue.json；默认值/说明/菜单路径来自 registry.json；黄色=与默认值不同的项。</div>
      <div style="max-height:560px;overflow:auto"><table class="cmp-table">
        <tr><th>参数名</th><th>默认值</th><th>当前值</th><th>参数说明 / 菜单路径</th></tr>{rows}</table></div>
    </div>'''


def nand_env_section(d):
    """单机模板：NAND Flash + LLDP + mcinfo 展示。"""
    nand = d.get("nand", {})
    lldp = d.get("lldp", {})
    mc = d.get("mcinfo", {})
    out = ""
    if nand:
        rows = "".join(f"<tr><td style='width:200px'>{esc(k)}</td><td class='mono'>{esc(v)}</td><td class='sub'>{esc({ 'vendor':'NAND Flash 厂商','remaining_lifetime':'剩余寿命（应>10%）','total_written':'累计写入量','daily_write':'近15天每日写入量' }.get(k,''))}</td></tr>"
                       for k, v in nand.items() if v not in (None, ""))
        out += f'<div class="card"><h3 style="margin-top:0">NAND Flash 寿命</h3><table><tr><th>项</th><th>值</th><th>说明</th></tr>{rows}</table></div>'
    if lldp:
        rows = "".join(f"<tr><td class='mono'>{esc(k)}</td><td class='mono'>{esc(v)}</td></tr>" for k, v in lldp.items())
        out += f'<div class="card"><h3 style="margin-top:0">LLDP 配置</h3><table>{rows}</table></div>'
    if mc.get("raw"):
        out += f'<div class="card"><h3 style="margin-top:0">BMC MCU 信息</h3><pre>{esc(mc["raw"])}</pre></div>'
    return out or '<div class="card">无 NAND/LLDP 数据</div>'


def parsed_files_section(d):
    pf = d.get("parsed_files", {})
    found = pf.get("found", [])
    missing = pf.get("missing", [])
    found_rows = "".join(
        f"<tr><td>{esc(f.get('group'))}</td><td class='mono'>{esc(f.get('rel'))}</td><td>{esc(f.get('size'))} B</td></tr>"
        for f in found)
    miss_rows = "".join(
        f"<tr><td>{esc(m.get('group'))}</td><td class='mono'>{esc(m.get('rel'))}</td></tr>"
        for m in missing)
    return f'''<div class="card"><h3 style="margin-top:0">表5-79 关键文件清单（可追溯性）</h3>
      <div class="sub">命中 {pf.get('found_count',0)} 个，缺失 {pf.get('missing_count',0)} 个（缺失不一定是问题，取决于机型/配置）。</div>
      <div class="grid grid-2">
        <div style="max-height:400px;overflow:auto"><table><tr><th>分组</th><th>文件</th><th>大小</th></tr>{found_rows}</table></div>
        <div style="max-height:400px;overflow:auto"><table><tr><th>分组</th><th>缺失文件</th></tr>{miss_rows or '<tr><td colspan=2 class=sub>无</td></tr>'}</table></div>
      </div></div>'''


# ---------------------------------------------------------------------------
# 单机模板主构建
# ---------------------------------------------------------------------------
def build_single_report(machine):
    m = machine
    ident = m.get("identity", {})
    sn = ident.get("product_sn") or m.get("machine_tag")
    title = f"BMC 诊断报告 · {ident.get('product_name') or '机器'} · {sn}"
    h = m.get("health", {})
    r = m.get("ranks", {})
    col = m.get("collected_at") or "-"

    nav = f'''
    <div class="brand"><div class="sig">B</div><div><b>iBMC 诊断台</b><small>DIAG CONSOLE</small></div></div>
    <div class="grp">总览</div>
    <a data-target="summary" href="#summary">分析结论</a>
    <a data-target="issues" href="#issues">问题清单</a>
    <a data-target="identity" href="#identity">身份与版本</a>
    <a data-target="current_event" href="#current_event">当前告警</a>
    <a data-target="led" href="#led">指示灯</a>
    <div class="grp">硬件</div>
    <a data-target="psu" href="#psu">电源 PSU</a>
    <a data-target="cpu" href="#cpu">CPU / 内存</a>
    <a data-target="npu" href="#npu">NPU / ECC</a>
    <a data-target="optical" href="#optical">光模块 / 端口</a>
    <a data-target="temp" href="#temp">温度 / 风扇</a>
    <a data-target="raid" href="#raid">RAID / 存储</a>
    <div class="grp">系统与环境</div>
    <a data-target="network" href="#network">网络配置</a>
    <a data-target="bmcenv" href="#bmcenv">BMC系统 / 扣卡 / 寄存器</a>
    <a data-target="nandenv" href="#nandenv">NAND / LLDP</a>
    <a data-target="bios" href="#bios">BIOS 配置（全量）</a>
    <a data-target="util" href="#util">利用率 / 功率曲线</a>
    <div class="grp">事件与日志</div>
    <a data-target="sel" href="#sel">SEL 事件</a>
    <a data-target="logs" href="#logs">日志 / OS / Nginx</a>
    <a data-target="files" href="#files">文件清单</a>
    <div class="foot">基于华为 iBMC 一键收集日志生成<br>依据 Atlas 26.1.0 交付标准</div>'''

    # ---- 顶部识别条 ----
    crumb = f'''<div class="crumb">
      <span class="chip"><span class="k">机型</span>{esc(r.get("product_name") or ident.get("product_name") or "-")}</span>
      <span class="chip"><span class="k">SN</span>{esc(sn)}</span>
      <span class="chip"><span class="k">iBMC</span>{val(r.get("ibmc"))}</span>
      <span class="chip"><span class="k">BIOS</span>{val(r.get("bios"))}</span>
      <span class="chip"><span class="k">采集</span>{esc(col)}</span>
      <span class="chip"><span class="k">来源</span>{esc(m.get("machine_tag"))}</span>
    </div>'''

    # ---- 健康评分（报告端计算：P0×30 + P1×15 + P2×5 + P3×1）----
    counts = h.get("counts", {})
    c0 = int(counts.get("P0", 0) or 0)
    c1 = int(counts.get("P1", 0) or 0)
    c2 = int(counts.get("P2", 0) or 0)
    c3 = int(counts.get("P3", 0) or 0)
    score = max(0, 100 - (c0 * 30 + c1 * 15 + c2 * 5 + c3 * 1))
    parts = []
    if c0: parts.append(f"P0×{c0}（-{c0 * 30}）")
    if c1: parts.append(f"P1×{c1}（-{c1 * 15}）")
    if c2: parts.append(f"P2×{c2}（-{c2 * 5}）")
    if c3: parts.append(f"P3×{c3}（-{c3}）")
    hint = "扣分构成：" + ("、".join(parts) if parts else "无扣分项")

    # ---- 10 维度健康带（告警/电源/CPU/内存/NPU/光模块/温度/风扇/存储/SEL）----
    def _dim(cls, pct, name):
        return (f'<div class="dim {cls}"><div class="bar">'
                f'<i style="width:{pct}%"></i></div><div class="n">{name}</div></div>')

    ca = str(r.get("current_alarm", "") or "")
    if ca == "空":
        d_alarm = _dim("ok", 100, "告警")
    elif ca == "Critical":
        d_alarm = _dim("bad", 18, "告警")
    elif ca:
        d_alarm = _dim("warn", 55, "告警")
    else:
        d_alarm = _dim("", 100, "告警")

    np_c = int(r.get("psu_count", 0) or 0)
    np_p = int(r.get("psu_present", 0) or 0)
    d_psu = (_dim("ok", 100, "电源") if np_c and np_p == np_c
             else _dim("bad", 40, "电源") if np_c else _dim("", 100, "电源"))
    d_cpu = _dim("ok", 100, "CPU") if int(r.get("cpu_count", 0) or 0) else _dim("", 100, "CPU")

    mb = int(r.get("mem_bad", 0) or 0)
    mc = int(r.get("mem_count", 0) or 0)
    d_mem = (_dim("ok", 100, "内存") if mb == 0 and mc
             else _dim("bad", 30, "内存") if mb > 2 else _dim("warn", 60, "内存") if mb
             else _dim("", 100, "内存"))

    ne = int(r.get("npu_multi_ecc", 0) or 0)
    se = int(r.get("npu_single_ecc", 0) or 0)
    nn = int(r.get("npu_count", 0) or 0)
    if ne:
        d_npu = _dim("bad", 25, "NPU")
    elif nn == 0:
        d_npu = _dim("", 100, "NPU")
    elif se:
        d_npu = _dim("warn", 65, "NPU")
    else:
        d_npu = _dim("ok", 100, "NPU")

    pe = int(r.get("port_events", 0) or 0)
    oc = int(r.get("optical_count", 0) or 0)
    d_opt = (_dim("warn", 60, "光模块") if pe
             else _dim("ok", 100, "光模块") if oc else _dim("", 100, "光模块"))

    try:
        it = float(r.get("inlet_temp"))
    except (TypeError, ValueError):
        it = None
    if it is None:
        d_tmp = _dim("", 100, "温度")
    elif it > 46:
        d_tmp = _dim("bad", 20, "温度")
    elif it > 42:
        d_tmp = _dim("warn", 55, "温度")
    else:
        d_tmp = _dim("ok", 100, "温度")

    d_fan = _dim("ok", 100, "风扇") if int(r.get("fan_count", 0) or 0) else _dim("", 100, "风扇")

    rh = str(r.get("raid_health", "") or "")
    if not rh:
        d_raid = _dim("", 100, "存储")
    elif "ok" in rh.lower() or "健康" in rh or "正常" in rh:
        d_raid = _dim("ok", 100, "存储")
    elif "degrad" in rh.lower() or "降级" in rh:
        d_raid = _dim("warn", 55, "存储")
    else:
        d_raid = _dim("bad", 30, "存储")

    sc_n = int(r.get("sel_critical", 0) or 0)
    sm_n = int(r.get("sel_major", 0) or 0)
    st_n = int(r.get("sel_count", 0) or 0)
    if sc_n:
        d_sel = _dim("bad", 25, "SEL")
    elif sm_n:
        d_sel = _dim("warn", 55, "SEL")
    elif st_n:
        d_sel = _dim("warn", 80, "SEL")
    else:
        d_sel = _dim("ok", 100, "SEL")

    dims = "".join([d_alarm, d_psu, d_cpu, d_mem, d_npu, d_opt, d_tmp, d_fan, d_raid, d_sel])
    dims_html = f'<div class="dim-strip">{dims}</div>'

    # ---- HERO：判定 + 健康带 + 评分环 ----
    hero = f'''{verdict_block(m, dims_html)}
        <div class="score"><div class="num">{score}<small>/100</small></div>
          <div class="lb">健康评分</div><div class="hint">{hint}</div></div>'''

    # ---- 顶部 KPI（(值, 标签, 状态)）----
    alarm_st = "ok" if ca == "空" else ("bad" if ca == "Critical" else ("warn" if ca else ""))
    kpi = [
        (f'<span style="font-size:15px">{esc(r.get("product_sn") or sn)}</span>', "SN", ""),
        (f'<span style="font-size:14px">{val(r.get("ibmc"))} / {val(r.get("bios"))}</span>', "iBMC / BIOS", ""),
        (ca if ca else "-", "当前告警", alarm_st),
        (f'{r.get("cpu_count", 0)}<small>核</small> / {r.get("mem_count", 0)}<small>条 · {r.get("mem_total_gb", 0)}GB</small>',
         "CPU / 内存", "ok" if not mb else "warn"),
        (f'{r.get("npu_count", 0)}<small>卡</small>', "NPU",
         "bad" if ne else ("warn" if se else ("ok" if nn else ""))),
        (f'{np_p}<small>/ {np_c} 在位</small>', "电源 PSU",
         "ok" if np_c and np_p == np_c else ("bad" if np_c else "")),
        (f'{r.get("inlet_temp") or "-"}<small>°C</small>', "进风温度",
         "bad" if it is not None and it > 46 else ("warn" if it is not None and it > 42 else ("ok" if it is not None else ""))),
        (f'<span class="tag p0">{c0}</span> <span class="tag p1">{c1}</span> <span class="tag p2">{c2}</span> <span class="tag p3">{c3}</span>',
         "问题分布", "bad" if c0 else ("warn" if (c1 or c2 or c3) else "ok")),
    ]

    sections = ""
    # 01 分析结论
    sections += f'''<div class="section" id="summary">
      <h2 class="sec"><span class="no">01</span>分析结论<span class="src">综合判定 · 基于全部收集项</span></h2>
      <div class="hero">{hero}</div>
      {kpi_block(kpi)}
      <div class="sub">日志收集时间：{esc(col)}｜来源：{esc(m.get('machine_tag'))}</div>
    </div>'''

    # 02 问题清单（分析先行）
    sections += f'<div class="section" id="issues"><h2 class="sec"><span class="no">02</span>问题清单<span class="src">按严重度排序 · 每项可追溯</span></h2>{issues_section(m)}</div>'

    sections += f'<div class="section" id="identity"><h2 class="sec"><span class="no">03</span>身份与版本<span class="src">product_info · versions</span></h2>{identity_section(m)}</div>'
    sections += f'<div class="section" id="current_event"><h2 class="sec"><span class="no">04</span>当前活动告警<span class="src">alarms · report</span></h2>{current_event_section(m)}</div>'
    sections += f'<div class="section" id="led"><h2 class="sec"><span class="no">05</span>指示灯状态<span class="src">LED status</span></h2>{led_section(m)}</div>'
    sections += f'<div class="section" id="psu"><h2 class="sec"><span class="no">06</span>电源 PSU<span class="src">psu info</span></h2>{psu_section(m)}</div>'
    sections += f'<div class="section" id="cpu"><h2 class="sec"><span class="no">07</span>CPU 与内存<span class="src">cpuinfo · memory RAS</span></h2>{cpu_mem_section(m)}</div>'
    sections += f'<div class="section" id="npu"><h2 class="sec"><span class="no">08</span>NPU 与 ECC<span class="src">npu list · npu ecc</span></h2>{npu_section(m)}</div>'
    sections += f'<div class="section" id="optical"><h2 class="sec"><span class="no">09</span>光模块与端口<span class="src">optical module · port events</span></h2>{optical_section(m)}</div>'
    sections += f'<div class="section" id="temp"><h2 class="sec"><span class="no">10</span>温度与风扇<span class="src">sensor info · fan detail</span></h2>{temp_fan_section(m)}</div>'
    sections += f'<div class="section" id="raid"><h2 class="sec"><span class="no">11</span>RAID 与存储<span class="src">raid controller</span></h2>{raid_section(m)}</div>'
    sections += f'<div class="section" id="network"><h2 class="sec"><span class="no">12</span>网络配置<span class="src">eth port config</span></h2>{network_section(m)}</div>'
    sections += f'<div class="section" id="bmcenv"><h2 class="sec"><span class="no">13</span>BMC 系统 / 扣卡 / 寄存器<span class="src">bmc env · netmode</span></h2>{bmc_env_section(m)}</div>'
    sections += f'<div class="section" id="nandenv"><h2 class="sec"><span class="no">14</span>NAND Flash / LLDP / MCU<span class="src">nand flash · lldp</span></h2>{nand_env_section(m)}</div>'
    sections += f'<div class="section" id="bios"><h2 class="sec"><span class="no">15</span>BIOS 配置（全量）<span class="src">bios config dump</span></h2>{bios_single_section(m)}</div>'
    sections += f'<div class="section" id="util"><h2 class="sec"><span class="no">16</span>利用率 / 功率曲线<span class="src">power_statistics · env_web_view</span></h2>{utilization_section(m)}</div>'
    sections += f'<div class="section" id="sel"><h2 class="sec"><span class="no">17</span>SEL 事件日志<span class="src">sel.db</span></h2>{sel_section(m)}</div>'
    sections += f'<div class="section" id="logs"><h2 class="sec"><span class="no">18</span>日志 / OS / Nginx<span class="src">os logs · nginx</span></h2>{logs_section(m)}</div>'
    sections += f'<div class="section" id="files"><h2 class="sec"><span class="no">19</span>文件清单<span class="src">一键收集文件清单</span></h2>{parsed_files_section(m)}</div>'

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}</style></head>
<body>
<div class="layout">
  <nav>
    {nav}
  </nav>
  <main>
    <div class="content-wrap">
    <h1>{esc(title)}</h1>
    {crumb}
    {sections}
    </div>
  </main>
</div>
<script>{JS}</script>
</body></html>'''


# ---------------------------------------------------------------------------
# 集群模板
# ---------------------------------------------------------------------------
def _cfg(m, path, default="-"):
    cur = m
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return default
        else:
            return default
        if cur is None:
            return default
    if cur in (None, "", "N/A", "na", []):
        return default
    return cur if not isinstance(cur, (dict, list)) else default


def _summ(m, key):
    r = m.get("ranks", {})
    return r.get(key, "-")


def cluster_verdict_section(machines):
    """集群总结论：HERO 判定 + 机队构成带 + KPI + 逐机判定表 + 健康分条。"""
    verdicts = [m.get("health", {}).get("verdict", "未知") for m in machines]
    n_bad = sum(1 for v in verdicts if v == "不正常")
    n_risk = sum(1 for v in verdicts if "有风险" == v)
    n_ok = sum(1 for v in verdicts if v == "正常")
    n_base = sum(1 for v in verdicts if v.startswith("基本正常"))
    overall = "有机器存在严重问题" if n_bad else ("有机器存在风险" if n_risk else "整体正常")
    overall_cls = "bad" if n_bad else ("warn" if n_risk else "ok")
    vcls = {"bad": "v-bad", "ok": "v-ok"}.get(overall_cls, "")

    # 健康分条形：绝对加权分（100 − 扣分），而非组内相对归一化。
    # 相对归一化（100 - s/maxscore*100）会让"最差机器"恒为 0%、"最好机器"恒为 100%，
    # 无法反映绝对健康水平；改为固定权重扣分：P0=30 / P1=15 / P2=5 / P3=1，
    # 无任何问题的机器恒为 100%，跨集群/跨批次结果也可直接比较。
    def score(m):
        c = m.get("health", {}).get("counts", {})
        return c.get("P0", 0) * 30 + c.get("P1", 0) * 15 + c.get("P2", 0) * 5 + c.get("P3", 0) * 1
    scores = [max(0, 100 - score(m)) for m in machines]
    avg = round(sum(scores) / len(scores)) if scores else 0

    # 集群 KPI（带右上角状态点）
    kpis = kpi_block([
        (len(machines), "机器总数", ""),
        (n_ok, "正常", "ok" if n_ok else ""),
        (n_base, "基本正常", "warn" if n_base else "ok"),
        (n_risk, "有风险", "warn" if n_risk else "ok"),
        (n_bad, "不正常", "bad" if n_bad else "ok"),
        (f'{avg}<small>分</small>', "平均健康分",
         "bad" if avg < 60 else ("warn" if avg < 85 else "ok")),
    ])

    # 机队构成带（对应单机的 10 维健康带，4 格：按判定占比填充）
    total = max(1, len(machines))
    def _cdim(cls, n, name):
        pct = round(n / total * 100)
        return (f'<div class="dim {cls}"><div class="bar">'
                f'<i style="width:{pct}%"></i></div><div class="n">{name} {n}台</div></div>')
    dims_html = ('<div class="dim-strip" style="grid-template-columns:repeat(4,1fr)">'
                 + _cdim("bad", n_bad, "不正常")
                 + _cdim("warn" if n_risk else "", n_risk, "有风险")
                 + _cdim("warn" if n_base else "", n_base, "基本正常")
                 + _cdim("ok", n_ok, "正常")
                 + '</div>')
    hero = f'''<div class="verdict {vcls}">
        <div class="v-row">
          <div class="v-dot"></div>
          <div class="v-txt">集群判定：<em>{esc(overall)}</em></div>
        </div>
        <div class="v-sub">共 {len(machines)} 台 · 不正常 {n_bad} / 有风险 {n_risk} / 基本正常 {n_base} / 正常 {n_ok}</div>
        {dims_html}
      </div>
      <div class="score"><div class="num">{avg}<small>/100</small></div>
        <div class="lb">平均健康分</div>
        <div class="hint">口径与单机一致<br>100 −（P0×30 + P1×15 + P2×5 + P3×1）</div></div>'''

    # 判定对比表
    rows = ""
    for m in machines:
        ident = m.get("identity", {})
        h = m.get("health", {})
        r = m.get("ranks", {})
        counts = h.get("counts", {})
        v = h.get("verdict", "")
        vt = "p0" if v == "不正常" else ("p1" if ("有风险" == v or v.startswith("基本正常")) else "ok")
        rows += f'''<tr>
          <td><b>{esc(r.get("product_name") or ident.get("product_name") or "-")}</b><br><span class="badge mono">{esc(r.get("product_sn") or m.get("machine_tag"))}</span></td>
          <td class="mono">{val(r.get("ibmc"))}</td>
          <td class="mono">{val(r.get("bios"))}</td>
          <td><span class="tag {vt}">{esc(v)}</span></td>
          <td style="white-space:nowrap"><span class="tag p0">{counts.get("P0",0)}</span> <span class="tag p1">{counts.get("P1",0)}</span> <span class="tag p2">{counts.get("P2",0)}</span> <span class="tag p3">{counts.get("P3",0)}</span></td>
        </tr>'''
    verdict_tbl = f'''<div class="card"><h3>逐机判定</h3><table>
      <tr><th>机器</th><th>iBMC</th><th>BIOS</th><th>判定</th><th>问题分布 P0/P1/P2/P3</th></tr>{rows}</table></div>'''
    strips = ""
    for m, s_pct in zip(machines, scores):
        r = m.get("ranks", {})
        v = m.get("health", {}).get("verdict", "")
        color = "var(--ok)" if v == "正常" else ("var(--bad)" if v == "不正常" else "var(--warn)")
        strips += f'''<div class="cluster-strip"><div class="name">{esc(r.get("product_sn") or m.get("machine_tag"))}</div>
          <div style="flex:1"><div class="bar"><i style="width:{s_pct:.0f}%;background:{color}"></i></div></div>
          <span class="mono">{s_pct:.0f}分</span></div>'''
    health_tbl = f'<div class="card"><h3>健康分（100 − 加权扣分：P0=30/P1=15/P2=5/P3=1）</h3>{strips}</div>'
    return f'''<div class="section" id="cluster-verdict">
      <h2 class="sec"><span class="no">01</span>集群总结论<span class="src">跨机判定 · 与单机同口径</span></h2>
      <div class="hero">{hero}</div>
      {kpis}
      <div class="grid grid-2">{verdict_tbl}{health_tbl}</div>
    </div>'''


def cluster_issue_distribution(machines):
    """问题主题 × 机器 矩阵。"""
    topics = []
    for m in machines:
        for i in m.get("health", {}).get("issues", []):
            if i["topic"] not in topics:
                topics.append(i["topic"])
    # 按出现机器数降序
    topic_cnt = {t: sum(1 for m in machines if any(i["topic"] == t for i in m.get("health", {}).get("issues", []))) for t in topics}
    topics_sorted = sorted(topics, key=lambda t: -topic_cnt[t])
    head = "".join(f"<th>{esc(m.get('ranks',{}).get('product_sn') or m.get('machine_tag'))}</th>" for m in machines)
    rows = ""
    for t in topics_sorted[:25]:
        tds = ""
        for m in machines:
            hits = [i for i in m.get("health", {}).get("issues", []) if i["topic"] == t]
            if not hits:
                tds += "<td class='sub'>-</td>"
            else:
                worst = min(hits, key=lambda i: "P0P1P2P3OK".index(i["level"]) if i["level"] in "P0P1P2P3OK" else 9)
                tds += f"<td><span class='tag {worst['level'].lower()}'>{worst['level']}</span></td>"
        rows += f"<tr><td><b>{esc(t)}</b></td>{tds}</tr>"
    return f'''<div class="section" id="cluster-issues">
      <h2 class="sec"><span class="no">02</span>问题主题分布<span class="src">主题 × 机器矩阵 · 按覆盖机器数排序</span></h2>
      <div class="card"><div style="overflow-x:auto"><table class="cmp-table"><tr><th>问题主题</th>{head}</tr>{rows}</table></div>
      <div class="sub" style="margin:8px 0 0">横向看同一主题各机严重度，快速定位共性 / 单机问题。</div></div>
    </div>'''


def _bios_map(m):
    """返回该机器 {attr_name: {value, display, help, menu}}。"""
    out = {}
    for it in m.get("bios", {}).get("items", []) or []:
        out[it.get("name")] = it
    return out


# 多机温度曲线配色（深空控制台色系：青碧/琥珀/蓝/绿/红/紫，每台机器一种颜色，可循环）
_MACHINE_COLORS = ["#2DD4BF", "#FBBF24", "#60A5FA", "#34D399",
                   "#F87171", "#A78BFA", "#22D3EE", "#FDE047",
                   "#4ADE80", "#FB7185", "#38BDF8", "#C084FC"]


def _ts_to_unix(ts_str):
    """'2026/08/13 16:10:04' → unix 秒。失败返回 None。

    时间源为 iBMC 采样文件（env_web_view.dat / *_hbm_webview.dat）中的原始墙钟
    字符串，按本地时区解析（naive strptime + timestamp()），与 parse_bmc_collect.py
    侧 SEL 时间（同样按本地时区生成）口径一致，不涉及 UTC 换算。
    """
    try:
        from datetime import datetime
        dt = datetime.strptime(ts_str.strip(), "%Y/%m/%d %H:%M:%S")
        return int(dt.timestamp())
    except Exception:
        return None


def _machine_color(idx):
    return _MACHINE_COLORS[idx % len(_MACHINE_COLORS)]


def _machine_label(m):
    return (m.get("ranks", {}).get("product_sn") or m.get("machine_tag") or "?")


def cluster_temp_comparison(machines):
    """多机温度对比：环境温度 + NPU HBM 最高温度 叠加曲线（每台一种颜色）+ 当前温度快照表。"""
    if not machines:
        return ('<div class="section" id="cluster-temp"><h2 class="sec"><span class="no">03</span>多机温度对比<span class="src">Inlet / HBM 曲线叠加</span></h2>'
                '<div class="card sub">无机器数据，无法生成温度对比。</div></div>')
    out = '<div class="section" id="cluster-temp"><h2 class="sec"><span class="no">03</span>多机温度对比<span class="src">Inlet / HBM 曲线叠加 · 每台一色</span></h2>'

    # ---------- 1. 环境温度曲线（每台机器一条，X=真实时间戳 unix 秒） ----------
    env_series = []
    for idx, m in enumerate(machines):
        env = m.get("utilization", {}).get("env_temp", []) or []
        pts = []
        for e in env:
            ux = _ts_to_unix(e.get("time", ""))
            if ux is not None:
                try:
                    pts.append([ux, float(e.get("value"))])
                except (TypeError, ValueError):
                    continue
        if pts:
            env_series.append({"name": _machine_label(m), "color": _machine_color(idx),
                               "points": pts})
    if env_series:
        import json as _json
        spec = {"series": env_series,
                "opts": {"height": 300, "title": "Inlet 环境温度(°C) 趋势对比", "yLabel": "°C",
                         "threshold": {"value": 42, "color": "#F87171", "label": "42°C 上限"}}}
        cid = "ch-cluster-env"
        out += f'''<div class="card"><h3 style="margin-top:0">环境温度（Inlet）多机对比</h3>
          <div class="chart-box"><div class="chart-title">各机器进风温度趋势（同一时间轴，每台一色）</div>
          <div class="chart-sub">标准：&lt;42°C（Minor）/ &lt;46°C（Major）；采样约 10 分钟/点</div>
          <div id="{cid}" data-chart="{_json_safe(spec)}"></div></div></div>'''

    # ---------- 2. NPU HBM 最高温度对比（每台取 8 个 HBM 的最高值序列） ----------
    hbm_series = []
    for idx, m in enumerate(machines):
        hbm_files = m.get("utilization", {}).get("hbm_temp", []) or []
        # 把所有 HBM 文件的 (ts, val) 合并，按时间取最大值 → 该机 HBM 最高温度曲线
        aggr = {}
        for hf in hbm_files:
            for line in (hf.get("sample") or "").splitlines():
                line = line.strip()
                if "#" not in line:
                    continue
                t, _, v = line.partition("#")
                ux = _ts_to_unix(t)
                if ux is None:
                    continue
                try:
                    val = float(v.strip())
                except (TypeError, ValueError):
                    continue
                if ux not in aggr or val > aggr[ux]:
                    aggr[ux] = val
        if aggr:
            pts = sorted([ux, v] for ux, v in aggr.items())
            hbm_series.append({"name": _machine_label(m), "color": _machine_color(idx),
                               "points": pts})
    if hbm_series:
        spec = {"series": hbm_series,
                "opts": {"height": 300, "title": "NPU HBM 最高温度(°C) 对比", "yLabel": "°C",
                         "threshold": {"value": 95, "color": "#F87171", "label": "95°C 上限"}}}
        cid = "ch-cluster-hbm"
        out += f'''<div class="card"><h3 style="margin-top:0">NPU HBM 最高温度多机对比</h3>
          <div class="chart-box"><div class="chart-title">各机 8 个 NPU HBM 温度的最大值序列（每台一色）</div>
          <div class="chart-sub">标准：&lt;95°C；某机曲线显著高于其它 → 该机散热/负载异常</div>
          <div id="{cid}" data-chart="{_json_safe(spec)}"></div></div></div>'''

    # ---------- 3. 当前温度快照对比表 ----------
    rows = ""
    head = "".join(f"<th>{esc(_machine_label(m))}</th>" for m in machines)
    temp_rows_defs = []
    sensors_all = []
    for m in machines:
        sensors_all.append(m.get("sensors", []) or [])
    # 找共同的温度传感器名：先收集所有机器的传感器名并集（避免首台无数据时为空），
    # 再只保留每台机器都有的传感器
    snames = []
    for sl in sensors_all:
        for s in sl:
            if "degrees" in str(s.get("unit", "")) and s.get("name") not in snames:
                snames.append(s.get("name"))
    common = [n for n in snames if all(any(s.get("name") == n for s in sl) for sl in sensors_all)]
    for n in common[:12]:
        tds = ""
        for sl in sensors_all:
            hit = next((s for s in sl if s.get("name") == n), None)
            if hit:
                tds += f"<td class='mono'>{esc(hit.get('value'))}{esc(hit.get('unit',''))}</td>"
            else:
                tds += "<td class='sub'>-</td>"
        rows += f"<tr><td><b>{esc(n)}</b></td>{tds}</tr>"
    if rows:
        out += f'''<div class="card"><h3 style="margin-top:0">当前温度快照对比</h3>
          <div style="overflow-x:auto"><table class="cmp-table"><tr><th>传感器</th>{head}</tr>{rows}</table></div>
          <div class="sub" style="margin-top:8px">传感器来自 sensor_info.txt 当前快照；数值异常时结合上方曲线看趋势。</div></div>'''

    if not env_series and not hbm_series and not rows:
        # 三类数据全为空时给出明确提示，而不是渲染一个空白 section
        out += ('<div class="card sub">未采集到可对比的温度数据：'
                '缺少 env_web_view.dat / NPU HBM 采样文件，或时间戳/数值解析失败。</div>')

    out += "</div>"
    return out


def cluster_comparison(machines):
    """逐维度横向对比矩阵（分块 + 每列一机器 + 最后一列参数说明）。"""
    head = "".join(f"<th>{esc(m.get('ranks',{}).get('product_sn') or m.get('machine_tag'))}</th>" for m in machines)

    def _row(label, path_or_fn, doc, render=None):
        """生成一行：label | 各机值 | doc(说明)。"""
        vals = []
        for m in machines:
            if callable(path_or_fn):
                try:
                    v = path_or_fn(m)
                except Exception:
                    v = "-"
            else:
                v = _cfg(m, path_or_fn)
            vals.append(esc(v) if not callable(render) else esc(render(v)))
        uniq = {v for v in vals if v not in ("-", "", "&lt;null&gt;")}
        tds = ""
        for v in vals:
            if len(uniq) > 1 and v not in ("-", ""):
                tds += f'<td class="mono diff-hi">{v}</td>'
            else:
                tds += f'<td class="mono">{v}</td>'
        return f'<tr><td><b>{esc(label)}</b></td>{tds}<td class="sub" style="min-width:220px">{esc(doc)}</td></tr>'

    # ===== 分块定义 =====
    blocks = []
    # 1. 身份与版本
    rows = []
    rows += [_row("机型", "ranks.product_name", "产品名称（如 Atlas 800I A2 / HuaKun AT3500G3）"),
             _row("SN", "ranks.product_sn", "产品序列号，唯一标识一台机器"),
             _row("主板", "ranks.board_name", "主板产品名"),
             _row("型号", "ranks.model", "产品型号 Model"),
             _row("iBMC 版本", "ranks.ibmc", "iBMC 固件版本（Active）"),
             _row("Backup iBMC", "ranks.backup_ibmc", "备用 iBMC 版本"),
             _row("BIOS 版本", "ranks.bios", "BIOS 固件版本"),
             _row("CPLD", "ranks.cpld", "CPLD 版本"),
             _row("RTOS", "ranks.rtos", "RTOS 版本"),
             _row("主机名", "ranks.hostname", "iBMC 主机名"),
             _row("时区", "ranks.timezone", "iBMC 时区"),
             _row("收集时间", "ranks.collected_at", "日志收集时间")]
    blocks.append(("身份与版本", "identity", "".join(rows)))

    # 2. 硬件配置
    rows = []
    rows += [
        _row("CPU 颗数", "ranks.cpu_count", "CPU 物理颗数（标准 4 颗）"),
        _row("CPU 型号", "ranks.cpu_model", "CPU 型号（如 Kunpeng 920 5250）"),
        _row("内存条数", "ranks.mem_count", "内存 DIMM 条数"),
        _row("内存容量(GB)", "ranks.mem_total_gb", "内存总容量（GB）"),
        _row("内存异常", "ranks.mem_bad", "健康状态非 OK 的内存条数（应=0）"),
        _row("PSU 在位", "ranks.psu_present", "在位电源个数 / 总数（标准 4/4）"),
        _row("PSU Vin(V)", "ranks.psu_vin", "电源输入电压（标准≈220V, 180~264V）"),
        _row("PSU Vout(V)", "ranks.psu_vout", "电源输出电压（标准≈12V, 11.5~12.6V）"),
        _row("NPU 卡数", "ranks.npu_count", "NPU 卡数量（标准 8 卡）"),
        _row("NPU 单bit ECC", "ranks.npu_single_ecc", "NPU 单 bit ECC 累计（>0 需关注趋势）"),
        _row("NPU 多bit ECC", "ranks.npu_multi_ecc", "NPU 多 bit ECC 累计（>0=硬件故障 P0）"),
        _row("光模块数", "ranks.optical_count", "光模块在位数量（标准 8 个）"),
        _row("端口事件数", "ranks.port_events", "NPU 参数面端口 up/down 事件总数（频繁=链路不稳定）"),
        _row("风扇数", "ranks.fan_count", "风扇模块数量"),
        _row("NAND 寿命", "ranks.nand_lifetime", "BMC NAND Flash 剩余寿命（应>10%）"),
        _row("NAND 写入量", "ranks.nand_total_written", "BMC NAND Flash 累计写入量"),
    ]
    blocks.append(("硬件配置", "hardware", "".join(rows)))

    # 3. 温度与健康
    rows = []
    rows += [
        _row("进风温度(°C)", "ranks.inlet_temp", "Inlet Temp，标准 <42°C（Minor）/ <46°C（Major）"),
        _row("NPU HBM最高(°C)", "ranks.hbm_worst", "NPU HBM 最高温度，标准 <95°C"),
        _row("当前告警", "ranks.current_alarm", "当前活动告警（Critical/有内容/空）"),
        _row("LED 状态", lambda m: "; ".join(f"{k}:{v.get('State','')}/{v.get('Color','')}" for k, v in (m.get("led") or {}).items()), "系统指示灯 State/Color"),
    ]
    blocks.append(("温度与健康", "health", "".join(rows)))

    # 4. RAID / 存储
    rows = []
    rows += [
        _row("RAID 健康", "ranks.raid_health", "RAID 控制器健康状态（应=Normal）"),
        _row("RAID 模式", "ranks.raid_mode", "控制器模式（RAID/HBA/JBOD）"),
        _row("逻辑盘数", "ranks.logical_drives", "逻辑盘数量（生产机应≥1）"),
        _row("物理盘数", "ranks.physical_drives", "物理盘数量"),
        _row("RAID DDR ECC", lambda m: (m.get("raid") or {}).get("controller", {}).get("ddr_ecc", ""), "RAID 控制器 DDR ECC 计数（应=0）"),
    ]
    blocks.append(("RAID / 存储", "storage", "".join(rows)))

    # 5. 网络
    rows = []
    rows += [
        _row("管理 IP", "ranks.mgmt_ip", "管理网口 IPv4 地址"),
        _row("网络模式", "ranks.net_mode", "管理网口网络模式（Manual/DHCP）"),
        _row("VLAN 使能", "ranks.vlan", "Dedicated 端口 VLAN 使能（应 disabled）"),
        _row("LLDP 使能", lambda m: (m.get("lldp") or {}).get("LLDPEnable", ""), "LLDP 协议使能"),
    ]
    blocks.append(("网络配置", "network", "".join(rows)))

    # 6. BIOS 配置（全量比对）
    bios_names = []
    for m in machines:
        bm = _bios_map(m)
        for n in bm:
            if n not in bios_names:
                bios_names.append(n)
    bios_rows = []
    for name in bios_names:
        doc = ""
        vals = []
        for m in machines:
            it = _bios_map(m).get(name)
            if it:
                vals.append(it.get("value"))
                if not doc:
                    doc = (it.get("display_name") or "") + ((" — " + it.get("help_text")) if it.get("help_text") else "")
                    if it.get("menu_path"):
                        doc += f" [菜单: {it['menu_path']}]"
            else:
                vals.append("-")
        uniq = {str(v) for v in vals if v not in ("-", None, "")}
        tds = ""
        for v in vals:
            vs = esc(v)
            if len(uniq) > 1 and v not in ("-", None, ""):
                tds += f'<td class="mono diff-hi">{vs}</td>'
            else:
                tds += f'<td class="mono">{vs}</td>'
        bios_rows.append(f'<tr><td><b>{esc(name)}</b></td>{tds}<td class="sub" style="min-width:240px">{esc(doc)}</td></tr>')
    blocks.append((f"BIOS 配置（{len(bios_names)} 项）", "bios", "".join(bios_rows)))

    # 7. SEL / 事件
    rows = []
    rows += [
        _row("SEL 总数", "ranks.sel_count", "SEL 事件总条数"),
        _row("SEL Critical", "ranks.sel_critical", "SEL 中 CRITICAL 事件数"),
        _row("SEL Major", "ranks.sel_major", "SEL 中 MAJOR 事件数"),
    ]
    blocks.append(("SEL / 事件", "sel", "".join(rows)))

    # 8. 资产 / OS
    rows = []
    rows += [
        _row("SP OS", "ranks.os_name", "SP 操作系统版本"),
        _row("ESN", "ranks.esn", "产品 ESN（License 设备标识）"),
        _row("License 状态", "ranks.license_status", "License 状态（Undefined/Active 等）"),
    ]
    blocks.append(("资产 / OS", "assets", "".join(rows)))

    # 组装 HTML（每个分块一个编号 section + 锚点；不再有外层包裹 section）
    NO = {"identity": "04", "hardware": "05", "health": "06", "storage": "07",
          "network": "08", "bios": "09", "sel": "10", "assets": "11"}
    SRC = {"identity": "机型 / SN / 固件版本一致性",
           "hardware": "CPU / 内存 / PSU / NPU / 光模块 / NAND",
           "health": "温度 / 告警 / LED",
           "storage": "RAID 控制器 / 逻辑盘 / 物理盘",
           "network": "管理网口 / VLAN / LLDP",
           "bios": "全量配置逐项比对",
           "sel": "事件计数（Critical / Major）",
           "assets": "OS / ESN / License"}
    out = ""
    for label, anchor, rows_html in blocks:
        out += f'''<div class="section" id="cluster-{anchor}">
      <h2 class="sec"><span class="no">{NO.get(anchor, "")}</span>{esc(label)}<span class="src">{SRC.get(anchor, "")} · {len(machines)} 台对比</span></h2>
      <div class="card"><div style="overflow-x:auto"><table class="cmp-table">
        <tr><th>参数</th>{head}<th style="min-width:220px">参数说明</th></tr>{rows_html}</table></div>
      <div class="sub" style="margin:8px 0 0"><span class="diff-hi">黄色高亮</span> = 各机不一致项（配置漂移 / 差异）；最后一列为参数说明。</div></div>
    </div>'''

    return out


def cluster_machine_detail(machines):
    """每台机器详情（可折叠）。"""
    def _num(x):
        try:
            return int(str(x))
        except (TypeError, ValueError):
            return 0
    out = ('<div class="section" id="cluster-detail">'
           '<h2 class="sec"><span class="no">12</span>各机器详情<span class="src">可折叠 · 展开查看问题清单</span></h2>')
    for m in machines:
        ident = m.get("identity", {})
        sn = ident.get("product_sn") or m.get("machine_tag")
        h = m.get("health", {})
        verdict = h.get("verdict", "")
        r = m.get("ranks", {})
        mb = _num(r.get("mem_bad", 0))
        se = _num(r.get("npu_single_ecc", 0))
        me = _num(r.get("npu_multi_ecc", 0))
        np_c = _num(r.get("psu_count", 0))
        np_p = _num(r.get("psu_present", 0))
        vt = "p0" if verdict == "不正常" else ("p1" if ("有风险" == verdict or verdict.startswith("基本正常")) else "ok")
        tid = "m-" + re.sub(r'\W+', '', str(sn))[:20]
        out += f'''<div class="card">
          <h3 class="collapsible" data-target="{tid}">{esc(sn)} · {esc(ident.get('product_name') or '')} <span class="tag {vt}">{esc(verdict)}</span></h3>
          <div id="{tid}" style="margin-top:12px">
            {kpi_block([
              (f'{esc(r.get("cpu_count", "-"))}<small>颗</small>', "CPU", "ok"),
              (f'{esc(r.get("mem_count", "-"))}<small>条 · {esc(r.get("mem_total_gb", "-"))}GB</small>', "内存",
               "ok" if not mb else "warn"),
              (f'{esc(r.get("npu_count", "-"))}<small>卡</small>', "NPU",
               "bad" if me else ("warn" if se else "ok")),
              (f'{np_p}<small>/ {np_c} 在位</small>', "电源 PSU",
               "ok" if np_c and np_p == np_c else ("bad" if np_c else "")),
            ])}
            <h3 style="margin:12px 0 8px">问题清单</h3>
            {issues_section(m)}
          </div>
        </div>'''
    return out + '</div>'


def build_cluster_report(machines):
    title = f"BMC 集群诊断对比报告 · {len(machines)} 台机器"
    nav = f'''
    <div class="brand"><div class="sig">B</div><div><b>iBMC 诊断台</b><small>DIAG CONSOLE</small></div></div>
    <div class="grp">总览</div>
    <a data-target="cluster-verdict" href="#cluster-verdict">集群总结论</a>
    <a data-target="cluster-issues" href="#cluster-issues">问题主题分布</a>
    <a data-target="cluster-temp" href="#cluster-temp">多机温度对比</a>
    <div class="grp">对比分块</div>
    <a data-target="cluster-identity" href="#cluster-identity">身份与版本</a>
    <a data-target="cluster-hardware" href="#cluster-hardware">硬件配置</a>
    <a data-target="cluster-health" href="#cluster-health">温度与健康</a>
    <a data-target="cluster-storage" href="#cluster-storage">RAID / 存储</a>
    <a data-target="cluster-network" href="#cluster-network">网络配置</a>
    <a data-target="cluster-bios" href="#cluster-bios">BIOS 配置</a>
    <a data-target="cluster-sel" href="#cluster-sel">SEL / 事件</a>
    <a data-target="cluster-assets" href="#cluster-assets">资产 / OS</a>
    <div class="grp">机器明细</div>
    <a data-target="cluster-detail" href="#cluster-detail">各机器详情</a>'''
    # 每台机器一个导航项
    for m in machines:
        ident = m.get("identity", {})
        sn = ident.get("product_sn") or m.get("machine_tag")
        tid = "m-" + re.sub(r'\W+', '', str(sn))[:20]
        nav += f'<a data-target="{tid}" href="#{tid}">{esc(sn)}</a>'
    nav += '''
    <div class="foot">基于华为 iBMC 一键收集日志生成<br>依据 Atlas 26.1.0 交付标准</div>'''

    # 顶部识别条
    verdicts = [m.get("health", {}).get("verdict", "未知") for m in machines]
    n_bad = sum(1 for v in verdicts if v == "不正常")
    n_risk = sum(1 for v in verdicts if "有风险" == v)
    n_ok = sum(1 for v in verdicts if v == "正常")
    t_p0 = sum(int((m.get("health", {}).get("counts", {}) or {}).get("P0", 0) or 0) for m in machines)
    t_p1 = sum(int((m.get("health", {}).get("counts", {}) or {}).get("P1", 0) or 0) for m in machines)
    cols = sorted({m.get("ranks", {}).get("collected_at") or "" for m in machines} - {""})
    col = cols[-1] if cols else "-"
    crumb = f'''<div class="crumb">
      <span class="chip"><span class="k">机器数</span>{len(machines)}</span>
      <span class="chip"><span class="k">判定</span>不正常 {n_bad} / 有风险 {n_risk} / 正常 {n_ok}</span>
      <span class="chip"><span class="k">P0/P1</span>{t_p0} / {t_p1}</span>
      <span class="chip"><span class="k">采集</span>{esc(col)}</span>
    </div>'''

    # 分析先行：结论 → 问题 → 温度对比（异常线索）→ 逐维度矩阵（配置核查）→ 各机详情
    sections = cluster_verdict_section(machines)
    sections += cluster_issue_distribution(machines)
    sections += cluster_temp_comparison(machines)
    sections += cluster_comparison(machines)
    sections += cluster_machine_detail(machines)

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}</style></head>
<body>
<div class="layout">
  <nav>
    {nav}
  </nav>
  <main>
    <div class="content-wrap">
    <h1>{esc(title)}</h1>
    {crumb}
    {sections}
    </div>
  </main>
</div>
<script>{JS}</script>
</body></html>'''


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="生成 BMC 诊断 HTML 报告（单机/集群模板自动切换）")
    ap.add_argument("inputs", nargs="+", help="JSON 文件（或多机 all_machines_bmc.json）")
    ap.add_argument("-o", "--output", required=True, help="输出 HTML 文件")
    args = ap.parse_args()

    machines = []
    for inp in args.inputs:
        with open(inp, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "machines" in data:
            machines.extend(data["machines"])
        elif isinstance(data, list):
            machines.extend(data)
        else:
            machines.append(data)

    if len(machines) >= 2:
        html_doc = build_cluster_report(machines)
    else:
        html_doc = build_single_report(machines[0])
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"report written: {args.output} ({os.path.getsize(args.output)/1024:.1f} KB, {len(machines)} machine(s))")


if __name__ == "__main__":
    main()
