#!/usr/bin/env python3
"""Phase 1 fallback: advisor-equivalent expert advice for the WHOLE dataset.

One advisor run covers all cards: single card -> single-card advisor; multi-card
root -> one aggregated advisor across every rank (mirrors `msprof-analyze
advisor all -d <root>`). Reads text outputs (step_trace_time.csv /
op_statistic.csv / kernel_details.csv / communication.json / api_statistic.csv)
and produces ONE advisor.md + advisor.json.

Units: CSV are us; communication.json is ms. Report outputs ms.
"""
import argparse
import csv
import json
import os
import re
import sys

from lib.common import is_junk, iter_csv, read_csv_rows, read_json, to_f, us_to_ms
from lib.config import AGG_ROWS, COMM_NAME_PATTERN
from lib import prof_data
from lib import analysis_scope



def find_cards(root):
    """Root itself a card dir, or children card dirs (one level deep)."""
    from detect_prof import find_card_dirs
    return find_card_dirs(root)


def card_rank(card_dir):
    for fn in sorted(os.listdir(card_dir)):
        m = re.match(r'^profiler_info_(\d+)\.json$', fn)
        if m:
            info = read_json(os.path.join(card_dir, fn)) or {}
            try:
                return int(info.get('rank_id', m.group(1)))
            except (TypeError, ValueError):
                return m.group(1)
    m = re.search(r'_(\d+)_\d{14,}_ascend_', os.path.basename(card_dir))
    return m.group(1) if m else os.path.basename(card_dir)


# ---------------- per-card loaders ----------------

def load_step_trace(apo):
    """step/window 摘要：TEXT CSV 优先，缺失时回退 analysis.db::StepTraceTime。

    返回 dict（含固定指标键）或 None。附带 source 与 scope：
    scope='whole_prof' 表示整个无分步 prof 合为一个汇总 step，不是训练迭代，
    结论必须按采集窗口径解释（单位 us，与 CSV 同）。
    """
    rows = analysis_scope.load_steps(apo)
    if not rows:
        return None
    source, scope = rows[0]['_source'], analysis_scope.scope_of(rows)
    null_metrics = sum(1 for r in rows for key in analysis_scope.METRIC_KEYS
                       if key in r and analysis_scope.number(r.get(key)) is None)
    required = ('Stage', 'Computing', 'Communication(Not Overlapped)', 'Free')
    missing_required = sorted({key for r in rows for key in required
                               if analysis_scope.number(r.get(key)) is None})
    agg = {k: 0.0 for k in ('Computing', 'Communication(Not Overlapped)', 'Communication',
                            'Free', 'Stage', 'Bubble', 'Preparing')}
    for r in rows:
        for k in agg:
            agg[k] += to_f(r.get(k))
    n = len(rows)
    return {k: v / n for k, v in agg.items()} | {'steps': n, 'source': source,
                                                 'step_ids': sorted({r['Step'] for r in rows}),
                                                 'scope': scope,
                                                 'null_metrics': null_metrics,
                                                 'missing_required': missing_required}


def load_ops(apo):
    stats = read_csv_rows(os.path.join(apo, 'op_statistic.csv'))
    stats.sort(key=lambda r: to_f(r.get('Total Time(us)')), reverse=True)
    return stats


def load_kernel_findings(apo):
    """No-bound kernels + block-dim misalignment + AI Core op count."""
    no_bound, bad_blockdim = [], []
    aicore_ops = 0
    kd_path = os.path.join(apo, 'kernel_details.csv')
    for r in iter_csv(kd_path):
        if COMM_NAME_PATTERN.search(r.get('Name', '')):
            continue
        core = r.get('Accelerator Core', '')
        dur = to_f(r.get('Duration(us)'))
        if core in ('AI_CORE', 'MIX_AIC'):
            aicore_ops += 1
            if dur >= 20:
                mac = to_f(r.get('aic_mac_ratio'), None)
                fix = to_f(r.get('aic_fixpipe_ratio'), None)
                mte2 = to_f(r.get('aic_mte2_ratio'), None)
                if any(v is None for v in (mac, fix, mte2)):
                    continue  # Missing counters are not measured zero utilization.
                if mac < 0.8 and fix < 0.75 and mte2 < 0.95:
                    no_bound.append((r.get('Name', ''), dur, mac, fix, mte2))
        # Block Dim alone cannot establish utilization without device/core capability.
    return no_bound, bad_blockdim, aicore_ops


