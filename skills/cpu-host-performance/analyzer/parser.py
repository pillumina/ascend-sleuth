# -*- coding: utf-8 -*-
"""parser.py — 多格式 CPU trace 健壮解析器 (仅标准库)

支持输入:
  1. cpu_trace_*.tar.gz / *.tar.gz / *.tgz / *.zip (采集脚本产物或任意含 trace 的压缩包)
  2. 目录 (内含 trace*.txt 与系统快照)
  3. 裸 ftrace 文本 (cat /sys/kernel/debug/tracing/trace 原样输出)
  4. trace-cmd report 输出的文本 (无 flags 列)
  5. Chrome Tracing / Perfetto JSON (traceEvents 数组)
解析失败行自动跳过并计数, 任何一项缺失不致命。
"""
import io
import os
import re
import json
import tarfile
import zipfile
import tempfile
import shutil

# ---------------------------------------------------------------
# 统一事件模型
# ---------------------------------------------------------------
class Event(object):
    __slots__ = ("ts", "cpu", "etype", "task", "pid", "fields")
    def __init__(self, ts, cpu, etype, task="", pid=-1, fields=None):
        self.ts = ts            # 秒 (float, 相对 trace 起点)
        self.cpu = cpu          # int 或 None
        self.etype = etype      # 事件类型字符串, 如 sched_switch / softirq_entry
        self.task = task
        self.pid = pid
        self.fields = fields or {}

    def __repr__(self):
        return "Event(ts=%.6f cpu=%s %s task=%s pid=%s %s)" % (
            self.ts, self.cpu, self.etype, self.task, self.pid, self.fields)

EVENT_KEYS = {
    "sched_switch": "sched_switch", "sched_wakeup": "sched_wakeup",
    "sched_waking": "sched_waking", "sched_wakeup_new": "sched_wakeup_new",
    "sched_migrate_task": "sched_migrate_task", "task_newtask": "task_newtask",
    "irq_handler_entry": "irq_handler_entry", "irq_handler_exit": "irq_handler_exit",
    "softirq_entry": "softirq_entry", "softirq_exit": "softirq_exit",
    "softirq_raise": "softirq_raise", "cpu_idle": "cpu_idle",
    "cpu_frequency": "cpu_frequency",
}

class TraceData(object):
    def __init__(self):
        self.events = []          # List[Event]
        self.format_name = ""
        self.snapshot = {}        # 快照文件名 -> 文本内容
        self.metadata = {}        # metadata.txt 键值
        self.warnings = []        # 解析告警 (中文)
        self.parse_stats = {"total": 0, "parsed": 0, "failed": 0}
        self.trace_root = ""      # 临时解压根目录

# ---------------------------------------------------------------
# ftrace 文本解析
# ---------------------------------------------------------------
# 标准格式:  <idle>-0     [003] d.h. 12345.678901: sched_switch: prev_comm=...
# trace-cmd: <idle>-0     [003] 12345.678901: sched_switch: prev_comm=...
_LINE_RE = re.compile(
    r'^\s*(?P<task>.+?)\s*-\s*(?P<pid>\d+)\s+\[(?P<cpu>\d+)\]\s*'
    r'(?P<flags>[^\s]*)?\s*(?P<ts>\d+(?:\.\d+)?):\s+(?P<event>[\w:]+):\s*(?P<rest>.*)$')
# 某些导出无 CPU 列 (trace-cmd report --cpu 选项合并后), 兜底
_LINE_NOCPU_RE = re.compile(
    r'^\s*(?P<task>.+?)\s*-\s*(?P<pid>\d+)\s+(?P<ts>\d+(?:\.\d+)?):\s+'
    r'(?P<event>[\w:]+):\s*(?P<rest>.*)$')

_KV_RE = re.compile(r'(\w+)=(?:"([^"]*)"|(\S+))')
_SOFTIRQ_ACT_RE = re.compile(r'\[action=([A-Z_]+)\]')

def _parse_kv(rest):
    out = {}
    m = _SOFTIRQ_ACT_RE.search(rest)
    if m:
        out["action"] = m.group(1)
    for mm in _KV_RE.finditer(rest):
        k = mm.group(1)
        if k == "action" and "action" in out:
            continue  # 保留专用正则提取的干净 action (避免 "vec=3 [action=NET_RX]" 尾括号污染)
        out[k] = mm.group(2) if mm.group(2) is not None else mm.group(3)
    return out

