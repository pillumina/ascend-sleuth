"""Shared data preparation for the cluster comparison reports."""
from collections import defaultdict
from itertools import zip_longest
import json
import math
import re


def label_order(label):
    return (0, int(label), label) if label.isdecimal() else (1, label.casefold(), label)


def ordinal_step_pairs(a, b):
    """仅在两侧有 Step 且编号完全不重叠时按采集顺序对齐。"""
    if not a or not b or a.keys() & b.keys():
        return [], ""
    a_order, b_order = (sorted(steps, key=label_order) for steps in (a, b))
    pairs = [(f"对齐{i}：A {sa if sa is not None else '—'} ↔ B {sb if sb is not None else '—'}", sa, sb)
             for i, (sa, sb) in enumerate(zip_longest(a_order, b_order), 1)]
    note = (f"两侧采集的 Step 编号不重叠（基准 A：{'、'.join(a_order)}；对比 B：{'、'.join(b_order)}）。"
            "按采集顺序对齐（A 第 i 个 Step ↔ B 第 i 个 Step），并据此计算 B − A。"
            "配对的 Step 并非同一迭代，结果仅用于形态对比，不能作为逐步性能结论。")
    return pairs, note


def finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def first(row, fields):
    return next((row[key] for key in fields if row.get(key) not in (None, "")), None)


# Metric order is shared with the Rank chart. All step_statistic formats use μs.
RANK_FIELDS = (
    ("stage_time", "stage", "Stage"),
    ("communication_time", "communication", "Communication"),
    ("free_time", "free", "Free"),
    ("overlap_communication_time", "overlapped", "Overlapped"),
    ("pure_communication_time", "communication_not_overlapped", "Communication(Not Overlapped)"),
    ("compute_time", "computing", "Computing"),
)
SUMMARY_FIELDS = ("avg_stage", "avg_comm", "avg_free", "avg_overlap", "avg_pure_comm", "avg_compute")


def time_difference(total, part):
    return total - part if total is not None and part is not None and total >= part else None


def rank_times(row, fields):
    stage, comm, free, overlap, pure_comm, compute = [
        finite_number(first(row, aliases)) for aliases in fields
    ]
    if overlap is None:
        overlap = time_difference(comm, pure_comm)
    if pure_comm is None:
        pure_comm = time_difference(comm, overlap)
    return (stage, comm, free, overlap, pure_comm, time_difference(compute, overlap))


def cluster_rank_steps(data):
    steps = defaultdict(dict)
    duplicates = {}
    for row in data.get("step_statistic", []):
        if str(first(row, ("type", "Type")) or "rank").lower() != "rank":
            continue
        step = first(row, ("step_id", "step", "Step"))
        rank = first(row, ("rank_id", "index", "Index"))
        if step is None or rank is None:
            continue
        step, rank = str(step), str(rank)
        values = rank_times(row, RANK_FIELDS)
        step_rows = steps[step]
        if rank in step_rows:
            key = (step, rank)
            if key not in duplicates:
                duplicates[key] = [[value or 0, int(value is not None)] for value in step_rows[rank]]
            for totals, value in zip(duplicates[key], values):
                if value is not None:
                    totals[0] += value
                    totals[1] += 1
        else:
            step_rows[rank] = values
    for (step, rank), totals in duplicates.items():
        steps[step][rank] = [total / count if count else None for total, count in totals]
    return steps


