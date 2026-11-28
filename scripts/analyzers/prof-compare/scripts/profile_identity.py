"""Keep report roles and profiler-local device identity independent."""
import csv
import json
import re
from contextlib import suppress
from pathlib import Path

from npu_source import columns, is_main_db, open_db


ROLES = {"base": ("基线", "-bp"), "compare": ("比对", "-d")}
XLSX_HEADERS = {"base": "Base Profiling: ", "compare": "Comparison Profiling: "}


def text(value):
    if isinstance(value, str) and value.strip().lower() not in ("", "/", "n/a", "na", "unknown", "未知"):
        return value.strip()
    return None


def number(value):
    if isinstance(value, (int, str)) and not isinstance(value, bool) and str(value).strip().isdecimal():
        return int(value)
    return None


def unique(values):
    known = {v for v in values if v is not None}
    return next(iter(known)) if len(known) == 1 else None


def path_parts(path):
    return tuple(p for p in re.split(r"[/\\]+", str(path or "")) if p)


def path_rank(path):
    for part in reversed(path_parts(path)):
        rank = re.fullmatch(r"rank[_-](\d+)", part, re.IGNORECASE)
        if rank:
            return int(rank[1])
    return None


def read_object(path):
    with suppress(OSError, ValueError):
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(value, dict):
            return value
    return {}


def npu_db_identity(source, rank_hint):
    def rows(table, *fields):
        if set(fields) <= columns(db, table):
            return db.execute(f"SELECT {', '.join(fields)} FROM {table}").fetchall()
        return []

    with open_db(source) as db:
        rank_map = rows("RANK_DEVICE_MAP", "rankId", "deviceId")
        selected = [row for row in rank_map if number(row[0]) == rank_hint] if rank_hint is not None else rank_map
        if not selected and len(rank_map) == 1:
            selected = rank_map
        rank = unique(number(r[0]) for r in selected)
        device = unique(number(r[1]) for r in selected)
        if device is None and not rank_map and "deviceId" in columns(db, "TASK"):
            device = unique(number(r[0]) for r in db.execute("SELECT DISTINCT deviceId FROM TASK LIMIT 3"))
        model = unique(text(name) for idx, name in rows("NPU_INFO", "id", "name") if number(idx) == device
                       and device is not None)
        host = unique(text(r[0]) for r in rows("HOST_INFO", "hostName"))
    return device, model, host, rank


def npu_text_device(source):
    with suppress(OSError, UnicodeError, csv.Error):
        with (source / "kernel_details.csv").open(encoding="utf-8-sig", newline="") as f:
            devices = set()
            for row in csv.DictReader(f):
                device = number(row.get("Device_id"))
                if device is not None:
                    devices.add(device)
                    if len(devices) > 1:
                        return None
            return unique(devices)
    return None


def read_npu_identity(input_path, source):
    source = Path(source)
    db_source = is_main_db(source)
    capture = source.parent if db_source else source
    if capture.name == "ASCEND_PROFILER_OUTPUT":
        capture = capture.parent
    match = re.fullmatch(r"ascend_(?:pytorch|mindspore)_profiler_(\d+)\.db", source.name)
    rank_hint = int(match[1]) if match else path_rank(input_path)
    device = model = host = rank = None
    if db_source:
        with suppress(ValueError):
            device, model, host, rank = npu_db_identity(source, rank_hint)
    else:
        device = npu_text_device(source)

    if rank is None:
        sidecars = list(capture.glob("profiler_info*.json"))
        if rank_hint is not None and (capture / f"profiler_info_{rank_hint}.json").is_file():
            sidecars = [capture / f"profiler_info_{rank_hint}.json"]
        if len(sidecars) == 1:
            rank = number(read_object(sidecars[0]).get("rank_id"))
        if rank is None:
            rank = rank_hint

    if host is None:
        host = unique(text(read_object(p).get("hostname")) for p in capture.glob("PROF_*/host/info.json"))
    if device is not None and model is None:
        model = unique(text(read_object(p).get("socName"))
                       for p in capture.glob(f"PROF_*/device_{device}/info.json.{device}"))
    return dict(input_path=str(input_path), source_path=str(source), capture_path=str(capture),
                input_path_origin="prof", device_type="NPU", device_id=device, device_model=model,
                hostname=host, rank=rank)