def _norm_event_name(name):
    name = name.strip().rstrip(":")
    return EVENT_KEYS.get(name, name)

def _mk_event(task, pid, cpu, ts, ename, rest):
    etype = _norm_event_name(ename)
    fields = _parse_kv(rest)
    ev = Event(float(ts), int(cpu) if cpu is not None else None, etype, task, int(pid), fields)
    # 归一化常用字段
    if etype == "sched_switch":
        ev.fields.setdefault("prev_pid", "-1")
    if etype == "cpu_idle":
        st = fields.get("state")
        ev.fields["idle_exit"] = (st == "4294967295" or st == "-1")
    if etype == "irq_handler_entry":
        ev.fields.setdefault("name", fields.get("irq", "?"))
    return ev

def parse_ftrace_text(text, td):
    """逐行解析 ftrace / trace-cmd 文本, 失败行计数跳过。"""
    total = parsed = failed = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("Tracing") \
           or line.startswith("VERSION") or line.startswith("CPU:") \
           or line.startswith("entries-in-buffer"):
            continue
        total += 1
        m = _LINE_RE.match(line)
        if m:
            cpu = m.group("cpu")
        else:
            m = _LINE_NOCPU_RE.match(line)
            cpu = None
        if not m:
            failed += 1
            continue
        try:
            ev = _mk_event(m.group("task"), m.group("pid"), cpu, m.group("ts"),
                           m.group("event"), m.group("rest"))
        except Exception:
            failed += 1
            continue
        td.events.append(ev)
        parsed += 1
    td.parse_stats["total"] += total
    td.parse_stats["parsed"] += parsed
    td.parse_stats["failed"] += failed
    return parsed

# ---------------------------------------------------------------
# Chrome Tracing / Perfetto JSON
# ---------------------------------------------------------------
def parse_chrome_json_text(text, td):
    """解析 traceEvents JSON。缺 cpu 字段时置 None (仅做全机聚合)。"""
    data = None
    try:
        data = json.loads(text)
    except Exception:
        # 可能是多个 JSON 行 (JSON Lines)
        data = []
        for line in text.splitlines():
            line = line.strip().rstrip(",")
            if not line or line in ("[", "]"):
                continue
            try:
                data.append(json.loads(line))
            except Exception:
                pass
    if isinstance(data, dict):
        data = data.get("traceEvents", data.get("systemTraceEvents", []))
    if not isinstance(data, list):
        td.warnings.append("JSON 结构无法识别 (缺少 traceEvents 数组)")
        return 0
    parsed = 0
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "")
        etype = _norm_event_name(str(name))
        if etype not in EVENT_KEYS.values():
            continue
        args = item.get("args", {}) or {}
        if isinstance(args, dict) and "args" in args and isinstance(args["args"], dict):
            args = args["args"]
        ts = item.get("ts")
        if ts is None:
            continue
        cpu = args.get("cpu", args.get("cpu_id"))
        if cpu is None:
            cpu = args.get("target_cpu")
        pid = item.get("pid", -1)
        task = str(args.get("prev_comm", args.get("comm", item.get("pname", ""))))
        try:
            ev = Event(float(ts) / 1e6, int(cpu) if cpu is not None else None,
                       etype, task, int(pid) if pid is not None else -1, {})
        except Exception:
            continue
        # 关键字段映射
        for k in ("prev_pid", "next_pid", "pid", "target_cpu", "vec", "action",
                  "irq", "name", "state", "cpu_id", "state_val"):
            if k in args:
                ev.fields[k] = args[k]
        if etype == "cpu_idle" and "state" in ev.fields:
            ev.fields["idle_exit"] = str(ev.fields["state"]) in ("4294967295", "-1")
        td.events.append(ev)
        parsed += 1
    td.parse_stats["total"] += parsed
    td.parse_stats["parsed"] += parsed
    return parsed

