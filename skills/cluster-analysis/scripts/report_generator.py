#!/usr/bin/env python3
"""Phase 6: assemble all middleware into one self-contained HTML report.

Reads from the middleware directory:
  detect_result.json, advisor/advisor.{md,json} (unified, all cards; legacy
  advisor_rank{N}.{md,json} also supported), swimlane/swimlane_rank{N}.{md,json}
  (Thread/Stream/通信域 lanes), swimlane/swimlane_compare.md,
  compare/compare_analysis_result.json, cluster_analysis_output/recipes_summary.json

Three templates: --mode single | cluster | compare. All share a fixed left
sidebar navigation; the INFO OVERVIEW comes FIRST (section 1), followed by
CONCLUSIONS & SUGGESTIONS (section 2); cluster overview keeps the step
dimension (one rank may span multiple steps); advanced analysis is centralized
in one section grouped by the five categories; every major section is wrapped
in <details> so it can be folded; vendor sub-reports (cluster-analysis /
prof-compare HTML) are embedded in a dedicated section. No "card list
(cluster mode)" section is rendered.

Output: perf_report.html (dark theme, ECharts via CDN with table fallback).
"""
import argparse
import datetime
import glob
import html
import json
import os
import re
import sys

from lib.common import read_json

# ---------- 外置报告模板（scripts/report_assets/）----------
# 模板/样式/图表脚本与代码解耦：改报告外观无需动 Python 逻辑。
# chart_*.js 内含 {steps}/{series} 等 format 占位符，{{ }} 为转义大括号，与 str.format 配套。
ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'report_assets')


def _asset(name):
    path = os.path.join(ASSET_DIR, name)
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except OSError as e:
        print(f'ERROR: report asset missing: {path} ({e})', file=sys.stderr)
        sys.exit(1)


PAGE_CSS = _asset('page.css')
PAGE_JS = _asset('page.js')
TEMPLATE = _asset('template.html')
CLUSTER_CHART_JS = _asset('chart_cluster.js')
RANK_DIFF_CHART_JS = _asset('chart_rank_diff.js')


def read_text(path):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ''


def md_tables(md_text):
    """Parse markdown tables -> list of {header: [..], rows: [[..]]}."""
    tables = []
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith('|') and i + 1 < len(lines) and \
                re.match(r'^\|[\s\-|:]+\|$', lines[i + 1]):
            header = [c.strip() for c in lines[i].strip('|').split('|')]
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].startswith('|'):
                rows.append([c.strip() for c in lines[j].strip('|').split('|')])
                j += 1
            tables.append({'header': header, 'rows': rows})
            i = j
        else:
            i += 1
    return tables


class Raw(str):
    """Marker: cell content is already-escaped HTML; html_table must not escape it."""


def esc(v):
    return html.escape(str(v if v is not None else ''))


def ratio_text(value):
    return f'{value*100:+.1f}%' if isinstance(value, (int, float)) else str(value if value is not None else '—')


def overall_direction(compare):
    row = next((r for r in compare.get('overall_metrics', []) if r.get('Dimension') == 'E2E Time'), None)
    if not row or not isinstance(row.get('Diff(ms)'), (int, float)):
        return '整体快慢证据不足'
    delta = row['Diff(ms)']
    return f'E2E {"增加" if delta > 0 else "减少" if delta < 0 else "持平"} {abs(delta):.3f}ms（仅限对齐采集窗口）'


HEADER_ZH = {
    'step': '迭代', 'rank': '卡号', 'rank_id': '卡号', 'rankId': '卡号',
    'rank_set': '参与卡号', 'op': '算子', 'name': '名称', 'module': '模块',
    'group': '通信组', 'group_name': '通信组', 'pg_name': '并行组名',
    'hccl_op_name': '通信算子', 'votes': '候选次数', 'vote_ratio': '候选占比',
    'free(us)': '空闲时间(μs)', 'stage(us)': '阶段时间(μs)',
    'computing(us)': '计算时间(μs)', 'communication(us)': '通信时间(μs)',
    'overlapped(us)': '掩盖时间(μs)', 'not_overlapped(us)': '未掩盖通信时间(μs)',
    'free_ratio': '空闲占比', 'free_vs_computing': '空闲与计算时间比',
    'potential_gain(%)': '空闲占阶段时间(%，非收益承诺)',
    'masking_ratio': '通信掩盖率', 'wait_ratio': '等待占比',
    'bottleneck_type': '瓶颈类型', 'total_elapse(ms)': '累计通信时间(ms)',
    'total_wait(ms)': '累计等待时间(ms)', 'total_transit(ms)': '累计传输时间(ms)',
    'total_idle(ms)': '累计空转时间(ms)', 'count': '次数', 'total(ms)': '累计时间(ms)',
    'op_kinds': '算子种类数', 'metric': '指标', 'value(MHz)': '频率(MHz)',
    'api': '接口', 'transport_type': '传输类型', 'Input Shapes': '输入形状',
    'Input Data Types': '输入数据类型', 'Input Formats': '输入格式',
    'Output Shapes': '输出形状', 'Output Data Types': '输出数据类型',
    'Output Formats': '输出格式', 'Accelerator Core': '加速器核',
    'Block Dim': 'Block数量', 'Kernel': '核函数', '通信 Kernel': '通信核函数',
    'Diff(ms)': '差值(ms)', 'Diff(us)': '差值(μs)', 'Diff Ratio': '变化比例',
}


def chinese_header(value):
    value = str(value)
    if value in HEADER_ZH:
        return HEADER_ZH[value]
    if value.lower() in HEADER_ZH:
        return HEADER_ZH[value.lower()]
    m = re.fullmatch(r'rank(\d+)_(total\(ms\)|count|elapse\(ms\)|wait\(ms\)|transit\(ms\))', value)
    if m:
        label = {'total(ms)': '累计时间(ms)', 'count': '次数',
                 'elapse(ms)': '通信时间(ms)', 'wait(ms)': '等待时间(ms)',
                 'transit(ms)': '传输时间(ms)'}[m[2]]
        return f'{m[1]}卡{label}'
    for old, new in (('Rank 数', '卡数'), ('Step', '迭代'), ('Rank', '卡号'),
                     ('Stage', '阶段时间'), ('(us)', '(μs)')):
        value = value.replace(old, new)
    return value


def html_table(header, rows, cls='tbl', max_rows=None):
    if not header:
        return ''
    shown = rows[:max_rows] if max_rows else rows
    out = [f'<div class="tw"><table class="{cls}"><thead><tr>']
    out += [f'<th>{esc(chinese_header(h))}</th>' for h in header]
    out.append('</tr></thead><tbody>')
    for r in shown:
        cells = []
        for c in r:
            cells.append(str(c) if isinstance(c, Raw) else esc(c))
        out.append('<tr>' + ''.join(f'<td>{c}</td>' for c in cells) + '</tr>')
    out.append('</tbody></table></div>')
    if max_rows and len(rows) > max_rows:
        out.append(f'<p class="text-xs text-slate-500 mt-1">共 {len(rows)} 行，'
                   f'完整数据见中间件文件</p>')
    return ''.join(out)


def badge(text, kind='ok'):
    return f'<span class="badge badge-{kind}">{esc(text)}</span>'


def table_md_by_header(tables, first_cols):
    for t in tables:
        if t['header'][:len(first_cols)] == list(first_cols):
            return t
    return None


# ---------- shared helpers ----------