def rank_chart_data(data_a, data_b):
    clusters = (data_a, data_b)
    a, b = (cluster_rank_steps(data) for data in clusters)
    summary_only = [name for name, steps, data in zip(("A", "B"), (a, b), clusters)
                    if not steps and data.get("rank_summary")]
    use_summary = not a and not b and bool(summary_only)
    if use_summary:
        a, b = ({"跨 Step 均值": {
            str(rank): rank_times(row, [(field,) for field in SUMMARY_FIELDS])
            for rank, row in data.get("rank_summary", {}).items()
        }} for data in clusters)

    pairs, pairing_note = ordinal_step_pairs(a, b)
    if not pairs:
        pairs = [(step, step, step) for step in sorted(a.keys() | b.keys(), key=label_order)]

    ranks = sorted({rank for cluster in (a, b) for rows in cluster.values() for rank in rows}, key=label_order)
    rank_index = {rank: index for index, rank in enumerate(ranks)}

    def pack(rows):
        values = []
        for rank, times in rows.items():
            values.append(rank_index[rank])
            values.extend(round(value / 1000, 9) if value is not None else None for value in times)
        return values

    return {
        "ranks": ranks,
        "steps": [[label, pack(a.get(sa, {})), pack(b.get(sb, {}))] for label, sa, sb in pairs],
        "pairing": "ordinal" if pairing_note else None,
        "pairingNote": pairing_note,
        "summaryOnly": summary_only,
        "usesSummary": use_summary,
    }


COMM_TYPES = (
    "BatchSendRecv", "BatchSendReceive", "AllGatherV", "AllGather", "AllReduce",
    "AllToAllVC", "AllToAllV", "AllToAll", "ReduceScatterV", "ReduceScatter",
    "Broadcast", "Reduce", "Scatter", "Gather", "SendRecv", "SendReceive", "Send",
    "Receive", "Recv", "Barrier",
)
COMM_LABELS = {kind.lower(): kind for kind in COMM_TYPES}
COMM_LABELS.update(batchsendreceive="BatchSendRecv", sendreceive="SendRecv", recv="Receive")
COMM_TYPE_PATTERN = re.compile("|".join(sorted(COMM_LABELS, key=len, reverse=True)))


def communication_type(name):
    name = name.partition("@")[0].strip().lower()
    if not name or name.startswith("total"):
        return None
    name = re.sub(r"^(?:hcom|hccl|nccl)", "", name)
    match = COMM_TYPE_PATTERN.match(re.sub(r"[^a-z0-9]", "", name))
    return COMM_LABELS[match[0]] if match else "其他通信"


def communication_top_differences(data_a, data_b):
    """Rank comparable operators by signed mean elapsed difference (B − A)."""
    def elapsed_by_name(data):
        divisor = 1 if data.get("format") == "text" else 1000
        entries = {}
        for op in data.get("comm_time_ops", []):
            name = first(op, ("op_name", "hccl_op_name"))
            elapsed = finite_number(first(op, ("avg_elapsed", "avg_elapsed_time")))
            if name and communication_type(name) and elapsed is not None:
                entries[name] = elapsed / divisor
        return entries

    a, b = (elapsed_by_name(data) for data in (data_a, data_b))
    groups = defaultdict(list)
    for name in a.keys() & b.keys():
        groups[communication_type(name)].append((name, a[name], b[name], b[name] - a[name]))
    top = {kind: sorted(rows, key=lambda row: (-row[3], row[0]))[:10] for kind, rows in sorted(groups.items())}
    partial = [name for name, data in zip(("A", "B"), (data_a, data_b))
               if data.get("comm_time_ops") and not data.get("comm_time_ops_complete")]
    notes = []
    if a.keys() ^ b.keys():
        notes.append(f"{len(a.keys() ^ b.keys())} 个算子仅在一侧有耗时，未参与排名。")
    if partial:
        notes.append(f"集群 {'、'.join(partial)} 的旧提取结果可能只含全局 Top 20，重新提取后可获得完整排名。")
    return top, notes


COMM_DIFF_UNIT = "μs"
COMM_DIFF_NOTE = "HCCL 微算子单次耗时为微秒量级，平均耗时与差值以 μs 展示。"


def communication_diff_display(data_a, data_b):
    groups, notes = communication_top_differences(data_a, data_b)
    return {kind: [(name, *(round(value * 1000, 3) or 0.0 for value in (a, b, delta)))
                   for name, a, b, delta in rows] for kind, rows in groups.items()}, notes


def inline_json(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
