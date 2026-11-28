"""Compare NPU-led host and device hotspots, preserving attribution boundaries."""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from cross_trace import Metric, gpu_file, ranked_keys, read_gpu, read_npu
from npu_source import npu_source
from kernel_execution import gpu_pair, npu_pair


# Match the actual CUDA entry point or a FlashAttention implementation template.
# Dispatch/combine main and epilogue are deliberately disjoint.
PHASES = {
    "MoeEpDispatch": r"\bdeep_ep::(?:\w+::)*dispatch_impl<",
    "MoeEpDispatchEpilogue": r"\bdeep_ep::(?:\w+::)*dispatch_copy_epilogue_impl<",
    "MoeEpCombine": r"\bdeep_ep::(?:\w+::)*combine_impl<",
    "MoeEpCombineEpilogue": r"\bdeep_ep::(?:\w+::)*combine_reduce_epilogue_impl<",
    "FlashAttnGrad": r"\bflash::FlashAttnBwd(?:Sm\d+|Preprocess|Postprocess\w*)<",
}


def diff(n, g):
    return dict(delta_ms=(n.us - g.us) / 1000, ratio=n.us / g.us if g.us else None,
                avg_delta_us=n.us / n.calls - g.us / g.calls if n.calls and g.calls else None)


def sum_times(items):
    total = Metric()
    for x in items:
        total.merge(x)
    return total


def missing_details(label, groups, hosts):
    notes = []
    if not any(not n.startswith("ProfilerStep#") for n in hosts):
        notes.append(f"{label} 缺少框架算子事件，无法计算 Host 耗时。")
    if not groups:
        notes.append(f"{label} 缺少 device 任务明细，无法统计 Kernel 排名或单次执行。")
    return notes


def tagged_gemm(typ, group, buckets):
    """Use annotated operation counts, not kernel counts (split-K adds launches)."""
    if typ == "GroupedMatmulAdd":
        rules = {"gemm_bf16_tn_o_fp32": group.group_counts["1"],
                 "grouped_gemm_bf16_tn_o_fp32": sum(v for k, v in group.group_counts.items()
                                                    if k.isdigit() and int(k) > 1)}
        dtype = "FLOAT"
    else:
        rules = {"grouped_gemm_bf16_nt": None, "grouped_gemm_bf16_nn": None}
        dtype = "DT_BF16"
    if not all(out == dtype and inp.startswith("DT_BF16;DT_BF16;") for inp, out in group.dtypes):
        return []
    selected = [k for k in buckets if k[1] in rules]
    counts = {tag: len({i for k in selected if k[1] == tag for i in buckets[k].annotations})
              for tag in rules}
    if sum(counts.values()) != group.time.calls:
        return []
    if any(n is not None and counts[t] != n for t, n in rules.items()):
        return []
    return selected


def matmul_subset(group, key, groups, buckets):
    # A GPU operation can include multiple launches, e.g. GEMM + split-K reduce.
    # Match complete shape buckets only, and decline shapes shared by two NPU cores.
    siblings = [g for k, g in groups.items() if k != key and k[0] == key[0]]
    eligible = {s for s in group.bf16_shapes - group.other_shapes if all(s not in g.shapes for g in siblings)}
    by_shape = defaultdict(list)
    for k in buckets:
        if k[1] in ("gemm_bf16_nn", "gemm_bf16_nt") and k[2] in eligible:
            by_shape[k[2]].append(k)
    keys, subset = [], Metric()
    for shape, entries in by_shape.items():
        keys.extend(entries)
        subset.merge(group.shapes[shape])
    return keys, subset


def host_index(groups):
    index = defaultdict(set)
    for key, group in groups.items():
        for chain in group.paths:
            for owner in chain.split(" > "):
                index[owner].add(key)
    return index


