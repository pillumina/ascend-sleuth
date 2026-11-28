"""Per-implementation execution sequences for the offline report."""
import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from cross_trace import kernel_rows
from npu_source import is_main_db

BASE_FIELDS = [
    ("名称", ""), ("类型", ""), ("加速器核", ""), ("开始时间", "ms"), ("时长", "μs"),
    ("等待时间", "μs"), ("Block 数量", ""), ("输入 Shapes", ""), ("输入数据类型", ""),
    ("输入格式", ""), ("输出 Shapes", ""), ("输出数据类型", ""), ("输出格式", "")]
COUNTERS = [f"{core}_{suffix}" for core in ("aic", "aiv") for suffix in (
    "fixpipe_ratio", "fixpipe_time", "icache_miss_rate", "mac_ratio", "mac_time",
    "mte1_ratio", "mte1_time", "mte2_ratio", "mte2_time", "mte3_ratio", "mte3_time",
    "scalar_ratio", "scalar_time", "total_cycles", "total_time", "vec_ratio", "vec_time")]
FIELDS = BASE_FIELDS + [(key, "ns" if key.endswith("_time") else "cycles" if key.endswith("_cycles")
                          else "比值") for key in COUNTERS]
TENSORS = [prefix + " " + field for prefix in ("Input", "Output") for field in ("Shapes", "Data Types", "Formats")]


def clean(value):
    value = str(value).strip().strip('"') if value is not None else ""
    return value if value not in ("", "N/A", "None") else None


def number(value):
    value = clean(value)
    if value is None:
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except ValueError:
        return None


def ns(value):
    return int(Decimal(str(value).strip()) * 1000)


def session_start(path):
    if path is not None and is_main_db(path):
        try:
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                return db.execute("SELECT MIN(CAST(startTimeNs AS INTEGER)) FROM SESSION_TIME_INFO").fetchone()[0]
        except sqlite3.Error:
            pass
    return None


def clock_origin(source, first_ns):
    start = session_start(source)
    if start is None:
        return first_ns, "本侧首个 kernel"
    folder = source.parent
    rank_folder = folder.parent.parent if folder.name == "ASCEND_PROFILER_OUTPUT" else folder.parent
    if re.fullmatch(r"rank_\d+", rank_folder.name):
        starts = [start]
        for peer in rank_folder.parent.glob("rank_*"):
            exports = list(peer.glob("*_ascend_pt/ASCEND_PROFILER_OUTPUT"))
            if peer != rank_folder and len(exports) == 1:
                candidates = [p for p in exports[0].glob("*.db") if is_main_db(p)]
                other = session_start(candidates[0]) if len(candidates) == 1 else None
                if other is not None:
                    starts.append(other)
        return min(starts), "同一采集目录的最早会话起点"
    return start, "本侧会话起点"


def pmu_by_task(path):
    if not is_main_db(path):
        return {}
    query = """SELECT p.globalTaskId,s.value,p.value
               FROM TASK_PMU_INFO p
               JOIN STRING_IDS s ON s.id=p.name"""
    out = defaultdict(dict)
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            for task, name, value in db.execute(query):
                value = number(value)
                if value is not None:
                    out[task][name] = value
    except sqlite3.Error:
        return {}
    return out


def csv_counters(row):
    out = []
    for name in COUNTERS:
        if name.endswith("_time"):
            column = {"aic_total_time": "aicore_time", "aiv_total_time": "aiv_time"}.get(name, name)
            value = number(row.get(column + "(us)"))
            out.append(value * 1000 if value is not None else None)
        else:
            out.append(number(row.get(name)))
    return out


