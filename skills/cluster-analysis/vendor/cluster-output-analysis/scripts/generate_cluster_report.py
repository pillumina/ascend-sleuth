#!/usr/bin/env python3
"""
generate_cluster_report.py
基于提取的 JSON 数据生成 HTML 集群分析/比对报告（深色主题版）。
"""
import argparse
import json
import os
from datetime import datetime

US_TO_MS = 1000.0

def safe_div(a, b):
    if abs(b) < 1e-9:
        return 0
    return round(a / b, 4)

def us_to_ms(us_val):
    if us_val is None:
        return 0
    return round(float(us_val) / US_TO_MS, 2)

def fmt_signed(val):
    """带正负号的格式化"""
    if val >= 0:
        return f"+{val}"
    return str(val)

# ==================== 单集群报告 ====================

def generate_single_report(data, template_path, output_path):
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    ss = data.get("step_summary", {})
    steps = sorted(ss.keys(), key=lambda x: (0, int(x)) if x.isdigit() else (1, x))
    rank_summary = data.get("rank_summary", {})
    rank_count = len(rank_summary)
    step_count = len(steps)

    all_stage = [s["avg_stage"] for s in ss.values()]
    all_compute = [s["avg_compute"] for s in ss.values()]
    all_comm = [s["avg_comm"] for s in ss.values()]
    all_free = [s["avg_free"] for s in ss.values()]
    all_overlap = [s["avg_overlap"] for s in ss.values()]

    avg_stage = sum(all_stage) / len(all_stage) if all_stage else 0
    avg_compute = sum(all_compute) / len(all_compute) if all_compute else 0
    avg_comm = sum(all_comm) / len(all_comm) if all_comm else 0
    avg_free = sum(all_free) / len(all_free) if all_free else 0
    avg_overlap = sum(all_overlap) / len(all_overlap) if all_overlap else 0

    total = avg_stage if avg_stage > 0 else 1
    compute_ratio = safe_div(avg_compute, total) * 100
    comm_ratio = safe_div(avg_comm, total) * 100
    free_ratio = safe_div(avg_free, total) * 100

    bi = data.get("base_info", {})
    tp = bi.get("tp_size", "?")
    pp = bi.get("pp_size", "?")
    dp = bi.get("dp_size", "?")

    free_ratio_color = "text-red-400" if free_ratio > 20 else "text-orange-400" if free_ratio > 10 else "text-emerald-400"

    r = {
        "{{DATA_PATH}}": data.get("data_dir", "?"),
        "{{GENERATE_TIME}}": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "{{TP_SIZE}}": str(tp), "{{PP_SIZE}}": str(pp), "{{DP_SIZE}}": str(dp),
        "{{RANK_COUNT}}": str(rank_count),
        "{{STEP_COUNT}}": str(step_count),
        "{{AVG_STAGE_MS}}": str(us_to_ms(avg_stage)),
        "{{AVG_COMPUTE_MS}}": str(us_to_ms(avg_compute)),
        "{{AVG_COMM_MS}}": str(us_to_ms(avg_comm)),
        "{{AVG_FREE_MS}}": str(us_to_ms(avg_free)),
        "{{COMPUTE_RATIO}}": str(round(compute_ratio, 1)),
        "{{COMM_RATIO}}": str(round(comm_ratio, 1)),
        "{{FREE_RATIO}}": str(round(free_ratio, 1)),
        "{{FREE_RATIO_COLOR}}": free_ratio_color,
        "{{STEP_LABELS}}": json.dumps(steps),
        "{{STAGE_TREND}}": json.dumps([us_to_ms(ss[s]["avg_stage"]) for s in steps]),
        "{{COMPUTE_TREND}}": json.dumps([us_to_ms(ss[s]["avg_compute"]) for s in steps]),
        "{{COMM_TREND}}": json.dumps([us_to_ms(ss[s]["avg_comm"]) for s in steps]),
        "{{FREE_TREND}}": json.dumps([us_to_ms(ss[s]["avg_free"]) for s in steps]),
        "{{COMPUTE_BAR}}": json.dumps([us_to_ms(ss[s]["avg_compute"]) for s in steps]),
        "{{COMM_BAR}}": json.dumps([us_to_ms(ss[s]["avg_comm"]) for s in steps]),
        "{{FREE_BAR}}": json.dumps([us_to_ms(ss[s]["avg_free"]) for s in steps]),
        "{{PIE_COMPUTE}}": str(us_to_ms(avg_compute)),
        "{{PIE_COMM}}": str(us_to_ms(avg_comm)),
        "{{PIE_FREE}}": str(us_to_ms(avg_free)),
        "{{PIE_OVERLAP}}": str(us_to_ms(avg_overlap)),
    }

    # 热力表
    heatmap_html = '<table class="w-full text-sm"><thead><tr><th class="text-left p-3">Rank</th>'
    for s in steps:
        heatmap_html += f'<th class="text-center p-3">Step {s}</th>'
    heatmap_html += '<th class="text-center p-3">平均</th></tr></thead><tbody>'
    for rid in sorted(rank_summary.keys(), key=lambda x: int(x) if x.isdigit() else 999):
        rs = rank_summary[rid]
        row_html = f'<tr><td class="p-3 font-bold text-white">{rid}</td>'
        step_data = data.get("step_statistic", [])
        rank_step_stage = {}
        for row in step_data:
            r_rank = str(row.get("rank_id", row.get("Index", row.get("index", "?"))))
            r_step = str(row.get("step_id", row.get("step", row.get("Step", "?"))))
            if r_rank == rid:
                stage_val = row.get("stage_time", row.get("stage", row.get("Stage", 0)))
                rank_step_stage[r_step] = float(stage_val) if stage_val else 0
        for s in steps:
            val = rank_step_stage.get(s, 0)
            val_ms = us_to_ms(val)
            ratio = safe_div(val, avg_stage) if avg_stage > 0 else 1
            if ratio > 1.1:
                cls = "heatmap-high"
            elif ratio < 0.9:
                cls = "heatmap-low"
            else:
                cls = "heatmap-mid"
            row_html += f'<td class="text-center p-2 {cls}">{val_ms}</td>'
        row_html += f'<td class="text-center p-2 font-bold text-white">{us_to_ms(rs["avg_stage"])}</td></tr>'
        heatmap_html += row_html
    heatmap_html += "</tbody></table>"
    r["{{RANK_HEATMAP_TABLE}}"] = heatmap_html

    # 慢卡识别
    slow_rows = ""
    for rid in sorted(rank_summary.keys(), key=lambda x: us_to_ms(rank_summary[x]["avg_stage"]), reverse=True):
        rs = rank_summary[rid]
        deviation = safe_div(rs["avg_stage"] - avg_stage, avg_stage) * 100 if avg_stage > 0 else 0
        if abs(deviation) > 10:
            badge = '<span class="badge-critical">严重偏差</span>' if deviation > 10 else '<span class="badge-warn">偏低</span>'
        else:
            badge = '<span class="badge-ok">正常</span>'
        slow_rows += f'<tr><td class="p-3 font-bold text-white">{rid}</td><td class="text-right p-3 text-slate-300">{us_to_ms(rs["avg_stage"])}</td><td class="text-right p-3 text-slate-300">{us_to_ms(rs["avg_compute"])}</td><td class="text-right p-3 text-slate-300">{us_to_ms(rs["avg_comm"])}</td><td class="text-right p-3 text-slate-300">{us_to_ms(rs["avg_free"])}</td><td class="text-right p-3 {"text-red-400" if deviation>10 else "text-emerald-400" if deviation<-10 else "text-slate-400"} font-semibold">{fmt_signed(round(deviation, 1))}%</td><td class="text-center p-3">{badge}</td></tr>'
    r["{{SLOW_RANK_ROWS}}"] = slow_rows

    # 通信算子 — TEXT 模式时间单位为 ms，DB 模式为 μs 需转换
    is_text_mode = data.get("format") == "text"
    comm_ops = data.get("comm_time_ops", [])
    if comm_ops:
        op_labels = [op.get("op_name", op.get("hccl_op_name", "?"))[:30] for op in comm_ops[:10]]
        r["{{COMM_HAS_DATA}}"] = "true"
        r["{{COMM_OP_LABELS}}"] = json.dumps(op_labels)
        # Units follow the table contract, never the container filename.
        comm_unit = data.get('units', {}).get('communication_time')
        if comm_unit is None:
            comm_unit = 'ms' if data.get('format') in ('text', 'db_new') else 'us'
        if comm_unit not in ('ms', 'us'):
            raise ValueError(f'unsupported communication time unit: {comm_unit}')
        def comm_time_val(op, keys):
            for k in keys:
                v = op.get(k)
                if v is not None:
                    return round(float(v) / US_TO_MS, 2) if comm_unit == 'us' else round(float(v), 4)
            return 0
        r["{{COMM_OP_ELAPSED}}"] = json.dumps([comm_time_val(op, ["avg_elapsed", "avg_elapsed_time"]) for op in comm_ops[:10]])
        r["{{COMM_OP_TRANSIT}}"] = json.dumps([comm_time_val(op, ["avg_transit", "transit_time"]) for op in comm_ops[:10]])
        r["{{COMM_OP_WAIT}}"] = json.dumps([comm_time_val(op, ["avg_wait", "wait_time"]) for op in comm_ops[:10]])
    else:
        r["{{COMM_HAS_DATA}}"] = "false"
        r["{{COMM_OP_LABELS}}"] = "[]"
        r["{{COMM_OP_ELAPSED}}"] = "[]"
        r["{{COMM_OP_TRANSIT}}"] = "[]"
        r["{{COMM_OP_WAIT}}"] = "[]"

    # 优化建议
    advice = ""
    if comm_ratio > 50:
        advice += f'<div class="bg-red-900/20 border-l-4 border-red-500 p-4 rounded-r-lg"><div class="text-red-400 text-xs font-bold uppercase">P0 — 通信主导</div><div class="text-white font-semibold mt-1">通信时间占比过高 ({comm_ratio:.1f}%)</div><div class="text-slate-400 text-sm mt-1">建议检查通信算子耗时 Top 列表，优化 AllReduce/AllGather，考虑通信压缩。</div></div>'
    if free_ratio > 20:
        advice += f'<div class="bg-orange-900/20 border-l-4 border-orange-500 p-4 rounded-r-lg"><div class="text-orange-400 text-xs font-bold uppercase">P1 — 空闲过高</div><div class="text-white font-semibold mt-1">空闲时间占比过高 ({free_ratio:.1f}%)</div><div class="text-slate-400 text-sm mt-1">可能存在流同步等待或 Host 下发瓶颈，检查算子下发效率。</div></div>'
    if rank_count > 1 and avg_stage > 0:
        max_dev = max(abs(safe_div(rank_summary[rr]["avg_stage"] - avg_stage, avg_stage) * 100) for rr in rank_summary)
        if max_dev > 10:
            advice += f'<div class="bg-orange-900/20 border-l-4 border-orange-500 p-4 rounded-r-lg"><div class="text-orange-400 text-xs font-bold uppercase">P1 — 负载不均</div><div class="text-white font-semibold mt-1">Rank 间负载不均 (最大偏差 {max_dev:.1f}%)</div><div class="text-slate-400 text-sm mt-1">检查数据分片均匀性和通信组配置。</div></div>'
    if compute_ratio > 70:
        advice += f'<div class="bg-blue-900/20 border-l-4 border-blue-500 p-4 rounded-r-lg"><div class="text-blue-400 text-xs font-bold uppercase">P2 — 计算主导</div><div class="text-white font-semibold mt-1">计算时间占比 {compute_ratio:.1f}%</div><div class="text-slate-400 text-sm mt-1">关注算子融合、计算精度优化和 Kernel 性能。</div></div>'
    if not advice:
        advice = '<div class="bg-emerald-900/20 border-l-4 border-emerald-500 p-4 rounded-r-lg"><div class="text-emerald-400 text-xs font-bold uppercase">P2</div><div class="text-white font-semibold mt-1">集群状态正常</div><div class="text-slate-400 text-sm mt-1">各项指标在正常范围内。</div></div>'
    r["{{ADVICE_CARDS}}"] = advice

    for key, val in r.items():
        html = html.replace(key, val)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"报告已生成: {output_path}")