def match_device(key, groups, buckets, names, index, n_hosts, g_hosts):
    typ, _ = key
    group = groups[key]
    siblings = sum(k[0] == typ for k in groups)
    if typ == "MatMulV3":
        keys, measured = matmul_subset(group, key, groups, buckets)
        if keys:
            return keys, measured, "形状分组", "两输入和输出形状、BF16 匹配，形状唯一归属本类型的一个核心。逐形状调用数可不同，GPU 含标注内的归约核。"
    if siblings == 1:
        exact = [k for k in buckets if k[0] in {typ, *group.symbols}]
        if exact:
            return exact, group.time, "同名", "GPU kernel 符号与 NPU 类型或实现名相同。"
        if typ in PHASES:
            keys = [k for k in buckets if re.search(PHASES[typ], k[0])]
            if keys:
                note = ("GPU 汇总显式 FlashAttnBwd 主核及前后处理；两侧拆核粒度可不同。"
                        if typ == "FlashAttnGrad" else "匹配 DeepEP 的相同方向和阶段；跨平台阶段边界可能不同。")
                return keys, group.time, "语义阶段", note
        if typ in ("GroupedMatmul", "GroupedMatmulAdd"):
            keys = tagged_gemm(typ, group, buckets)
            if keys:
                return keys, group.time, "语义分组", "按 GEMM 的 host 标注、输入/输出精度及调用数对齐；分组累加另核对单组与多组次数。各次 token 数可不同。"
        if typ == "_update_params_kernel" and "_update_params_kernel_graph" in names:
            keys = [k for k in buckets if k[0] == "_update_params_kernel_graph" and
                    buckets[k].graph_calls == buckets[k].time.calls]
            if keys:
                return keys, group.time, "图版本别名", "同名词干及 CUDA Graph 回放标记；总量和单次耗时分别解读。"
    # Conservative cross-vendor fallback for kernels with unrelated symbols.
    # A shared host op must exclusively own this group on the NPU. On the GPU,
    # reject mixed/unattributed launches of the chosen implementation.
    chains = [p.split(" > ") for p in group.paths]
    for owner in reversed(chains[0]):
        if (index[owner] != {key} or not all(owner in path for path in chains) or
                owner not in n_hosts or owner not in g_hosts or
                n_hosts[owner].calls != group.time.calls or g_hosts[owner].calls != group.time.calls):
            continue
        hits = [k for k, b in buckets.items() if owner in b.hosts]
        symbols = {k[0] for k in hits}
        if len(symbols) != 1:
            continue
        if (any(set(b.hosts) != {owner} for k, b in buckets.items() if k[0] in symbols) or
                sum(buckets[k].time.calls for k in hits) != group.time.calls):
            continue
        return hits, group.time, "共同 host", f"两端由 {owner} 关联，host 次数、kernel 次数一致，归属唯一。"
    return [], None, "待定位", "缺少可独占的 GPU kernel 或同口径的形状、阶段证据。"