def load_comm_ops(apo):
    """通信算子汇总：communication.json 优先，缺失时回退 analysis.db::CommAnalyzerTime。

    两个来源的时间均为 ms，返回 (comm_ops, wait_ratios)。
    """
    cj = read_json(os.path.join(apo, 'communication.json'))
    comm_ops, wait_ratios = [], []
    if cj:
        for step, groups in cj.items():
            for gtype in ('collective', 'p2p'):
                for op_key, info in (groups.get(gtype) or {}).items():
                    name = op_key.split('@')[0]
                    if name in AGG_ROWS or re.match(r'^Plan\d+$', name):
                        continue
                    ti = info.get('Communication Time Info', {})
                    elapse = to_f(ti.get('Elapse Time(ms)'))
                    wait = to_f(ti.get('Wait Time(ms)'))
                    transit = to_f(ti.get('Transit Time(ms)'))
                    idle = to_f(ti.get('Idle Time(ms)'))
                    comm_ops.append((name, elapse, wait, transit, idle))
                    if elapse > 0:
                        wait_ratios.append(wait / elapse)
        return comm_ops, wait_ratios
    for r in prof_data.read_comm_time(apo):
        name = str(r['op'] or '').split('@')[0]
        if not name or name in AGG_ROWS or re.match(r'^Plan\d+$', name):
            continue
        elapse, wait = to_f(r['elapse_ms']), to_f(r['wait_ms'])
        transit, idle = to_f(r['transit_ms']), to_f(r['idle_ms'])
        comm_ops.append((name, elapse, wait, transit, idle))
        if elapse > 0:
            wait_ratios.append(wait / elapse)
    return comm_ops, wait_ratios


def load_apis(apo):
    apis = read_csv_rows(os.path.join(apo, 'api_statistic.csv'))
    apis.sort(key=lambda r: to_f(r.get('Time(us)')), reverse=True)
    return apis


# ---------------- aggregate analysis ----------------

def advisor_overall(per_rank):
    """per_rank: {rank: step_trace}. Returns ratios, dominant, reason."""
    stage = sum(st['Stage'] for st in per_rank.values()) / len(per_rank)
    comp = sum(st['Computing'] for st in per_rank.values()) / len(per_rank)
    comm = sum(st['Communication(Not Overlapped)'] for st in per_rank.values()) / len(per_rank)
    free = sum(st['Free'] for st in per_rank.values()) / len(per_rank)
    ratio = {'computing': comp / stage if stage else 0,
             'communication': comm / stage if stage else 0,
             'free': free / stage if stage else 0}
    if any(st.get('missing_required') for st in per_rank.values()):
        return ratio, '证据不足', '部分摘要指标缺失或无效，仅保留已有绝对耗时与事件证据'
    if ratio['free'] > 0.5:
        dominant, reason = '空闲主导', 'Free 占比超过 50%，存在 Host 下发间隙、等待或流水线空泡，优先排查调度与数据供给'
    elif ratio['communication'] > 0.3:
        dominant, reason = '通信主导', '未掩盖通信占比超过 30%，优先排查通信域带宽/等待与计算通信重叠'
    elif ratio['computing'] > 0.6:
        dominant, reason = '计算主导', '计算占比最高，优先排查算子瓶颈（Top 算子、流水线利用率）'
    else:
        dominant, reason = '混合型', '各维度占比均衡，需结合算子级数据进一步定位'
    return ratio, dominant, reason