def cluster_dir(mw):
    """cluster_analysis_output: inside mw, else sibling of mw, else data root
    recorded in detect_result.json (input/cluster_output)."""
    d1 = os.path.join(mw, 'cluster_analysis_output')
    if os.path.isdir(d1):
        return d1
    d2 = os.path.join(os.path.dirname(mw), 'cluster_analysis_output')
    if os.path.isdir(d2):
        return d2
    det = read_json(os.path.join(mw, 'detect_result.json')) or {}
    co = det.get('cluster_output')
    if isinstance(co, dict):
        for key in ('path', 'expected_path'):
            if co.get(key) and os.path.isdir(co[key]):
                return co[key]
    root = det.get('cluster_root') or det.get('input')
    if root:
        d3 = os.path.join(root, 'cluster_analysis_output')
        if os.path.isdir(d3):
            return d3
    return d2


def cluster_rel(mw):
    """Relative href prefix from the final report to cluster_analysis_output."""
    d = cluster_dir(mw)
    if os.path.isdir(d):
        try:
            return os.path.relpath(d, mw).replace('\\', '/')
        except ValueError:  # cross-drive (e.g. mw on C:, data root on D:)
            return d.replace('\\', '/')
    return 'cluster_analysis_output'


def fold(section_html):
    """Wrap a <section id="..."> in <details open>, moving its <h2> into <summary>."""
    m = re.match(r'\s*<section id="([^"]+)">\s*<h2>(.*?)</h2>', section_html, re.S)
    if not m:
        return section_html
    sid, h2 = m.group(1), m.group(2)
    rest = section_html[m.end():]
    rest = re.sub(r'</section>\s*$', '', rest)
    return (f'<details class="sec" id="{sid}" open>'
            f'<summary><h2>{h2}</h2></summary>{rest}</details>')


# ---------- shared loaders ----------

def load_advisor(mw):
    """Unified advisor (advisor.json, covers all cards) or legacy per-rank files."""
    unified = read_json(os.path.join(mw, 'advisor', 'advisor.json'))
    if unified:
        md = read_text(os.path.join(mw, 'advisor', 'advisor.md'))
        return {'unified': True, 'data': unified, 'md': md, 'cards': []}
    cards = []
    for fp in sorted(glob.glob(os.path.join(mw, 'advisor', 'advisor_rank*.json'))):
        cards.append({'data': read_json(fp) or {},
                      'md': read_text(fp.replace('.json', '.md'))})
    if cards:
        return {'unified': False, 'data': cards[0]['data'], 'md': cards[0]['md'],
                'cards': cards}
    return None


def steps_ranks(ts_rows):
    steps = sorted({str(t['step']) for t in ts_rows},
                   key=lambda s: (len(s), s) if s.isdigit() else (99, s))
    ranks = sorted({t['rank'] for t in ts_rows})
    return steps, ranks


# ---------- section builders ----------

def sec_diagnosis(locator, num='2', title='瓶颈定位与解决'):
    """The only promoted findings are concrete, ranked Insight locations."""
    parts = [f'<section id="conclusions"><h2>{num}. {title}</h2>',
             '<h3>瓶颈定位与解决</h3>' if title != '瓶颈定位与解决' else '',
             f'<div class="card p-5"><p><b>{esc(locator.get("summary", "定位证据不足"))}</b></p></div>']
    for key, title in (('communication', '通信'), ('compute', '计算'), ('free', 'Free（设备空闲）')):
        findings = locator.get(key) or []
        parts.append(f'<div class="card p-5 mt-4"><h3>{title}</h3>')
        if findings:
            rows = [[r.get('location', '定位信息不足'), r.get('issue', ''),
                     r.get('impact', ''), r.get('cause', '')] for r in findings[:3]]
            parts.append(html_table(['Insight 定位', '主要问题', '影响程度', '可能原因与处理方向'], rows))
        else:
            parts.append(f'<p>{esc(locator.get(key + "_reason") or "当前证据未定位可确认的异常；数据不足不代表没有瓶颈。")}</p>')
        parts.append('</div>')
    limits = locator.get('limitations') or []
    if limits:
        parts.append('<p class="text-slate-400 text-sm mt-3">结论范围：' +
                     esc('；'.join(str(x) for x in limits)) + '</p>')
    parts.append('</section>')
    return ''.join(parts)


def compact_diagnosis_html(locator):
    """Offline entry point: three short evidence sections, no statistical appendix."""
    css = '''body{margin:0;background:#f5f7fb;color:#152238;font:15px/1.7 "Microsoft YaHei",sans-serif}
main{max-width:1440px;margin:auto;padding:32px}h1{font-size:25px;margin:0 0 8px}h2{font-size:21px}
h3{font-size:18px;color:#215794}p{margin:10px 0}.card{background:white;border:1px solid #dce4ef;border-radius:12px;padding:20px;margin:16px 0}
.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;table-layout:fixed}th,td{padding:12px;text-align:left;border-bottom:1px solid #e5eaf2;vertical-align:top;overflow-wrap:anywhere}
th{background:#eef3f9}th:first-child{width:39%}th:nth-child(2){width:14%}th:nth-child(3){width:18%}
.text-slate-400{color:#596a80}.text-sm{font-size:13px}@media(max-width:700px){main{padding:16px}table{min-width:900px}}'''
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Insight 关键瓶颈定位</title><style>' + css + '</style></head>'
            '<body><main><h1>Insight 关键瓶颈定位</h1>'
            '<p>按卡号、泳道、完整算子名和起始时间定位；每类只列最关键的点。</p>'
            + sec_diagnosis(locator, '1') + '</main></body></html>')


def sec_conclusions(advisor, cluster_summary, compare, mode, num='2', locator=None):
    if locator is not None:
        return sec_diagnosis(locator, num, title='结论与建议')
    items = []
    if advisor:
        a = advisor['data']
        prefix = '集群' if len(a.get('ranks', [])) > 1 else ''
        items.append(('High', f"{prefix}主导瓶颈：{a.get('dominant', '—')}；"
                              f"Stage 平均 {a.get('stage_ms', '—')}ms，"
                              f"计算 {(a.get('computing_ratio') or 0)*100:.0f}% / "
                              f"未掩盖通信 {(a.get('communication_ratio') or 0)*100:.0f}% / "
                              f"空闲 {(a.get('free_ratio') or 0)*100:.0f}%"))
        for adv in (a.get('advice') or [])[:5]:
            items.append((adv.get('level', 'Low'), adv.get('text', '')))
    if cluster_summary:
        ts = cluster_summary.get('time_summary', [])
        slow = cluster_summary.get('slow_rank', [])
        if ts:
            steps, ranks = steps_ranks(ts)
            avg_free = sum(t['free_ratio'] for t in ts) / len(ts)
            avg_comm = sum(t['comm_ratio'] for t in ts) / len(ts)
            worst = max(ts, key=lambda t: t['stage(us)'])
            items.append(('High', f"共 {len(ranks)} 个 rank × {len(steps)} 个 step："
                                  f"最慢组合为 step {worst['step']} / rank {worst['rank']}"
                                  f"（Stage {worst['stage(us)']/1000:.1f}ms）；"
                                  f"平均空闲占比 {avg_free*100:.1f}%，"
                                  f"未掩盖通信占比 {avg_comm*100:.1f}%"))
            if slow:
                items.append(('Medium', f"集合通信短耗时候选：rank {slow[0]['rank']} 在 "
                                      f"{slow[0]['vote_ratio']*100:.0f}% 的集合通信中"
                                      f"耗时最短；需到达时间戳交叉验证，不能直接认定慢卡"))
        bott = [r for r in cluster_summary.get('top_bottleneck_ops', [])
                if str(r.get('bottleneck_type', '')).startswith('wait')]
        if bott:
            items.append(('Medium', f"存在 {len(bott)} 个等待型通信算子"
                                    f"（如 {bott[0]['op']}）：各卡到达时间差大，"
                                    f"需结合到达时间与链路数据验证原因"))
    if compare:
        ins = compare.get('insights', {})
        ov = ins.get('overall', {})
        if isinstance(ov, dict):
            dm = ov.get('degraded_max')
            im = ov.get('improved_max')
            if dm:
                dim = dm.get('dimension') or dm.get('Dimension')
                items.append(('Medium', f"双卡比对：{dim} 劣化 {dm['diff_ratio']*100:+.1f}%"
                                        f"（{dm['diff_ms']}ms）；{overall_direction(compare)}"))
            if im:
                dim = im.get('dimension') or im.get('Dimension')
                items.append(('Low', f"双卡比对：{dim} 改善 {im['diff_ratio']*100:+.1f}%"))
        op_ins = ins.get('operator', {})
        if op_ins.get('top_degraded'):
            t = op_ins['top_degraded'][0]
            items.append(('Medium', f"比对劣化最大算子：{t['Op Type']}"
                                    f"（{t['Diff Duration(ms)']}ms，"
                                    f"{ratio_text(t.get('Diff Ratio'))}）"))
    if not items:
        items.append(('Low', '无可用中间件结论，详见各章节明细。'))
    order = {'High': 0, 'Medium': 1, 'Low': 2}
    items.sort(key=lambda x: order.get(x[0], 3))
    kind_map = {'High': 'critical', 'Medium': 'warn', 'Low': 'ok'}
    rows = [[Raw(badge(lv, kind_map.get(lv, 'ok'))), txt] for lv, txt in items]
    return f'''
<section id="conclusions">
  <h2>{num}. 结论与建议</h2>
  <div class="card p-5">{html_table(['优先级', '结论'], rows)}</div>
  <p class="text-xs text-slate-500 mt-3">结论由中间件自动汇聚生成；关键数值请以各章节明细表为准。</p>
</section>'''


