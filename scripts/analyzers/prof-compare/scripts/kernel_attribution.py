"""Attribute device events to framework calls before matching cross-platform groups."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import math
import re

from npu_source import columns, db_host_spans, db_kernels, is_main_db, open_db, string_ids


@dataclass(frozen=True)
class Span:
    id: int
    start: int | float
    end: int | float
    name: str
    args: dict = field(default_factory=dict)


@dataclass
class DeviceEvent:
    id: int
    us: float
    name: str
    scope: tuple
    launch: int | None
    correlation: int | None
    attrs: dict
    evidence: str


def containing_spans(lanes, queries):
    """Index intervals by lane. The launch start is in a half-open host span."""
    for lane, points in queries.items():
        spans = iter(sorted(lanes[lane], key=lambda s: (s.start, -s.end, s.id)))
        following = next(spans, None)
        active = []
        for start, stop, key in sorted(points):
            active = [s for s in active if s.end > start]
            while following is not None and following.start <= start:
                if following.end > start:
                    active.append(following)
                following = next(spans, None)
            yield key, tuple(s for s in active if s.end >= stop)


def unique_inner(scope):
    if not scope:
        return None
    inner = scope[-1]
    if any(s.end < inner.end or (s.start, s.end) == (inner.start, inner.end) for s in scope[:-1]):
        return None
    return inner


def accumulate(metrics, key, us):
    row = metrics.setdefault(key, {"calls": 0, "total_ms": 0})
    row["calls"] += 1
    row["total_ms"] += us / 1000


GRAPH_LAUNCH = re.compile(r"(?:cuda|cu)GraphLaunch\w*")
LAUNCH = re.compile(r"(?:cuda|cu)Launch(?:Kernel|CooperativeKernel)\w*")


def is_graph_launch(name):
    return GRAPH_LAUNCH.fullmatch(name) is not None


def gpu_attribution(events):
    from cross_trace import GEMM_TAG

    lanes, queries, launches, flow_starts = (defaultdict(list) for _ in range(4))
    flow_ends = set()
    for i, e in enumerate(events):
        cat, ph = e.get("cat"), e.get("ph")
        lane = (e.get("pid"), e.get("tid"))
        if cat == "ac2g" and e.get("id") is not None:
            if ph == "s":
                flow_starts[e["id"]].append((*lane, e["ts"]))
            elif ph == "f":
                flow_ends.add((e["id"], *lane, e["ts"]))
        if ph != "X":
            continue
        args = e.get("args", {})
        if cat in ("cpu_op", "user_annotation"):
            lanes[lane].append(Span(i, e["ts"], e["ts"] + e["dur"], e["name"], args))
        elif cat in ("cuda_runtime", "cuda_driver") and (LAUNCH.fullmatch(e["name"]) or is_graph_launch(e["name"])):
            correlation = args.get("correlation")
            if correlation is None:
                continue
            launches[correlation].append(i)
            queries[lane].append((e["ts"], e["ts"] + e["dur"], i))

    scopes = dict(containing_spans(lanes, queries))
    metrics = {key: {"calls": 0, "total_ms": 0} for key in (
        "all", "launch", "flow", "launch_and_flow", "graph_replay", "framework",
        "no_cpu_context", "no_launch", "ambiguous_launch", "aten", "gemm_annotation_only")}
    records = {}
    for i, e in enumerate(events):
        if (e.get("cat"), e.get("ph")) != ("kernel", "X"):
            continue
        args = e.get("args", {})
        correlation = args.get("correlation")
        possible = [j for j in launches.get(correlation, ()) if events[j]["ts"] <= e["ts"]]
        launch = possible[0] if len(possible) == 1 else None
        scope = scopes.get(launch, ())
        owner = unique_inner(tuple(s for s in scope if events[s.id]["cat"] == "cpu_op"))
        us = float(e["dur"])
        endpoint = (correlation, e.get("pid"), e.get("tid"), e["ts"])
        flow = endpoint in flow_ends and bool(flow_starts.get(correlation))
        accumulate(metrics, "all", us)
        if flow:
            accumulate(metrics, "flow", us)
        if launch is not None:
            accumulate(metrics, "launch", us)
            runtime = events[launch]
            if flow and (runtime.get("pid"), runtime.get("tid"), runtime["ts"]) in flow_starts[correlation]:
                accumulate(metrics, "launch_and_flow", us)
            external = args.get("External id", runtime.get("args", {}).get("External id"))
            if owner and external is not None and owner.args.get("External id") not in (None, external):
                owner = None

        if args.get("graph id") or (launch is not None and is_graph_launch(events[launch]["name"])):
            status = "graph_replay"
        elif owner:
            status = "framework"
            if any(s.name.startswith("aten::") for s in scope):
                accumulate(metrics, "aten", us)
            records[i] = DeviceEvent(i, us, e["name"], scope, launch, correlation, args, status)
        elif launch is not None:
            status = "no_cpu_context"
            tags = tuple(s for s in scope if events[s.id]["cat"] == "user_annotation" and GEMM_TAG.match(s.name))
            if len(tags) == 1:
                accumulate(metrics, "gemm_annotation_only", us)
                records[i] = DeviceEvent(i, us, e["name"], tags, launch, correlation, args, "gemm_annotation")
        else:
            status = "ambiguous_launch" if possible else "no_launch"
        accumulate(metrics, status, us)
    return records, metrics


def npu_attribution(path):
    lanes, native_links, cann_links = (defaultdict(list) for _ in range(3))
    queries = defaultdict(list)
    for lane, start, stop, name, shape, links, data in db_host_spans(path, include_data=True):
        span = Span(data["id"], start, stop, name, {"shape": shape, "dtype": data["dtype"]})
        lanes[lane].append(span)
        if links:
            queries[lane].append((start, stop, ("host", span.id)))
        for connection in links:
            native_links[connection].append(span)

    with open_db(path) as db:
        if {"startNs", "endNs", "globalTid", "connectionId", "name"} <= columns(db, "CANN_API"):
            strings = string_ids(db)
            for row in db.execute("SELECT rowid AS source_rowid,* FROM CANN_API"):
                if strings.get(row["name"]) == "launch" and row["startNs"] is not None and row["endNs"] is not None:
                    cann_links[row["connectionId"]].append(row)

    tasks = [row for row in db_kernels(path) if row["Accelerator Core"] != "COMMUNICATION"]
    task_counts = defaultdict(int)
    for row in tasks:
        task_counts[row["globalTaskId"]] += 1
    for row in tasks:
        key = row["globalTaskId"]
        connection = row["connection"]
        if task_counts[key] != 1 or connection is None or native_links.get(connection):
            continue
        possible = cann_links.get(connection, ())
        if len(possible) == 1:
            launch, = possible
            queries[launch["globalTid"]].append((int(launch["startNs"]), int(launch["endNs"]), ("task", key)))

    scopes = dict(containing_spans(lanes, queries))
    metrics = {key: {"calls": 0, "total_ms": 0} for key in (
        "all", "native_framework", "cann_context", "no_unique_framework")}
    records = {}
    for row in tasks:
        us = float(row["Duration(us)"])
        key = row["globalTaskId"]
        connection = row["connection"]
        direct = native_links.get(connection, ())
        scope = ()
        launch_id = None
        status = "no_unique_framework"
        if key is not None and task_counts[key] == 1:
            if len(direct) == 1:
                owner, = direct
                outer = tuple(s for s in scopes.get(("host", owner.id), ()) if s.id != owner.id
                              and (s.start < owner.start or s.end > owner.end))
                scope = (*outer, owner)
                status = "native_framework"
            elif not direct:
                candidates = scopes.get(("task", key), ())
                if unique_inner(candidates):
                    scope = candidates
                    launch_id = cann_links[connection][0]["source_rowid"]
                    status = "cann_context"
        if scope:
            records[key] = DeviceEvent(key, us, row["Name"], scope, launch_id, connection, row, status)
        accumulate(metrics, "all", us)
        accumulate(metrics, status, us)
    add_owners = defaultdict(int)
    for row in tasks:
        if row["Type"] == "Add":
            event = records.get(row["globalTaskId"])
            owner = next((span.name for span in reversed(event.scope) if span.name.startswith("aten::")),
                         "未定位") if event else "未定位"
            add_owners[owner] += 1
    return records, metrics, dict(add_owners)


def npu_shapes(value):
    return tuple(x.strip().replace(",", "x") for x in (value or "").strip('"').split(";") if x.strip())


def gpu_shapes(value):
    return tuple("x".join(map(str, x)) for x in (value or ()) if isinstance(x, list) and x)


def normalize_dtype(value):
    value = value.strip().lower() if isinstance(value, str) else ""
    return {"c10::bfloat16": "bf16", "dt_bf16": "bf16", "bfloat16": "bf16",
            "float": "fp32", "dt_float": "fp32", "int": "int32", "long int": "int64",
            "long": "int64", "c10::half": "fp16"}.get(value, value)


CE_MODULE = "_MMQKernelsLinearCrossEntropy"
CE_OWNER = {"mmq_ascendc::ce_forward_out": ("CE 前向", CE_MODULE),
            "mmq_ascendc::ce_backward_out": ("CE 反向", CE_MODULE + "Backward")}
GPU_CE = re.compile(r"quackcross_entropyCrossEntropy(Backward)?_object_at__tensorptrbf16gmemalign\d+o([1-9]\d*)i")


def named_scope(event, name):
    return unique_inner(tuple(s for s in event.scope if s.name == name))


def positive_int(value):
    return int(value) if isinstance(value, str) and value.isdecimal() and int(value) > 0 else None


def ce_key(event, gpu):
    if gpu:
        hit = GPU_CE.search(event.name)
        if hit is None:
            return None
        width = positive_int(hit[2])
        op, name = CE_OWNER["mmq_ascendc::ce_backward_out" if hit[1] else "mmq_ascendc::ce_forward_out"]
        host = named_scope(event, name)
        if not host:
            return None
        shape = gpu_shapes(host.args.get("Input Dims", ()))
        tokens = positive_int(shape[0].split("x")[0]) if shape else None
    else:
        owner = event.scope[-1]
        if owner.name not in CE_OWNER:
            return None
        op, name = CE_OWNER[owner.name]
        host = named_scope(event, name)
        shape = npu_shapes(owner.args.get("shape"))
        matrix = shape[0].split("x") if shape else ()
        if not host or len(matrix) != 2 or normalize_dtype((owner.args.get("dtype") or "").split(";")[0]) != "bf16":
            return None
        tokens, width = map(positive_int, matrix)
    if width and tokens:
        return (op, tokens, width), host


def add_key(event, gpu):
    names = ("aten::add", "aten::add_", "aten::addmm")
    if not gpu and event.attrs.get("Type") != "Add":
        return None
    host = unique_inner(tuple(s for s in event.scope if s.name in names))
    if not host or host.name == "aten::addmm":
        return None
    if gpu:
        if not re.search(r"CUDAFunctor(?:OnSelf)?_add<", event.name):
            return None
        shape = gpu_shapes(host.args.get("Input Dims", ()))
        dtype = tuple(normalize_dtype(x) for x in (host.args.get("Input type") or ()) if x)
    else:
        shape = npu_shapes(host.args.get("shape"))
        dtype = tuple(normalize_dtype(x) for x in (host.args.get("dtype") or "").split(";") if x.strip())
    if len(shape) == 2 and dtype and len(dtype) >= 2:
        return (host.name, shape, dtype), host


def add_context(event):
    """Use the nearest annotated autograd/module identity when available."""
    names = [s.name for s in event.scope if s.name.startswith("autograd::engine::evaluate_function: ")]
    return names[-1] if names else None


def buckets(records, key_function, gpu):
    result = defaultdict(list)
    for event in records.values():
        found = key_function(event, gpu)
        if found:
            key, owner = found
            result[key].append((event, owner))
    return result


def metrics(items):
    calls = len({host.id for _, host in items})
    total = math.fsum(event.us for event, _ in items) / 1000
    return {"kernels": len(items), "logical_calls": calls, "total_ms": total, "mean_ms": total / calls,
            "event_ids": [event.id for event, _ in items],
            "sources": [{"event": e.id, "host": host.id, "launch": e.launch,
                         "correlation": e.correlation, "evidence": e.evidence} for e, host in items]}


def group(op, signature, left, right, comparable, note):
    a, b = metrics(left), metrics(right)
    return {"op": op, "signature": signature, "npu": a, "gpu": b, "comparable": comparable,
            "mean_ratio": a["mean_ms"] / b["mean_ms"] if comparable and b["mean_ms"] else None,
            "note": note}


def ce_tile_rows(event):
    # In the recognized Quack kernels, grid.x is the number of token rows.
    grid = event.attrs.get("grid")
    if (isinstance(grid, list) and len(grid) == 3 and grid[2] == 1
            and all(type(value) is int and value > 0 for value in grid)):
        return grid[0]
    return 0


def ce_groups(npu, gpu):
    left, right = buckets(npu, ce_key, False), buckets(gpu, ce_key, True)
    for key in sorted(left.keys() & right.keys()):
        op, tokens, width = key
        a, b = left[key], right[key]
        rows_by_call = defaultdict(list)
        for event, host in b:
            rows_by_call[host.id].append(ce_tile_rows(event))
        comparable = (len({host.id for _, host in a}) == len(a)
                      and all(all(rows) and sum(rows) == tokens for rows in rows_by_call.values()))
        note = ("同交叉熵模块、token 数和词表宽。GPU 每次调用的分块行数与逻辑 token 数一致。"
                if comparable else "交叉熵语义和形状候选。分块覆盖或 NPU 调用边界未验证，保留实测。")
        yield group(op, f"{tokens}×{width} BF16", a, b, comparable, note)


def add_groups(npu, gpu):
    left, right = buckets(npu, add_key, False), buckets(gpu, add_key, True)
    for op, shape, dtype in sorted(left.keys() & right.keys()):
        a, b = left[op, shape, dtype], right[op, shape, dtype]
        if len(a) != len(b) or any(len({host.id for _, host in items}) != len(items) for items in (a, b)):
            continue
        contexts = {add_context(event) for event, _ in a + b}
        device_shapes = all(npu_shapes(e.attrs.get("Input Shapes")) == shape
                            and npu_shapes(e.attrs.get("Output Shapes")) == shape[:1] for e, _ in a)
        comparable = device_shapes and len(contexts) == 1 and None not in contexts
        note = ("同 Autograd 模块、输入形状和 dtype，NPU 设备形状吻合。"
                if comparable else "框架签名和次数吻合。设备形状或模块边界未独立确认，保留实测值。")
        yield group(op, " / ".join(shape) + " · " + "/".join(dtype[:2]), a, b, comparable, note)



def gemm_matrices(shape):
    matrices = [tuple(positive_int(n) for n in x.split("x")) for x in shape[:2]]
    if len(matrices) != 2 or any(len(x) != 2 or None in x for x in matrices):
        return None
    (t1, m), (t2, n) = matrices
    return (t1, m, n) if t1 == t2 else None


def npu_gemm(event):
    a = event.attrs
    if a.get("Type") != "GroupedMatmulAdd":
        return None
    if a.get("Input Data Types", "").split(";")[:2] != ["DT_BF16", "DT_BF16"]:
        return None
    if normalize_dtype(a.get("Output Data Types", "")) != "fp32":
        return None
    shape = npu_shapes(a.get("Input Shapes"))
    matrices = gemm_matrices(shape)
    if matrices is None or len(shape) < 3:
        return None
    rows, m, n = matrices
    count = positive_int(shape[2])
    if count is None:
        return None
    if count > 1:
        owner = named_scope(event, "npu::npu_grouped_matmul_add_")
        key = (f"{count} 专家", m, n)
    else:
        owner = named_scope(event, CE_MODULE + "Backward")
        key = ("CE 权重梯度", m, n, rows)
    return (key, owner, owner, rows) if owner else None


def gpu_gemm(event):
    from cross_trace import GEMM_TAG

    tags = [(s, hit.groups()) for s in event.scope if (hit := GEMM_TAG.match(s.name))]
    if len(tags) != 1:
        return None
    tag, (name, a, b, out) = tags[0]
    matrices = gemm_matrices((a, b))
    if matrices is None:
        return None
    rows, m, n = matrices
    if name == "grouped_gemm_bf16_tn_o_fp32":
        dims = out.split("x")
        if len(dims) != 3 or dims[1:] != [str(m), str(n)] or not positive_int(dims[0]):
            return None
        return ((f"{dims[0]} 专家", m, n), tag, tag, rows)
    if name == "gemm_bf16_tn_o_fp32" and out == f"{m}x{n}":
        owner = named_scope(event, CE_MODULE + "Backward")
        dims = gpu_shapes(owner.args.get("Input Dims", ())) if owner else ()
        tokens = positive_int(dims[0]) if dims else None
        if tokens:
            return (("CE 权重梯度", m, n, tokens), owner, tag, rows)
    return None


def gemm_groups(npu, gpu):
    left, right = defaultdict(list), defaultdict(list)
    for records, collect, grouped in ((npu, npu_gemm, left), (gpu, gpu_gemm, right)):
        for event in records.values():
            found = collect(event)
            if found:
                key, owner, tag, rows = found
                grouped[key].append((event, owner, tag, rows))

    for key in sorted(left.keys() & right.keys()):
        a, b = left[key], right[key]
        rows_a = {tag.id: rows for _, _, tag, rows in a}
        rows_b = {tag.id: rows for _, _, tag, rows in b}
        if len(rows_a) != len(a):
            continue
        description, m, n, *tokens = key
        if tokens:
            chunk_rows = defaultdict(dict)
            for _, host, tag, rows in b:
                chunk_rows[host.id][tag.id] = rows
            if any(sum(rows.values()) != tokens[0] for rows in chunk_rows.values()):
                continue
            signature = f"{description} T={tokens[0]} · {m}×{n}"
            note = "同 CE 反向模块与权重梯度矩阵。GPU 每次框架调用包含多个分块 GEMM，保留实测供核对。"
        else:
            if len(rows_a) != len(rows_b):
                continue
            signature = f"{description} · {m}×{n}"
            note = "专家数、矩阵尾维和逻辑调用数一致。逐专家 token 切分待核对，保留实测。"
        match = group("GroupedMatmulAdd", signature, [(e, host) for e, host, _, _ in a],
                      [(e, host) for e, host, _, _ in b], False, note)
        for side, rows in (("npu", rows_a), ("gpu", rows_b)):
            match[side]["operand_rows"] = sum(rows.values())
        yield match


def cross_platform_attribution(path, gpu, gpu_metrics):
    npu, npu_metrics, add_owners = npu_attribution(path) if is_main_db(path) else ({}, {}, {})
    matches = [*ce_groups(npu, gpu), *add_groups(npu, gpu), *gemm_groups(npu, gpu)]
    # An event belongs to at most one group. Keep conflicted rows out of the performance view.
    used = {side: defaultdict(int) for side in ("npu", "gpu")}
    for match in matches:
        for side in used:
            for event_id in match[side]["event_ids"]:
                used[side][event_id] += 1
    matches = [m for m in matches if all(used[side][i] == 1 for side in used for i in m[side]["event_ids"])]
    return {"npu": npu_metrics, "gpu": gpu_metrics, "groups": matches, "npu_add_owners": add_owners}
