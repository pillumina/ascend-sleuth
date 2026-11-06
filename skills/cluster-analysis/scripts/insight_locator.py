#!/usr/bin/env python3
"""Locate up to three actionable observations per Insight timeline category.

This stage is deliberately read-only. It needs original card evidence, never
turns a duration vote into a causal claim, and can report missing capabilities.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
from statistics import median

from lib.common import read_json, to_f
from lib.insight_data import Card, ns, stamp


def ms(value):
    return f'{value / 1_000_000:.3f}'


def share(card, step, value):
    stage=card.stage_ns(step)
    return f'{value / stage * 100:.2f}%（同卡迭代 Stage 为 {ms(stage)}ms）' if stage else '占比不可计算（缺同卡迭代 Stage）'


def position(card, step, lane, start, end, name, origin):
    return f'迭代 {step} / {card.rank}卡 / {lane} / {card.host}（首次导入标记 0，{card.rank}卡） / {stamp(start-origin)}～{stamp(end-origin)} / {name}'


def communication(cards, origin):
    grouped=defaultdict(list);by_rank={c.rank:c for c in cards}
    for card in cards:
        for event in card.comms:
            if '未解析通信域' in event['lane']:
                continue
            # The exact operator instance is significant: removing its suffix
            # would merge distinct collectives and hide causal timing.
            key=(event['step'],event['lane'],event['name'])
            grouped[key].append(event)
    candidates=[]
    for key,events in grouped.items():
        events=list({(e['rank'],e['start'],e['end']):e for e in events}.values())
        distinct={e['rank'] for e in events}
        if len(distinct)<2 or key[0]=='未知':
            continue
        # Malformed repeated instance keys are not aligned across ranks.
        if len(distinct)!=len(events):
            continue
        earliest=min(events,key=lambda e:e['start']);latest=max(events,key=lambda e:e['start'])
        skew=latest['start']-earliest['start']
        end_spread=max(e['end'] for e in events)-min(e['end'] for e in events)
        durations=[e['end']-e['start'] for e in events]
        if skew<1_000_000 and max(durations)-min(durations)<1_000_000:
            continue
        candidates.append((skew,latest,earliest,events,end_spread))
    result=[]
    for skew,latest,earliest,events,end_spread in sorted(candidates,key=lambda v:v[0],reverse=True)[:3]:
        slow=by_rank[latest['rank']];waiting=by_rank[earliest['rank']];step=latest['step']
        residual_min=min(e['end']-max(v['start'] for v in events) for e in events)
        residual_max=max(e['end']-max(v['start'] for v in events) for e in events)
        converged=end_spread<=max(1_000_000,int(skew*.1))
        location=position(slow,step,latest['lane']+' / Communication (HCCL)',latest['start'],latest['end'],latest['name'],origin)
        location += f'；代表等待卡 {earliest["rank"]}卡 起点 {stamp(earliest["start"]-origin)}'
        issue=f'已采集卡中 {latest["rank"]}卡 Device 起点最晚，为通信到达不齐候选'
        impact=f'起点差 {ms(skew)}ms；最早到达 {earliest["rank"]}卡等待暴露上界为同卡迭代 {share(waiting,step,skew)}。'
        impact+=f'结束跨度 {ms(end_spread)}ms；上界不等于可消除时间。'
        cause=[];machine={'step':step,'semantic_group':latest['semantic'],'operator_instance':latest['name'],
            'latest_observed_rank':latest['rank'],'start_skew_ns':skew,'end_spread_ns':end_spread,
            'aligned_ranks':sorted(e['rank'] for e in events),'start_ns':latest['start'],'end_ns':latest['end'],
            'relative_start_ns':latest['start']-origin,'relative_end_ns':latest['end']-origin,
            'wait_ns_by_rank':{str(e['rank']):e['wait'] for e in events},
            'duration_ns_by_rank':{str(e['rank']):e['end']-e['start'] for e in events}}
        machine['arrival_ns_by_rank']={str(e['rank']):e['start'] for e in events}
        machine['residual_after_latest_arrival_ns']=[max(0,residual_min),max(0,residual_max)]
        brief=[]
        if converged:
            cause.append(f'各卡结束收敛（差 {ms(end_spread)}ms），与到达不齐造成先到卡等待相符。')
        else:
            cause.append(f'各卡结束不收敛（差 {ms(end_spread)}ms），剩余通信/传输路径差异仍需排查，不能仅凭短耗时确认到达根因。')
        host_l=slow.linked_host(latest);host_e=waiting.linked_host(earliest)
        if host_l and host_e:
            start_delta=host_l['start']-host_e['start'];end_delta=host_l['end']-host_e['end']
            duration_delta=(host_l['end']-host_l['start'])-(host_e['end']-host_e['start'])
            machine['host_api']={'latest_rank':host_l,'earliest_rank':host_e,'start_delta_ns':start_delta,'end_delta_ns':end_delta,'duration_delta_ns':duration_delta}
            cause.append(f'关联 Host API {host_l["name"]} 开始差 {ms(start_delta)}ms、结束差 {ms(end_delta)}ms、API自身耗时差 {ms(duration_delta)}ms。')
            brief.append(f'Host 下发开始差 {ms(start_delta)}ms。')
            device_gap=(latest['start']-host_l['end'])-(earliest['start']-host_e['end'])
            if start_delta>skew*.6:
                cause.append('通信下发开始已明显落后，优先检查之前的 Host 路径。')
            elif device_gap>max(1_000_000,skew*.5):
                cause.append(f'API 完成到 Device 开始的间隔差 {ms(device_gap)}ms，更接近前序 Device 依赖候选。')
            else:
                cause.append('Host 开始/完成与 Device 依赖尚未形成单一主因。')
            left=slow.anchors(host_l,step);right=waiting.anchors(host_e,step)
            common=set(left)&set(right)
            differences=[]
            for key in common:
                a,b=left[key],right[key]
                difference=(a['end']-a['start'])-(b['end']-b['start'])
                if difference>1_000_000:
                    differences.append((difference,a,b))
            if differences:
                diff,a,b=max(differences,key=lambda v:v[0])
                cause.append(f'向前同名同序锚点 {a["name"]}（本迭代第 {a["ordinal"]} 次）自身耗时多 {ms(diff)}ms，慢卡区间 {stamp(a["start"]-origin)}～{stamp(a["end"]-origin)}；包含子调用，需在该 Host 泳道继续展开。')
                machine['host_anchor_difference']={'duration_delta_ns':diff,'latest_rank_anchor':a,'earliest_rank_anchor':b}
            elif common:
                key=max(common,key=lambda k:min(left[k]['end'],right[k]['end']))
                a,b=left[key],right[key]
                delta=a['end']-b['end']
                cause.append(f'前序同名同序锚点 {a["name"]}（第 {a["ordinal"]} 次）完成已相差 {ms(delta)}ms；该差异为累计路径证据，不能解释为该算子自身耗时差。')
                machine['host_anchor_completion']={'completion_delta_ns':delta,'latest_rank_anchor':a,'earliest_rank_anchor':b}
            else:
                cause.append('缺少可靠同名同序的前序 Host 锚点。')
            peer_by_name={e['name']:e for e in waiting.comms if e['step']==step and e['end']<earliest['start']
                          and e['lane']==earliest['lane']}
            previous=[e for e in slow.comms if e['step']==step and e['end']<latest['start']
                      and e['name'] in peer_by_name and e['lane']==latest['lane']]
            if previous:
                predecessor=max(previous,key=lambda e:e['end'])
                path_l=slow.host_path(latest,host_l,predecessor)
                path_e=waiting.host_path(earliest,host_e,peer_by_name[predecessor['name']])
                if path_l and path_e and path_l['boundary']==path_e['boundary']:
                    count_diff=path_l['cann_event_count']-path_e['cann_event_count']
                    busy_diff=path_l['python_busy_union_ns']-path_e['python_busy_union_ns']
                    tiling=sorted(((name,count-path_e['cann_counts'].get(name,0)) for name,count in path_l['cann_counts'].items()
                                   if 'Tiling' in name and count>path_e['cann_counts'].get(name,0)),key=lambda pair:pair[1],reverse=True)
                    machine['host_path_comparison']={'latest_rank':path_l,'earliest_rank':path_e,
                        'python_busy_delta_ns':busy_diff,'cann_count_delta':count_diff,'additional_tiling':tiling[:5]}
                    detail=f'同一前序通信锚点后，Host 路径区间 {ms(path_l["duration_ns"])} vs {ms(path_e["duration_ns"])}ms，Python 忙区并集多 {ms(busy_diff)}ms，CANN 调用多 {count_diff} 次'
                    if tiling:
                        detail+='（'+ '、'.join(f'{name} +{count}' for name,count in tiling[:3])+'）'
                    cause.append(detail+'；两卡区间 '+stamp(path_l['start_ns']-origin)+'～'+stamp(path_l['end_ns']-origin)+' 与 '+stamp(path_e['start_ns']-origin)+'～'+stamp(path_e['end_ns']-origin)+'。')
                    extra_tiling=sum(count for _,count in tiling)
                    calls=(f'Tiling 多 {extra_tiling} 次' if tiling else
                           f'CANN {"多" if count_diff>=0 else "少"} {abs(count_diff)} 次')
                    direction='下发/tiling 路径' if tiling else 'Host 调用开销及调用间空隙'
                    api=host_l.get('pytorch_parent') or host_l.get('pytorch') or host_l
                    thread=int(api['tid']) & 0xffffffff
                    machine['host_path_comparison']['host_lane']=f'Python / Thread {thread}'
                    machine['host_path_comparison']['additional_tiling_count']=extra_tiling
                    brief.append(f'回溯 Python/Thread {thread} 的 {stamp(path_l["start_ns"]-origin)}～{stamp(path_l["end_ns"]-origin)}'
                                 f'（{predecessor["name"]} 后 Broadcast）；忙区多 {ms(busy_diff)}ms、{calls}；优先核查{direction}。')
            if len(brief)==1:
                if differences:
                    brief.append(f'前序同名同序 {a["name"]} 自身多 {ms(diff)}ms；优先展开该 Host 区间。')
                elif start_delta>skew*.6:
                    brief.append('下发开始已落后；优先沿前序 Host 同名同序锚点检查累计空隙。')
                elif device_gap>max(1_000_000,skew*.5):
                    brief.append(f'API→Device 间隔差 {ms(device_gap)}ms，优先查前序 Device 依赖。')
            activity=slow.interval_activity(earliest['start'],latest['start'])
            if activity:
                machine['latest_rank_arrival_interval_activity']=activity
                cause.append(f'慢卡在最早卡到达至自身到达区间内，计算活动约 {ms(activity.get("computing_ns",0))}ms、Free 约 {ms(activity.get("free_ns",0))}ms（重叠区间先合并）；下发累计差异可能由碎片空隙形成，不能推定存在同等时长单个慢核。')
        else:
            cause.append('connectionId 未能完整关联两卡 Host API，无法区分下发延迟与前序 Device 依赖。')
            brief.append('Host 关联证据不足，无法区分下发延迟与前序 Device 依赖。')
        prior_l=slow.preceding_device(latest);prior_e=waiting.preceding_device(earliest)
        if prior_l and prior_e:
            machine['preceding_device']={'latest_rank':prior_l,'earliest_rank':prior_e}
            cause.append(f'慢卡紧邻此前 Device 算子为 {prior_l["name"]}（Stream {prior_l["stream"]}，结束 {stamp(prior_l["end"]-origin)}）；跨流相邻关系不能替代事件依赖证据。')
        members=set(latest['members']);missing=members-{c.rank for c in cards}
        if missing:
            cause.append(f'完整通信域仍缺 {len(missing)} 卡，仅为已采集卡候选，不能确认全域根因。')
        waits=[e['wait'] for e in events]
        if any(waits):
            cause.append(f'记录的等待时间范围 {ms(min(waits))}～{ms(max(waits))}ms；Wait 可能与算子区间重叠，不能另加为总时长。')
        details={str(e['rank']):by_rank[e['rank']].communication_detail(e) for e in events}
        if any(details.values()):
            machine['communication_detail_by_rank']=details
            wait_export=[];transit_export=[]
            for detail in details.values():
                times=detail.get('Communication Time Info') or {}
                if 'Wait Time(ms)' in times:
                    wait_export.append(to_f(times['Wait Time(ms)']))
                if 'Transit Time(ms)' in times:
                    transit_export.append(to_f(times['Transit Time(ms)']))
            if wait_export:
                cause.append(f'通信导出等待/同步时间范围 {min(wait_export):.3f}～{max(wait_export):.3f}ms，Wait 与 Synchronization 可能表示同一等待，不能相加。')
            if transit_export:
                cause.append(f'导出传输时间范围 {min(transit_export):.3f}～{max(transit_export):.3f}ms；微量控制通信的 GB/s 不适合据此判定链路带宽异常。')
        if not converged:
            brief.append('结束不收敛，仍需检查剩余通信/带宽差异。')
        machine['causal_analysis']=cause
        result.append({'location':location,'issue':issue,'impact':impact,'cause':' '.join(brief),'evidence':machine})
    return result


def memory_bytes(shape,dtype):
    sizes={'FLOAT':4,'FLOAT32':4,'FP32':4,'FLOAT16':2,'HALF':2,'BFLOAT16':2,'BF16':2,'DOUBLE':8,'INT64':8,'INT32':4,'INT8':1,'UINT8':1}
    kind=re.split(r'[;,\s]+',dtype.strip('"').upper())[0]
    # Ascend shape exports use semicolons for multiple inputs; a Muls second
    # scalar input may have an empty shape. Estimate the tensor input only.
    dims=[int(v) for v in re.findall(r'\d+',shape.strip('"').split(';')[0])]
    if not dims or kind not in sizes:
        return None
    elements=1
    for dimension in dims:
        elements*=dimension
    return elements*sizes[kind]


def compute(cards,origin):
    grouped=defaultdict(list);by_rank={c.rank:c for c in cards}
    for card in cards:
        for key,item in card.compute.items():
            grouped[key].append(item)
    candidates=[]
    for key,items in grouped.items():
        slow=max(items,key=lambda i:i['total']);fast=min(items,key=lambda i:i['total'])
        comparable=len({i['rank'] for i in items})>=2 and len({i['count'] for i in items})==1
        excess=slow['total']-fast['total'] if comparable else 0
        # Prefer material rank disparity; a large hotspot without disparity is
        # still explainable, but never described as a degraded device.
        size=memory_bytes(slow['shape'],slow['dtype'])
        large_muls=size and size>=1_000_000_000 and 'Muls' in slow['name']
        stage=by_rank[slow['rank']].stage_ns(slow['step'])
        if excess<1_000_000 and not large_muls and not (stage and slow['total']/stage>=.05):
            continue
        score=(2,excess) if excess>=1_000_000 else (1 if large_muls else 0,slow['total'])
        candidates.append((score,slow,fast,comparable,excess))
    result=[];used=set()
    for _,item,baseline,comparable,excess in sorted(candidates,key=lambda v:v[0],reverse=True):
        family=item['name']
        if family in used:
            continue
        used.add(family)
        card=by_rank[item['rank']];row=item['row'];step=item['step']
        location=position(card,step,'Ascend Hardware / Stream '+str(item['stream']),item['start'],item['start']+item['largest'],item['name'],origin)
        impact=f'本卡本迭代同配置累计 {ms(item["total"])}ms（{item["count"]} 次），占 {share(card,step,item["total"])}。'
        if item['count']>1:
            impact+=f'实例最长 {ms(item["largest"])}ms；累计不等于端到端可节省时间。'
        cause=[];issue='计算热点候选'
        if comparable:
            cause.append(f'同迭代、同形状、同 dtype、同 core、同次数比较，{baseline["rank"]}卡累计 {ms(baseline["total"])}ms；{item["rank"]}卡多 {ms(excess)}ms。')
            if excess>=1_000_000:
                issue='同配置计算耗时跨卡差异候选'
                impact+=f'同配置跨卡超额 {ms(excess)}ms，占 {share(card,step,excess)}；不是已确认可节省时间。'
        else:
            cause.append('缺少同迭代/同形状/同 dtype/同 core/同次数的可比卡；仅说明热点，不能确认性能劣化。')
        ratios=[]
        active_metrics=('aiv_mte2_ratio','aiv_mte3_ratio','aiv_vec_ratio') if 'VECTOR' in item['core'] or 'AIV' in item['core'] else ('aic_mte2_ratio','aic_mac_ratio')
        labels={'aiv_mte2_ratio':'AIV 搬入占用','aiv_mte3_ratio':'AIV 搬出占用','aiv_vec_ratio':'向量计算占用',
                'aic_mte2_ratio':'AIC 搬入占用','aic_mac_ratio':'矩阵计算占用'}
        for name in active_metrics:
            if row.get(name) not in (None,'','N/A'):
                value=to_f(row[name])*100
                pipeline=name.replace('_ratio','_time(us)')
                denominator='aiv_time(us)' if name.startswith('aiv_') else 'aicore_time(us)'
                if to_f(row.get(denominator))>0 and row.get(pipeline) not in (None,'','N/A'):
                    value=to_f(row[pipeline])/to_f(row[denominator])*100
                if value>0:
                    ratios.append(f'{labels[name]} {value:.2f}%')
        if ratios:
            cause.append('PMU '+ '，'.join(ratios)+'；各流水可重叠，比例不是互斥组成，MTE 搬运占用高不能证明带宽已劣化。')
        size=memory_bytes(item['shape'],item['dtype'])
        traffic=2*size if size and re.search(r'Muls',item['name'],re.I) else None
        if traffic:
            cause.append(f'输入 {item["dtype"]} {item["shape"]}，一次读写至少 {traffic/1e9:.2f}GB；可验证将缩放并入生产者或优化器，当前无同等级跨卡劣化证据。')
        result.append({'location':location,'issue':issue,'impact':impact,'cause':' '.join(cause),'evidence':{
            'rank':item['rank'],'step':step,'name':item['name'],'shape':item['shape'],'dtype':item['dtype'],'core':item['core'],
            'start_ns':item['start'],'relative_start_ns':item['start']-origin,'duration_ns':item['largest'],
            'total_ns':item['total'],'count':item['count'],'matching_rank':baseline['rank'] if comparable else None,
            'matching_rank_excess_ns':excess if comparable else None,'minimum_read_write_bytes':traffic,
            'compute_source':card.compute_source,
            'pmu_units':{'kernel_details_csv_time':'us','TASK_PMU_INFO_time':'ns in verified Ascend schema; otherwise validate schema before conversion'},
            'pmu_csv':{k:v for k,v in row.items() if k.endswith(('_ratio','_time(us)','utilization(%)'))}}})
        if len(result)==3:
            break
    return result


def free(cards,origin,communication_results=None):
    largest=[];regular=[]
    for card in cards:
        for step,gaps in card.frees.items():
            if not gaps:
                continue
            ordered=sorted(gaps,key=lambda pair:pair[1]-pair[0],reverse=True)
            start,end=ordered[0]
            largest.append((end-start,card,step,start,end))
            # Repeated short idle periods matter even when no single gap is
            # conspicuous. A duration band is evidence of repetition only.
            small=[pair for pair in gaps if pair[1]-pair[0]<=min(2_000_000,(end-start)*.5)]
            if len(small)>=3:
                typical=median(b-a for a,b in small)
                band=[pair for pair in small if typical*.5<=pair[1]-pair[0]<=typical*2]
                if len(band)>=3:
                    regular.append((sum(b-a for a,b in band),card,step,band))
    result=[]
    paths=[]
    by_rank={c.rank:c for c in cards}
    for observation in communication_results or []:
        evidence=observation['evidence'];comparison=evidence.get('host_path_comparison') or {}
        path=comparison.get('latest_rank')
        other=comparison.get('earliest_rank')
        if path and path.get('free_interval_count',0)>=3 and path.get('free_ns',0)>=1_000_000:
            paths.append((path['free_ns'],by_rank[evidence['latest_observed_rank']],evidence['step'],path,other,
                          min(evidence['arrival_ns_by_rank'],key=evidence['arrival_ns_by_rank'].get)))
    # Keep two longest independent observations and one aggregate; otherwise
    # eight ranks of the same idle gap would bury repeated launch gaps.
    selected=[];seen=set()
    for value,card,step,start,end in sorted(largest,key=lambda x:x[0],reverse=True):
        # near-synchronous gaps across ranks describe the same observation
        bucket=(step,round((start-origin)/1_000_000),round((end-start)/1_000_000))
        if bucket in seen:
            continue
        seen.add(bucket);selected.append((value,card,step,start,end))
        if len(selected)==(1 if paths else 2 if regular else 3):
            break
    for value,card,step,start,end in selected:
        result.append({'location':position(card,step,'Overlap Analysis / Free',start,end,'Free',origin),
            'issue':'最长 Device 空闲区间候选','impact':f'连续空闲 {ms(value)}ms，占 {share(card,step,value)}；Free 与计算/通信取互补口径。',
            'cause':card.free_cause(start,end),'evidence':{'rank':card.rank,'step':step,'start_ns':start,'end_ns':end,
                'relative_start_ns':start-origin,'relative_end_ns':end-origin,'duration_ns':value}})
    if paths:
        for total,card,step,path,other,peer in sorted(paths,key=lambda x:x[0],reverse=True):
            if any(step==row['evidence']['step'] and card.rank==row['evidence']['rank']
                   and path['start_ns']<row['evidence']['end_ns'] and path['end_ns']>row['evidence']['start_ns'] for row in result
                   if 'start_ns' in row['evidence']):
                continue
            start,end=path['start_ns'],path['end_ns'];examples=path['free_examples_ns'][:3]
            location=position(card,step,'Overlap Analysis / Free',start,end,'Free 聚集窗口',origin)
            location+='；例段 '+'；'.join(f'{stamp(a-origin)}～{stamp(b-origin)}' for a,b in examples)
            result.append({'location':location,'issue':f'通信前规律碎片 Free 候选（{path["free_interval_count"]} 段）',
                'impact':f'窗口内 Free 合计 {ms(total)}ms，占 {share(card,step,total)}；对齐 {peer}卡为 {ms(other.get("free_ns",0))}ms，多 {ms(total-other.get("free_ns",0))}ms。',
                'cause':f'同一通信锚点后的 Host 忙区并集多 {ms(path["python_busy_union_ns"]-other["python_busy_union_ns"])}ms，Device 计算为 {ms(path.get("computing_ns",0))} vs {ms(other.get("computing_ns",0))}ms；优先核查下发/tiling 路径，不能归因于单个长计算核。',
                'evidence':{'rank':card.rank,'step':step,'start_ns':start,'end_ns':end,'total_ns':total,
                    'count':path['free_interval_count'],'example_intervals_ns':[[a-origin,b-origin] for a,b in examples],
                    'aligned_rank':int(peer),'aligned_free_ns':other.get('free_ns',0),'basis':'communication host_path_comparison'}})
            if len(result)==3:
                break
    elif regular:
        total,card,step,gaps=max(regular,key=lambda x:x[0])
        examples=sorted(gaps,key=lambda x:x[1]-x[0],reverse=True)[:3]
        intervals='；'.join(f'{stamp(a-origin)}～{stamp(b-origin)}' for a,b in examples)
        result.append({'location':f'迭代 {step} / {card.rank}卡 / Overlap Analysis / Free / {card.host} / Free；例段 {intervals}',
            'issue':f'规律小 Free 聚集候选（{len(gaps)} 段相近时长）',
            'impact':f'本卡本迭代这些小 Free 合计 {ms(total)}ms，占 {share(card,step,total)}；与上方最大区间分开，例段只展示最多 3 段。',
            'cause':card.free_cause(*examples[0])+' 规律性仅指时长相近，需要逐段沿相邻下发/同步事件验证共同成因。',
            'evidence':{'rank':card.rank,'step':step,'count':len(gaps),'total_ns':total,
                        'example_intervals_ns':[[a-origin,b-origin] for a,b in examples]}})
    return result[:3]


def analyze(detect):
    if isinstance(detect,(str,Path)):
        detect=read_json(str(detect),{}) or {}
    cards=[];limitations=[]
    try:
        for raw in detect.get('cards',[]):
            if raw.get('usable',True) and raw.get('dir') and raw.get('rank') is not None:
                card=Card(raw);cards.append(card)
                if card.errors:
                    limitations.append(f'{card.rank}卡原始 DB 不可读，已使用可用文件降级。')
        observed=sorted(c.rank for c in cards)
        worlds=[int(c.world) for c in cards if c.world]
        declared=(detect.get('coverage') or {}).get('expected_world_size')
        if declared:
            worlds.append(int(declared))
        world=max(worlds) if worlds else None
        missing=sorted(set(range(world))-set(observed)) if world else []
        if missing:
            limitations.append(f'只覆盖已采集 {", ".join(str(v) for v in observed)} 卡；期望 world_size={world}，缺 {", ".join(str(v) for v in missing)} 卡。通信最晚到达只是在已采集卡中定位的候选，不能确认全域根因。')
        elif not world:
            limitations.append('未提供期望 world_size，无法确认通信域采集完整性。')
        for card in cards:
            card.load_events()
        starts=[c.session_start if c.conn else c.trace_start for c in cards if (c.session_start if c.conn else c.trace_start) is not None]
        if starts:
            origin=min(starts)
            origin_basis='全部已导入 DB 卡 SESSION_TIME_INFO.startTimeNs 的最小有效正数（Insight TraceTime 规则）'
            if any(c.conn is None and c.trace_start for c in cards):
                origin_basis='Trace/TEXT 卡以 slice 与 counter 最小 timestamp，DB 卡以 SESSION_TIME_INFO.startTimeNs，最后取全局最小（Insight 对应导入模式）'
            if len(starts)!=len(cards):
                limitations.append('部分卡缺 SESSION_TIME_INFO，已知卡的全局起点可能不完整。')
        else:
            origin=min((s['start'] for c in cards for s in c.steps),default=0)
            origin_basis='缺 SESSION_TIME_INFO，降级使用已知 Step 起点，不能保证与 Insight 零点一致'
            limitations.append(origin_basis+'。')
        if not origin:
            origin=min((e['start'] for c in cards for e in c.comms),default=0)
        coverage={'observed_ranks':observed,'expected_world_size':world,'missing_ranks':missing,
                  'steps':sorted({s['id'] for c in cards for s in c.steps}),
                  'origin_ns':origin,'origin_basis':origin_basis,'ui_manual_or_auto_offset_ns':0,
                  'import_mode_by_rank':{str(c.rank):'DB' if c.conn else 'Trace/TEXT' for c in cards},
                  'ui_offset_basis':'zero assumed; manual and selected host/device side alignment are separate from collection origin'}
        coverage['analysis_scope_by_rank'] = {str(c.rank): c.analysis_scope for c in cards}
        whole_prof = any(c.analysis_scope == 'whole_prof' for c in cards)
        if whole_prof:
            limitations.append('无分步标识的卡将整个 prof 作为一个汇总 step（prof）；'
                               '不是单次训练迭代或推理请求，跨卡时窗/负载等价尚需验证。')
        comm=communication(cards,origin)
        result={'schema_version':1,'summary':'','coverage':coverage,'limitations':limitations,
                'communication':comm,'compute':compute(cards,origin),'free':free(cards,origin,comm)}
        reasons={'communication':'缺少可按同迭代、通信域、完整实例对齐的跨卡 Device 时间证据，或未见大于 1ms 的差异。',
                 'compute':'缺少可用的计算 kernel 明细与同配置证据，不能定位计算异常。',
                 'free':'缺少 OVERLAP_ANALYSIS 或 Trace Free 区间，不能准确定位 Device 空闲。'}
        for category in reasons:
            result[category+'_reason']='' if result[category] else reasons[category]
        found=[name for key,name in [('communication','通信到达差异'),('compute','计算热点/跨卡差异'),('free','Device 空闲')] if result[key]]
        supported_paths=[item['evidence'].get('host_path_comparison') for item in comm]
        supported_paths=[path for path in supported_paths if path and path['python_busy_delta_ns']>1_000_000 and path['cann_count_delta']>0]
        if supported_paths:
            result['summary']='主要候选是 Host 下发/路径差异形成的碎片 Free 与通信到达不齐；计算未见同等级的同配置跨卡劣化。结论限于已采集卡与迭代。'
        else:
            result['summary']='已定位 '+ '、'.join(found)+'；结论限定于已采集卡与迭代，根因按证据强度表述为候选。' if found else '原始证据不足，当前不能给出可复现的 Insight 瓶颈定位。'
        if any(c.conn is None for c in cards):
            limitations.append('部分卡缺可用原始 DB；Trace 按流式读取，Host connectionId 与原始 PMU 关联能力可能不足。')
        limitations.append('跨卡相对时间遵循 Insight 全局采集起点；未模拟用户手工时间偏移，时钟偏差/界面自动对齐需在 UI 核对。')
        if whole_prof:
            for category in ('communication', 'compute', 'free'):
                for item in result[category]:
                    is_whole = item.get('evidence', {}).get('step') == 'prof'
                    for key in ('location', 'issue', 'impact', 'cause'):
                        if key in item:
                            item[key] = item[key].replace('迭代 prof', '整段 prof 汇总 step')
                            if is_whole:
                                item[key] = item[key].replace('本迭代', '本段 prof').replace('同迭代', '同段 prof')
            result['summary'] = result['summary'].replace('卡与迭代', '卡与采集范围')
        return result
    finally:
        for card in cards:
            card.close()


def markdown(result):
    lines=['# Insight 瓶颈定位','',result['summary'],'']
    for text in result['limitations']:
        lines.append('- '+text)
    lines.append('')
    for category,title in [('communication','通信'),('compute','计算'),('free','Free')]:
        lines.extend(['## '+title,''])
        if not result[category]:
            lines.extend([result[category+'_reason'],''])
        for number,item in enumerate(result[category],1):
            lines.extend([f'{number}. **位置**：{item["location"]}',f'   **问题**：{item["issue"]}',
                          f'   **影响**：{item["impact"]}',f'   **原因**：{item["cause"]}',''])
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--detect',required=True,help='detect_result.json')
    parser.add_argument('--output',required=True,help='middleware output directory')
    args=parser.parse_args()
    detect=read_json(args.detect)
    if not isinstance(detect,dict):
        parser.error('无法读取 detect_result.json')
    result=analyze(detect)
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    (output/'insight_bottlenecks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'insight_bottlenecks.md').write_text(markdown(result),encoding='utf-8')
    print(result['summary'])


if __name__=='__main__':
    main()