def sec_overview(detect, advisor, cluster_summary, mode, num='1'):
    cards = detect.get('cards', [])
    a = (advisor or {}).get('data') or {}
    coverage = detect.get('coverage') or {}
    world = coverage.get('expected_world_size')
    observed = coverage.get('observed_ranks', [])
    missing = coverage.get('missing_ranks', [])
    coverage_html = ('<div class="card p-5 mt-4"><h3>数据覆盖与结论范围</h3>'
                     f'<p>已提供 {len(observed)}/{world if world is not None else "未知"} rank；'
                     f'唯一 step：{coverage.get("unique_step_count", "未知")}；'
                     f'rank-step 样本：{coverage.get("rank_step_samples", "未知")}。'
                     f'缺失 rank：{esc(missing if missing else "无或未知")}。'
                     '结论仅限已提供的 rank 与采集窗口；不据此定位未提供 rank 的瓶颈。</p></div>') if coverage else ''
    whole_ranks = coverage.get('synthetic_step_ranks', [])
    if whole_ranks:
        coverage_html += ('<div class="card p-5 mt-4"><h3>整段 prof 汇总口径</h3>'
                          f'<p>rank {esc(whole_ranks)} 未提供分步标识，整个 prof 作为一个汇总 step（prof）。'
                          '每卡只计 1 个分析 step；它不代表一次训练迭代或一个推理请求。'
                          f'原始有效 step 标识数：{coverage.get("known_step_count", 0)}。'
                          '比较以各卡提供的采集范围为准；时窗和负载等价需另行核验。</p></div>')
    missing_metrics = {rank: value.get('missing_required') for rank, value in (a.get('per_rank') or {}).items()
                       if value.get('missing_required')}
    if missing_metrics:
        coverage_html += ('<div class="card p-5 mt-4"><h3>部分摘要指标未知</h3>'
                          f'<p>{esc(missing_metrics)}。相关占比不具备诊断依据；'
                          '兼容表中的缺省数字不是实测值，请使用已有绝对时间与事件证据。</p></div>')
    kpis = []
    ts = (cluster_summary or {}).get('time_summary', [])
    if mode != 'single' and ts:
        steps, ranks = steps_ranks(ts)
        avg_stage = sum(t['stage(us)'] for t in ts) / len(ts) / 1000
        kpis = [
            ('Rank 数', f'{len(ranks)}', '个', 'text-blue-400', '🖥️'),
            ('Step 数', f'{len(steps)}', '个/卡', 'text-purple-400', '🪜'),
            ('平均 Stage', f'{avg_stage:.1f}', 'ms', 'text-sky-400', '⏱️'),
            ('计算占比', f"{sum(t['computing_ratio'] for t in ts)/len(ts)*100:.1f}", '%',
             'text-emerald-400', '⚙️'),
            ('未掩盖通信占比', f"{sum(t['comm_ratio'] for t in ts)/len(ts)*100:.1f}", '%',
             'text-orange-400', '📡'),
            ('空闲占比', f"{sum(t['free_ratio'] for t in ts)/len(ts)*100:.1f}", '%',
             'text-amber-400', '💤'),
        ]
    else:
        kpis = [
            ('卡数', f'{max(len(cards), 1)}', '', 'text-blue-400', '🖥️'),
            ('主导瓶颈', a.get('dominant', '—'), '', 'text-orange-400', '🎯'),
            ('Stage', a.get('stage_ms', '—'), 'ms', 'text-purple-400', '⏱️'),
            ('计算占比', f"{(a.get('computing_ratio') or 0)*100:.1f}", '%',
             'text-emerald-400', '⚙️'),
            ('通信占比', f"{(a.get('communication_ratio') or 0)*100:.1f}", '%',
             'text-orange-400', '📡'),
            ('空闲占比', f"{(a.get('free_ratio') or 0)*100:.1f}", '%',
             'text-amber-400', '💤'),
        ]
    if missing_metrics:
        keys = {key for values in missing_metrics.values() for key in values}
        mapping = {'计算占比': 'Computing', '未掩盖通信占比': 'Communication(Not Overlapped)',
                   '通信占比': 'Communication(Not Overlapped)', '空闲占比': 'Free'}
        kpis = [(k[0], '未知', '', k[3], k[4])
                if mapping.get(k[0]) in keys or ('Stage' in keys and k[0] in mapping)
                else k for k in kpis]
    kpi_html = ''.join(
        f'<div class="card p-5 relative overflow-hidden"><div class="text-slate-400 text-sm mb-1">'
        f'{k[0]}</div><div class="text-3xl font-bold {k[3]}">{k[1]}'
        f'<span class="text-lg text-slate-500"> {k[2]}</span></div>'
        f'<div class="absolute -right-3 -bottom-4 opacity-10 text-6xl">{k[4]}</div></div>'
        for k in kpis)
    # 概览小结：自动解读 KPI 结构，给出最可能的问题方向
    if missing_metrics:
        ov_summary = ('<div class="card p-5 mt-4"><h3>概览小结</h3>'
                      '<p>部分摘要指标未知；不能确定时间结构或主导瓶颈。'
                      '整个 prof 的范围和已有绝对事件证据仍可查看。</p></div>')
    elif mode != 'single' and ts:
        c_pct = sum(t['computing_ratio'] for t in ts) / len(ts)
        m_pct = sum(t['comm_ratio'] for t in ts) / len(ts)
        f_pct = sum(t['free_ratio'] for t in ts) / len(ts)
        struct = {'计算': c_pct, '未掩盖通信': m_pct, '空闲': f_pct}
        top_part = max(struct, key=struct.get)
        hint = {
            '计算': '计算占主导，属计算密集负载，优化重点在算子效率与融合。',
            '未掩盖通信': '未掩盖通信占主导，多为等待型通信或负载不均，'
                       '优化重点在计算/通信掩盖与慢卡处理。',
            '空闲': '空闲占主导，多为 Host 下发不足或调度空隙，'
                  '优化重点在提升下发并发度。',
        }[top_part]
        ov_summary = (f'<div class="card p-5 mt-4"><h3>概览小结</h3>'
                      f'<p>本次采集覆盖 <b class="text-blue-400">{len(ranks)}</b> 个 rank × '
                      f'<b class="text-purple-400">{len(steps)}</b> 个 step，平均 Stage '
                      f'<b class="text-sky-400">{avg_stage:.1f}ms</b>；时间结构为计算 '
                      f'{c_pct*100:.1f}% / 未掩盖通信 {m_pct*100:.1f}% / 空闲 {f_pct*100:.1f}%。'
                      f'占比最高的是 <b class="text-orange-400">{top_part}</b>'
                      f'（{struct[top_part]*100:.1f}%）——{hint}'
                      f'建议结合"结论与建议"章节与对应进阶分析类别深入定位。</p></div>')
    else:
        dom = str(a.get('dominant', '—') or '—')
        ov_summary = (f'<div class="card p-5 mt-4"><h3>概览小结</h3>'
                      f'<p>本次共识别 {max(len(cards), 1)} 张卡；主导瓶颈为 '
                      f'<b class="text-orange-400">{esc(dom)}</b>，'
                      f'Stage {a.get("stage_ms", "—")}ms，时间结构为计算 '
                      f'{(a.get("computing_ratio") or 0)*100:.1f}% / 通信 '
                      f'{(a.get("communication_ratio") or 0)*100:.1f}% / 空闲 '
                      f'{(a.get("free_ratio") or 0)*100:.1f}%。'
                      f'建议从"专家建议"章节入手，按瓶颈类型跳转到对应进阶分析明细。</p></div>')
    cards_html = ''
    if mode == 'single' and cards:
        cards_html = ('<div class="card p-5 mt-4"><h3>卡片清单</h3>' + html_table(
            ['rank', '数据目录', '格式', '框架', '可用'],
            [[c['rank'], c['dir'], c['format'], c.get('framework'),
              '✓' if c.get('usable') else '✗'] for c in cards]) + '</div>')
    return f'''
<section id="overview">
  <h2>{num}. 数据概览</h2>
  {coverage_html}
  <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">{kpi_html}</div>
  {ov_summary}
  {cards_html}
</section>'''