def companion_counters(source):
    """Supplement missing counters only for uniquely identified tasks of this rank."""
    if not is_main_db(source) or not (source.parent / "kernel_details.csv").is_file():
        return {}
    if sum(is_main_db(p) for p in source.parent.glob("*.db")) != 1:
        return {}
    counters = {}
    for row in kernel_rows(source.parent):
        start = clean(row.get("Start Time(us)"))
        if start and clean(row.get("Task ID")):
            key = (row.get("Device_id"), row.get("Stream ID"), row["Task ID"], ns(start),
                   row["Name"], row["Type"])
            counters[key] = csv_counters(row) if key not in counters else None
    return counters


def npu_sequences(folder, supplement=False):
    timed, incomplete = [], set()
    for order, row in enumerate(kernel_rows(folder)):
        if not clean(row.get("Name")) or not clean(row.get("Type")):
            continue
        if number(row.get("Start Time(us)")) is None:
            incomplete.add((row["Type"], row["Name"]))
            continue
        timed.append((ns(row["Start Time(us)"]), order, row))
    series = defaultdict(list)
    origin, clock = clock_origin(folder, min((x[0] for x in timed), default=0))
    counters = pmu_by_task(folder)
    csv_pmu = companion_counters(folder) if supplement else {}
    for start, _, r in sorted(timed, key=lambda x: (x[0], x[1])):
        key = r["Type"], r["Name"]
        if key in incomplete:
            continue  # A missing timestamp would renumber all subsequent occurrences.
        stream, task = r.get("Stream ID"), r.get("Task ID")
        raw = counters.get(r.get("globalTaskId"), {})
        fallback = csv_pmu.get((r.get("Device_id"), stream, task, start, r["Name"], r["Type"]))
        pmu = [raw.get(k, v) for k, v in zip(COUNTERS, fallback or csv_counters(r))]
        record = [r["Name"], r["Type"], clean(r.get("Accelerator Core")), (start-origin)/1e6,
                  number(r.get("Duration(us)")), number(r.get("Wait Time(us)")), number(r.get("Block Num", r.get("Block Dim")))]
        record.extend(clean(r.get(k)) for k in TENSORS)
        series[key].append(record + pmu + [task, stream])
    return series, clock


def make_catalog(left, right, top_types, left_clock, right_clock, reasons=None):
    priority = {t: i for i, t in enumerate(dict.fromkeys(top_types))}
    return dict(fields=FIELDS, clocks=[left_clock, right_clock], series=[
        dict(type=t, name=n, left=left[t,n], right=right.get((t,n), []),
             note=(reasons or {}).get((t,n), ""))
        for t,n in sorted(left, key=lambda k:(priority.get(k[0],len(priority)), k[0], k[1]))])


def npu_pair(current, baseline, top_rows, alias_types, supplement=(False, False)):
    left, lc = npu_sequences(current, supplement[0])
    right, rc = npu_sequences(baseline, supplement[1])
    pairs = {k:k for k in left.keys() & right.keys()}
    # An implementation can change spelling between exports. Reserve exact
    # pairs first; allow only a unique remaining match with evidence.
    rem = right.keys() - pairs.keys()
    def evidence(a,b):
        return {r[2] for r in a} == {r[2] for r in b} and bool(
            {(r[7], r[8], r[10], r[11]) for r in a if r[7] and r[8]} &
            {(r[7], r[8], r[10], r[11]) for r in b if r[7] and r[8]})
    candidates = {k:[q for q in rem if (k[0] == q[0] or (k[1] == q[1] and (k[0],q[0]) in alias_types))
                      and evidence(left[k],right[q])] for k in left.keys()-pairs.keys()}
    uses = Counter(q for qs in candidates.values() for q in qs)
    for k, qs in candidates.items():
        if len(qs)==1 and uses[qs[0]]==1:
            pairs[k]=qs[0]
    occurrences = {k:[[event] for event in right[q]] for k,q in pairs.items()}
    return make_catalog(left, occurrences, (r["op"] for r in top_rows), lc, rc)