def gpu_identity(header, events):
    devices = set()
    has_cuda_events = False
    for event in events:
        cat = event.get("cat")
        if cat in ("cuda_driver", "cuda_runtime"):
            has_cuda_events = True
        if (cat, event.get("ph")) == ("kernel", "X"):
            has_cuda_events = True
            device = number((event.get("args") or {}).get("device"))
            if device is not None:
                devices.add(device)
    props = header.get("deviceProperties")
    if not isinstance(props, list):
        props = []
    device = unique(devices)
    model = unique(text(p.get("name")) for p in props if isinstance(p, dict)
                   and device is not None and number(p.get("id")) == device)
    distributed = header.get("distributedInfo")
    rank = number(distributed.get("rank")) if isinstance(distributed, dict) else None
    return dict(device_type="GPU" if has_cuda_events or props else None, device_id=device,
                device_model=model, hostname=text(header.get("hostname")) or text(header.get("hostName")), rank=rank)


def read_profile_identity(input_path, npu, gpu, parsed_gpu=None):
    if npu is not None:
        return read_npu_identity(input_path, npu)
    identity = dict(input_path=str(input_path), source_path=str(gpu) if gpu else None, input_path_origin="prof",
                    rank=path_rank(input_path))
    if gpu:
        from cross_trace import trace_document

        if parsed_gpu is None:
            with suppress(OSError, ValueError, TypeError, AttributeError):
                parsed_gpu = gpu_identity(*trace_document(gpu))
        if parsed_gpu:
            parsed_gpu = {k: v for k, v in parsed_gpu.items() if v is not None}
            identity.update(parsed_gpu)
    return identity


def workbook_identities(wb):
    paths = {role: set() for role in ROLES}
    for ws in wb:
        for row in ws.iter_rows(max_row=2, values_only=True):
            for value in row:
                if isinstance(value, str):
                    for role, prefix in XLSX_HEADERS.items():
                        if value.startswith(prefix) and (path := text(value[len(prefix):])):
                            paths[role].add(path)
    return {
        role: dict(input_path=path, input_path_origin="xlsx" if path else None,
                   rank=path_rank(path))
        for role, values in paths.items() if (path := unique(values))
    }


def source_fragments(base, compare):
    a, b = path_parts(base), path_parts(compare)
    while a and b and a[-1] == b[-1]:
        a, b = a[:-1], b[:-1]
    return [p[-1] if p else None for p in (a, b)]


def comparison_identity(base=None, compare=None, labels=(None, None)):
    records = []
    for (role, (name, flag)), data, label in zip(ROLES.items(), (base, compare), labels):
        record = dict.fromkeys(("input_path", "input_path_origin", "source_path", "device_type",
                                "device_id", "device_model", "hostname", "rank"))
        record.update(data or {})
        record.update(role=role, role_name=name, flag=flag, label=text(label))
        device = record["device_type"]
        if device and record["device_id"] is not None:
            device += f' {record["device_id"]}'
        record["device"] = device
        records.append(record)

    paths = [r.pop("capture_path", None) or r["source_path"] or r["input_path"] for r in records]
    if paths[0] == paths[1]:
        paths = [r["source_path"] or r["input_path"] for r in records]
    fragments = source_fragments(*paths)
    a, b = records
    same_name = (a["label"], a["device"]) == (b["label"], b["device"])
    different_hosts = a["hostname"] and b["hostname"] and a["hostname"] != b["hostname"]
    for record, fragment in zip(records, fragments):
        record["source"] = fragment
        parts = [record["role_name"], record["label"], record["device"]]
        if same_name:
            parts.append(record["hostname"] if different_hosts else fragment)
        record["short_label"] = " · ".join(filter(None, parts))
    return {record["role"]: record for record in records}


def add_label_args(parser):
    parser.add_argument("--base-label", help="基线侧的业务名称，例如旧版")
    parser.add_argument("--compare-label", help="比对侧的业务名称，例如新版")