def sec_cluster(cluster_summary, num='3'):
    ts = (cluster_summary or {}).get('time_summary', [])
    if not ts:
        return ''
    steps, ranks = steps_ranks(ts)

    # per (step, rank) detail — a rank may span multiple steps
    detail_rows = [[t['step'], t['rank'], f"{t['stage(us)']/1000:.1f}",
                    f"{t['computing(us)']/1000:.1f}",
                    f"{t['communication_not_overlapped(us)']/1000:.1f}",
                    f"{t['free(us)']/1000:.1f}",
                    f"{t['computing_ratio']*100:.1f}%", f"{t['comm_ratio']*100:.1f}%",
                    f"{t['free_ratio']*100:.1f}%"] for t in ts]
    detail_tbl = html_table(
        ['Step', 'Rank', 'Stage(ms)', '计算(ms)', '未掩盖通信(ms)', '空闲(ms)',
         '计算占比', '通信占比', '空闲占比'], detail_rows, max_rows=80)

    # per-step aggregation across ranks
    by_step = {}
    for t in ts:
        by_step.setdefault(str(t['step']), []).append(t)
    comp_avg = [round(sum(m['computing(us)'] for m in by_step.get(s, [])) /
                      max(len(by_step.get(s, [])), 1) / 1000, 2) for s in steps]
    comm_avg = [round(sum(m['communication_not_overlapped(us)'] for m in by_step.get(s, [])) /
                      max(len(by_step.get(s, [])), 1) / 1000, 2) for s in steps]
    free_avg = [round(sum(m['free(us)'] for m in by_step.get(s, [])) /
                      max(len(by_step.get(s, [])), 1) / 1000, 2) for s in steps]

    # 部分维度分组柱状图：x=计算/通信/free 三分类，每个分类内每个 step 一根柱，
    # 展现计算、通信、free 各部分耗时在不同 step 之间的差异（跨 rank 平均）
    part_series = [{'name': f'step {s}', 'type': 'bar',
                    'data': [comp_avg[i], comm_avg[i], free_avg[i]]}
                   for i, s in enumerate(steps)]
    part_chart_data = {'categories': json.dumps(['计算', '通信', 'free']),
                       'series': json.dumps(part_series)}
    step_rows = []
    for s in steps:
        members = by_step.get(s, [])
        n = max(len(members), 1)
        stage_avg = sum(m['stage(us)'] for m in members) / n / 1000
        worst = max(members, key=lambda m: m['stage(us)'])
        spread = (max(m['stage(us)'] for m in members) -
                  min(m['stage(us)'] for m in members)) / 1000 if len(members) > 1 else 0
        step_rows.append([s, len(members), f'{stage_avg:.1f}',
                          f"{sum(m['computing(us)'] for m in members)/n/1000:.1f}",
                          f"{sum(m['communication_not_overlapped(us)'] for m in members)/n/1000:.1f}",
                          f"{sum(m['free(us)'] for m in members)/n/1000:.1f}",
                          f"step{s}/rank{worst['rank']}", f'{spread:.1f}'])
    step_tbl = html_table(
        ['Step', 'Rank 数', '平均 Stage(ms)', '平均计算(ms)', '平均未掩盖通信(ms)',
         '平均空闲(ms)', '最慢组合', 'Stage 极差(ms)'], step_rows, max_rows=40)

    chart_data = {
        'steps': json.dumps(steps),
        'comp': json.dumps(comp_avg),
        'comm': json.dumps(comm_avg),
        'free': json.dumps(free_avg),
    }

    slow = (cluster_summary or {}).get('slow_rank', [])
    slow_html = ''
    if slow:
        s0 = slow[0]
        slow_html = (f'<div class="card p-5 mt-4"><h3>短通信耗时候选（需验证到达时间）</h3>'
                     f'<p>rank <b class="text-red-400">{s0["rank"]}</b> 在 '
                     f'{s0["vote_ratio"]*100:.1f}% 的集合通信中耗时最短。'
                     f'这仅提供慢卡候选，需要结合各卡到达时间和下发/设备依赖验证'
                     f'（共 {s0["votes"]} 次投票）。</p>'
                     + html_table(['Rank', '投票数', '占比'],
                                  [[r['rank'], r['votes'], f"{r['vote_ratio']*100:.1f}%"]
                                   for r in slow]) + '</div>')

    # 集群小结：自动汇总时间结构与最慢/波动最大的 step
    total_stage = sum(_f(r[2]) for r in step_rows) or 1.0
    c_share = sum(_f(r[3]) for r in step_rows) / total_stage
    m_share = sum(_f(r[4]) for r in step_rows) / total_stage
    f_share = sum(_f(r[5]) for r in step_rows) / total_stage
    slow_row = max(step_rows, key=lambda r: _f(r[2]))
    vola_row = max(step_rows, key=lambda r: _f(r[7]))
    vola_pct = _f(vola_row[7]) / _f(slow_row[2]) * 100 if _f(slow_row[2]) else 0
    cluster_note = f'''<div class="card p-5 mt-4"><h3>集群小结</h3>
<p>全部 step 合计时间结构：计算 <b class="text-emerald-400">{c_share*100:.1f}%</b> /
未掩盖通信 <b class="text-orange-400">{m_share*100:.1f}%</b> /
空闲 <b class="text-amber-400">{f_share*100:.1f}%</b>。最慢 step 为
<b class="text-red-400">step {esc(str(slow_row[0]))}</b>（平均 Stage {slow_row[2]}ms，
最慢组合 {esc(str(slow_row[6]))}）；step 间波动最大的是 step {esc(str(vola_row[0]))}
（Stage 极差 {vola_row[7]}ms，约为其平均 Stage 的 {vola_pct:.0f}%）。</p>
<p class="text-slate-400 text-sm mt-2">解读：未掩盖通信或空闲占比高，通常指向等待型通信、
负载不均或 Host 下发不足，优先对照"进阶分析"的通信类 / Host 下发类条目与慢卡识别结果；
若结构稳定且计算占主导，则重点看计算类条目与 Top 耗时算子。</p></div>'''

    return f'''
<section id="cluster">
  <h2>{num}. 集群总览（Step × Rank）</h2>
  <div class="card p-5"><h3>按 Step 聚合（各 rank 平均）</h3>{step_tbl}</div>
  <div class="card p-5 mt-4"><h3>Step × Rank 明细（同一 rank 的多个 step 分行展示）</h3>{detail_tbl}</div>
  <div class="card p-5 mt-4"><h3>计算 / 通信 / free 三部分的 Step 间耗时差异（ms）</h3>
  <p class="text-slate-400 text-sm mb-2">横轴为计算、通信、free 三个部分；每部分内的多根柱子对应不同 step
  （跨 rank 平均），用于观察各部分耗时在不同 step 之间的波动与差异。</p>
  <div id="chart-part-step" style="width:100%;height:420px;"></div></div>
  <script>{RANK_DIFF_CHART_JS.format(**part_chart_data)}</script>
  {slow_html}
  <div class="card p-5 mt-4"><h3>各 Step 平均时间分解（ms，跨 rank 平均）</h3>
  <div id="chart-cluster" style="width:100%;height:360px;"></div></div>
  <script>{CLUSTER_CHART_JS.format(**chart_data)}</script>
  {cluster_note}
</section>'''