# ---------------------------------------------------------------
# 输入类型探测与装载
# ---------------------------------------------------------------
_TRACE_FILE_HINTS = ("trace", ".trace", ".log", ".txt")
_SNAPSHOT_FILES = ("cpuinfo.txt", "proc_stat.txt", "loadavg.txt", "meminfo.txt",
                   "interrupts.txt", "softirqs.txt", "schedstat.txt", "vmstat.txt",
                   "cpufreq.txt", "numa.txt", "system_info.txt", "metadata.txt",
                   "cpu_online.txt", "trace_start_time.txt", "trace_end_time.txt",
                   "trace_overrun.txt", "collection_manifest.json", "npu_smi_info.txt",
                   "npu_smi_map.txt", "npu_smi_topology.txt", "kernel_cmdline.txt",
                   "interrupts_at_end.txt", "softirqs_at_end.txt")

def _looks_like_ftrace(text_head):
    return bool(re.search(r'\[\s*\d+\]\s*(?:[a-z.]{0,4}\s+)?\d+\.\d+:', text_head)) or \
           bool(re.search(r'-\s*\d+\s+\d+\.\d+:\s+\w[\w_]*:', text_head))

def _looks_like_json(text_head):
    h = text_head.lstrip()
    return h.startswith("{") or h.startswith("[")

def _read_head(path, nbytes=8192):
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(nbytes)
    except Exception:
        return ""

def _load_dir_into_td(dirpath, td):
    """目录 (或解压后目录) -> 找 trace 文本与快照。"""
    found_trace = []
    snapshot = {}
    for root, _dirs, files in os.walk(dirpath):
        for fn in files:
            fp = os.path.join(root, fn)
            # hostbound/ 下的 PID/TID affinity、进程线程等快照以相对路径为 key
            # 保留，供报告列明证据覆盖范围；不会把它们误当作 trace 文本解析。
            rel = os.path.relpath(fp, dirpath).replace(os.sep, "/")
            is_hostbound_snapshot = rel.startswith("hostbound/") and (fn.endswith(".txt") or fn.endswith(".json"))
            if fn in _SNAPSHOT_FILES or is_hostbound_snapshot:
                try:
                    with io.open(fp, "r", encoding="utf-8", errors="replace") as f:
                        snapshot[rel if is_hostbound_snapshot else fn] = f.read()
                except Exception:
                    snapshot[rel if is_hostbound_snapshot else fn] = ""
            else:
                low = fn.lower()
                if low.startswith("trace") or low.endswith(".trace") or low.endswith(".log") or low.endswith(".json"):
                    found_trace.append(fp)
    if not found_trace:
        td.warnings.append("未在输入中找到 trace 数据文件")
        return False
    # 多个 trace 文件: 合并解析
    total_parsed = 0
    is_json_any = False
    for fp in sorted(found_trace):
        head = _read_head(fp)
        if not head.strip():
            continue
        if _looks_like_json(head) and not _looks_like_ftrace(head):
            is_json_any = True
            with io.open(fp, "r", encoding="utf-8", errors="replace") as f:
                total_parsed += parse_chrome_json_text(f.read(), td)
        else:
            with io.open(fp, "r", encoding="utf-8", errors="replace") as f:
                total_parsed += parse_ftrace_text(f.read(), td)
    if is_json_any and total_parsed:
        td.format_name = "Chrome/Perfetto JSON (目录内)"
    elif total_parsed:
        td.format_name = "ftrace 文本 (目录内)"
    td.snapshot = snapshot
    if "metadata.txt" in snapshot:
        for line in snapshot["metadata.txt"].splitlines():
            if ":" in line:
                k, _sep, v = line.partition(":")
                td.metadata[k.strip()] = v.strip()
    return total_parsed > 0

def _finalize_events(td):
    """统一按时间戳稳定排序。

    采集脚本并行导出 per_cpu 缓冲区后拼接, 以及目录内多个 trace 文件合并时,
    跨文件行序可能与真实时序不同; 中断/唤醒配对与时间窗统计依赖全局时序,
    因此在加载完成后统一排序 (稳定排序保证同时间戳事件相对次序不变)。
    """
    td.events.sort(key=lambda e: e.ts)
    return td

# ---------------------------------------------------------------
# 安全解压 (防 Zip Slip / Tar Slip 与 zip bomb)
# ---------------------------------------------------------------
_EXTRACT_MAX_TOTAL_BYTES = 512 * 1024 * 1024   # 累计解压大小上限: 512 MB