def dedup_top(pairs, n=5):
    seen, out = set(), []
    for item in pairs:
        key = item[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= n:
            break
    return out


def analyze(cards):
    """cards: [{rank, dir, apo}]. Returns dict with all analysis pieces."""
    per_rank = {}
    card_ctx = {}
    for c in cards:
        st = load_step_trace(c['apo'])
        if st:
            per_rank[c['rank']] = st
        ops = load_ops(c['apo'])
        no_bound, bad_bd, aicore_ops = load_kernel_findings(c['apo'])
        comm_ops, wait_ratios = load_comm_ops(c['apo'])
        apis = load_apis(c['apo'])
        card_ctx[c['rank']] = {
            'ops': ops, 'no_bound': no_bound, 'bad_blockdim': bad_bd,
            'aicore_ops': aicore_ops, 'comm_ops': comm_ops,
            'wait_ratios': wait_ratios, 'apis': apis, 'st': st,
        }
    if not per_rank:
        return None

    ratio, dominant, reason = advisor_overall(per_rank)

    # cross-rank op aggregation (compute ops only)
    op_totals = {}
    for rank, ctx in card_ctx.items():
        for r in ctx['ops']:
            name = r.get('OP Type', '')
            if not name or COMM_NAME_PATTERN.search(name):
                continue
            e = op_totals.setdefault(name, {'total': 0.0, 'count': 0, 'max': 0.0,
                                            'per_rank': {}})
            t = to_f(r.get('Total Time(us)'))
            e['total'] += t
            e['count'] += int(to_f(r.get('Count')))
            e['max'] = max(e['max'], to_f(r.get('Max Time(us)')))
            e['per_rank'][rank] = {'total': t, 'count': int(to_f(r.get('Count'))),
                                   'avg': to_f(r.get('Avg Time(us)'))}
    top_ops = sorted(op_totals.items(), key=lambda kv: -kv[1]['total'])[:10]

    # no-bound / block-dim across ranks
    all_nb, all_bb = [], []
    for rank in sorted(card_ctx, key=lambda r: str(r)):
        for name, dur, mac, fix, mte2 in card_ctx[rank]['no_bound']:
            all_nb.append((name, dur, mac, fix, mte2, rank))
        for name, bd in card_ctx[rank]['bad_blockdim']:
            all_bb.append((name, bd, rank))
    all_nb.sort(key=lambda x: x[1], reverse=True)
    nb_top = dedup_top(all_nb)
    bb_top = dedup_top(all_bb)

    # comm aggregation
    comm_totals = {}
    wait_ratios = []
    for rank, ctx in card_ctx.items():
        wait_ratios += ctx['wait_ratios']
        for name, elapse, wait, transit, idle in ctx['comm_ops']:
            e = comm_totals.setdefault(name, {'elapse': 0.0, 'wait': 0.0, 'transit': 0.0,
                                              'idle': 0.0, 'n': 0})
            e['elapse'] += elapse
            e['wait'] += wait
            e['transit'] += transit
            e['idle'] += idle
            e['n'] += 1
    top_comm = sorted(comm_totals.items(), key=lambda kv: -kv[1]['elapse'])[:10]

    # api aggregation
    api_totals = {}
    for rank, ctx in card_ctx.items():
        for r in ctx['apis']:
            name = r.get('API Name', '')
            if not name:
                continue
            e = api_totals.setdefault(name, {'total': 0.0, 'count': 0})
            e['total'] += to_f(r.get('Time(us)'))
            e['count'] += int(to_f(r.get('Count')))
    top_apis = sorted(api_totals.items(), key=lambda kv: -kv[1]['total'])[:10]

    return {'per_rank': per_rank, 'card_ctx': card_ctx, 'ratio': ratio,
            'dominant': dominant, 'reason': reason, 'top_ops': top_ops,
            'nb_top': nb_top, 'bb_top': bb_top, 'top_comm': top_comm,
            'top_apis': top_apis, 'wait_ratios': wait_ratios,
            'comm_totals': comm_totals}


def build_advice(res):
    """Merged advice list [(level, text)] across ranks."""
    items = []
    missing = sorted({key for rank in res['per_rank'].values()
                      for key in rank.get('missing_required', [])})
    if missing:
        return [('Medium', '摘要指标证据不足：' + '、'.join(missing)
                 + ' 未提供或无效；相关占比和正常判定不可用，优先查看已有事件热点。')]
    ranks = sorted(res['per_rank'], key=lambda r: str(r))
    ratio = res['ratio']
    multi = len(ranks) > 1
    prefix = '集群' if multi else ''

    if ratio['free'] > 0.5:
        items.append(('High', f"{prefix}空闲占 Stage 的 {ratio['free']*100:.1f}%：Host 下发间隙、"
                              f"数据加载等待或跨卡等待是首要瓶颈，建议查看 Host API Top 与集群慢卡分析"))
    elif ratio['free'] > 0.3:
        items.append(('Medium', f"{prefix}空闲占 {ratio['free']*100:.1f}%，存在可压缩的调度间隙"))
    if ratio['communication'] > 0.3:
        items.append(('High', f"{prefix}未掩盖通信占 {ratio['communication']*100:.1f}%，"
                              f"建议开启计算通信重叠或优化通信策略"))
    if multi:
        stages = {r: res['per_rank'][r]['Stage'] for r in ranks}
        worst = max(stages, key=lambda r: stages[r])
        fastest = min(stages, key=lambda r: stages[r])
        spread = (stages[worst] / stages[fastest] - 1) * 100 if stages[fastest] else 0
        if spread > 2:
            items.append(('High', f"卡间负载不均：rank {worst} Stage 最长"
                                  f"（{us_to_ms(stages[worst])}ms），rank {fastest} 最短"
                                  f"（{us_to_ms(stages[fastest])}ms），差距 {spread:.1f}%"))
    if res['top_ops']:
        name, e = res['top_ops'][0]
        comp = sum(res['per_rank'][r]['Computing'] * res['per_rank'][r]['steps'] for r in ranks)
        total = sum(v['total'] for r, v in e['per_rank'].items() if r in res['per_rank'])
        share = total / comp if comp else 0
        if share >= 0.1:
            items.append(('High', f"Top1 计算算子 {name} 占计算时间 {share*100:.1f}%"
                                  f"（同一采集窗口累计，kernel 时长/Computing 近似比；"
                                  f"{us_to_ms(total/len(ranks))}ms/卡，合计{e['count']}次），"
                                  f"优先针对性优化（融合/替换实现/检查 shape）"))
        elif share >= 0.05:
            items.append(('Medium', f"Top1 计算算子 {name} 占计算时间 {share*100:.1f}%，可考虑优化"))
    if res['nb_top']:
        items.append(('Medium', f"发现 {len(res['nb_top'])} 类无流水线瓶颈点的算子"
                                f"（耗时≥20us 且 mac/fixpipe/mte2 均低于阈值），"
                                f"如 {res['nb_top'][0][0]}，建议检查算子切分或替换实现"))
    if res['wait_ratios']:
        avg_wait = sum(res['wait_ratios']) / len(res['wait_ratios'])
        if avg_wait > 0.5:
            items.append(('High', f"通信算子平均等待占比 {avg_wait*100:.0f}%（等待型通信），"
                                  f"各卡到达时间差异大，优先解决慢卡/负载不均"))
    if res['top_comm']:
        name, e = res['top_comm'][0]
        items.append(('Low', f"耗时最大通信算子 {name}：elapse {e['elapse']:.3f}ms "
                             f"(wait {e['wait']:.3f}ms / transit {e['transit']:.3f}ms / "
                             f"idle {e['idle']:.3f}ms)"))
    if res['top_apis']:
        name, e = res['top_apis'][0]
        if e['total'] > 1000:
            items.append(('Low', f"Host 侧 Top1 API {name} 累计 {us_to_ms(e['total'])}ms"
                                 f"（{e['count']} 次），若下发密集可考虑合并调用"))
    if not items:
        items.append(('Low', '各维度指标均在正常阈值内，未发现明显瓶颈'))
    order = {'High': 0, 'Medium': 1, 'Low': 2}
    items.sort(key=lambda x: order[x[0]])
    return items


def write_report(res, cards, out_dir, root):
    ranks = sorted(res['per_rank'], key=lambda r: str(r))
    multi = len(cards) > 1
    items = build_advice(res)
    avg = {k: sum(res['per_rank'][r][k] for r in ranks) / len(ranks)
           for k in ('Stage', 'Computing', 'Communication(Not Overlapped)', 'Free',
                     'Bubble', 'Preparing')}
    total_steps = sum(res['per_rank'][r]['steps'] for r in ranks)
    unique_steps = sorted({step for r in ranks for step in res['per_rank'][r]['step_ids']})
    missing_required = {key for r in ranks for key in res['per_rank'][r]['missing_required']}

    lines = []
    title = f"专家建议报告（整体 · {len(cards)} 卡）" if multi else '专家建议报告（单卡）'
    lines.append(f'# {title}')
    lines.append('')
    lines.append(f'- 数据根目录：`{root}`')
    lines.append(f'- 覆盖 Rank：{", ".join(str(r) for r in ranks)}')
    lines.append(f'- Rank-step 样本数：{total_steps}；每 rank 的 step 数见下表，不代表独立训练 step 总数')
    scopes = {res['per_rank'][r].get('scope') for r in ranks}
    sources = {res['per_rank'][r].get('source') for r in ranks}
    if 'whole_prof' in scopes:
        lines.append('- 分步口径：**整个 prof 作为一个汇总 step（prof）**；'
                     '每卡一次汇总，不代表一次训练迭代或一个推理请求。'
                     '不同卡按各自提供的采集范围比较，时窗对齐与负载等价需另行核验。')
    elif 'capture_window' in scopes:
        lines.append('- 数据口径：**采集窗（capture window）**：摘要行来自 NULL-step 采集窗'
                     '（analysis.db），不是训练 step；指标为采集窗口径，不能输出迭代吞吐或按 step 结论')
    elif 'analysis.db:StepTraceTime' in sources:
        lines.append('- 数据来源：analysis.db::StepTraceTime（TEXT 导出缺失时的 DB 适配；'
                     '单位 us，与 step_trace_time.csv 同口径）')
    if any(res['per_rank'][r].get('null_metrics') for r in ranks):
        lines.append('- 警告：部分 DB 摘要行存在 NULL 指标，按 0 参与均值统计，不代表实测为 0')
    lines.append(f'- 主导瓶颈：**{res["dominant"]}**')
    lines.append('')

    lines.append('## 1. 总体摘要')
    lines.append('')
    lines.append('| 指标 | 平均耗时(ms) | 平均占比 |')
    lines.append('|---|---|---|')
    for key, label in [('Stage', 'E2E Stage'), ('Computing', '计算'),
                       ('Communication(Not Overlapped)', '未掩盖通信'), ('Free', '空闲'),
                       ('Bubble', 'Bubble'), ('Preparing', 'Preparing')]:
        if key in missing_required:
            lines.append(f'| {label} | 未知 | 未知 |')
            continue
        pct = avg[key] / avg['Stage'] * 100 if avg['Stage'] else 0
        lines.append(f'| {label} | {us_to_ms(avg[key])} | {pct:.1f}% |')
    lines.append('')
    lines.append(f'诊断：{res["reason"]}。')
    lines.append('')

    if multi:
        lines.append('### 各 Rank 分解')
        lines.append('')
        lines.append('| Rank | Step数 | Stage(ms) | 计算(ms) | 未掩盖通信(ms) | 空闲(ms) | 通信占比 | 空闲占比 |')
        lines.append('|---|---|---|---|---|---|---|---|')
        for r in ranks:
            st = res['per_rank'][r]
            lines.append(f"| {r} | {st['steps']} | {us_to_ms(st['Stage'])} | "
                         f"{us_to_ms(st['Computing'])} | "
                         f"{us_to_ms(st['Communication(Not Overlapped)'])} | "
                         f"{us_to_ms(st['Free'])} | "
                         f"{st['Communication(Not Overlapped)']/st['Stage']*100 if st['Stage'] else 0:.1f}% | "
                         f"{st['Free']/st['Stage']*100 if st['Stage'] else 0:.1f}% |")
        lines.append('')

    lines.append('## 2. 计算分析')
    lines.append('')
    aicore_total = sum(ctx['aicore_ops'] for ctx in res['card_ctx'].values())
    lines.append(f'AI Core 计算核数任务总数（全部卡）：{aicore_total}')
    lines.append('')
    lines.append('### Top 10 耗时算子（全部卡聚合，op_statistic）')
    lines.append('')
    if multi:
        lines.append('| 算子 | 总耗时(ms) | 次数 | 平均(ms) | 最大(ms) | 明细(per rank) |')
        lines.append('|---|---|---|---|---|---|')
        for name, e in res['top_ops']:
            detail = ' / '.join(f"r{r}:{us_to_ms(v['total'])}" for r, v in
                                sorted(e['per_rank'].items(), key=lambda kv: str(kv[0])))
            avg_t = e['total'] / len(ranks)
            lines.append(f'| {name} | {us_to_ms(avg_t)} | {e["count"]} | '
                         f'{us_to_ms(avg_t/max(e["count"],1)*len(ranks))} | {us_to_ms(e["max"])} | {detail} |')
    else:
        lines.append('| 算子 | 总耗时(ms) | 次数 | 平均(ms) | 最大(ms) |')
        lines.append('|---|---|---|---|---|')
        for name, e in res['top_ops']:
            lines.append(f'| {name} | {us_to_ms(e["total"])} | {e["count"]} | '
                         f'{us_to_ms(e["total"]/max(e["count"],1))} | {us_to_ms(e["max"])} |')
    if res['nb_top']:
        lines.append('')
        lines.append('### 无流水线瓶颈点算子（no-bound，建议优化）')
        lines.append('')
        lines.append('| 算子 | 耗时(ms) | mac_ratio | fixpipe_ratio | mte2_ratio | rank |')
        lines.append('|---|---|---|---|---|---|')
        for name, dur, mac, fix, mte2, rank in res['nb_top']:
            lines.append(f'| {name} | {us_to_ms(dur)} | {mac:.2f} | {fix:.2f} | {mte2:.2f} | {rank} |')
    if res['bb_top']:
        lines.append('')
        lines.append('### Block Dim 未对齐算子')
        lines.append('')
        lines.append('| 算子 | block_dim | rank |')
        lines.append('|---|---|---|')
        for name, bd, rank in res['bb_top']:
            lines.append(f'| {name} | {bd} | {rank} |')
    lines.append('')

    lines.append('## 3. 通信分析')
    lines.append('')
    if res['top_comm']:
        lines.append('### Top 10 通信算子（全部卡聚合，单位 ms）')
        lines.append('')
        lines.append('| 算子 | Elapse | Wait | Transit | Idle | 次数 |')
        lines.append('|---|---|---|---|---|---|')
        for name, e in res['top_comm']:
            lines.append(f'| {name} | {e["elapse"]:.3f} | {e["wait"]:.3f} | '
                         f'{e["transit"]:.3f} | {e["idle"]:.3f} | {e["n"]} |')
    else:
        lines.append('未发现通信算子数据。')
    lines.append('')

    lines.append('## 4. 调度分析（Host）')
    lines.append('')
    lines.append('| API | 累计耗时(ms) | 次数 |')
    lines.append('|---|---|---|')
    for name, e in res['top_apis']:
        lines.append(f'| {name} | {us_to_ms(e["total"])} | {e["count"]} |')
    lines.append('')

    lines.append('## 5. 建议清单')
    lines.append('')
    lines.append('| 优先级 | 建议 |')
    lines.append('|---|---|')
    for level, advice in items:
        lines.append(f'| {level} | {advice} |')
    lines.append('')

    os.makedirs(out_dir, exist_ok=True)
    out_md = os.path.join(out_dir, 'advisor.md')
    with open(out_md, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    summary = {
        'scope': 'all_cards' if multi else 'single_card',
        'step_scope': next(iter(scopes)) if len(scopes) == 1 else 'mixed',
        'synthetic_step': 'whole_prof' in scopes,
        'ranks': [str(r) for r in ranks],
        'dominant': res['dominant'],
        'stage_ms': us_to_ms(avg['Stage']),
        'steps': total_steps,
        'unique_step_count': len(unique_steps),
        'step_ids': unique_steps,
        'computing_ratio': None if {'Computing', 'Stage'} & missing_required else round(res['ratio']['computing'], 4),
        'communication_ratio': None if {'Communication(Not Overlapped)', 'Stage'} & missing_required else round(res['ratio']['communication'], 4),
        'free_ratio': None if {'Free', 'Stage'} & missing_required else round(res['ratio']['free'], 4),
        'per_rank': {str(r): {'stage_ms': us_to_ms(res['per_rank'][r]['Stage']),
                              'step_scope': res['per_rank'][r]['scope'],
                              'source': res['per_rank'][r]['source'],
                              'missing_required': res['per_rank'][r]['missing_required'],
                              'steps': res['per_rank'][r]['steps'],
                              'comm_ratio': round(res['per_rank'][r]['Communication(Not Overlapped)']
                                                  / res['per_rank'][r]['Stage'], 4)
                              if res['per_rank'][r]['Stage'] else 0,
                              'free_ratio': round(res['per_rank'][r]['Free']
                                                  / res['per_rank'][r]['Stage'], 4)
                              if res['per_rank'][r]['Stage'] else 0}
                     for r in ranks},
        'top_op': res['top_ops'][0][0] if res['top_ops'] else None,
        'advice_count': len(items),
        'advice': [{'level': lv, 'text': tx} for lv, tx in items[:10]],
    }
    with open(out_md.replace('.md', '.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f'advisor fallback done ({len(cards)} cards): {out_md}')
    print(f"dominant={res['dominant']} comm_ratio={res['ratio']['communication']:.3f} "
          f"free_ratio={res['ratio']['free']:.3f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True,
                        help='card dir (single) or multi-card root (advisor covers ALL cards)')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    cards = find_cards(root)
    if not cards:
        print(f'ERROR: no card dir with ASCEND_PROFILER_OUTPUT under {root}', file=sys.stderr)
        sys.exit(1)
    card_list = [{'rank': card_rank(c), 'dir': c,
                  'apo': os.path.join(c, 'ASCEND_PROFILER_OUTPUT')} for c in cards]
    res = analyze(card_list)
    if not res:
        print('ERROR: 无可用 step/window 摘要：step_trace_time.csv 与 '
              'analysis.db StepTraceTime 均缺失或为空', file=sys.stderr)
        sys.exit(1)
    write_report(res, card_list, args.output, root)


if __name__ == '__main__':
    main()