def gpu_record(bucket_key, event, origin):
    name, tag, shapes = bucket_key
    args = event.get("args", {})
    grid = args.get("grid")
    blocks = (grid[0] * grid[1] * grid[2] if isinstance(grid, list) and len(grid) == 3
              and all(isinstance(i, int) for i in grid) else None)
    row = [name, tag or event["cat"], None, (ns(event["ts"])-origin)/1e6, float(event["dur"]),
           None, blocks, None, None, None, None, None, None]
    if tag and len(shapes)==3:
        a,b,out = (v.replace("x",",") for v in shapes)
        row[7:13] = [a+";"+b, "BF16;BF16", None, out, "FP32" if tag.endswith("o_fp32") else "BF16", None]
    # GPU PMU is not an Ascend AIC/AIV counter. Keep the GPU record compact.
    return dict(values=row, task=args.get("correlation"), stream=args.get("stream"))


def gpu_occurrences(keys, buckets, status, origin):
    calls = defaultdict(list)
    for k in keys:
        for order, tag_id, e in buckets[k].launches:
            if status in ("语义分组", "形状分组"):
                if tag_id is None:
                    return []
                owner = tag_id
            elif status == "语义阶段" and any("FlashAttnBwd" in s[0] for s in keys):
                owner = e.get("args",{}).get("External id")
                if owner is None:
                    return []
            else:
                owner = order
            calls[owner].append((ns(e["ts"]), order, k, e))
    ordered = [sorted(group, key=lambda x:x[:2]) for group in calls.values()]
    if status == "语义阶段" and any("FlashAttnBwd" in s[0] for s in keys):
        if any(sum(bool(re.search(r"FlashAttnBwdSm\d+", x[2][0])) for x in group)!=1 for group in ordered):
            return []
    return [[gpu_record(k,e,origin) for _,_,k,e in group]
            for group in sorted(ordered,key=lambda g:g[0][:2])]


def gpu_pair(folder, groups, buckets, proposals, gpu_meta, top, supplement=False):
    left, clock = npu_sequences(folder, supplement)
    # A raw CUDA symbol or a complete uniquely attributable semantic operation
    # defines a sequence. Partial shape buckets cannot retain original ordinals.
    claims = defaultdict(set)
    status_by_key = {}
    by_name = defaultdict(list)
    for key in buckets:
        by_name[key[0]].append(key)
    symbol_uses = Counter(name for _,name in left)
    for typ,name in left:
        impl = typ,name
        if name in by_name and symbol_uses[name]==1:
            claims[impl].update(by_name[name])
            status_by_key[impl]="同名"
            continue
        members = [key for key,g in groups.items() if key[0]==typ and name in g.symbols]
        if not members or any(not proposals[k][0] or len(groups[k].symbols) != 1
                              or proposals[k][1].calls != groups[k].time.calls for k in members):
            continue
        statuses = {proposals[k][2] for k in members}
        if len(statuses) == 1:
            status_by_key[impl] = statuses.pop()
            for key in members:
                claims[impl].update(proposals[key][0])
    uses = Counter(k for ks in claims.values() for k in ks)
    right, reasons = {}, {}
    origin=ns(gpu_meta["origin_us"])
    for impl in left:
        keys = claims.get(impl, ())
        if keys and all(uses[k]==1 for k in keys):
            right[impl]=gpu_occurrences(keys,buckets,status_by_key[impl],origin)
        if not right.get(impl):
            reasons[impl]="GPU 侧缺少可独立编号的完整对应实现序列。"
    return make_catalog(left,right,(k[0] for k in top),clock,gpu_meta["origin_kind"],reasons)


def render_execution(result, comparison=None):
    catalog = result.get("execution")
    if not catalog or not catalog["series"]:
        return ""
    template = Path(__file__).with_name("execution_panel.html").read_text(encoding="utf-8-sig")
    from host_kernel_report import labels
    left, right, peer = labels(result, comparison)
    display = dict(labels=[left, right], gpu_peer=peer == "gpu")
    payload = json.dumps({**catalog, **display}, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False).replace("<", "\\u003c")
    return template.replace("__DATA__", payload, 1)