def _check_member_name(name):
    """校验压缩包成员名, 拒绝绝对路径与路径穿越。"""
    n = (name or "").replace("\\", "/")
    if not n:
        raise ValueError("空成员名")
    if n.startswith("/") or (len(n) >= 2 and n[1] == ":"):
        raise ValueError("拒绝绝对路径成员: %r" % name)
    if any(seg == ".." for seg in n.split("/")):
        raise ValueError("拒绝路径穿越成员: %r" % name)


def _safe_extract_tar(tf, dest):
    """安全解压 tar: 先遍历校验成员名与累计大小, 再落盘。"""
    total = 0
    members = []
    for m in tf.getmembers():
        _check_member_name(m.name)
        total += int(m.size or 0)
        if total > _EXTRACT_MAX_TOTAL_BYTES:
            raise ValueError("累计解压大小超过上限 %d MB" % (_EXTRACT_MAX_TOTAL_BYTES // (1024 * 1024)))
        members.append(m)
    try:
        tf.extractall(dest, members=members, filter="data")  # py3.12+: 二次兜底
    except TypeError:      # 旧版本解释器无 filter 参数
        tf.extractall(dest, members=members)


def _safe_extract_zip(zf, dest):
    """安全解压 zip: 先遍历校验成员名与累计大小, 再落盘。"""
    total = 0
    for info in zf.infolist():
        _check_member_name(info.filename)
        total += int(info.file_size or 0)
        if total > _EXTRACT_MAX_TOTAL_BYTES:
            raise ValueError("累计解压大小超过上限 %d MB" % (_EXTRACT_MAX_TOTAL_BYTES // (1024 * 1024)))
    zf.extractall(dest)


def load_input(path):
    """入口: 任意路径 -> TraceData (自动识别格式)"""
    td = TraceData()
    if not os.path.exists(path):
        raise IOError("输入路径不存在: %s" % path)

    if os.path.isdir(path):
        td.format_name = "目录输入"
        ok = _load_dir_into_td(path, td)
        if not ok:
            td.warnings.append("目录中未解析出任何事件")
        return _finalize_events(td)

    low = path.lower()
    # 压缩包
    if tarfile.is_tarfile(path):
        tmp = tempfile.mkdtemp(prefix="cpu_trace_")
        td.trace_root = tmp
        try:
            with tarfile.open(path, "r:*") as tf:
                _safe_extract_tar(tf, tmp)
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            raise IOError("解压 tar 失败: %s" % e)
        td.format_name = "tar 压缩包"
        _load_dir_into_td(tmp, td)
        return _finalize_events(td)
    if zipfile.is_zipfile(path):
        tmp = tempfile.mkdtemp(prefix="cpu_trace_")
        td.trace_root = tmp
        try:
            with zipfile.ZipFile(path) as zf:
                _safe_extract_zip(zf, tmp)
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            raise IOError("解压 zip 失败: %s" % e)
        td.format_name = "zip 压缩包"
        _load_dir_into_td(tmp, td)
        return _finalize_events(td)

    # 单文件: JSON 或文本
    head = _read_head(path)
    if _looks_like_json(head) and not _looks_like_ftrace(head):
        td.format_name = "Chrome/Perfetto JSON"
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            parse_chrome_json_text(f.read(), td)
    elif head.startswith("\xd0\x63") or low.endswith(".perfetto"):  # protobuf 魔数
        td.warnings.append("检测到 Perfetto protobuf 二进制格式 (.perfetto/.pb), 本分析器仅支持 JSON 导出; "
                           "请在 https://ui.perfetto.dev 中导出 JSON 或使用 trace-cmd report 转文本后重试")
    else:
        td.format_name = "ftrace / trace-cmd 文本"
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            parse_ftrace_text(f.read(), td)

    if not td.events and not td.warnings:
        td.warnings.append("文件中未识别出任何支持的事件, 请确认是 ftrace/trace-cmd/JSON trace")
    return _finalize_events(td)

def cleanup_temp(td):
    if td.trace_root and os.path.isdir(td.trace_root):
        shutil.rmtree(td.trace_root, ignore_errors=True)