def sec_advisor(advisor, mw, num='4'):
    if not advisor:
        return ''
    a = advisor['data']
    md = advisor['md']
    tables = md_tables(md)

    inner = ''
    if advisor['unified']:
        scope = '整体（全部卡）' if len(a.get('ranks', [])) > 1 else '单卡'
        ranks = ', '.join(str(r) for r in a.get('ranks', []))
        step_text = (f'每卡 1 个整段汇总 step；{a.get("steps")} 个 rank-step 样本'
                     if a.get('step_scope') == 'whole_prof' else f'{a.get("steps")} 个 rank-step 样本')
        def ratio_text(key):
            value = a.get(key)
            return '未知' if value is None else f'{value * 100:.0f}%'
        inner = (f'<p>分析范围：<b>{esc(scope)}</b> · 覆盖 Rank：{esc(ranks)} · '
                 f'主导瓶颈：{badge(a.get("dominant", "—"), "warn")} · '
                 f'Stage {a.get("stage_ms")} ms · {step_text} · '
                 f'计算 {ratio_text("computing_ratio")} / '
                 f'通信 {ratio_text("communication_ratio")} / '
                 f'空闲 {ratio_text("free_ratio")} · '
                 f'Top 算子 <code>{esc(a.get("top_op") or "—")}</code></p>')
    else:
        cards_html = []
        for c in advisor['cards']:
            ca = c['data']
            rank = ca.get('rank', os.path.basename(
                glob.glob(os.path.join(mw, 'advisor', 'advisor_rank*.json'))[0]))
            cards_html.append(f'<div class="card p-5"><h3>Rank {esc(rank)}</h3>'
                              f'<p>主导瓶颈：{badge(ca.get("dominant", "—"), "warn")} · '
                              f'Stage {ca.get("stage_ms")} ms</p></div>')
        inner = ''.join(cards_html)
        a = advisor['cards'][0]['data']
        tables = md_tables(advisor['cards'][0]['md'])

    advice_tbl = table_md_by_header(tables, ['优先级', '建议'])
    if advice_tbl:
        kind_map = {'High': 'critical', 'Medium': 'warn', 'Low': 'ok'}
        rows = [[Raw(badge(r[0], kind_map.get(r[0], 'ok'))), r[1]]
                for r in advice_tbl['rows'][:10]]
        inner += ('<div class="card p-5 mt-4"><h3>建议清单</h3>'
                  + html_table(['优先级', '建议'], rows) + '</div>')

    top_ops = table_md_by_header(tables, ['算子', '总耗时(ms)'])
    if top_ops:
        inner += ('<div class="card p-5 mt-4"><h3>Top 10 耗时算子（全部卡聚合）</h3>'
                  + html_table(top_ops['header'], top_ops['rows'][:10]) + '</div>')

    top_comm = table_md_by_header(tables, ['算子', 'Elapse'])
    if top_comm:
        inner += ('<div class="card p-5 mt-4"><h3>Top 10 通信算子（全部卡聚合，ms）</h3>'
                  + html_table(top_comm['header'], top_comm['rows'][:10]) + '</div>')

    per_rank = table_md_by_header(tables, ['Rank', 'Step数'])
    if per_rank:
        inner += ('<div class="card p-5 mt-4"><h3>各 Rank 时间分解</h3>'
                  + html_table(per_rank['header'], per_rank['rows']) + '</div>')

    # 瓶颈解读：把主导瓶颈映射到优化方向与对应进阶分析类别
    dom_key = str(a.get('dominant', '')).lower()
    if 'comm' in dom_key:
        dom_text = ('属于通信瓶颈：优先排查等待型通信与负载不均，评估计算/通信掩盖与切分策略，'
                    '可对照"进阶分析-通信类特性"与慢卡识别结果。')
    elif 'free' in dom_key:
        dom_text = ('属于空闲瓶颈：多为 Host 下发不足或调度空隙，优先提升并发度、'
                    '削减 host 算子，可对照"进阶分析-Host 下发类特性"与泳道统计。')
    elif 'comp' in dom_key:
        dom_text = ('属于计算瓶颈：优先排查低效算子与融合机会，关注 AI Core 频率，'
                    '可对照"进阶分析-计算类特性"与 Top 耗时算子。')
    else:
        dom_text = '瓶颈类型未显式识别，请结合下方建议清单与各明细表判断优化方向。'
    inner += (f'<div class="card p-5 mt-4"><h3>瓶颈解读</h3>'
              f'<p>主导瓶颈 <b class="text-orange-400">{esc(str(a.get("dominant", "—") or "—"))}</b>：'
              f'{dom_text}</p></div>')

    link = 'advisor/advisor.md' if advisor['unified'] else 'advisor/'
    inner += (f'<p class="text-xs text-slate-500 mt-2">完整报告：'
              f'<a href="{esc(link)}" target="_blank">{esc(link)}</a></p>')
    return f'''
<section id="advisor">
  <h2>{num}. 专家建议（advisor，整体口径）</h2>
  <div class="card p-5">{inner}</div>
</section>'''


# detail tables attached to each advanced-analysis category
RECIPE_DETAIL_DEFS = {
    'decomposition_compare': [
        ('module_statistic', 'module_statistic — PyTorch 模块热点 Top 15',
         ['module', 'total(ms)', 'count', 'op_kinds']),
    ],
    'compute': [
        ('freq_analysis', 'freq_analysis — AI Core 频率分布（MHz）',
         ['metric', 'value(MHz)']),
        ('masking', 'computational_op_masking — 计算通信掩盖（Top 20）',
         ['step', 'rank', 'communication(us)', 'overlapped(us)',
          'not_overlapped(us)', 'masking_ratio']),
    ],
    'communication': [
        ('slow_rank', 'slow_rank — 慢卡投票',
         ['rank', 'votes', 'vote_ratio']),
        ('top_bottleneck_ops', 'communication_bottleneck — 通信瓶颈分类（Top 10）',
         None),
        ('hccl_sum', 'hccl_sum — 通信算子汇总 Top 10（含各 rank 拆分）', None),
        ('pp_chart', 'pp_chart — PP 流水阶段耗时（Top 20）',
         None),
    ],
    'host_dispatch': [
        ('cann_api_sum', 'cann_api_sum — CANN 层 API 汇总 Top 10（含各 rank）', None),
        ('free_analysis', 'free_analysis — Device 空闲分析（Top 20）', None),
    ],
}