def compare_gpu(npu, gpu, reference=None, host_aliases=None, identity=None):
    folder = npu_source(npu)
    if folder is None:
        raise ValueError(f"未识别到 NPU profiler 主库或文本导出：{npu}")
    trace = gpu_file(gpu)
    if not trace:
        raise ValueError("请提供单个 GPU pt.trace.json 文件或所在目录")
    groups, n_hosts, self_us, n_steps, n_host_shapes, n_paths = read_npu(folder)
    top = ranked_keys(folder, groups, Path(reference) if reference else None)
    gpu_meta = {}
    buckets, g_hosts, g_steps, g_host_shapes, annotations = read_gpu(trace, gpu_meta, identity)
    names = {k[0] for k in buckets}
    index = host_index(groups)
    proposals = {key: match_device(key, groups, buckets, names, index, n_hosts, g_hosts) for key in groups}
    uses = Counter(k for key in top for k in proposals[key][0])
    self_by_name, self_by_event = gpu_meta["self_ns"]
    derived_self = {}
    device, derived_hosts = [], {}
    for key in top:
        group = groups[key]
        keys, measured, status, note = proposals[key]
        if any(uses[k] > 1 for k in keys):
            keys, measured, status, note = [], None, "待定位", "多个 NPU 分组命中同批 GPU 事件，耗时无法分摊。"
        if not keys and key[0] in ("FusedMatMul", "BatchMatMulV3"):
            candidates = sorted({k[0] for k, b in buckets.items() if b.graph_calls and
                                 re.search(r"^(nvjet_|.*(?:gemm|Gemm))", k[0])})
            if candidates:
                note += " CUDA Graph 中存在 GEMM 候选，但缺少将批量乘、融合乘加分开的逐核 host/shape。"
        else:
            candidates = []
        symbols, tags, owners = defaultdict(Metric), defaultdict(set), Counter()
        for k in keys:
            b = buckets[k]
            symbols[k[0]].merge(b.time)
            tags[k[1]].update(b.annotations)
            owners.update(b.hosts)
        gpu_time = sum_times(symbols.values())
        # Compare host annotations only when every launch belongs to this NPU
        # operator and both frameworks expose the same number of logical calls.
        if keys and status == "语义分组":
            host_name = {"GroupedMatmulAdd": "npu::npu_grouped_matmul_add_",
                         "GroupedMatmul": "npu::npu_grouped_matmul"}.get(key[0])
            ids = set().union(*tags.values())
            if (host_name in n_hosts and n_hosts[host_name].calls == group.time.calls == len(ids)
                    and all(host_name in p.split(" > ") for p in group.paths)):
                logical = Metric()
                raw_names = Counter()
                for i in ids:
                    label, us = annotations[i]
                    logical.add(us)
                    raw_names[label] += 1
                derived_hosts[host_name] = (" + ".join(sorted(tags)), logical, dict(raw_names))
                derived_self[host_name] = sum(self_by_event[i] for i in ids) / 1e6
        shape_details = []
        if status == "形状分组" and keys:
            for shape in sorted({k[2] for k in keys}, key=lambda s: -group.shapes[s].us):
                entry = [buckets[k] for k in keys if k[2] == shape]
                shape_details.append(dict(io=shape, npu=group.shapes[shape].values(),
                                          gpu=sum_times(b.time for b in entry).values(),
                                          gpu_ops=len(set().union(*(b.annotations for b in entry)))))
        device.append(dict(op=key[0], core=key[1], status=status, note=note,
                           npu=group.time.values(), matched_npu=measured.values() if keys else None,
                           gpu=gpu_time.values() if keys else None, diff=diff(measured, gpu_time) if keys else None,
                           gpu_annotation_calls={tag: len(ids) for tag, ids in tags.items() if tag},
                           matched_shapes=shape_details,
                           npu_symbols=dict(group.symbols), npu_hosts=dict(group.paths.most_common()),
                           npu_shapes=[dict(io=io, **v.values()) for io, v in
                                       sorted(group.shapes.items(), key=lambda x: -x[1].us)],
                           gpu_symbols={s: m.values() for s, m in sorted(symbols.items(), key=lambda x: -x[1].us)},
                           gpu_hosts=dict(owners.most_common()), candidates=candidates))
    host = compare_hosts(n_hosts, g_hosts, self_us, n_host_shapes, g_host_shapes, n_paths,
                         derived_hosts, host_aliases, "gpu")
    for row in host:
        if row["gpu_name"]:
            row["gpu_self_ms"] = (derived_self[row["npu_name"]] if row["gpu_annotations"] else
                                  self_by_name[row["gpu_name"]] / 1e6)
    result = dict(npu_path=str(folder), gpu_path=str(trace), notes=missing_details("NPU", groups, n_hosts),
                  reference=str(reference) if reference else None,
                  npu_steps=n_steps, gpu_steps=g_steps, gpu_kernel_calls=sum(b.time.calls for b in buckets.values()),
                  gpu_graph_calls=sum(b.graph_calls for b in buckets.values()), device=device, host=host)
    from kernel_attribution import cross_platform_attribution
    result["attribution"] = cross_platform_attribution(folder, *gpu_meta["attribution"])
    subgroups = {g["op"] for g in result["attribution"]["groups"]}
    display_ops = {"cross_entropy_forward_kernel": {"CE 前向"}, "cross_entropy_backward_kernel": {"CE 反向"},
                   "Add": {"aten::add", "aten::add_"}, "GroupedMatmulAdd": {"GroupedMatmulAdd"}}
    for row in device:
        if row["diff"] is None and subgroups.intersection(display_ops.get(row["op"], ())):
            row["status"] = "见框架子组"
            row["note"] = "框架归属章节列出可核对的子组、拆核和工作量。本行保留 NPU 全量统计。"
    result["execution"] = gpu_pair(folder, groups, buckets, proposals, gpu_meta, top, Path(npu).is_dir())
    return result


def compare_hosts(n_hosts, g_hosts, self_us, n_host_shapes, g_host_shapes, n_paths,
                  derived_hosts, host_aliases, peer, peer_self=None):
    aliases = json.loads(Path(host_aliases).read_text(encoding="utf-8-sig")) if host_aliases else {}
    if not isinstance(aliases, dict) or any(k not in n_hosts or not isinstance(v, str) or v not in g_hosts
                                            for k, v in aliases.items()):
        raise ValueError("host 别名应为 JSON 对象，键和值分别为排名侧、对照侧实际存在的算子名")
    host = []
    host_names = [n for n in n_hosts if not n.startswith("ProfilerStep#")]
    mapped_names = [aliases.get(n, n) for n in host_names if aliases.get(n, n) in g_hosts]
    if len(set(mapped_names)) != len(mapped_names):
        raise ValueError("host 别名将同一对照侧算子重复分配给多个 NPU 算子")
    for name in sorted(host_names, key=lambda n: -self_us[n]):
        gpu_name = aliases.get(name, name)
        g = g_hosts.get(gpu_name)
        n = n_hosts[name]
        evidence = {}
        if not g and name in derived_hosts:
            gpu_name, g, evidence = derived_hosts[name]
        shapes = []
        for shape, t in sorted(n_host_shapes[name].items(), key=lambda x: -x[1].us)[:5]:
            gt = g_host_shapes.get(gpu_name, {}).get(shape)
            shapes.append({"io": shape, "npu": t.values(), peer: gt.values() if gt else None})
        paths = [dict(path=k, **v.values()) for k, v in
                 sorted(n_paths[name].items(), key=lambda x: -x[1].us)[:5]]
        host.append(dict(npu_name=name, npu_self_ms=self_us[name]/1000, top_paths=paths,
                         top_shapes=shapes, npu=n.values(),
                         diff=diff(n, g) if g else None, **{peer: g.values() if g else None,
                         peer + "_name": gpu_name if g else None}))
        if peer == "gpu":
            host[-1]["gpu_annotations"] = evidence
        elif g:
            host[-1]["base_self_ms"] = peer_self[gpu_name] / 1000
    return host