# ==================== 比对报告 ====================

def generate_compare_report(data_a, data_b, template_path, output_path):
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    sa = data_a.get("step_summary", {})
    sb = data_b.get("step_summary", {})
    steps = sorted(set(list(sa.keys()) + list(sb.keys())), key=lambda x: int(x) if x.isdigit() else x)
    ra = data_a.get("rank_summary", {})
    rb = data_b.get("rank_summary", {})

    avg_a_stage = sum(s["avg_stage"] for s in sa.values()) / len(sa) if sa else 0
    avg_b_stage = sum(s["avg_stage"] for s in sb.values()) / len(sb) if sb else 0
    avg_a_compute = sum(s["avg_compute"] for s in sa.values()) / len(sa) if sa else 0
    avg_b_compute = sum(s["avg_compute"] for s in sb.values()) / len(sb) if sb else 0
    avg_a_comm = sum(s["avg_comm"] for s in sa.values()) / len(sa) if sa else 0
    avg_b_comm = sum(s["avg_comm"] for s in sb.values()) / len(sb) if sb else 0
    avg_a_free = sum(s["avg_free"] for s in sa.values()) / len(sa) if sa else 0
    avg_b_free = sum(s["avg_free"] for s in sb.values()) / len(sb) if sb else 0
    avg_a_overlap = sum(s["avg_overlap"] for s in sa.values()) / len(sa) if sa else 0
    avg_b_overlap = sum(s["avg_overlap"] for s in sb.values()) / len(sb) if sb else 0

    delta_stage = avg_b_stage - avg_a_stage
    delta_compute = avg_b_compute - avg_a_compute
    delta_comm = avg_b_comm - avg_a_comm
    delta_free = avg_b_free - avg_a_free

    stage_delta_pct = safe_div(delta_stage, avg_a_stage) * 100 if avg_a_stage else 0
    compute_contrib = safe_div(delta_compute, delta_stage) * 100 if delta_stage else 0
    comm_contrib = safe_div(delta_comm, delta_stage) * 100 if delta_stage else 0
    free_contrib = safe_div(delta_free, delta_stage) * 100 if delta_stage else 0

    # 占比
    total_a = avg_a_stage if avg_a_stage > 0 else 1
    total_b = avg_b_stage if avg_b_stage > 0 else 1
    a_comp_pct = round(safe_div(avg_a_compute, total_a) * 100, 1)
    a_comm_pct = round(safe_div(avg_a_comm, total_a) * 100, 1)
    a_free_pct = round(safe_div(avg_a_free, total_a) * 100, 1)
    b_comp_pct = round(safe_div(avg_b_compute, total_b) * 100, 1)
    b_comm_pct = round(safe_div(avg_b_comm, total_b) * 100, 1)
    b_free_pct = round(safe_div(avg_b_free, total_b) * 100, 1)

    bwa = data_a.get("comm_bandwidth", [])
    bwb = data_b.get("comm_bandwidth", [])
    bw_a_val = float(bwa[0].get("avg_bw", bwa[0].get("bandwidth_size", 0))) if bwa else 0
    bw_b_val = float(bwb[0].get("avg_bw", bwb[0].get("bandwidth_size", 0))) if bwb else 0
    bw_delta_pct = safe_div(bw_b_val - bw_a_val, bw_a_val) * 100 if bw_a_val else 0

    # 状态文字
    if stage_delta_pct > 10:
        status_text = "严重劣化"
        stage_delta_color = "text-red-400"
    elif stage_delta_pct > 5:
        status_text = "中度劣化"
        stage_delta_color = "text-orange-400"
    elif stage_delta_pct > 0:
        status_text = "轻微劣化"
        stage_delta_color = "text-orange-400"
    else:
        status_text = "性能改善"
        stage_delta_color = "text-emerald-400"

    bw_delta_color = "text-red-400" if bw_delta_pct < 0 else "text-emerald-400"
    load_type_text = f"计算 {a_comp_pct}% → {b_comp_pct}% | 通信 {a_comm_pct}% → {b_comm_pct}%"

    # 诊断摘要
    diagnosis = f"对比集群 B 的 Stage 总耗时{'增加' if delta_stage > 0 else '减少'} {abs(us_to_ms(delta_stage)):.1f} ms"
    if comm_contrib > 50:
        diagnosis += f"，通信是主要{'劣化' if delta_comm > 0 else '改善'}来源（贡献度 {comm_contrib:.1f}%）。"
    elif compute_contrib > 50:
        diagnosis += f"，计算是主要{'劣化' if delta_compute > 0 else '改善'}来源（贡献度 {compute_contrib:.1f}%）。"
    else:
        diagnosis += "，劣化来源分散。"

    r = {
        "{{PATH_A}}": data_a.get("data_dir", "?"),
        "{{PATH_B}}": data_b.get("data_dir", "?"),
        "{{GENERATE_TIME}}": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "{{STATUS_TEXT}}": status_text,
        "{{RANK_A}}": str(len(ra)), "{{RANK_B}}": str(len(rb)),
        "{{STEP_A}}": str(len(sa)), "{{STEP_B}}": str(len(sb)),
        "{{STAGE_A_MS}}": str(us_to_ms(avg_a_stage)), "{{STAGE_B_MS}}": str(us_to_ms(avg_b_stage)),
        "{{STAGE_DELTA_PERCENT}}": str(round(abs(stage_delta_pct), 1)),
        "{{STAGE_DELTA_SIGN}}": "+" if stage_delta_pct >= 0 else "",
        "{{STAGE_DELTA_COLOR}}": stage_delta_color,
        "{{DELTA_COMPUTE_MS}}": str(us_to_ms(abs(delta_compute))),
        "{{DELTA_COMPUTE_SIGN}}": "+" if delta_compute >= 0 else "",
        "{{DELTA_COMM_MS}}": str(us_to_ms(abs(delta_comm))),
        "{{DELTA_COMM_SIGN}}": "+" if delta_comm >= 0 else "",
        "{{COMPUTE_CONTRIB}}": str(round(compute_contrib, 1)),
        "{{COMM_CONTRIB}}": str(round(comm_contrib, 1)),
        "{{BW_A}}": str(round(bw_a_val, 2)), "{{BW_B}}": str(round(bw_b_val, 2)),
        "{{BW_DELTA_PERCENT}}": str(round(abs(bw_delta_pct), 1)),
        "{{BW_DELTA_SIGN}}": "+" if bw_delta_pct >= 0 else "",
        "{{BW_DELTA_COLOR}}": bw_delta_color,
        "{{DIAGNOSIS_TEXT}}": diagnosis,
        "{{LOAD_TYPE_TEXT}}": load_type_text,
        "{{STEP_LABELS}}": json.dumps(steps),
        "{{A_STAGE_BAR}}": json.dumps([us_to_ms(sa.get(s, {"avg_stage": 0})["avg_stage"]) for s in steps]),
        "{{B_STAGE_BAR}}": json.dumps([us_to_ms(sb.get(s, {"avg_stage": 0})["avg_stage"]) for s in steps]),
        "{{A_PIE_COMPUTE_PCT}}": str(a_comp_pct), "{{A_PIE_COMM_PCT}}": str(a_comm_pct), "{{A_PIE_FREE_PCT}}": str(a_free_pct),
        "{{B_PIE_COMPUTE_PCT}}": str(b_comp_pct), "{{B_PIE_COMM_PCT}}": str(b_comm_pct), "{{B_PIE_FREE_PCT}}": str(b_free_pct),
    }

    # 关键定位点
    key_points = ""
    if delta_comm != 0:
        key_points += f'<li class="flex items-start"><span class="mr-2 text-xl">📡</span><p>通信时间{"增加" if delta_comm > 0 else "减少"} <strong>{abs(us_to_ms(delta_comm)):.1f} ms</strong>，贡献度 {comm_contrib:.1f}%<br><span class="text-white font-semibold">{"通信为主要劣化来源" if delta_comm > 0 and comm_contrib > 50 else "通信有改善" if delta_comm < 0 else "通信变化不显著"}</span></p></li>'
    if a_comm_pct != b_comm_pct:
        dominant = "通信反超计算" if b_comm_pct > b_comp_pct and a_comm_pct <= a_comp_pct else "通信占比上升"
        key_points += f'<li class="flex items-start"><span class="mr-2 text-xl">📊</span><p>负载转换：通信占比 {a_comm_pct}% → {b_comm_pct}%<br><span class="text-orange-400 font-semibold">{dominant}</span></p></li>'
    if bw_delta_pct < -10:
        key_points += f'<li class="flex items-start"><span class="mr-2 text-xl">📉</span><p>带宽下降 {abs(bw_delta_pct):.1f}%（{bw_a_val:.1f} → {bw_b_val:.1f} GB/s）<br><span class="text-red-400 font-semibold">带宽暴跌，需排查硬件链路</span></p></li>'
    if delta_free > 0 and free_contrib > 10:
        key_points += f'<li class="flex items-start"><span class="mr-2 text-xl">💤</span><p>空闲时间增加 {us_to_ms(delta_free):.1f} ms（贡献度 {free_contrib:.1f}%）<br><span class="text-orange-400 font-semibold">可能存在 Host 下发瓶颈</span></p></li>'
    if not key_points:
        key_points = '<li class="flex items-start"><span class="mr-2 text-xl">✅</span><p>未发现显著性能差异</p></li>'
    r["{{KEY_POINTS_HTML}}"] = key_points

    # 瀑布图数据
    wf = [
        {"name": "基准 Stage", "value": us_to_ms(avg_a_stage), "contrib": ""},
        {"name": "计算变化", "value": round(us_to_ms(delta_compute), 1), "contrib": str(round(compute_contrib, 1))},
        {"name": "通信变化", "value": round(us_to_ms(delta_comm), 1), "contrib": str(round(comm_contrib, 1))},
        {"name": "空闲变化", "value": round(us_to_ms(delta_free), 1), "contrib": str(round(free_contrib, 1))},
        {"name": "对比 Stage", "value": us_to_ms(avg_b_stage), "contrib": ""},
    ]
    r["{{WATERFALL_DATA}}"] = json.dumps(wf, ensure_ascii=False)

    # 通信算子差异 — 需要统一单位到 ms
    is_a_text = data_a.get("format") == "text"
    is_b_text = data_b.get("format") == "text"
    ops_a = {op.get("op_name", op.get("hccl_op_name", "?")): op for op in data_a.get("comm_time_ops", [])}
    ops_b = {op.get("op_name", op.get("hccl_op_name", "?")): op for op in data_b.get("comm_time_ops", [])}
    all_ops = set(list(ops_a.keys()) + list(ops_b.keys()))
    diff_list = []
    for op in all_ops:
        ea_raw = ops_a.get(op, {}).get("avg_elapsed", ops_a.get(op, {}).get("avg_elapsed_time", 0))
        eb_raw = ops_b.get(op, {}).get("avg_elapsed", ops_b.get(op, {}).get("avg_elapsed_time", 0))
        # 统一到 ms: TEXT 模式已经是 ms，DB 模式需要 μs→ms
        ea = float(ea_raw or 0) if is_a_text else us_to_ms(float(ea_raw or 0))
        eb = float(eb_raw or 0) if is_b_text else us_to_ms(float(eb_raw or 0))
        diff = eb - ea
        diff_list.append((op, diff))
    diff_list.sort(key=lambda x: x[1], reverse=True)
    top_diff = diff_list[:10]
    if top_diff:
        r["{{COMM_DIFF_HAS_DATA}}"] = "true"
        r["{{COMM_DIFF_LABELS}}"] = json.dumps([d[0][:30] for d in top_diff])
        r["{{COMM_DIFF_VALUES}}"] = json.dumps([round(d[1], 2) for d in top_diff])
    else:
        r["{{COMM_DIFF_HAS_DATA}}"] = "false"
        r["{{COMM_DIFF_LABELS}}"] = "[]"
        r["{{COMM_DIFF_VALUES}}"] = "[]"

    # 带宽对比
    if bwa or bwb:
        bw_labels = list(set([b.get("transport_type", b.get("band_type", "?")) for b in bwa + bwb]))
        a_bw_map = {b.get("transport_type", b.get("band_type", "?")): b.get("avg_bw", b.get("bandwidth_size", 0)) for b in bwa}
        b_bw_map = {b.get("transport_type", b.get("band_type", "?")): b.get("avg_bw", b.get("bandwidth_size", 0)) for b in bwb}
        r["{{BW_HAS_DATA}}"] = "true"
        r["{{BW_LABELS}}"] = json.dumps(bw_labels)
        r["{{A_BW_BAR}}"] = json.dumps([round(float(a_bw_map.get(l, 0)), 2) for l in bw_labels])
        r["{{B_BW_BAR}}"] = json.dumps([round(float(b_bw_map.get(l, 0)), 2) for l in bw_labels])
    else:
        r["{{BW_HAS_DATA}}"] = "false"
        r["{{BW_LABELS}}"] = "[]"
        r["{{A_BW_BAR}}"] = "[]"
        r["{{B_BW_BAR}}"] = "[]"

    # Rank 差异表
    all_ranks = sorted(set(list(ra.keys()) + list(rb.keys())), key=lambda x: int(x) if x.isdigit() else 999)
    rank_diff_rows = ""
    for rid in all_ranks:
        sa_val = ra.get(rid, {"avg_stage": 0})["avg_stage"]
        sb_val = rb.get(rid, {"avg_stage": 0})["avg_stage"]
        diff = sb_val - sa_val
        pct = safe_div(diff, sa_val) * 100 if sa_val else 0
        if diff > 0:
            trend = '<span class="delta-up">↑ 劣化</span>'
        elif diff < 0:
            trend = '<span class="delta-down">↓ 改善</span>'
        else:
            trend = '<span class="delta-neutral">→ 持平</span>'
        rank_diff_rows += f'<tr><td class="p-3 font-bold text-white">{rid}</td><td class="text-right p-3 text-slate-300">{us_to_ms(sa_val)}</td><td class="text-right p-3 text-slate-300">{us_to_ms(sb_val)}</td><td class="text-right p-3 {"delta-up" if diff>0 else "delta-down" if diff<0 else "delta-neutral"}>{fmt_signed(us_to_ms(diff))}</td><td class="text-right p-3 {"delta-up" if pct>0 else "delta-down" if pct<0 else "delta-neutral"}>{fmt_signed(round(pct, 1))}%</td><td class="text-center p-3">{trend}</td></tr>'
    r["{{RANK_DIFF_ROWS}}"] = rank_diff_rows

    # 劣化根因列表
    deg_items = ""
    if stage_delta_pct > 10:
        deg_items += f'<div class="flex items-center justify-between p-3 bg-red-900/20 rounded-lg"><div><span class="text-red-400 font-bold mr-2">P0</span><span class="text-white">Stage 总耗时增幅 {stage_delta_pct:.1f}%</span></div><span class="text-red-400 font-mono">+{us_to_ms(delta_stage):.1f} ms</span></div>'
    if comm_contrib > 50 and delta_comm > 0:
        deg_items += f'<div class="flex items-center justify-between p-3 bg-orange-900/20 rounded-lg"><div><span class="text-orange-400 font-bold mr-2">P0</span><span class="text-white">通信劣化主导 ({comm_contrib:.1f}%)</span></div><span class="text-orange-400 font-mono">+{us_to_ms(delta_comm):.1f} ms</span></div>'
    if bw_delta_pct < -10:
        deg_items += f'<div class="flex items-center justify-between p-3 bg-red-900/20 rounded-lg"><div><span class="text-red-400 font-bold mr-2">P0</span><span class="text-white">带宽暴跌 {abs(bw_delta_pct):.1f}%</span></div><span class="text-red-400 font-mono">{bw_a_val:.1f}→{bw_b_val:.1f}</span></div>'
    if compute_contrib > 50 and delta_compute > 0:
        deg_items += f'<div class="flex items-center justify-between p-3 bg-blue-900/20 rounded-lg"><div><span class="text-blue-400 font-bold mr-2">P1</span><span class="text-white">计算劣化 ({compute_contrib:.1f}%)</span></div><span class="text-blue-400 font-mono">+{us_to_ms(delta_compute):.1f} ms</span></div>'
    if free_contrib > 10 and delta_free > 0:
        deg_items += f'<div class="flex items-center justify-between p-3 bg-orange-900/20 rounded-lg"><div><span class="text-orange-400 font-bold mr-2">P1</span><span class="text-white">空闲增加 ({free_contrib:.1f}%)</span></div><span class="text-orange-400 font-mono">+{us_to_ms(delta_free):.1f} ms</span></div>'
    if not deg_items:
        deg_items = '<div class="p-3 bg-emerald-900/20 rounded-lg text-emerald-400">未发现显著劣化</div>'
    r["{{DEGRADATION_ITEMS}}"] = deg_items

    # 行动建议
    actions = ""
    if bw_delta_pct < -10:
        actions += '<li class="flex items-start"><div class="flex-shrink-0 w-8 h-8 rounded-full bg-emerald-500/20 flex items-center justify-center text-emerald-400 font-bold mr-3">1</div><div><h4 class="text-sm font-semibold text-white">网络拓扑与硬件检查</h4><p class="text-xs text-slate-400 mt-1">重点检查 HCCS 链路状态、交换机拥塞、光模块降级。</p></div></li>'
    if comm_contrib > 50:
        actions += '<li class="flex items-start"><div class="flex-shrink-0 w-8 h-8 rounded-full bg-emerald-500/20 flex items-center justify-center text-emerald-400 font-bold mr-3">2</div><div><h4 class="text-sm font-semibold text-white">集合通信算法调优</h4><p class="text-xs text-slate-400 mt-1">对比通信域切分策略、AllReduce/AllGather 算法参数。</p></div></li>'
    if compute_contrib > 50:
        actions += '<li class="flex items-start"><div class="flex-shrink-0 w-8 h-8 rounded-full bg-emerald-500/20 flex items-center justify-center text-emerald-400 font-bold mr-3">3</div><div><h4 class="text-sm font-semibold text-white">算子性能排查</h4><p class="text-xs text-slate-400 mt-1">检查计算算子变化、精度配置、Kernel 编译优化。</p></div></li>'
    if free_contrib > 10:
        actions += '<li class="flex items-start"><div class="flex-shrink-0 w-8 h-8 rounded-full bg-emerald-500/20 flex items-center justify-center text-emerald-400 font-bold mr-3">4</div><div><h4 class="text-sm font-semibold text-white">Host 下发效率</h4><p class="text-xs text-slate-400 mt-1">检查算子下发、流同步、CPU 负载。</p></div></li>'
    if not actions:
        actions = '<li class="flex items-start"><div class="flex-shrink-0 w-8 h-8 rounded-full bg-emerald-500/20 flex items-center justify-center text-emerald-400 font-bold mr-3">1</div><div><h4 class="text-sm font-semibold text-white">持续监控</h4><p class="text-xs text-slate-400 mt-1">性能差异在可接受范围，建议持续监控。</p></div></li>'
    r["{{ACTION_ITEMS}}"] = actions

    for key, val in r.items():
        html = html.replace(key, val)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"比对报告已生成: {output_path}")

# ==================== 主入口 ====================

def main():
    parser = argparse.ArgumentParser(description="集群报告生成器")
    parser.add_argument("--mode", required=True, choices=["single", "compare"])
    parser.add_argument("--data", help="单集群 JSON 路径")
    parser.add_argument("--data-a", help="比对: 集群A JSON")
    parser.add_argument("--data-b", help="比对: 集群B JSON")
    parser.add_argument("--template-dir", default=None)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    tpl_dir = args.template_dir or os.path.join(script_dir, "..", "templates")

    if args.mode == "single":
        with open(args.data, "r", encoding="utf-8") as f:
            data = json.load(f)
        generate_single_report(data, os.path.join(tpl_dir, "cluster_analysis_report.html"), args.output)
    else:
        with open(args.data_a, "r", encoding="utf-8") as f:
            data_a = json.load(f)
        with open(args.data_b, "r", encoding="utf-8") as f:
            data_b = json.load(f)
        generate_compare_report(data_a, data_b, os.path.join(tpl_dir, "cluster_compare_report.html"), args.output)

if __name__ == "__main__":
    main()