def sec_recipes(cluster_summary, mw, num='5'):
    if not cluster_summary:
        return ''
    categories = cluster_summary.get('categories', [])
    if not categories:
        return ''
    parts = [f'''<section id="recipes"><h2>{num}. 进阶分析（五大类集中展示）</h2>
<p class="text-slate-400 text-sm mb-3">五大类进阶分析（拆解对比类、计算类特性、通信类特性、
Host 下发类特性、其他特性）直接展示分析结果；未支持项与完整能力清单见文末 recipes_summary.md。</p>''']
    for cat in categories:
        cat_title = cat.get('title', cat.get('key', ''))
        cat_parts = []
        for key, subtitle, header in RECIPE_DETAIL_DEFS.get(cat.get('key', ''), []):
            rows = cluster_summary.get(key) or []
            if not rows:
                continue
            hdr = header
            if hdr is None:
                hdr = list(rows[0].keys())
            data = [[row.get(c, '') for c in hdr] for row in rows]
            cat_parts.append(f'<div class="mt-4"><h4 class="sub-t">{esc(subtitle)}</h4>'
                             + html_table(hdr, data, max_rows=20) + '</div>')
        if cat_parts:
            parts.append('<div class="card p-5 mt-4"><h3>' + esc(cat_title) + '</h3>'
                         + ''.join(cat_parts) + '</div>')
    crel = cluster_rel(mw)
    md_link = f'{crel}/recipes_summary.md'
    parts.append(f'<p class="text-xs text-slate-500 mt-2">完整汇总：'
                 f'<a href="{esc(md_link)}" target="_blank">recipes_summary.md</a> · '
                 f'明细 CSV：<a href="{crel}/recipes/" target="_blank">'
                 f'recipes/</a></p>')
    parts.append('</section>')
    return ''.join(parts)


def sec_compare(compare, num='6'):
    if not compare:
        return ''
    base = compare.get('base_card', {})
    comp = compare.get('compare_card', {})
    ov = compare.get('overall_metrics', [])
    ins = compare.get('insights', {})
    rows = [[r['Dimension'], r.get('Baseline(ms)'), r.get('Compare(ms)'),
             r.get('Diff(ms)'),
             f"{r['Diff Ratio']*100:+.1f}%" if isinstance(r.get('Diff Ratio'),
                                                            (int, float))
             else r.get('Diff Ratio')] for r in ov]
    base_pct = f"{base.get('comm_ratio')*100:.1f}%" if base.get('comm_ratio') is not None else '?'
    comp_pct = f"{comp.get('comm_ratio')*100:.1f}%" if comp.get('comm_ratio') is not None else '?'
    parts = [f'''<section id="compare"><h2>{num}. 双卡比对（通信占比最大 vs 最小）</h2>
<div class="card p-5">
<p>基线：rank <b>{base.get('rank')}</b>（通信占比 {base_pct}）
&nbsp;⇄&nbsp; 比对：rank <b>{comp.get('rank')}</b>（通信占比 {comp_pct}）</p>
<h3>总体指标</h3>{html_table(['维度', '基线(ms)', '比对(ms)', 'Diff(ms)', 'Diff Ratio'], rows)}</div>''']
    op_ins = ins.get('operator', {})
    if op_ins.get('top_degraded'):
        rows = [[r['Op Type'], r['Baseline Total Time(ms)'], r['Compare Total Time(ms)'],
                 r['Diff Duration(ms)'],
                 f"{r['Diff Ratio']*100:+.0f}%" if isinstance(r.get('Diff Ratio'),
                                                                (int, float))
                 else r.get('Diff Ratio')] for r in op_ins['top_degraded'][:10]]
        conc = op_ins.get('degradation_concentration_top10')
        note = f'（Top10 集中度 {conc*100:.0f}%）' if conc is not None else ''
        parts.append(f'<div class="card p-5 mt-4"><h3>劣化 Top 算子 {note}</h3>'
                     + html_table(['算子', '基线(ms)', '比对(ms)', 'Diff(ms)', 'Diff Ratio'],
                                  rows) + '</div>')
    k_ins = ins.get('kernel', {})
    if k_ins.get('significant_degraded_top10'):
        rows = [[r['Kernel Name'], r['Baseline Total(us)'], r['Compare Total(us)'],
                 r['Diff Total(us)'], r['Baseline Calls'], r['Compare Calls']]
                for r in k_ins['significant_degraded_top10'][:10]]
        parts.append(f'<div class="card p-5 mt-4"><h3>显著劣化 Kernel（ratio&gt;5%）'
                     f'共 {k_ins.get("significant_degraded_count", 0)} 个，Top 10</h3>'
                     + html_table(['Kernel', '基线(us)', '比对(us)', 'Diff(us)', '基线次数',
                                   '比对次数'], rows) + '</div>')
    if k_ins.get('comm_kernel_top10'):
        rows = [[r['Kernel Name'], r['Baseline Total(us)'], r['Compare Total(us)'],
                 r['Diff Total(us)'], r['Baseline Calls'], r['Compare Calls']]
                for r in k_ins['comm_kernel_top10'][:10]]
        parts.append('<div class="card p-5 mt-4"><h3>通信 Kernel 比对（Top 10）</h3>'
                     + html_table(['通信 Kernel', '基线(us)', '比对(us)', 'Diff(us)',
                                   '基线次数', '比对次数'], rows) + '</div>')
    if k_ins.get('load_imbalance_kernels'):
        rows = [[r['Kernel Name'], r['Baseline Calls'], r['Compare Calls']]
                for r in k_ins['load_imbalance_kernels'][:10]]
        parts.append('<div class="card p-5 mt-4"><h3>负载不均 Kernel（次数差 &gt;2x）</h3>'
                     + html_table(['Kernel', '基线次数', '比对次数'], rows) + '</div>')
    c_ins = ins.get('communication', {})
    if c_ins.get('top_degraded'):
        rows = [[r['Comm Op'], r['Baseline Total(us)'], r['Compare Total(us)'],
                 r['Diff(ms)'],
                 r['Compare Wait(ms)'] if 'Compare Wait(ms)' in r else '',
                 r['Compare Transit(ms)'] if 'Compare Transit(ms)' in r else '']
                for r in c_ins['top_degraded'][:10]]
        parts.append('<div class="card p-5 mt-4"><h3>通信算子比对（劣化 Top 10，'
                     '含 Wait/Transit 拆解）</h3>'
                     + html_table(['通信算子', '基线(us)', '比对(us)', 'Diff(ms)',
                                   '比对 Wait(ms)', '比对 Transit(ms)'], rows) + '</div>')
    # 比对小结：自动归纳双卡差异的方向与集中点
    pts = []
    worse = [r for r in ov if isinstance(r.get('Diff Ratio'), (int, float))
             and r['Diff Ratio'] > 0]
    if worse:
        top_bad = max(worse, key=lambda r: r['Diff Ratio'])
        pts.append(f"总体指标中 <b>{esc(str(top_bad['Dimension']))}</b> 劣化最明显"
                   f"（{top_bad['Diff Ratio']*100:+.1f}%），"
                   f"{overall_direction(compare)}")
    else:
        pts.append(overall_direction(compare))
    if op_ins.get('top_degraded'):
        t0 = op_ins['top_degraded'][0]
        ratio = t0.get('Diff Ratio')
        rtxt = f'{ratio*100:+.0f}%' if isinstance(ratio, (int, float)) else '—'
        pts.append(f"算子维度劣化集中在 <b>{esc(str(t0['Op Type']))}</b>"
                   f"（Diff {t0['Diff Duration(ms)']}ms / {rtxt}），"
                   '建议优先核查该类算子在两卡上的输入规模与下发次数')
    if c_ins.get('top_degraded'):
        t0 = c_ins['top_degraded'][0]
        if _f(t0.get('Compare Wait(ms)')) > _f(t0.get('Compare Transit(ms)')):
            pts.append('通信算子比对中 Wait 时间高于 Transit：差异主要来自'
                       '等对方到达（负载不均 / 下发时机），而非带宽不足')
        else:
            pts.append('通信算子比对中 Transit 占主导：数据量或链路带宽是差异主因')
    if k_ins.get('load_imbalance_kernels'):
        pts.append(f"检出 {len(k_ins['load_imbalance_kernels'])} 个负载不均 Kernel"
                   '（两卡执行次数差 &gt;2x），是双卡节奏差的重要来源')
    parts.append('<div class="card p-5 mt-4"><h3>比对小结</h3><ul class="list-disc pl-6 '
                 'text-slate-300 space-y-1">' + ''.join(f'<li>{p}。</li>' for p in pts)
                 + '</ul></div>')
    json_link = 'compare/compare_analysis_result.json'
    parts.append(f'<p class="text-xs text-slate-500 mt-2">中间件：'
                 f'<a href="{esc(json_link)}" target="_blank">'
                 f'compare_analysis_result.json</a> · '
                 f'<a href="compare/csv/" target="_blank">csv/</a></p></section>')
    return ''.join(parts)


