"""Read single-rank Ascend and Kineto profiles. Aggregate durations are in µs."""
import csv
import gzip
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from npu_source import db_host_spans, db_kernels, is_main_db


@dataclass
class Metric:
    calls: int = 0
    us: float = 0

    def add(self, duration, calls=1):
        self.calls += calls
        self.us += duration

    def merge(self, other):
        self.add(other.us, other.calls)

    def values(self):
        return dict(calls=self.calls, total_ms=self.us / 1000,
                    avg_us=self.us / self.calls if self.calls else None)


def rows(path, required):
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = set(required) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path.name} 缺少列 {sorted(missing)}")
        yield from reader


def duration(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"无效的耗时 {value}")
    return value


def trace_document(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as f:
        obj = json.load(f)
    events = obj.get("traceEvents") if isinstance(obj, dict) else obj
    if not isinstance(events, list):
        raise ValueError(f"{path} 缺少 traceEvents 数组")
    return (obj if isinstance(obj, dict) else {}), events


def trace_events(path):
    return trace_document(path)[1]


def gpu_file(path):
    path = Path(path)
    if path.is_file() and path.name.endswith((".json", ".json.gz")):
        return path
    files = sorted([*path.glob("*.pt.trace.json"), *path.glob("*.pt.trace.json.gz")])
    # Exporters often leave the original and its decompressed copy side by side.
    if len(files) == 2 and files[1] == Path(str(files[0]) + ".gz"):
        with files[0].open("rb") as plain, gzip.open(files[1], "rb") as compressed:
            while True:
                chunk = plain.read(1024 * 1024)
                if chunk != compressed.read(1024 * 1024):
                    break
                if not chunk:
                    return files[0]
    if len(files) > 1:
        raise ValueError("GPU 目录中有多个 trace，请指定单个 rank 的 trace 文件")
    return files[0] if files else None


def trace_host_spans(path):
    """Attach each torch_to_npu device endpoint to its source span."""
    events = trace_events(path) if path.is_file() else []
    sources, ends = {}, {}
    flows = defaultdict(set)
    for e in events:
        if e.get("cat") == "async_npu" and e.get("name") == "torch_to_npu":
            key = (e["pid"], e["tid"], Decimal(str(e["ts"])))
            if e["ph"] == "s":
                sources[e["id"]] = key
            elif e["ph"] == "f":
                ends[e["id"]] = key
    for flow, (_, stream, ts) in ends.items():
        if flow in sources:
            flows[sources[flow]].add((str(stream), ts))
    for e in events:
        if e.get("cat") == "cpu_op" and e.get("ph") == "X":
            ts = Decimal(str(e["ts"]))
            start = int(ts * 1000)
            yield ((e["pid"], e["tid"]), start, start + int(Decimal(str(e["dur"])) * 1000),
                   e["name"], e.get("args", {}).get("Input Dims"), flows.get((e["pid"], e["tid"], ts), ()))


def framework_metrics(spans, *, db, use_csv):
    hosts, shapes = defaultdict(Metric), defaultdict(lambda: defaultdict(Metric))
    host_paths = defaultdict(lambda: defaultdict(Metric))
    paths = defaultdict(set)
    lanes, intervals = defaultdict(list), defaultdict(list)
    for idx, (lane, start, end, name, shape, links) in enumerate(spans):
        us = duration((end - start) / 1000)
        if not use_csv:
            hosts[name].add(us)
            if isinstance(shape, str) and shape:
                shapes[name][tuple(s.strip().replace(",", "x") for s in shape.strip('"').split(";"))].add(us)
            # Ascend operator_details subtracts nested framework work in the same
            # process, including autograd workers. Flow anchors remain thread-local.
            pid = int(lane) >> 32 if db else lane[0]
            intervals[pid].append((start, end, name, idx))
        lanes[lane].append((start, end, name, links))
    for ops in lanes.values():
        stack = []
        for start, stop, name, links in sorted(ops, key=lambda op: (op[0], -op[1])):
            while stack and (stack[-1][0] <= start or stack[-1][0] < stop):
                stack.pop()
            stack.append((stop, name))
            chain = tuple(name for _, name in stack)
            host_paths[name][chain].add((stop-start)/1000)
            for link in links:
                paths[link].add(chain)
    self_ns, _ = host_self_ns(intervals)
    return (hosts, Counter({n: v / 1000 for n, v in self_ns.items()}), shapes, host_paths,
            {k: next(iter(v)) for k, v in paths.items() if len(v) == 1})


def kernel_rows(source):
    if is_main_db(source):
        yield from db_kernels(source)
    elif (source / "kernel_details.csv").is_file():
        yield from rows(source / "kernel_details.csv", ["Type", "Accelerator Core", "Duration(us)", "Name"])


@dataclass
class NpuGroup:
    time: Metric = field(default_factory=Metric)
    symbols: Counter = field(default_factory=Counter)
    paths: Counter = field(default_factory=Counter)
    shapes: dict = field(default_factory=lambda: defaultdict(Metric))
    dtypes: Counter = field(default_factory=Counter)
    bf16_shapes: set = field(default_factory=set)
    other_shapes: set = field(default_factory=set)
    group_counts: Counter = field(default_factory=Counter)


def read_npu(folder):
    db = is_main_db(folder)
    spans = db_host_spans(folder) if db else trace_host_spans(folder / "trace_view.json")
    use_csv = not db and (folder / "operator_details.csv").is_file()
    hosts, self_us, host_shapes, host_paths, paths = framework_metrics(spans, db=db, use_csv=use_csv)
    groups = defaultdict(NpuGroup)
    steps, devices = set(), set()
    for r in kernel_rows(folder):
        if r["Duration(us)"].strip() in ("", "N/A") or r["Type"] in ("", "N/A"):
            continue
        group = groups[r["Type"], r["Accelerator Core"]]
        us = duration(r["Duration(us)"])
        group.time.add(us)
        group.symbols[r["Name"]] += 1
        ts = r.get("Start Time(us)", "").strip()
        anchor = r.get("connection")
        if not db and ts not in ("", "N/A"):
            anchor = (r.get("Stream ID"), Decimal(ts))
        path = paths.get(anchor)
        group.paths[" > ".join(path) if path else "未关联"] += 1
        inp = r.get("Input Shapes", "").strip('"').split(";")
        out = r.get("Output Shapes", "").strip('"')
        io = tuple(s.replace(",", "x") for s in [*inp, out])
        group.shapes[io].add(us)
        dtype = (r.get("Input Data Types", ""), r.get("Output Data Types", ""))
        group.dtypes[dtype] += 1
        if dtype == ("DT_BF16;DT_BF16", "DT_BF16"):
            group.bf16_shapes.add(io)
        else:
            group.other_shapes.add(io)
        if len(inp) >= 3:
            group.group_counts[inp[2]] += 1
        steps.add(r.get("Step Id", "未知"))
        devices.add(r.get("Device_id", "未知"))
    if len(devices - {"未知", "N/A", ""}) > 1:
        raise ValueError("NPU 数据包含多卡，请指定单卡导出")
    if use_csv:
        for r in rows(folder / "operator_details.csv", ["Name", "Host Self Duration(us)", "Host Total Duration(us)"]):
            total = duration(r["Host Total Duration(us)"])
            hosts[r["Name"]].add(total)
            if r.get("Input Shapes"):
                shape = tuple(s.strip().replace(",", "x") for s in r["Input Shapes"].split(";"))
                host_shapes[r["Name"]][shape].add(total)
            self_us[r["Name"]] += duration(r["Host Self Duration(us)"])
    if not groups and not hosts:
        raise ValueError(f"{folder} 中没有可读取的框架算子或 kernel 明细")
    return groups, hosts, self_us, sorted(steps), host_shapes, host_paths


def ranked_keys(folder, groups, reference, limit=15):
    source = folder / "op_statistic.csv"
    if not is_main_db(folder) and source.is_file() and groups:
        ranks = {}
        for r in rows(source, ["OP Type", "Core Type", "Count", "Total Time(us)"]):
            k = r["OP Type"], r["Core Type"]
            if k in ranks:
                raise ValueError(f"op_statistic 重复分组 {k}")
            ranks[k] = Metric(int(r["Count"]), duration(r["Total Time(us)"]))
    else:
        # op_statistic ranks device tasks; a logical communication op spans its
        # transport/scheduling tasks and is available in execution detail only.
        ranks = {k: g.time for k, g in groups.items() if k[1] != "COMMUNICATION"}
    ordered = sorted(ranks, key=lambda k: (-ranks[k].us, k))[:limit]
    def check(k, count, us, tolerance):
        if (k not in groups or groups[k].time.calls != count or
                abs(groups[k].time.us - us) > tolerance):
            raise ValueError(f"分组 {k} 的次数或总耗时与当前 rank 的 kernel 明细不符")
    for k in ordered:
        check(k, ranks[k].calls, ranks[k].us, 0.011)
    if reference:
        exported = {}
        for r in rows(reference, ["opType", "accCore", "count", "totalTime"]):
            k = r["opType"], r["accCore"]
            if k in exported:
                raise ValueError(f"排名 CSV 重复分组 {k}")
            exported[k] = duration(r["totalTime"])
            check(k, int(r["count"]), exported[k], 0.011)
        exported_top = sorted(exported, key=lambda k: (-exported[k], k))[:limit]
        if set(ordered) != set(exported_top):
            raise ValueError("提供的 CSV 与当前 rank 的 Top 分组不一致，请核对 rank 和采样窗口")
    return ordered


GEMM_TAG = re.compile(r"^((?:grouped_)?gemm_bf16_(?:nn|nt|tn_o_fp32))\.[\w]+:\s*a\[([\dx]+)\]\s+b\[([\dx]+)\]\s+out\[([\dx]+)\]")


@dataclass
class GpuBucket:
    time: Metric = field(default_factory=Metric)
    annotations: set = field(default_factory=set)
    hosts: Counter = field(default_factory=Counter)
    graph_calls: int = 0
    launches: list = field(default_factory=list)


def read_gpu(path, execution=None, identity=None):
    from kernel_attribution import gpu_attribution, is_graph_launch

    header, events = trace_document(path)
    if identity is not None:
        from profile_identity import gpu_identity
        identity.update(gpu_identity(header, events))
    del header
    lanes, hosts, external = defaultdict(list), defaultdict(Metric), defaultdict(set)
    steps, devices = set(), set()
    host_shapes = defaultdict(lambda: defaultdict(Metric))
    annotation_events = {}
    launch_external = defaultdict(set)
    graph_launches = set()
    host_lanes = defaultdict(list)
    # Attribute launch correlation IDs to the containing annotated GEMM call.
    for idx, e in enumerate(events):
        if e.get("ph") != "X":
            continue
        cat = e.get("cat")
        if cat in ("cpu_op", "user_annotation"):
            name = e["name"]
            hosts[name].add(duration(e["dur"]))
            if execution is not None:
                start = int(Decimal(str(e["ts"])) * 1000)
                stop = start + int(Decimal(str(e["dur"])) * 1000)
                host_lanes[e["pid"], e["tid"]].append((start, stop, name, idx))
            dims = e.get("args", {}).get("Input Dims")
            if isinstance(dims, list) and all(isinstance(s, list) for s in dims):
                shape = tuple("x".join(map(str, s)) for s in dims)
                host_shapes[name][shape].add(e["dur"])
            ext = e.get("args", {}).get("External id")
            if ext is not None:
                external[ext].add(name)
            if name.startswith("ProfilerStep#"):
                steps.add(name)
            if cat == "user_annotation":
                match = GEMM_TAG.match(name)
                if match:
                    annotation_events[idx] = (name, e["dur"])
                    lanes[e["pid"], e["tid"]].append((e, (idx, match.groups())))
        elif cat in ("cuda_driver", "cuda_runtime"):
            lanes[e["pid"], e["tid"]].append((e, None))
            args = e.get("args", {})
            if "correlation" in args and is_graph_launch(e["name"]):
                graph_launches.add(args["correlation"])
            if "External id" in args and "correlation" in args:
                launch_external[args["correlation"]].add(args["External id"])
    correlation = defaultdict(set)
    for lane in lanes.values():
        active = []
        for e, tag in sorted(lane, key=lambda x: (x[0]["ts"], x[1] is None, -x[0]["dur"])):
            active = [(end, t) for end, t in active if end > e["ts"]]
            if tag:
                active.append((e["ts"] + e["dur"], tag))
            elif active and "correlation" in e.get("args", {}):
                correlation[e["args"]["correlation"]].update(t for end, t in active if end >= e["ts"] + e["dur"])
    buckets = defaultdict(GpuBucket)
    for idx, e in enumerate(events):
        if (e.get("cat"), e.get("ph")) != ("kernel", "X"):
            continue
        args = e.get("args", {})
        devices.add(args.get("device", e.get("pid")))
        graph = bool(args.get("graph id", 0)) or args.get("correlation") in graph_launches
        refs = correlation.get(args.get("correlation"), ()) if not graph else ()
        tag_id, spec = next(iter(refs)) if len(refs) == 1 else (None, ("",))
        b = buckets[e["name"], spec[0], spec[1:]]
        if execution is not None:
            b.launches.append((idx, tag_id, e))
        b.time.add(duration(e["dur"]))
        b.graph_calls += int(graph)
        if tag_id is not None:
            b.annotations.add(tag_id)
        owners = external.get(args.get("External id"), ()) if not graph else ()
        if not owners and not graph:
            ext = launch_external.get(args.get("correlation"), ())
            if len(ext) == 1:
                owners = external.get(next(iter(ext)), ())
        b.hosts[next(iter(owners)) if len(owners) == 1 else "未关联"] += 1
    if len(devices) != 1 or not hosts:
        raise ValueError("GPU trace 需要包含单卡 kernel 和 host 算子事件")
    if execution is not None:
        execution["attribution"] = gpu_attribution(events)
        execution["self_ns"] = host_self_ns(host_lanes)
        trace_starts = [e["ts"] for e in events if e.get("cat") == "Trace" and e.get("ph") == "X"]
        execution["origin_us"] = min(trace_starts) if trace_starts else min(
            e["ts"] for e in events if e.get("cat") == "kernel" and e.get("ph") == "X")
        execution["origin_kind"] = "trace 起点" if trace_starts else "首个 kernel"
    return buckets, hosts, sorted(steps), host_shapes, annotation_events


def host_self_ns(lanes):
    """Subtract the union of strictly contained framework spans on the same lane."""
    by_event = {}
    for spans in lanes.values():
        active = []
        for start, end, _, idx in sorted(spans, key=lambda v: (v[0], -v[1], v[3])):
            active = [p for p in active if p[1] > start]
            for parent in active:
                if end <= parent[1] and (start, end) != (parent[0], parent[1]):
                    by_event[parent[3]] -= max(0, end - max(start, parent[2]))
                    parent[2] = max(parent[2], end)
            by_event[idx] = end - start
            active.append([start, end, start, idx])
    by_name = Counter()
    for spans in lanes.values():
        for _, _, name, idx in spans:
            by_name[name] += by_event[idx]
    return by_name, by_event