def compare_npus(current, baseline, reference=None, host_aliases=None):
    folder, base_folder = npu_source(current), npu_source(baseline)
    if folder is None or base_folder is None:
        raise ValueError("两侧均需要单卡 NPU profiler 主库或文本导出")
    groups, hosts, self_us, steps, shapes, paths = read_npu(folder)
    base_groups, base_hosts, base_self, base_steps, base_shapes, _ = read_npu(base_folder)
    top = ranked_keys(folder, groups, Path(reference) if reference else None)
    # Reserve exact pairs across the full profile before matching renamed groups.
    missing = groups.keys() - base_groups.keys()
    unused = base_groups.keys() - groups.keys()
    candidates_by_key = {}
    for key in missing:
        group = groups[key]
        candidates_by_key[key] = [
            other for other in unused if other[1] == key[1] and
            bool(set(group.symbols) - {"", "N/A"}) and group.symbols.keys() == base_groups[other].symbols.keys() and
            group.dtypes.keys() == base_groups[other].dtypes.keys() and
            any(any(dim not in ("", "N/A") for dim in shape)
                for shape in group.shapes.keys() & base_groups[other].shapes.keys())]
    uses = Counter(candidate for matches in candidates_by_key.values() for candidate in matches)
    renamed = {key: matches[0] for key, matches in candidates_by_key.items()
               if len(matches) == 1 and uses[matches[0]] == 1}
    device = []
    for key in top:
        group = groups[key]
        matches = candidates_by_key.get(key, [])
        base_key = key if key in base_groups else renamed.get(key)
        base = base_groups.get(base_key)
        candidates = sorted({f"{op} / {core}" for op, core in base_groups if op == key[0] and core != key[1]} |
                            {f"{op} / {core}" for op, core in matches})
        status = "同类型、同核心" if base_key == key else "未匹配"
        note = "双方按本组所有调用累计。" if base else "缺少唯一的基准分组。"
        if base and base_key != key:
            status = "异名、同实现"
            note = "两侧核心、实现名集合与精度一致，存在共同形状，且双方均唯一匹配。"
        row = dict(op=key[0], core=key[1], npu=group.time.values(),
                   matched_npu=group.time.values() if base else None, base=base.time.values() if base else None,
                   diff=diff(group.time, base.time) if base else None,
                   status=status, note=note, base_op=base_key[0] if base else None,
                   npu_symbols=dict(group.symbols), npu_hosts=dict(group.paths.most_common()),
                   base_symbols=dict(base.symbols) if base else {}, base_hosts=dict(base.paths.most_common()) if base else {},
                   candidates=[] if base else candidates, matched_shapes=[])
        other_shapes = base.shapes if base else {}
        shape_keys = sorted(group.shapes.keys() | other_shapes.keys(),
                            key=lambda s: -(group.shapes.get(s) or other_shapes[s]).us)
        for shape in shape_keys:
            a, b = group.shapes.get(shape), other_shapes.get(shape)
            row["matched_shapes"].append(dict(io=shape, npu=a.values() if a else None, base=b.values() if b else None))
        device.append(row)
    host = compare_hosts(hosts, base_hosts, self_us, shapes, base_shapes, paths, {}, host_aliases, "base", base_self)
    return dict(mode="npu_npu", npu_path=str(folder), base_path=str(base_folder),
                notes=missing_details("比对 NPU", groups, hosts) + missing_details("基准 NPU", base_groups, base_hosts),
                reference=str(reference) if reference else None, npu_steps=steps, base_steps=base_steps,
                device=device, host=host, execution=npu_pair(folder, base_folder, device,
                    {(key[0], other[0]) for key, other in renamed.items()},
                    (Path(current).is_dir(), Path(baseline).is_dir())))