LANE_CATEGORY = {'thread': 'Process（host算子）',
                 'stream': 'Ascend Hardware（npu算子）',
                 'comm': 'Communication'}
CATEGORY_ORDER = ['Process（host算子）', 'Ascend Hardware（npu算子）', 'Communication']
OP_STAT_COLS = ['持续时间(ms)', '自用时间(ms)', '平均持续时间(ms)',
                '最大持续时间(ms)', '最小持续时间(ms)', '发生次数']


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def sec_swimlane(mode, mw, num='7'):
    files = sorted(glob.glob(os.path.join(mw, 'swimlane', 'swimlane_rank*.json')))
    if not files:
        return ''
    cards = [read_json(fp) or {} for fp in files]

    # 三大类聚合（Thread→Process / Stream→Ascend Hardware / 通信域→Communication）：
    # 跨全部 rank 累加持续时间/自用时间/次数，平均 = 累计持续时间 ÷ 累计次数，
    # 最大/最小取跨 rank 极值；Plane 与总览泳道不统计
    merged = {}
    for c in cards:
        for l in c.get('lanes', []):
            cat = LANE_CATEGORY.get(l.get('type'))
            if not cat:
                continue
            bucket = merged.setdefault(cat, {})
            for op in l.get('ops', []):
                agg = bucket.setdefault(str(op.get('名称', '—')),
                                        {'d': 0.0, 's': 0.0, 'n': 0, 'mx': None, 'mn': None})
                agg['d'] += _f(op.get('持续时间(ms)'))
                agg['s'] += _f(op.get('自用时间(ms)'))
                agg['n'] += int(_f(op.get('发生次数')))
                mx, mn = op.get('最大持续时间(ms)'), op.get('最小持续时间(ms)')
                if mx not in (None, ''):
                    agg['mx'] = _f(mx) if agg['mx'] is None else max(agg['mx'], _f(mx))
                if mn not in (None, ''):
                    agg['mn'] = _f(mn) if agg['mn'] is None else min(agg['mn'], _f(mn))

    def fmt(v):
        if v is None:
            return '—'
        return f'{v:.3f}'.rstrip('0').rstrip('.')

    sum_rows = []
    for cat in CATEGORY_ORDER:
        bucket = merged.get(cat) or {}
        d = sum(a['d'] for a in bucket.values())
        s = sum(a['s'] for a in bucket.values())
        n = sum(a['n'] for a in bucket.values())
        mx = max((a['mx'] for a in bucket.values() if a['mx'] is not None), default=None)
        mn = min((a['mn'] for a in bucket.values() if a['mn'] is not None), default=None)
        sum_rows.append([cat, fmt(d), fmt(s), fmt(d / n if n else None),
                         fmt(mx), fmt(mn), n])

    src = esc(cards[0].get('source', '—')) if cards else '—'
    parts = [f'''<section id="swimlane"><h2>{num}. 泳道算子统计（Process / Ascend Hardware / Communication）</h2>
<p class="text-slate-400 text-sm mb-3">按三大类聚合全部 Rank 的泳道算子：Thread 泳道→Process（host算子），
Stream 泳道→Ascend Hardware（npu算子），通信域泳道→Communication；Plane 与总览泳道不统计。
持续/自用时间为各 Rank 累加，平均持续时间 = 累计持续时间 ÷ 累计发生次数，最大/最小为跨 Rank 极值。
数据源：{src}</p>
<div class="card p-5"><h3>三大类汇总（跨全部 Rank 聚合）</h3>
{html_table(['类别'] + OP_STAT_COLS, sum_rows)}</div>''']

    for cat in CATEGORY_ORDER:
        bucket = merged.get(cat) or {}
        top = sorted(bucket.items(), key=lambda kv: -kv[1]['d'])[:10]
        rows = [[name, fmt(a['d']), fmt(a['s']),
                 fmt(a['d'] / a['n'] if a['n'] else None),
                 fmt(a['mx']), fmt(a['mn']), a['n']]
                for name, a in top]
        parts.append(f'<div class="card p-5 mt-4"><h3>{esc(cat)} — 持续耗时 Top 10 算子'
                     f'（去重后共 {len(bucket)} 个算子）</h3>'
                     + html_table(['算子名称'] + OP_STAT_COLS, rows) + '</div>')

    # 泳道小结：指出占比最高的类别与各类 Top1 算子，并给出解读
    tot_d = sum(_f(r[1]) for r in sum_rows) or 1.0
    top_cat, top_pct = max(((r[0], _f(r[1]) / tot_d * 100) for r in sum_rows),
                           key=lambda x: x[1])
    tops = []
    for cat in CATEGORY_ORDER:
        bucket = merged.get(cat) or {}
        if bucket:
            name, ag = max(bucket.items(), key=lambda kv: kv[1]['d'])
            tops.append(f'{esc(cat)}：{esc(name)}（{fmt(ag["d"])}ms）')
    parts.append(f'''<div class="card p-5 mt-4"><h3>泳道小结</h3>
<p>三类算子累计持续时间中，<b class="text-orange-400">{esc(top_cat)}</b> 占比最高
（{top_pct:.1f}%）；各类 Top1 算子：{'；'.join(tops)}。</p>
<p class="text-slate-400 text-sm mt-2">解读：Process（host算子）占比偏高说明 Host 下发/调度开销大，
常伴随 Device 空闲（free）升高；Communication 占比偏高需结合计算掩盖情况判断，
未掩盖的等待型通信多指向负载不均；Ascend Hardware（npu算子）占主导则优化重点在算子效率。</p></div>''')
    links = ' · '.join(
        f'<a href="swimlane/swimlane_rank{c.get("rank")}.md" target="_blank">'
        f'swimlane_rank{c.get("rank")}.md</a>' for c in cards)
    extra = (' · <a href="swimlane/swimlane_compare.md" target="_blank">'
             'swimlane_compare.md</a>'
             if os.path.isfile(os.path.join(mw, 'swimlane', 'swimlane_compare.md'))
             else '')
    parts.append(f'<p class="text-xs text-slate-500 mt-2">各 Rank 全部算子明细：{links}{extra}</p>')
    parts.append('</section>')
    return ''.join(parts)


def sec_appendix(mw, num='8'):
    files = []
    for pattern in ('detect_result.json', 'advisor/*', 'swimlane/*', 'compare/*',
                    'cluster_analysis_output/recipes_summary.*',
                    'cluster_analysis_output/recipes/*/*'):
        for fp in glob.glob(os.path.join(mw, pattern)):
            if os.path.isfile(fp):
                rel = os.path.relpath(fp, mw).replace('\\', '/')
                files.append((rel, os.path.getsize(fp)))
    files.sort()
    crel = cluster_rel(mw)
    ca_prefix = 'cluster_analysis_output/'
    rows = []
    for rel, size in files:
        href = (f'{crel}/{rel[len(ca_prefix):]}'
                if rel.startswith(ca_prefix) else rel)
        rows.append([Raw(f'<a href="{esc(href)}" target="_blank">{esc(rel)}</a>'),
                     f'{size/1024:.1f} KB'])
    return f'''<section id="appendix"><h2>{num}. 附录：中间件清单</h2>
<div class="card p-5">{html_table(['文件', '大小'], rows)}</div></section>'''


def sec_subreports(out_dir, num='8'):
    """vendor 子报告（cluster-output-analysis / prof-compare）：iframe 内嵌 + 新窗口链接。"""
    defs = [
        ('reports/cluster_analysis_report.html', 'cluster-output-analysis 子报告',
         'vendor cluster-output-analysis 生成：集群时间拆解、通信域映射、通信矩阵、'
         '慢卡/慢链路等完整可视化'),
        ('reports/compare_analysis_report.html', 'prof-compare 子报告',
         'vendor prof-compare 生成：双卡算子 / Kernel / API / 模块维度比对完整可视化'),
    ]
    cards = []
    for rel, name, desc in defs:
        fp = os.path.join(out_dir, rel)
        if not os.path.isfile(fp):
            continue
        cards.append(f'''<div class="card p-5 mt-4">
<h3>{esc(name)} <a class="text-sm" href="{esc(rel)}" target="_blank">↗ 新窗口打开</a></h3>
<p class="text-slate-400 text-sm mb-2">{esc(desc)}</p>
<iframe src="{esc(rel)}" loading="lazy"
  style="width:100%;height:840px;border:1px solid #334155;border-radius:.5rem;background:#0b1220;"></iframe>
</div>''')
    if not cards:
        return ''
    return f'''<section id="subreports">
  <h2>{num}. vendor 子报告（cluster-output-analysis / prof-compare）</h2>
  {''.join(cards)}
  <div class="card p-5 mt-4"><h3>子报告阅读指引</h3>
  <p>cluster-output-analysis 子报告展示集群整体时序拆解、通信域映射与慢卡定位，
  与本报告"集群总览 / 进阶分析"章节互为补充；prof-compare 子报告提供双卡差异的
  算子 / Kernel / API 级归因，是"双卡比对"章节的明细展开。
  建议先读主报告"结论与建议"，再按需深入对应子报告定位细节。</p></div>
  <p class="text-xs text-slate-500 mt-2">子报告由 vendor 技能直接生成并嵌入本报告；
  若内嵌区显示为空（浏览器安全策略），请点击"新窗口打开"。</p>
</section>'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--middleware', required=True)
    parser.add_argument('--mode', choices=['single', 'cluster', 'compare'], required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    mw_dir = os.path.abspath(args.middleware)
    workflow = read_json(os.path.join(mw_dir, 'workflow_status.json')) or {}
    detect = read_json(os.path.join(mw_dir, 'detect_result.json')) or {}
    cluster_summary = read_json(os.path.join(cluster_dir(mw_dir), 'recipes_summary.json'))
    compare = read_json(os.path.join(mw_dir, 'compare', 'compare_analysis_result.json'))
    advisor = load_advisor(mw_dir)
    locator = read_json(os.path.join(mw_dir, 'insight_bottlenecks.json'))
    if args.mode in ('cluster', 'compare') and not cluster_summary:
        print('WARN: cluster/compare mode but recipes_summary.json missing; '
              'cluster sections will be thin')

    exec_mode = 'msprof-analyze CLI' if detect.get('exec_mode') == 'cli' else 'fallback (built-in)'

    out_dir = os.path.dirname(os.path.abspath(args.output))

    if args.mode == 'cluster':
        sections = [
            sec_overview(detect, advisor, cluster_summary, 'cluster', '1'),
            sec_conclusions(advisor, cluster_summary, compare, 'cluster', '2', locator=locator),
            sec_cluster(cluster_summary, '3'),
            sec_advisor(advisor, mw_dir, '4'),
            sec_recipes(cluster_summary, mw_dir, '5'),
            sec_compare(compare, '6'),
            sec_swimlane('cluster', mw_dir, '7'),
            sec_subreports(out_dir, '8'),
            sec_appendix(mw_dir, '9'),
        ]
        nav_items = [('overview', '数据概览'), ('conclusions', '结论与建议'),
                     ('cluster', '集群总览'), ('advisor', '专家建议'),
                     ('recipes', '进阶分析'), ('compare', '双卡比对'),
                     ('swimlane', '泳道算子'), ('subreports', 'vendor 子报告'),
                     ('appendix', '附录')]
        title = 'NPU 集群性能分析报告'
        subtitle = ('集群分析（Step×Rank）· 五大类进阶分析 · 通信占比极值卡比对 · '
                    '泳道算子统计 · vendor 子报告')
        mode_label = '集群模式'
    elif args.mode == 'compare':
        sections = [
            sec_overview(detect, advisor, cluster_summary, 'compare', '1'),
            sec_conclusions(advisor, cluster_summary, compare, 'compare', '2', locator=locator),
            sec_advisor(advisor, mw_dir, '3'),
            sec_compare(compare, '4'),
            sec_swimlane('compare', mw_dir, '5'),
            sec_subreports(out_dir, '6'),
            sec_appendix(mw_dir, '7'),
        ]
        nav_items = [('overview', '数据概览'), ('conclusions', '结论与建议'),
                     ('advisor', '专家建议'), ('compare', '双卡比对'),
                     ('swimlane', '泳道算子'), ('subreports', 'vendor 子报告'),
                     ('appendix', '附录')]
        title = 'NPU 集群比对报告'
        subtitle = ('通信占比最大 vs 最小卡比对 · 劣化算子 / Kernel / 通信拆解 · '
                    'vendor 子报告')
        mode_label = '集群比对模式'
    else:
        sections = [
            sec_overview(detect, advisor, None, 'single', '1'),
            sec_conclusions(advisor, None, None, 'single', '2', locator=locator),
            sec_advisor(advisor, mw_dir, '3'),
            sec_swimlane('single', mw_dir, '4'),
            sec_appendix(mw_dir, '5'),
        ]
        nav_items = [('overview', '数据概览'), ('conclusions', '结论与建议'),
                     ('advisor', '专家建议'), ('swimlane', '泳道算子'),
                     ('appendix', '附录')]
        title = 'NPU 单卡性能分析报告'
        subtitle = '专家建议 · 泳道算子统计（Thread / Stream / 通信域）'
        mode_label = '单卡模式'

    nav = ''.join(f'<a href="#{i}">{t}</a>' for i, t in nav_items)

    # every major section folds into <details open> (user requirement #9)
    body_parts = [fold(s) for s in sections if s]
    html_out = TEMPLATE.format(
        title=title, subtitle=subtitle, mode_label=mode_label,
        data_path=esc(detect.get('input', mw_dir)),
        gen_time=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        exec_mode=exec_mode, nav=nav, css=PAGE_CSS, spy_js=PAGE_JS,
        body='\n'.join(body_parts))

    if workflow.get('status') in ('partial', 'failed'):
        banner = ('<section class="card p-5"><h2>分析未完整完成</h2>'
                  f'<p>{esc("; ".join(workflow.get("errors", [])))}</p>'
                  '<p>缺失章节不代表健康；请查看 workflow_status.json。</p></section>')
        html_out = html_out.replace('<section', banner + '<section', 1)
    out = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html_out)
    if locator is not None:
        compact = os.path.join(out_dir, 'insight_bottlenecks.html')
        with open(compact, 'w', encoding='utf-8') as f:
            f.write(compact_diagnosis_html(locator))
    print(f'report written: {out} ({len(html_out)/1024:.1f} KB)')


if __name__ == '__main__':
    main()
