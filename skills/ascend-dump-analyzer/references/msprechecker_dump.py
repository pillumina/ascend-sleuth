#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
msprechecker_dump.py — 独立环境信息采集脚本

从 msprechecker 项目中提取的 dump 功能，用于在昇腾 NPU 服务器上
快速采集系统、环境、Ascend 组件、配置文件、网络拓扑、权重哈希等信息，
并保存为 JSON 快照文件，便于后续比对分析。

本脚本仅依赖 Python 标准库，无需安装 msprechecker 或 msguard/psutil。

用法:
    python3 msprechecker_dump.py                                          # 采集默认信息
    python3 msprechecker_dump.py -o /tmp/snapshot.json                    # 指定输出路径
    python3 msprechecker_dump.py --filter                                 # 仅采集昇腾相关环境变量
    python3 msprechecker_dump.py --mies-config-path /path/to/config.json  # 额外采集 MindIE 配置
    python3 msprechecker_dump.py --rank-table-path /path/to/rank_table.json --scene mindie
    python3 msprechecker_dump.py --weight-dir /path/to/weights --chunk-size 64
"""

import os
import re
import sys
import json
import stat
import time
import shutil
import hashlib
import shlex
import socket
import platform
import subprocess
import ipaddress
import threading
import argparse
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Union
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

__version__ = "1.1.0"

# Keep this helper identical in both standalone scripts; no deployment dependency.
SENSITIVE_KEY = re.compile(
    r'password|passwd|(?:^|[_\-])pwd(?:$|[_\-])|token$|secret$|'
    r'(?:^|[_\-])(?:token|secret)(?:$|[_\-])|'
    r'api[_\-]?key|access[_\-]?key|credential|private[_\-]?key|authorization',
    re.IGNORECASE,
)
MASKED_VALUE = "***MASKED***"


def sensitive_values(data):
    """Collect known credentials so copies in raw text are masked too."""
    values = set()
    if isinstance(data, dict):
        for key, value in data.items():
            if SENSITIVE_KEY.search(str(key)) and isinstance(value, str) and value:
                values.add(value)
            values.update(sensitive_values(value))
    elif isinstance(data, (list, tuple)):
        for value in data:
            values.update(sensitive_values(value))
    return values


def redact_sensitive(data, secrets=None):
    """Mask sensitive fields, known secret copies, assignments, and URL credentials.

    This is a sharing safeguard, not proof that arbitrary raw text is secret-free.
    Process arguments are deliberately omitted because positional secrets cannot
    be identified reliably. Keys and evidence paths remain available.
    """
    secrets = sensitive_values(data) if secrets is None else secrets

    def scrub(value):
        if isinstance(value, dict):
            sensitive_path = SENSITIVE_KEY.search(str(value.get('path', '')))
            result = {}
            for key, item in value.items():
                if key == 'values' and sensitive_path and isinstance(item, dict):
                    result[key] = {label: MASKED_VALUE for label in item}
                elif str(key).startswith('$[') and SENSITIVE_KEY.search(str(key)) and isinstance(item, dict):
                    result[key] = {label: MASKED_VALUE for label in item}
                elif str(key) in ('cmd', 'cmdline', 'ps_raw'):
                    result[key] = MASKED_VALUE + ' (process arguments omitted)'
                elif SENSITIVE_KEY.search(str(key)):
                    result[key] = MASKED_VALUE
                else:
                    result[key] = scrub(item)
            return result
        if isinstance(value, (list, tuple)):
            result = []
            hide_next = False
            for item in value:
                result.append(MASKED_VALUE if hide_next else scrub(item))
                hide_next = (isinstance(item, str) and item.startswith('-')
                             and '=' not in item and bool(SENSITIVE_KEY.search(item)))
            return result
        if not isinstance(value, str):
            return value
        # Very short values are masked by field/assignment, never global substring:
        # TOKEN=x must not rewrite every letter x in evidence paths and timestamps.
        for secret in sorted(secrets, key=len, reverse=True):
            if len(secret) >= 4 and secret != MASKED_VALUE:
                value = value.replace(secret, MASKED_VALUE)
        value = re.sub(r'(?i)(https?://)[^/\s@]+@', r'\1***MASKED***@', value)
        value = re.sub(r'(?i)(\bbearer\s+)[^\s,;"\']+', r'\1***MASKED***', value)
        value = re.sub(
            r'(?i)((?:--)?[\w-]*(?:password|passwd|token|secret|api[_-]?key|access[_-]?key)'
            r'[\w-]*["\']?\s*(?:=|:|\s)\s*)(?:"[^"\n]*"|\'[^\'\n]*\'|[^\s,;&]+)',
            r'\1***MASKED***', value,
        )
        return value

    return scrub(data)



# ============================================================================
# 颜色输出
# ============================================================================

class Color:
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def info(msg, *args):
    print(f"{Color.GREEN}[INFO]{Color.RESET} {msg.format(*args) if args else msg}")

def warn(msg, *args):
    print(f"{Color.YELLOW}[WARNING]{Color.RESET} {msg.format(*args) if args else msg}", file=sys.stderr)

def error(msg, *args):
    print(f"{Color.RED}[ERROR]{Color.RESET} {msg.format(*args) if args else msg}", file=sys.stderr)


# ============================================================================
# 简易版本比较（替代 packaging.version.Version）
# ============================================================================

class SimpleVersion:
    """简易版本号比较，支持 major.minor[.patch] 格式"""

    def __init__(self, version_str: str):
        self._raw = str(version_str).strip()
        parts = re.split(r'[.\-+]', self._raw)
        self._parts = []
        for p in parts:
            m = re.match(r'(\d+)', p)
            if m:
                self._parts.append(int(m.group(1)))
            else:
                break
        if not self._parts:
            self._parts = [0]

    def __ge__(self, other):
        if isinstance(other, str):
            other = SimpleVersion(other)
        return self._parts >= other._parts

    def __gt__(self, other):
        if isinstance(other, str):
            other = SimpleVersion(other)
        return self._parts > other._parts

    def __eq__(self, other):
        if isinstance(other, str):
            other = SimpleVersion(other)
        return self._parts == other._parts

    def __repr__(self):
        return f"Version('{self._raw}')"


# ============================================================================
# NPU 工具函数
# ============================================================================

HCCN_TOOL_CMD = "/usr/local/Ascend/driver/tools/hccn_tool"


def get_npu_device_ids() -> List[int]:
    """Enumerate visible character-device IDs, including sparse container mappings."""
    ids = []
    try:
        names = os.listdir('/dev')
    except OSError:
        return ids
    for name in names:
        match = re.fullmatch(r'davinci(\d+)', name)
        if not match:
            continue
        try:
            if stat.S_ISCHR(os.stat(os.path.join('/dev', name)).st_mode):
                ids.append(int(match.group(1)))
        except OSError:
            continue
    return sorted(set(ids))


def get_npu_count() -> int:
    return len(get_npu_device_ids())


def is_in_container() -> bool:
    """检测是否运行在容器中（多信号综合判断，避免 PID1 为 systemd 的容器误判）"""
    # 显式容器标志文件
    if os.path.exists('/.dockerenv') or os.path.exists('/run/.containerenv'):
        return True
    try:
        with open('/proc/1/cgroup', 'r') as f:
            content = f.read()
    except Exception:
        content = ""
    # cgroup 路径中出现容器运行时标记
    if re.search(r'docker|kubepods|containerd|libpod|lxc', content):
        return True
    # cgroup v2：容器内（启用 cgroup namespace）PID1 位于根路径
    for line in content.splitlines():
        if line.strip() == '0::/':
            return True
    # 弱信号：宿主机 PID1 进程名通常为 systemd/init
    try:
        with open('/proc/1/sched', 'r') as f:
            first_line = f.readline()
        if first_line and first_line.startswith(('systemd', 'init')):
            return False
    except Exception:
        pass
    return False


def which(cmd: str) -> Optional[str]:
    """安全版 shutil.which"""
    return shutil.which(cmd)


COMMAND_TIMEOUT = 15
COMMAND_FAILURES = []
COMMAND_FAILURE_LOCK = threading.Lock()


def run_cmd(cmd, timeout=COMMAND_TIMEOUT) -> Tuple[int, str]:
    """Bounded argv execution; drain stdout/stderr together and retain failures."""
    argv = []
    try:
        argv = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
        proc = subprocess.run(
            argv, shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors='replace', timeout=timeout,
        )
        rc, output = proc.returncode, (proc.stdout or '').strip()
    except subprocess.TimeoutExpired:
        rc, output = -1, f'command timeout after {timeout}s'
    except Exception as exc:
        rc, output = -1, f'command failed: {exc}'
    if rc != 0:
        with COMMAND_FAILURE_LOCK:
            COMMAND_FAILURES.append({'command': argv, 'returncode': rc, 'output': output})
    return rc, output


def checked_output(cmd, timeout=COMMAND_TIMEOUT):
    """Compatibility adapter for collectors that use check_output-style control flow."""
    rc, output = run_cmd(cmd, timeout)
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd, output=output)
    return output


def compress_ids(ids) -> str:
    """将整数列表压缩为 '0-3,8,10-11' 形式的区间字符串（用于 CPU/NUMA 映射展示）"""
    ids = sorted(set(ids))
    if not ids:
        return ""
    parts = []
    start = prev = ids[0]
    for x in ids[1:]:
        if x == prev + 1:
            prev = x
            continue
        parts.append(f"{start}-{prev}" if prev > start else f"{start}")
        start = prev = x
    parts.append(f"{start}-{prev}" if prev > start else f"{start}")
    return ",".join(parts)


# ============================================================================
# Rank Table 解析
# ============================================================================

class Framework(Enum):
    MINDIE = "mindie"
    VLLM = "vllm"


@dataclass
class DeviceInfo:
    device_ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]
    device_id: int
    rank_id: int


@dataclass
class RankTable:
    host_to_devices: Dict
    server_count: int
    version: SimpleVersion


class RankTableParseError(ValueError):
    pass


_HOST_LIMIT = 1000
_DEVICE_LIMIT_PER_HOST = 32


def _load_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        raise RankTableParseError(f"无法加载 JSON 文件: {path!r}") from exc


def _parse_mindie_rank_table(path: str) -> RankTable:
    data = _load_json(path)

    if "server_list" not in data:
        raise RankTableParseError(f"rank table 中未找到 'server_list': {path!r}")
    if "server_count" not in data:
        raise RankTableParseError(f"rank table 中未找到 'server_count': {path!r}")

    host_to_devices = {}
    for host_num, server_info in enumerate(data["server_list"]):
        if host_num >= _HOST_LIMIT:
            raise RankTableParseError(f"主机数量超过限制 {_HOST_LIMIT}")

        host_ip_str = server_info.get("server_id", "")
        device_list = server_info.get("device", [])

        if not host_ip_str or not device_list:
            continue

        try:
            host_ip = ipaddress.ip_address(host_ip_str)
        except ValueError:
            warn("无效的 server_id: {!r}, 跳过", host_ip_str)
            continue

        if host_ip not in host_to_devices:
            host_to_devices[host_ip] = []

        for dev_num, dev_info in enumerate(device_list):
            if dev_num >= _DEVICE_LIMIT_PER_HOST:
                raise RankTableParseError(
                    f"主机 {host_ip_str!r} 的设备数量超过限制 {_DEVICE_LIMIT_PER_HOST}"
                )
            try:
                device_ip = ipaddress.ip_address(dev_info.get("device_ip", ""))
                device_id = int(dev_info.get("device_id", ""))
                rank_id = int(dev_info.get("rank_id", ""))
            except (ValueError, TypeError):
                continue
            host_to_devices[host_ip].append(
                DeviceInfo(device_ip=device_ip, device_id=device_id, rank_id=rank_id)
            )

    if not host_to_devices:
        raise RankTableParseError(f"rank table 中未解析出任何设备: {path!r}")

    server_count = data["server_count"]
    if isinstance(server_count, str):
        server_count = int(server_count) if server_count.isdigit() else 0

    return RankTable(
        host_to_devices=host_to_devices,
        server_count=server_count,
        version=SimpleVersion(data.get("version", "1.0")),
    )


def _parse_vllm_rank_table(path: str) -> RankTable:
    data = _load_json(path)

    if "prefill_device_list" not in data or "decode_device_list" not in data:
        raise RankTableParseError(
            f"vllm rank table 中需要 'prefill_device_list' 和 'decode_device_list': {path!r}"
        )

    host_to_devices = {}
    for device_list in [data["prefill_device_list"], data["decode_device_list"]]:
        if device_list is None:
            continue
        for dev in device_list:
            host_ip_str = dev.get("server_id", "")
            try:
                host_ip = ipaddress.ip_address(host_ip_str)
            except ValueError:
                continue

            if host_ip not in host_to_devices:
                if len(host_to_devices) >= _HOST_LIMIT:
                    raise RankTableParseError(f"主机数量超过限制 {_HOST_LIMIT}")
                host_to_devices[host_ip] = []

            if len(host_to_devices[host_ip]) >= _DEVICE_LIMIT_PER_HOST:
                raise RankTableParseError(
                    f"主机 {host_ip_str!r} 的设备数量超过限制 {_DEVICE_LIMIT_PER_HOST}"
                )

            try:
                device_ip = ipaddress.ip_address(dev.get("device_ip", ""))
                device_id = int(dev.get("device_id", ""))
                cluster_id = int(dev.get("cluster_id", "1"))
            except (ValueError, TypeError):
                continue

            host_to_devices[host_ip].append(
                DeviceInfo(device_ip=device_ip, device_id=device_id, rank_id=cluster_id - 1)
            )

    if not host_to_devices:
        raise RankTableParseError(f"rank table 中未解析出任何设备: {path!r}")

    server_count = data.get("server_count", len(host_to_devices))
    if isinstance(server_count, str):
        server_count = int(server_count) if server_count.isdigit() else 0

    return RankTable(
        host_to_devices=host_to_devices,
        server_count=server_count,
        version=SimpleVersion(data.get("version", "1.0")),
    )


def parse_rank_table(path: str, framework: Union[str, Framework]) -> RankTable:
    """解析 rank table 文件"""
    if isinstance(framework, str):
        framework = Framework(framework)

    if framework == Framework.MINDIE:
        return _parse_mindie_rank_table(path)
    elif framework == Framework.VLLM:
        return _parse_vllm_rank_table(path)
    else:
        raise ValueError(f"不支持的框架: {framework!r}")


# ============================================================================
# 采集器
# ============================================================================

class CollectorResult:
    """采集结果容器"""
    def __init__(self, data, collect_type: str, errors: list = None):
        self.data = data
        self.collect_type = collect_type
        self.errors = errors or []

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0


class SysCollector:
    """系统信息采集器 — 采集 CPU、内核、内存、虚拟化等信息"""

    def __init__(self):
        self.collect_type = "system"

    def _collect_lscpu(self) -> dict:
        try:
            output = checked_output(['/usr/bin/lscpu'])
        except Exception:
            return {}

        info = {}
        for line in output.splitlines():
            if ':' not in line:
                continue
            key, value = [x.strip() for x in line.split(':', 1)]
            if key in ("Model name", "型号名称"):
                info["model_name"] = value
            elif key == "BIOS Model name" and "model_name" not in info:
                info["model_name"] = value
        return info

    def _collect_virtual_machine(self) -> dict:
        keywords = ["hypervisor", "vmware", "virtualbox", "kvm", "xen"]
        try:
            with open("/proc/cpuinfo", 'r') as f:
                for line in f:
                    if any(kw in line.lower() for kw in keywords):
                        return {"virtual_machine": True}
        except Exception:
            pass
        return {"virtual_machine": False}

    def _collect_cpu_high_performance(self) -> dict:
        """检测 CPU 是否处于高性能模式（多策略降级）"""
        strategies = [
            self._check_scaling_governor,
            self._check_dmidecode,
            self._check_cpupower,
            self._check_psutil,
            self._check_lshw,
        ]
        for strategy in strategies:
            try:
                if strategy():
                    return {"high_performance": True}
            except Exception:
                continue
        return {"high_performance": False}

    def _check_scaling_governor(self) -> bool:
        cpu_count = os.cpu_count()
        if not cpu_count:
            return False
        for core_id in range(cpu_count):
            gov_path = f'/sys/devices/system/cpu/cpu{core_id}/cpufreq/scaling_governor'
            try:
                with open(gov_path, 'r') as f:
                    if f.read().strip() != "performance":
                        return False
            except Exception:
                return False
        return True

    def _check_dmidecode(self) -> bool:
        try:
            output = checked_output(shlex.split("dmidecode -t processor"))
        except Exception:
            return False
        max_speeds = []
        current_speeds = []
        for line in output.splitlines():
            m = re.search(r'Max Speed:\s*(.+)', line, re.IGNORECASE)
            if m:
                max_speeds.append(m.group(1).strip())
            m = re.search(r'Current Speed:\s*(.+)', line, re.IGNORECASE)
            if m:
                current_speeds.append(m.group(1).strip())
        return bool(max_speeds and current_speeds and max_speeds == current_speeds)

    def _check_cpupower(self) -> bool:
        try:
            output = checked_output(shlex.split("cpupower frequency-info"))
        except Exception:
            return False
        max_m = re.search(r'hardware limits:\s*[\d\.]+\s*[GMK]?Hz\s*-\s*([\d\.]+\s*[GMK]?Hz)', output, re.IGNORECASE)
        cur_m = re.search(r'current CPU frequency:\s*([\d\.]+\s*[GMK]?Hz)', output, re.IGNORECASE)
        if max_m and cur_m:
            return max_m.group(1).strip() == cur_m.group(1).strip()
        return False

    def _check_psutil(self) -> bool:
        try:
            import psutil
            cpu_freq = psutil.cpu_freq()
            if cpu_freq:
                return cpu_freq.current == cpu_freq.max
        except ImportError:
            pass
        return False

    def _check_lshw(self) -> bool:
        try:
            output = checked_output(shlex.split("lshw -c cpu"))
        except Exception:
            return False
        sizes = []
        capacities = []
        for line in output.splitlines():
            m = re.search(r'size:\s*(.+)', line, re.IGNORECASE)
            if m:
                sizes.append(m.group(1).strip())
            m = re.search(r'capacity:\s*(.+)', line, re.IGNORECASE)
            if m:
                capacities.append(m.group(1).strip())
        return bool(sizes and capacities and sizes == capacities)

    def _collect_kernel_info(self) -> dict:
        info = dict(platform.uname()._asdict())
        try:
            with open('/sys/kernel/mm/transparent_hugepage/enabled', 'r') as f:
                content = f.read()
            m = re.search(r'\[(\w+)\]', content)
            info['transparent_hugepage'] = m.group(1) if m else content.strip()
        except Exception:
            pass
        return info

    def _collect_memory_info(self) -> dict:
        mem_info = {}
        try:
            mem_info['page_size'] = os.sysconf("SC_PAGESIZE")
        except Exception:
            pass
        try:
            with open('/proc/sys/vm/overcommit_memory', 'r') as f:
                mem_info['overcommit_memory'] = f.read().strip()
        except Exception:
            pass
        return mem_info

    def collect(self) -> CollectorResult:
        sub_collectors = [
            ("lscpu", self._collect_lscpu),
            ("vm", self._collect_virtual_machine),
            ("cpu_hp", self._collect_cpu_high_performance),
            ("kernel", self._collect_kernel_info),
            ("memory", self._collect_memory_info),
        ]

        result = {}
        errors = []

        max_workers = min(len(sub_collectors), os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers) as executor:
            futures = {
                executor.submit(fn): name
                for name, fn in sub_collectors
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    data = future.result()
                    result.update(data)
                except Exception as e:
                    errors.append(f"采集 {name} 失败: {e}")

        return CollectorResult(result, self.collect_type, errors)


class HardwareCollector:
    """硬件资源采集器 — CPU 拓扑 / 内存 / 磁盘 / PCIe&NUMA / 内核参数 / 时钟

    每个子项同时输出结构化字段（供 Agent 精确判断）与 raw 原始输出（现场证据）。
    """

    def __init__(self):
        self.collect_type = "hardware"

    # ------------------------------------------------------------------
    # 子采集器 1：内存（/proc/meminfo）
    # ------------------------------------------------------------------
    def _collect_memory(self) -> dict:
        out = {}
        try:
            with open('/proc/meminfo', 'r') as f:
                raw = f.read()
            out["raw"] = raw
            keep = ("MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached",
                    "SwapTotal", "SwapFree", "HugePages_Total", "Hugepagesize")
            for line in raw.splitlines():
                if ":" not in line:
                    continue
                key, val = line.split(":", 1)
                key = key.strip()
                if key in keep:
                    m = re.match(r'\s*([\d.]+)', val)
                    if m:
                        out[key] = round(float(m.group(1)), 1)
            total = float(out.get("MemTotal", 0) or 0)
            avail = float(out.get("MemAvailable", 0) or 0)
            swap = float(out.get("SwapTotal", 0) or 0)
            if total:
                out["mem_total_gb"] = round(total / 1048576, 1)
                out["mem_available_gb"] = round(avail / 1048576, 1)
                out["mem_used_pct"] = round((total - avail) / total * 100, 1)
            out["swap_total_gb"] = round(swap / 1048576, 1)
        except Exception as e:
            out["error"] = str(e)
        return {"memory": out}

    # ------------------------------------------------------------------
    # 子采集器 2：CPU 拓扑（lscpu -p：Socket/NUMA/核数/线程）
    # ------------------------------------------------------------------
    def _collect_cpu_topology(self) -> dict:
        out = {"raw": None}
        rc, raw = run_cmd("lscpu -p=CPU,SOCKET,NODE,CORE,ONLINE,MAXMHZ,MINMHZ")
        if rc != 0 or not raw:
            rc, raw = run_cmd("lscpu -p")
        out["raw"] = raw
        try:
            cpu_rows = []
            header = None
            for line in (raw or "").splitlines():
                line = line.strip()
                if line.startswith('#'):
                    header = [c.strip() for c in line.lstrip('# ').split(',')]
                    continue
                if not line:
                    continue
                cols = line.split(',')
                row = dict(zip(header, cols)) if header else {"CPU": cols[0]}
                cpu_rows.append(row)

            online_cpus, sockets, nodes, cores = [], set(), set(), set()
            per_numa, per_socket = {}, {}
            for r in cpu_rows:
                try:
                    cpu = int(r.get("CPU", -1))
                except (TypeError, ValueError):
                    continue
                if str(r.get("ONLINE", "1")) not in ("1", "Y", "y"):
                    continue
                online_cpus.append(cpu)
                socket = r.get("SOCKET", "-")
                node = r.get("NODE", "-")
                core = r.get("CORE", "-")
                sockets.add(socket)
                if node not in ("", "-"):
                    nodes.add(node)
                    per_numa.setdefault(node, []).append(cpu)
                per_socket.setdefault(socket, []).append(cpu)
                cores.add((socket, core))

            out["logical_cpus_online"] = len(online_cpus)
            out["socket_count"] = len(sockets)
            out["numa_node_count"] = len(nodes)
            out["physical_cores"] = len(cores)
            if cores:
                out["threads_per_core"] = round(len(online_cpus) / len(cores), 1)
            out["numa_cpu_map"] = {n: compress_ids(v) for n, v in per_numa.items()}
            out["socket_cpu_map"] = {s: compress_ids(v) for s, v in per_socket.items()}

            # lscpu 汇总信息（CPU 型号 / NUMA 分布）
            rc2, lscpu_all = run_cmd("lscpu")
            out["lscpu_raw"] = lscpu_all
            for line in (lscpu_all or "").splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                k = k.strip()
                if k in ("Model name", "Architecture", "CPU(s)", "On-line CPU(s) list",
                         "CPU MHz", "Hypervisor vendor", "Virtualization") \
                        or k.startswith("NUMA node"):
                    out[k.replace(" ", "_").replace("(", "").replace(")", "")] = v.strip()
        except Exception as e:
            out["error"] = str(e)
        return {"cpu_topology": out}

    # ------------------------------------------------------------------
    # 子采集器 3：每核 governor 与实际频率（逐核读取 cpufreq）
    # ------------------------------------------------------------------
    def _collect_cpu_runtime(self) -> dict:
        out = {"cores": []}
        raw_lines = []
        try:
            base = "/sys/devices/system/cpu"
            cpu_dirs = sorted(
                (d for d in os.listdir(base) if re.fullmatch(r'cpu\d+', d)),
                key=lambda x: int(x[3:]),
            )
            freqs = []
            for d in cpu_dirs:
                entry = {"cpu": int(d[3:])}
                for fname, key, scale in (
                    ("scaling_governor", "governor", 1),
                    ("scaling_cur_freq", "cur_freq_mhz", 1000),
                    ("cpuinfo_max_freq", "max_freq_mhz", 1000),
                    ("online", "online", 1),
                ):
                    if key == "online":
                        fpath = os.path.join(base, d, fname)
                    else:
                        fpath = os.path.join(base, d, "cpufreq", fname)
                    try:
                        with open(fpath) as f:
                            val = f.read().strip()
                        entry[key] = round(float(val) / scale, 0) if scale > 1 else val
                        if key == "cur_freq_mhz":
                            freqs.append(float(val))
                    except Exception:
                        entry[key] = None
                out["cores"].append(entry)
                raw_lines.append(
                    f"cpu{entry['cpu']}: governor={entry['governor']} "
                    f"cur={entry['cur_freq_mhz']}MHz max={entry['max_freq_mhz']}MHz "
                    f"online={entry['online']}"
                )
            out["raw"] = "\n".join(raw_lines) or None
            if freqs:
                out["avg_cur_freq_mhz"] = round(sum(freqs) / len(freqs) / 1000, 0)
            govs = {c["governor"] for c in out["cores"] if c["governor"]}
            out["governor_modes"] = sorted(govs)
        except Exception as e:
            out["error"] = str(e)
        return {"cpu_runtime": out}

    # ------------------------------------------------------------------
    # 子采集器 4：磁盘与 BIOS/BMC（df / lsblk / sysfs-dmi / ipmitool）
    # ------------------------------------------------------------------
    def _collect_disk(self) -> dict:
        out = {"filesystems": [], "block_devices": []}
        raw_parts = []
        rc, raw = run_cmd("df -hP -x tmpfs -x devtmpfs -x overlay -x squashfs")
        if rc != 0 or not raw:
            rc, raw = run_cmd("df -hP")
        out["df_raw"] = raw
        raw_parts.append(raw or "")
        try:
            for line in (raw or "").splitlines()[1:]:
                cols = line.split()
                if len(cols) >= 6:
                    out["filesystems"].append({
                        "fs": cols[0], "size": cols[1], "used": cols[2],
                        "avail": cols[3], "use_pct": cols[4], "mount": cols[5],
                    })
        except Exception as e:
            out["error_df"] = str(e)

        rc, raw = run_cmd("lsblk -d -o NAME,MODEL,ROTA,SIZE,TYPE")
        if rc == 0 and raw:
            out["lsblk_raw"] = raw
            raw_parts.append(raw)
            try:
                for line in raw.splitlines()[1:]:
                    cols = line.split(None, 4)
                    if len(cols) >= 4:
                        out["block_devices"].append({
                            "name": cols[0],
                            "model": cols[1] if len(cols) > 1 else "",
                            "rotational": cols[2] if len(cols) > 2 else "",
                            "size": cols[3] if len(cols) > 3 else "",
                        })
            except Exception as e:
                out["error_lsblk"] = str(e)

        # BIOS / 主板信息（优先 sysfs 免 root 读取）
        bios = {}
        for key in ("bios_vendor", "bios_version", "bios_date",
                    "board_vendor", "board_name", "product_name"):
            try:
                with open(f"/sys/class/dmi/id/{key}") as f:
                    bios[key] = f.read().strip()
            except Exception:
                pass
        # BMC 固件版本（需要 root + ipmitool，失败则尝试 dmidecode）
        rc, raw = run_cmd("ipmitool mc info")
        if rc == 0 and raw:
            m = re.search(r'Firmware Revision\s*:\s*(\S+)', raw)
            if m:
                bios["bmc_firmware"] = m.group(1)
            bios["ipmitool_raw"] = raw
        else:
            rc, raw = run_cmd("dmidecode -t bios")
            if rc == 0 and raw:
                bios["dmidecode_raw"] = raw
        out["bios_bmc"] = bios
        out["raw"] = "\n\n".join(p for p in raw_parts if p) or None
        return {"disk": out}

    # ------------------------------------------------------------------
    # 子采集器 5：PCIe / NUMA 拓扑（NPU 与网卡的 PCIe/NUMA 归属）
    # ------------------------------------------------------------------
    def _collect_pcie_numa(self) -> dict:
        out = {}
        pci_base = "/sys/bus/pci/devices"

        def _read_pci_fields(addr):
            entry = {}
            for field, key in (("numa_node", "numa_node"),
                               ("current_link_speed", "pcie_speed"),
                               ("current_link_width", "pcie_width")):
                try:
                    with open(os.path.join(pci_base, addr, field)) as f:
                        entry[key] = f.read().strip()
                except Exception:
                    entry[key] = None
            return entry

        # 5.1 NPU PCIe 设备（华为厂商 ID 0x19e5）
        rc, raw = run_cmd("lspci -nn -d 19e5:")
        out["lspci_npu_raw"] = raw if rc == 0 else None
        npu_devices = []
        for line in (raw or "").splitlines() if rc == 0 else []:
            m = re.match(r'([0-9a-fA-F:.]+)\s+(.*)', line)
            if not m:
                continue
            addr, desc = m.group(1), m.group(2).strip()
            entry = {"pci_addr": addr, "device_name": desc}
            entry.update(_read_pci_fields(addr))
            npu_devices.append(entry)
        out["npu_pcie_devices"] = npu_devices
        out["npu_numa_map"] = {d["pci_addr"]: d.get("numa_node") for d in npu_devices}

        # 5.2 物理网卡及其 NUMA 归属（跳过 lo / veth 等虚拟口）
        nics = []
        try:
            for ifname in sorted(os.listdir("/sys/class/net")):
                dev_link = os.path.join("/sys/class/net", ifname, "device")
                if not os.path.islink(dev_link):
                    continue
                pci_addr = os.path.basename(os.path.realpath(dev_link))
                entry = {"nic": ifname, "pci_addr": pci_addr}
                entry.update(_read_pci_fields(pci_addr))
                nics.append(entry)
        except Exception as e:
            out["error_nic"] = str(e)
        out["nic_pcie"] = nics

        # 5.3 numactl 硬件拓扑（NUMA 内存分布）
        rc, raw = run_cmd("numactl -H")
        out["numactl_raw"] = raw if rc == 0 else None
        numa_mem = {}
        if rc == 0:
            for line in (raw or "").splitlines():
                m = re.match(r'node (\d+) size:\s*(\d+) MB', line)
                if m:
                    numa_mem[f"node{m.group(1)}_mem_gb"] = round(int(m.group(2)) / 1024, 1)
                    continue
                m = re.match(r'node (\d+) cpus:', line)
                if m:
                    cpus = [int(x) for x in line.split(":", 1)[1].split()]
                    numa_mem[f"node{m.group(1)}_cpus"] = compress_ids(cpus)
        if numa_mem:
            out["numa_memory"] = numa_mem
        return {"pcie_numa": out}

    # ------------------------------------------------------------------
    # 子采集器 6：内核调优参数与进程资源限制
    # ------------------------------------------------------------------
    def _collect_kernel_params(self) -> dict:
        out = {}
        sysctl_keys = [
            ("/proc/sys/vm/swappiness", "vm.swappiness"),
            ("/proc/sys/vm/max_map_count", "vm.max_map_count"),
            ("/proc/sys/vm/overcommit_memory", "vm.overcommit_memory"),
            ("/proc/sys/vm/overcommit_ratio", "vm.overcommit_ratio"),
            ("/proc/sys/fs/file-max", "fs.file-max"),
            ("/proc/sys/kernel/numa_balancing", "kernel.numa_balancing"),
            ("/proc/sys/kernel/core_pattern", "kernel.core_pattern"),
            ("/proc/sys/kernel/pid_max", "kernel.pid_max"),
            ("/proc/sys/kernel/threads-max", "kernel.threads-max"),
        ]
        for path, key in sysctl_keys:
            try:
                with open(path) as f:
                    out[key] = f.read().strip()
            except Exception:
                out[key] = None

        # /proc/self/limits 等价 ulimit -a（nofile / memlock / nproc 等）
        limits = {}
        interesting = {
            "Max open files": "nofile",
            "Max locked memory": "memlock",
            "Max processes": "nproc",
            "Max stack size": "stack",
            "Max address space": "address_space",
        }
        try:
            with open("/proc/self/limits") as f:
                raw = f.read()
            out["ulimit_raw"] = raw
            for line in raw.splitlines():
                for src, dst in interesting.items():
                    if line.startswith(src):
                        parts = line.split()
                        if len(parts) >= 3:
                            limits[dst] = {"soft": parts[-3], "hard": parts[-2]}
        except Exception as e:
            out["error_limits"] = str(e)
        out["limits"] = limits
        return {"kernel_params": out}

    # ------------------------------------------------------------------
    # 子采集器 7：时钟源与 NTP 同步状态
    # ------------------------------------------------------------------
    def _collect_clock(self) -> dict:
        out = {}
        try:
            with open("/sys/devices/system/clocksource/clocksource0/current_clocksource") as f:
                out["clocksource"] = f.read().strip()
        except Exception:
            pass
        try:
            with open("/sys/devices/system/clocksource/clocksource0/available_clocksource") as f:
                out["clocksource_available"] = f.read().strip()
        except Exception:
            pass

        rc, raw = run_cmd("chronyc tracking")
        if rc == 0 and raw and "failed" not in raw.lower():
            out["chrony_raw"] = raw
            for line in raw.splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                k = k.strip()
                if k in ("Stratum", "Leap status", "Last offset"):
                    out[f"ntp_{k.lower().replace(' ', '_')}"] = v.strip()
            out["ntp_synchronized"] = \
                "yes" if out.get("ntp_leap_status") == "normal" else "check"
        else:
            rc, raw = run_cmd("timedatectl")
            out["timedatectl_raw"] = raw if rc == 0 and raw else None
            for line in (raw or "").splitlines():
                if "System clock synchronized" in line:
                    out["ntp_synchronized"] = line.split(":", 1)[1].strip()
                elif "NTP service" in line:
                    out["ntp_service"] = line.split(":", 1)[1].strip()
                elif "Time zone" in line:
                    out["timezone"] = line.split(":", 1)[1].strip()
        return {"clock": out}

    # ------------------------------------------------------------------
    # 汇总入口：7 个子采集器并发执行（与 SysCollector 相同的线程池模式）
    # ------------------------------------------------------------------
    def collect(self) -> CollectorResult:
        sub_collectors = [
            ("memory", self._collect_memory),
            ("cpu_topology", self._collect_cpu_topology),
            ("cpu_runtime", self._collect_cpu_runtime),
            ("disk", self._collect_disk),
            ("pcie_numa", self._collect_pcie_numa),
            ("kernel_params", self._collect_kernel_params),
            ("clock", self._collect_clock),
        ]
        result = {}
        errors = []
        max_workers = min(len(sub_collectors), os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers) as executor:
            futures = {executor.submit(fn): name for name, fn in sub_collectors}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result.update(future.result())
                except Exception as e:
                    errors.append(f"采集 {name} 失败: {e}")
        return CollectorResult(result, self.collect_type, errors)


class NPUCollector:
    """NPU 运行态采集器（与 AscendCollector 的组件版本采集互补）

    覆盖：npu-smi 全量快照、逐卡健康/温度/功耗/HBM 占用/ECC、固件版本、
    /dev 设备节点权限、光模块收发状态、昇腾日志目录元信息。
    每个子项同时保留结构化字段与 raw 原始输出。
    """

    # /dev 下除 davinciN 外必须存在的昇腾设备节点（容器场景高频故障点）
    REQUIRED_NODES = ("davinci_manager", "devmm_svm", "hisi_hdc")

    # 每卡采集的 npu-smi info -t 子命令
    PER_DEVICE_QUERIES = ("board", "common", "usages", "health", "temp", "power", "ecc")

    # npu-smi 命令候选路径（不在 PATH 时兜底）
    SMI_CANDIDATES = ("/usr/local/sbin/npu-smi", "/usr/local/Ascend/driver/tools/npu-smi")

    # 昇腾日志目录候选
    LOG_DIR_CANDIDATES = ("/root/ascend/log", "/var/log/npu", "/var/log/ascend")

    def __init__(self):
        self.collect_type = "npu"
        self.device_ids = get_npu_device_ids()
        self.npu_count = len(self.device_ids)
        self.smi_cmd = self._resolve_smi()

    def _resolve_smi(self) -> Optional[str]:
        """定位 npu-smi 命令：优先 PATH，其次常见安装路径"""
        found = which("npu-smi")
        if found:
            return found
        for cand in self.SMI_CANDIDATES:
            if os.path.isfile(cand):
                return cand
        return None

    # ------------------------------------------------------------------
    # 解析辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_kv(raw: str) -> dict:
        """将 'Key : Value' 风格输出解析为字典（npu-smi -t 系列命令）"""
        kv = {}
        for line in raw.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                k = k.strip()
                if k:
                    kv[k] = v.strip()
        return kv

    @staticmethod
    def _kv_match(kv: dict, *keywords):
        """按关键词（不区分大小写、忽略括号）模糊匹配，返回第一个命中的 (key, value)"""
        for key, value in kv.items():
            norm = key.lower().replace("(", "").replace(")", "")
            if all(w.lower() in norm for w in keywords):
                return key, value
        return None, None

    @classmethod
    def _kv_get(cls, kv: dict, *keywords):
        return cls._kv_match(kv, *keywords)[1]

    @staticmethod
    def _to_num(value):
        """尽力转为数字，失败则返回原字符串"""
        if value is None:
            return None
        try:
            f = float(str(value).split()[0])
            return int(f) if f == int(f) else round(f, 2)
        except (ValueError, IndexError):
            return value

    # ------------------------------------------------------------------
    # 子采集器 1：npu-smi 全量快照（版本头 + 设备表格）
    # ------------------------------------------------------------------
    def _collect_smi(self) -> dict:
        out = {}
        if not self.smi_cmd:
            out['smi_collection'] = {'collection_status': 'unavailable', 'reason': '未找到 npu-smi 命令'}
            return out
        rc, raw = run_cmd(f"{self.smi_cmd} info", timeout=20)
        out['smi_collection'] = {'collection_status': 'success' if rc == 0 else 'failed'}
        out["smi_rc"] = rc
        out["smi_raw"] = raw if raw else None
        if rc == 0 and raw:
            for line in raw.splitlines():
                low = line.lower()
                # 表头形如：| npu-smi 24.1.rc1   Version: 24.1.rc1 |
                if "npu-smi" in low and "smi_version" not in out:
                    parts = line.split()
                    for idx, tok in enumerate(parts):
                        if tok.lower().startswith("npu-smi") and idx + 1 < len(parts):
                            out["smi_version"] = parts[idx + 1]
                            break
                if "Version:" in line and "driver_version" not in out:
                    val = line.split("Version:", 1)[1].split("|")[0].strip()
                    if val:
                        out["driver_version"] = val
            # 表格行交叉校验卡数（NPU 行：| <id> <非数字型号> ...）
            table_ids = []
            for line in raw.splitlines():
                fields = line.split()
                if (fields and fields[0] == "|" and len(fields) >= 3
                        and fields[1].isdigit() and not fields[2].isdigit()):
                    table_ids.append(int(fields[1]))
            if table_ids:
                out["smi_table_device_ids"] = compress_ids(table_ids)
        return out

    # ------------------------------------------------------------------
    # 子采集器 2：逐卡运行态（健康/温度/功耗/占用/ECC/固件）
    # ------------------------------------------------------------------
    def _collect_one_device(self, device_id: int) -> dict:
        dev = {"device_id": device_id}
        raw_map = {}
        query_status = {}
        for subcmd in self.PER_DEVICE_QUERIES:
            rc, raw = run_cmd(
                f"{self.smi_cmd} info -t {subcmd} -i {device_id}", timeout=20)
            # 部分版本需要显式指定芯片号，失败时以 -c 0 重试
            if (rc != 0 or not raw) and subcmd == "common":
                rc2, raw2 = run_cmd(
                    f"{self.smi_cmd} info -t {subcmd} -i {device_id} -c 0", timeout=20)
                if rc2 == 0 and raw2:
                    rc, raw = rc2, raw2
            raw_map[subcmd] = raw or ""
            query_status[subcmd] = {"returncode": rc, "status": "success" if rc == 0 else "failed"}
        dev["queries"] = query_status
        dev["raw"] = {k: v if v else None for k, v in raw_map.items()}

        common_kv = self._parse_kv(raw_map.get("common") or "")
        board_kv = self._parse_kv(raw_map.get("board") or "")
        usages_kv = self._parse_kv(raw_map.get("usages") or "")
        temp_kv = self._parse_kv(raw_map.get("temp") or "")
        power_kv = self._parse_kv(raw_map.get("power") or "")
        ecc_kv = self._parse_kv(raw_map.get("ecc") or "")

        dev["name"] = self._kv_get(common_kv, "Name") or self._kv_get(board_kv, "Name")
        dev["chip_type"] = self._kv_get(common_kv, "Chip", "Type")
        dev["aicore_count"] = self._to_num(self._kv_get(common_kv, "AICore", "Number"))
        dev["aicore_pct"] = self._to_num(self._kv_get(common_kv, "AICore", "Usage"))

        health_raw = (raw_map.get("health") or "").strip()
        dev["health"] = self._kv_get(common_kv, "Health") \
            or (health_raw.splitlines()[0] if health_raw else None)
        # 健康查询返回非 OK 时保留具体报错（如 Error code: 0x...）
        if health_raw and health_raw.upper() != "OK":
            dev["health_message"] = health_raw

        dev["temp_c"] = self._to_num(
            self._kv_get(temp_kv, "NPU", "Temperature")
            or self._kv_get(common_kv, "Temperature"))
        dev["hbm_temp_c"] = self._to_num(self._kv_get(temp_kv, "HBM", "Temperature"))

        # 功耗：键名可能为 Power(W) 或 Power(mW)，统一换算为 W
        pkey, pval = self._kv_match(power_kv, "power")
        if not pkey:
            pkey, pval = self._kv_match(common_kv, "power")
        if pkey:
            num = self._to_num(pval)
            if isinstance(num, (int, float)) and "(mw)" in pkey.lower():
                num = round(num / 1000, 2)
            dev["power_w"] = num

        # HBM/DDR 占用（910B 的 usages 输出以 DDR 命名，实为 HBM）
        dev["hbm_used_mb"] = self._to_num(self._kv_get(usages_kv, "Memory", "Used"))
        dev["hbm_total_mb"] = self._to_num(self._kv_get(usages_kv, "Memory", "Total"))
        dev["hbm_usage_pct"] = self._to_num(self._kv_get(usages_kv, "Usage", "Rate"))

        # ECC：保留含 error/correct/ecc 关键词的键值
        ecc_summary = {k: v for k, v in ecc_kv.items()
                       if any(w in k.lower() for w in ("error", "correct", "ecc"))}
        if ecc_summary:
            dev["ecc"] = ecc_summary

        # 固件/序列号来自 board 信息
        firmware = self._kv_get(board_kv, "Software", "Version") \
            or self._kv_get(board_kv, "Firmware")
        if firmware:
            dev["firmware_version"] = firmware
        serial = self._kv_get(board_kv, "Serial")
        if serial:
            dev["serial"] = serial
        return dev

    def _collect_per_device(self) -> dict:
        out = {}
        if not self.smi_cmd:
            out['per_device_collection'] = {'collection_status': 'unavailable', 'reason': '未找到 npu-smi 命令'}
            return out
        if self.npu_count <= 0:
            out['per_device_collection'] = {'collection_status': 'skipped', 'reason': '未检测到可见 NPU 设备'}
            return out
        devices = {}
        max_workers = min(self.npu_count, os.cpu_count() or 4)
        with ThreadPoolExecutor(max_workers) as executor:
            futures = {executor.submit(self._collect_one_device, i): i
                       for i in self.device_ids}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    devices[idx] = future.result()
                except Exception as e:
                    devices[idx] = {"device_id": idx, "error": str(e)}
        out["devices"] = [devices[i] for i in self.device_ids]
        out['per_device_collection'] = {'collection_status': 'success'}
        return out

    # ------------------------------------------------------------------
    # 子采集器 3：/dev 设备节点权限（容器场景高频故障点）
    # ------------------------------------------------------------------
    def _collect_device_nodes(self) -> dict:
        out = {}
        if not os.path.isdir("/dev"):
            out["error"] = "/dev 不可访问"
            return {"device_nodes": out}
        try:
            import pwd  # 仅 Linux 可用
        except ImportError:
            pwd = None
        try:
            import grp
        except ImportError:
            grp = None

        names = sorted(
            n for n in os.listdir("/dev")
            if n.startswith("davinci") or n in self.REQUIRED_NODES
        )
        out["davinci_count"] = sum(
            1 for n in names
            if n.startswith("davinci") and n[len("davinci"):].isdigit()
        )
        nodes = []
        for name in names:
            path = os.path.join("/dev", name)
            try:
                st = os.stat(path)
                entry = {
                    "node": name,
                    "type": ("char" if stat.S_ISCHR(st.st_mode)
                             else "block" if stat.S_ISBLK(st.st_mode) else "other"),
                    "mode": format(stat.S_IMODE(st.st_mode), "04o"),
                    "uid": st.st_uid,
                    "gid": st.st_gid,
                }
                if pwd:
                    try:
                        entry["user"] = pwd.getpwuid(st.st_uid).pw_name
                    except KeyError:
                        pass
                if grp:
                    try:
                        entry["group"] = grp.getgrgid(st.st_gid).gr_name
                    except KeyError:
                        pass
                nodes.append(entry)
            except OSError as e:
                nodes.append({"node": name, "error": str(e)})
        out["nodes"] = nodes
        missing = [n for n in self.REQUIRED_NODES if n not in names]
        if missing:
            out["missing_required_nodes"] = missing
        return {"device_nodes": out}

    # ------------------------------------------------------------------
    # 子采集器 4：光模块收发状态（hccn_tool optical）
    # ------------------------------------------------------------------
    def _collect_optical(self) -> dict:
        out = {}
        if not which(HCCN_TOOL_CMD):
            place = "容器" if is_in_container() else "宿主机"
            out["note"] = f"{place}上没有找到 'hccn_tool' 命令"
            return {"optical": out}
        if self.npu_count <= 0:
            out["note"] = "未检测到 NPU 设备"
            return {"optical": out}
        devices = {}
        errors = []
        max_workers = min(self.npu_count, os.cpu_count() or 4)
        with ThreadPoolExecutor(max_workers) as executor:
            futures = {executor.submit(self._run_optical, i): i
                       for i in self.device_ids}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    devices[str(idx)] = future.result()
                except Exception as e:
                    errors.append(f"采集 NPU {idx} 光模块信息失败: {e}")
        out["devices"] = devices
        if errors:
            out["errors"] = errors
        return {"optical": out}

    @staticmethod
    def _run_optical(device_id: int) -> dict:
        rc, raw = run_cmd(f"{HCCN_TOOL_CMD} -i {device_id} -optical -g", timeout=20)
        res = {"rc": rc, "raw": raw if raw else None}
        if rc == 0 and raw:
            lanes, rx_vals, tx_vals = [], [], []
            for line in raw.splitlines():
                low = line.lower()
                if "power" not in low:
                    continue
                # 尽力提取 "RX Power : -2.5 dBm" / "TX power 0: 640.1 uW" 类数值
                m = re.search(r"(rx|tx)\s*power[^:]*:\s*(-?[\d.]+)\s*(dbm|uw)?", low)
                if m:
                    kind = m.group(1).upper()
                    val = float(m.group(2))
                    unit = (m.group(3) or "").lower()
                    lanes.append({"kind": kind, "value": val, "unit": unit or "raw"})
                    if unit == "dbm":
                        (rx_vals if kind == "RX" else tx_vals).append(val)
            if lanes:
                res["power_readings"] = lanes
            if rx_vals:
                res["rx_power_avg_dbm"] = round(sum(rx_vals) / len(rx_vals), 2)
            if tx_vals:
                res["tx_power_avg_dbm"] = round(sum(tx_vals) / len(tx_vals), 2)
        return res

    # ------------------------------------------------------------------
    # 子采集器 5：昇腾日志目录元信息（plog/slog 大小与最新时间）
    # ------------------------------------------------------------------
    def _collect_log_dirs(self) -> dict:
        out = {"dirs": []}
        candidates = [os.path.expanduser("~/ascend/log")]
        for cand in self.LOG_DIR_CANDIDATES:
            if cand not in candidates:
                candidates.append(cand)
        for base in candidates:
            if not os.path.isdir(base):
                continue
            entry = {"path": base, "subdirs": {}}
            try:
                for name in sorted(os.listdir(base)):
                    sub = os.path.join(base, name)
                    total, count, latest = 0, 0, 0.0
                    if os.path.isfile(sub):
                        files = [sub]
                    else:
                        files = []
                        for root, _dirs, fs in os.walk(sub):
                            files.extend(os.path.join(root, f) for f in fs)
                    for fp in files:
                        try:
                            st = os.stat(fp)
                        except OSError:
                            continue
                        total += st.st_size
                        count += 1
                        latest = max(latest, st.st_mtime)
                    entry["subdirs"][name] = {
                        "size_mb": round(total / 1048576, 1),
                        "file_count": count,
                        "latest_mtime": time.strftime(
                            "%Y-%m-%d %H:%M:%S", time.localtime(latest)
                        ) if latest else None,
                    }
            except OSError as e:
                entry["error"] = str(e)
            out["dirs"].append(entry)
        return {"log_dirs": out}

    # ------------------------------------------------------------------
    # 汇总入口：5 个子采集器并发执行（与 HardwareCollector 相同的线程池模式）
    # ------------------------------------------------------------------
    def collect(self) -> CollectorResult:
        sub_collectors = [
            ("smi", self._collect_smi),
            ("per_device", self._collect_per_device),
            ("device_nodes", self._collect_device_nodes),
            ("optical", self._collect_optical),
            ("log_dirs", self._collect_log_dirs),
        ]
        result = {}
        errors = []
        max_workers = min(len(sub_collectors), os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers) as executor:
            futures = {executor.submit(fn): name for name, fn in sub_collectors}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result.update(future.result())
                except Exception as e:
                    errors.append(f"采集 {name} 失败: {e}")
        # 顶层汇总字段：count / devices / firmware_version，方便 Agent 直接判断多卡一致性
        devices = result.get("devices") or []
        result["count"] = len(devices) if devices else self.npu_count
        if devices and isinstance(devices[0], dict) and devices[0].get("firmware_version"):
            result["firmware_version"] = devices[0]["firmware_version"]
        return CollectorResult(result, self.collect_type, errors)


class AscendCollector:
    """Ascend 组件版本采集器"""

    COMPONENTS = [
        ("driver", "", "", "/usr/local/Ascend/driver/version.info", ("version",), "", ""),
        ("toolkit", "ASCEND_TOOLKIT_HOME", "/usr/local/Ascend/ascend-toolkit/latest/",
         "toolkit/version.info", ("version", "version_dir"), "timestamp", ""),
        ("opp_kernel", "ASCEND_TOOLKIT_HOME", "/usr/local/Ascend/ascend-toolkit/latest/",
         "opp_kernel/version.info", ("version", "version_dir"), "timestamp", ""),
        ("mindstudio_toolkit", "ASCEND_TOOLKIT_HOME", "/usr/local/Ascend/ascend-toolkit/latest/",
         "mindstudio-toolkit/version.info", ("version",), "", ""),
        ("atb", "ATB_HOME_PATH",
         "/usr/local/Ascend/nnal/atb/latest/atb/cxx_abi_0",
         "../../version.info", ("ascend-cann-atb version",), "", "commit id"),
        ("mindie", "MINDIE_LLM_HOME_PATH",
         "/usr/local/Ascend/mindie/latest/mindie-llm",
         "../version.info", ("ascend-mindie",), "timestamp", ""),
        ("atb-models", "ATB_SPEED_HOME_PATH",
         "/usr/local/Ascend/atb-models",
         "version.info", ("atb-models version",), "time", "commit id"),
    ]

    def __init__(self):
        self.collect_type = "ascend"

    @staticmethod
    def _get_version_file(env_var, default_home, version_file):
        home = os.getenv(env_var) if env_var else ''
        base_path = home or default_home
        if version_file.startswith('/'):
            return os.path.normpath(version_file)
        return os.path.normpath(os.path.join(base_path, version_file))

    @staticmethod
    def _parse_version_file(file_path, ver_keys, ts_key, commit_key):
        result = {'source': file_path, 'collection_status': 'success'}
        if not os.path.isfile(file_path):
            return {'source': file_path, 'collection_status': 'unavailable',
                    'reason': 'version.info 不存在或不可访问；不能据此断言组件未安装'}
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split('=', 1) if '=' in line else line.split(':', 1)
                    if len(parts) != 2:
                        continue
                    key, value = parts[0].strip().lower(), parts[1].strip()
                    for ver_key in ver_keys:
                        if ver_key == key:
                            if 'version' not in result:
                                result['version'] = value
                            else:
                                result['version'] += f' ({value})'
                    if ts_key and ts_key == key:
                        result['timestamp'] = value
                    if commit_key and commit_key == key:
                        result['commit'] = value
        except Exception as exc:
            result.update(collection_status='failed', error=str(exc))
        if 'version' not in result and result['collection_status'] == 'success':
            result.update(collection_status='unavailable', reason='未解析到版本字段')
        return result

    def collect(self) -> CollectorResult:
        results = {}
        for name, env_var, default_home, version_file, ver_keys, ts_key, commit_key in self.COMPONENTS:
            file_path = self._get_version_file(env_var, default_home, version_file)
            results[name] = self._parse_version_file(file_path, ver_keys, ts_key, commit_key)
        return CollectorResult(results, self.collect_type)


class EnvCollector:
    """环境变量采集器 — 采集时对疑似敏感变量脱敏，避免密钥泄露进 dump 文件"""

    ENV_FILTERS = [
        "ASCEND", "MINDIE", "ATB_", "HCCL_", "MIES",
        "RANKTABLE", "GE_", "TORCH", "ACL_", "NPU_",
        "LCCL_", "LCAL_", "OPS", "INF_"
    ]

    # 疑似敏感变量的 key 匹配模式（值脱敏，key 名保留用于环境一致性比对）
    SENSITIVE_PATTERN = SENSITIVE_KEY
    MASKED_VALUE = "***MASKED***"

    CRITICAL_ENV = {
        'ASCEND_HOME_PATH', 'ASCEND_TOOLKIT_HOME', 'LD_LIBRARY_PATH',
        'MINDIE_LLM_HOME_PATH', 'ATB_HOME_PATH', 'ATB_SPEED_HOME_PATH',
        'HCCL_BUFFSIZE', 'TASK_QUEUE_ENABLE', 'RANK_TABLE_FILE',
        'OMP_NUM_THREADS', 'PYTORCH_NPU_ALLOC_CONF',
    }

    def __init__(self, filter_env: bool = False):
        self.collect_type = "env"
        self.filter_env = filter_env

    def collect(self) -> CollectorResult:
        env_items = dict(os.environ)
        if self.filter_env:
            env_items = {
                k: v for k, v in env_items.items()
                if k in self.CRITICAL_ENV or any(f in k for f in self.ENV_FILTERS)
            }

        # 敏感变量脱敏
        masked_keys = sorted(k for k in env_items if self.SENSITIVE_PATTERN.search(k))
        for k in masked_keys:
            env_items[k] = self.MASKED_VALUE
        if masked_keys:
            preview = ", ".join(masked_keys[:10]) + ("..." if len(masked_keys) > 10 else "")
            env_items["__masking_warning__"] = (
                f"{len(masked_keys)} 个疑似敏感环境变量已脱敏为 {self.MASKED_VALUE}"
                f"（key 名保留用于一致性比对）: {preview}"
            )

        return CollectorResult(env_items, self.collect_type)


class ConfigCollector:
    """JSON 配置文件采集器"""

    def __init__(self, config_path: str, collect_type: str = "config"):
        self.config_path = config_path
        self.collect_type = collect_type

    def collect(self) -> CollectorResult:
        errors = []
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return CollectorResult(redact_sensitive(data), self.collect_type)
        except FileNotFoundError:
            errors.append(f"配置文件不存在: {self.config_path!r}")
        except json.JSONDecodeError as e:
            errors.append(f"配置文件 JSON 解析失败: {self.config_path!r}: {e}")
        except Exception as e:
            errors.append(f"读取配置文件失败: {self.config_path!r}: {e}")
        return CollectorResult({}, self.collect_type, errors)


class PingCollector:
    """网络连通性采集器 — ping rank table 中的所有主机"""

    def __init__(self, rank_table: RankTable):
        self.collect_type = "ping"
        self.rank_table = rank_table

    def collect(self) -> CollectorResult:
        result = {}
        errors = []

        if not which("/usr/bin/ping"):
            errors.append("当前环境没有 'ping' 命令")
            return CollectorResult(result, self.collect_type, errors)

        host_to_devices = self.rank_table.host_to_devices
        if not host_to_devices:
            errors.append("rank table 没有解析出任何主机信息")
            return CollectorResult(result, self.collect_type, errors)

        def ping_one(host):
            try:
                output = checked_output(shlex.split(f"/usr/bin/ping -c 3 -q -W 2 {host}"), timeout=10)
            except Exception:
                output = "ping failed"
            return str(host), output

        # 并发 ping，避免主机较多时串行执行过慢
        max_workers = min(len(host_to_devices), (os.cpu_count() or 4) * 2) or 1
        with ThreadPoolExecutor(max_workers) as executor:
            futures = [executor.submit(ping_one, host) for host in host_to_devices]
            for future in as_completed(futures):
                host, output = future.result()
                result[host] = output

        return CollectorResult(result, self.collect_type, errors)


class HCCNCollector:
    """hccn_tool 命令采集器基类 — 采集 Link/VNIC/TLS 状态"""

    def __init__(self, cmd_name: str, collect_type: str):
        self.cmd_name = cmd_name
        self.collect_type = collect_type
        self.device_ids = get_npu_device_ids()
        self.npu_count = len(self.device_ids)

    def _run_cmd(self, device_id: int) -> str:
        cmd = f"{HCCN_TOOL_CMD} -i {device_id} -{self.cmd_name} -g"
        try:
            return checked_output(shlex.split(cmd))
        except subprocess.CalledProcessError as exc:
            return "command failed: " + str(redact_sensitive(exc.output))

    def collect(self) -> CollectorResult:
        errors = []
        if not which(HCCN_TOOL_CMD):
            place = "容器" if is_in_container() else "宿主机"
            errors.append(f"{place}上没有找到 'hccn_tool' 命令")
            return CollectorResult([], self.collect_type, errors)

        if not self.device_ids:
            return CollectorResult([] if self.collect_type in ('link', 'vnic', 'tls') else {},
                                   self.collect_type, ['未检测到可访问的 NPU 设备'])
        max_workers = min(self.npu_count, os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers) as executor:
            futures = [executor.submit(self._run_cmd, i) for i in self.device_ids]
            results = [f.result() for f in futures]

        return CollectorResult(results, self.collect_type)


class HCCLCollector:
    """HCCL 通信连通性采集器 — NPU 间 HCCS ping"""

    def __init__(self, rank_table: RankTable):
        self.collect_type = "hccl"
        self.rank_table = rank_table
        self.device_ids = get_npu_device_ids()
        self.npu_count = len(self.device_ids)
        self.option = (
            "-hccs_ping" if rank_table.version >= SimpleVersion("1.2") else "-ping"
        )

    def _run_cmd(self, device_id, device_ip):
        if device_ip.version == 4:
            cmd = f"{HCCN_TOOL_CMD} -i {device_id} {self.option} -g address {device_ip}"
        elif device_ip.version == 6:
            cmd = f"{HCCN_TOOL_CMD} -i {device_id} {self.option} -inet6 -g ipv6_address {device_ip}"
        else:
            return None, None

        ret, output = run_cmd(shlex.split(cmd))
        return cmd, (ret, output)

    def collect(self) -> CollectorResult:
        errors = []
        if not which(HCCN_TOOL_CMD):
            place = "容器" if is_in_container() else "宿主机"
            errors.append(f"{place}上没有找到 'hccn_tool' 命令")
            return CollectorResult({}, self.collect_type, errors)

        all_device_ips = [
            dev_info.device_ip
            for dev_list in self.rank_table.host_to_devices.values()
            for dev_info in dev_list
        ]

        if not self.device_ids:
            return CollectorResult([] if self.collect_type in ('link', 'vnic', 'tls') else {},
                                   self.collect_type, ['未检测到可访问的 NPU 设备'])
        max_workers = min(self.npu_count, os.cpu_count() or 1)
        results = {}

        with ThreadPoolExecutor(max_workers) as executor:
            futures = [
                executor.submit(self._run_per_device, device_id, all_device_ips)
                for device_id in self.device_ids
            ]
            for future in as_completed(futures):
                results.update(future.result())

        return CollectorResult(results, self.collect_type)

    def _run_per_device(self, device_id, device_ips):
        result = {}
        for device_ip in device_ips:
            cmd, ret_output = self._run_cmd(device_id, device_ip)
            if cmd:
                result[cmd] = list(ret_output) if ret_output else [None, None]
        return result


class NetworkCollector:
    """网络环境采集器 — 网卡状态/路由/RDMA RoCE/监听端口与秩间业务端口连通性"""

    PROBE_TIMEOUT = 2.0
    MAX_PEER_PROBE_PORTS = 8

    def __init__(self, rank_table: "RankTable" = None):
        self.collect_type = "network"
        self.rank_table = rank_table

    def collect(self) -> CollectorResult:
        sub_collectors = [
            ("nics", self._collect_nics),
            ("routes", self._collect_routes),
            ("rdma", self._collect_rdma),
            ("listen_ports", self._collect_listen_ports),
            ("peer_ports", self._collect_peer_ports),
        ]
        result = {}
        errors = []
        max_workers = min(len(sub_collectors), os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers) as executor:
            futures = {executor.submit(fn): name for name, fn in sub_collectors}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result.update(future.result())
                except Exception as e:
                    errors.append(f"采集 {name} 失败: {e}")

        # MTU 一致性结构化判断（排除 lo）
        nics = result.get("nics") or []
        mtus = {
            n.get("mtu") for n in nics
            if isinstance(n, dict) and n.get("mtu") and n.get("name") != "lo"
        }
        result["mtu_consistent"] = len(mtus) <= 1
        if len(mtus) > 1:
            result["mtu_values"] = sorted(mtus)
        return CollectorResult(result, self.collect_type, errors)

    # ---------- 工具方法 ----------

    @staticmethod
    def _read_sys(path):
        try:
            with open(path, "r", errors="replace") as f:
                return f.read().strip()
        except (OSError, ValueError):
            return None

    @staticmethod
    def _resolve_driver(base):
        driver_link = os.path.join(base, "device", "driver")
        if os.path.islink(driver_link):
            try:
                return os.path.basename(os.readlink(driver_link))
            except OSError:
                return None
        return None

    @staticmethod
    def _parse_proc_net(path, results):
        """解析 /proc/net/tcp(6)，收集 LISTEN 状态（0A）端口"""
        try:
            with open(path, "r", errors="replace") as f:
                lines = f.readlines()[1:]
        except OSError:
            return
        for line in lines:
            fields = line.split()
            if len(fields) < 4:
                continue
            local, tcp_state = fields[1], fields[3]
            if tcp_state != "0A":
                continue
            addr_part = local.split(":")
            if len(addr_part) != 2:
                continue
            try:
                port = int(addr_part[-1], 16)
            except ValueError:
                continue
            if port not in results:
                results.append(port)

    def _probe_port(self, host, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.PROBE_TIMEOUT)
        try:
            sock.connect((host, port))
            return "open"
        except socket.timeout:
            return "filtered"
        except ConnectionRefusedError:
            return "refused"
        except OSError:
            return "unreachable"
        finally:
            sock.close()

    # ---------- 子采集器 ----------

    def _collect_nics(self):
        net_dir = "/sys/class/net"
        if not os.path.isdir(net_dir):
            return {"nics": [], "error": "未找到 /sys/class/net"}
        try:
            ifaces = sorted(os.listdir(net_dir))
        except OSError as e:
            return {"nics": [], "error": str(e)}

        nics = []
        for iface in ifaces:
            base = os.path.join(net_dir, iface)
            info = {"name": iface}
            mtu = self._read_sys(os.path.join(base, "mtu"))
            if mtu and mtu.isdigit():
                info["mtu"] = int(mtu)
            speed = self._read_sys(os.path.join(base, "speed"))
            if speed and speed.isdigit():
                info["speed_mbps"] = int(speed)
            duplex = self._read_sys(os.path.join(base, "duplex"))
            if duplex:
                info["duplex"] = duplex
            operstate = self._read_sys(os.path.join(base, "operstate"))
            if operstate:
                info["operstate"] = operstate
            mac = self._read_sys(os.path.join(base, "address"))
            if mac:
                info["mac"] = mac
            driver = self._resolve_driver(base)
            if driver:
                info["driver"] = driver
            # bond 归属判断
            if os.path.isdir(os.path.join(base, "bonding")):
                info["type"] = "bond"
                members = []
                for other in ifaces:
                    master_link = os.path.join(net_dir, other, "master")
                    if os.path.islink(master_link):
                        try:
                            if os.path.basename(os.readlink(master_link)) == iface:
                                members.append(other)
                        except OSError:
                            pass
                info["members"] = members
            elif os.path.islink(os.path.join(base, "master")):
                info["type"] = "bond_member"
            nics.append(info)

        result = {"nics": nics}
        rc, out = run_cmd("ip -br addr")
        if rc == 0 and out:
            result["addr_raw"] = out.splitlines()
        return result

    def _collect_routes(self):
        result = {}
        rc, out = run_cmd("ip route")
        if rc == 0 and out:
            result["route_raw"] = out.splitlines()
            for line in out.splitlines():
                if line.startswith("default"):
                    result["default_gateway"] = line
                    break
        rc, out = run_cmd("ip -6 route")
        if rc == 0 and out:
            result["route6_raw"] = out.splitlines()
        return result

    def _collect_rdma(self):
        result = {"devices": []}
        rdma_cls = "/sys/class/infiniband"
        if os.path.isdir(rdma_cls):
            try:
                devices = sorted(os.listdir(rdma_cls))
            except OSError as e:
                return {"devices": [], "error": str(e)}
            for dev in devices:
                dev_info = {"name": dev}
                ports_dir = os.path.join(rdma_cls, dev, "ports")
                if os.path.isdir(ports_dir):
                    ports = {}
                    for port in sorted(
                        os.listdir(ports_dir),
                        key=lambda p: int(p) if p.isdigit() else 0
                    ):
                        pbase = os.path.join(ports_dir, port)
                        port_info = {}
                        state = self._read_sys(os.path.join(pbase, "state"))
                        if state and ":" in state:
                            port_info["state"] = state.split(":")[-1].strip()
                        rate = self._read_sys(os.path.join(pbase, "rate"))
                        if rate:
                            port_info["rate"] = rate
                        gids = []
                        gid_dir = os.path.join(pbase, "gids")
                        if os.path.isdir(gid_dir):
                            for gid_file in sorted(os.listdir(gid_dir)):
                                val = self._read_sys(os.path.join(gid_dir, gid_file))
                                if val:
                                    gids.append(val)
                        port_info["gids"] = gids
                        ports[port] = port_info
                    dev_info["ports"] = ports
                result["devices"].append(dev_info)
        else:
            result["note"] = "未发现 /sys/class/infiniband（RoCE/RDMA 未启用或驱动未加载）"
        rc, out = run_cmd("ibv_devinfo")
        if rc == 0 and out:
            result["ibv_devinfo_raw"] = out.splitlines()
        return result

    def _collect_listen_ports(self):
        ports = []
        self._parse_proc_net("/proc/net/tcp", ports)
        self._parse_proc_net("/proc/net/tcp6", ports)
        ports.sort()
        result = {"tcp_listen": ports}
        rc, out = run_cmd("ss -tlnp")
        if rc == 0 and out:
            result["ss_raw"] = out.splitlines()
        return result

    def _collect_peer_ports(self):
        """秩间业务端口连通性：对本机监听的业务端口（>=1024）
        逐一探测 rank table 中各主机的连通性（ICMP 通不代表业务端口通）"""
        host_to_devices = {}
        if self.rank_table is not None:
            host_to_devices = getattr(self.rank_table, "host_to_devices", {}) or {}
        if not host_to_devices:
            return {"peers": {}, "note": "无 rank table，跳过秩间端口探测"}

        listen_ports = []
        self._parse_proc_net("/proc/net/tcp", listen_ports)
        self._parse_proc_net("/proc/net/tcp6", listen_ports)
        biz_ports = [p for p in sorted(set(listen_ports)) if p >= 1024]
        if not biz_ports:
            return {"peers": {}, "note": "本机未发现 >=1024 的监听端口，跳过秩间端口探测"}
        biz_ports = biz_ports[: self.MAX_PEER_PROBE_PORTS]

        tasks = [(str(host), port) for host in host_to_devices for port in biz_ports]
        peers = {}
        max_workers = min(len(tasks), (os.cpu_count() or 4) * 2) or 1
        with ThreadPoolExecutor(max_workers) as executor:
            futures = {executor.submit(self._probe_port, h, p): (h, p) for h, p in tasks}
            for future in as_completed(futures):
                h, p = futures[future]
                peers[f"{h}:{p}"] = future.result()

        anomalies = {k: v for k, v in peers.items() if v != "open"}
        result = {"peers": peers, "probe_ports": biz_ports, "anomalies": anomalies}
        if anomalies:
            result["note"] = "refused 多为服务未在该节点部署，filtered/unreachable 需排查防火墙或路由"
        return result


class RuntimeCollector:
    """软件运行时采集器 — Python 包/推理进程/容器与 cgroup"""

    WATCHED_PACKAGES = (
        "torch", "torch-npu", "vllm", "vllm-ascend", "transformers",
        "mindspore", "mindie", "numpy", "triton", "onnx", "onnxruntime",
    )
    TARGET_PROCESS_KEYWORDS = ("mindie", "vllm", "torchrun", "python")
    MAX_TARGET_PROCESSES = 40

    def __init__(self):
        self.collect_type = "runtime"

    def collect(self) -> CollectorResult:
        sub_collectors = [
            ("python", self._collect_python),
            ("packages", self._collect_packages),
            ("processes", self._collect_processes),
            ("container", self._collect_container),
        ]
        result = {}
        errors = []
        max_workers = min(len(sub_collectors), os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers) as executor:
            futures = {executor.submit(fn): name for name, fn in sub_collectors}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result.update(future.result())
                except Exception as e:
                    errors.append(f"采集 {name} 失败: {e}")
        return CollectorResult(result, self.collect_type, errors)

    # ---------- 工具方法 ----------

    @staticmethod
    def _read_file(path):
        try:
            with open(path, "r", errors="replace") as f:
                return f.read().strip()
        except OSError:
            return None

    def _read_proc_cmdline(self, pid):
        content = self._read_file(f"/proc/{pid}/cmdline")
        if not content:
            return []
        return [part for part in content.split("\0") if part]

    def _read_proc_status(self, pid):
        content = self._read_file(f"/proc/{pid}/status")
        if not content:
            return {}
        status = {}
        for line in content.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            value = value.strip()
            status[key.strip()] = int(value) if value.isdigit() else value
        return status

    # ---------- 子采集器 ----------

    def _collect_python(self):
        result = {
            "python_version": platform.python_version(),
            "python_executable": sys.executable,
        }
        rc, out = run_cmd([sys.executable, '-m', 'pip', '--version'], timeout=20)
        if rc == 0 and out:
            result["pip"] = out.strip()
        conda_env = os.environ.get("CONDA_DEFAULT_ENV")
        if conda_env:
            result["conda_env"] = conda_env
        virtual_env = os.environ.get("VIRTUAL_ENV")
        if virtual_env:
            result["virtual_env"] = virtual_env
        return result

    def _collect_packages(self):
        """pip 包版本：环境比对的核心差异源（torch/torch_npu/vllm/transformers 等）"""
        result = {"watched": {}}
        watched_norm = {p.lower().replace("-", "_") for p in self.WATCHED_PACKAGES}
        try:
            import importlib.metadata as importlib_metadata
            for dist in importlib_metadata.distributions():
                name = (dist.metadata.get("Name") or "").lower().replace("-", "_")
                if name in watched_norm:
                    result["watched"][name] = dist.version
        except Exception as e:
            result["watched_error"] = str(e)
        rc, out = run_cmd([sys.executable, '-m', 'pip', 'list', '--format=freeze'], timeout=60)
        if rc == 0 and out:
            result["pip_list_raw"] = out.splitlines()
        return result

    def _collect_processes(self):
        """运行进程快照：识别 mindie/vllm/torchrun/python 及其启动参数与 CPU 亲和性"""
        result = {"targets": [], "total": 0}
        pids = []
        try:
            for entry in os.listdir("/proc"):
                if entry.isdigit():
                    pids.append(int(entry))
        except OSError:
            pass
        result["total"] = len(pids)

        targets = []
        for pid in pids:
            if pid == os.getpid():
                continue  # 排除采集器自身
            cmdline = self._read_proc_cmdline(pid)
            if not cmdline:
                continue
            cmd_join = " ".join(cmdline)
            low = cmd_join.lower()
            if not any(k in low for k in self.TARGET_PROCESS_KEYWORDS):
                continue
            info = {"pid": pid, "executable": os.path.basename(cmdline[0]),
                    "cmd": MASKED_VALUE + " (process arguments omitted)"}
            status = self._read_proc_status(pid)
            if status:
                if isinstance(status.get("PPid"), int):
                    info["ppid"] = status["PPid"]
                if isinstance(status.get("Threads"), int):
                    info["threads"] = status["Threads"]
                allowed = status.get("Cpus_allowed_list")
                if allowed:
                    info["cpu_affinity"] = allowed
            targets.append(info)
        targets.sort(key=lambda t: t.get("pid", 0))
        result["targets"] = targets[: self.MAX_TARGET_PROCESSES]

        rc, out = run_cmd("ps -eo pid,ppid,psr,pcpu,pmem,nlwp,comm --sort=-pcpu")
        if rc == 0 and out:
            result["ps_raw"] = out.splitlines()[:200]
        return result

    def _collect_container(self):
        """容器环境：cgroup 版本/cpuset/内存限制、NPU 设备透传、挂载点"""
        result = {"in_container": is_in_container()}
        content = self._read_file("/proc/self/cgroup")
        if content:
            result["cgroup_raw"] = content.splitlines()
            m = re.search(r"[0-9a-f]{64}", content)
            if m:
                result["container_id"] = m.group(0)[:12]
        if os.path.exists("/sys/fs/cgroup/cgroup.controllers"):
            result["cgroup_version"] = 2
        elif os.path.exists("/sys/fs/cgroup/cpuset"):
            result["cgroup_version"] = 1

        cpuset = self._read_file("/sys/fs/cgroup/cpuset.cpus.effective")
        if cpuset is None:
            cpuset = self._read_file("/sys/fs/cgroup/cpuset/cpuset.effective_cpus")
        if cpuset:
            result["cpuset_cpus"] = cpuset
        mem_limit = self._read_file("/sys/fs/cgroup/memory.max")
        if mem_limit is None:
            mem_limit = self._read_file("/sys/fs/cgroup/memory/memory.limit_in_bytes")
        if mem_limit:
            result["memory_limit"] = mem_limit

        npu_devs = set()
        try:
            for name in os.listdir("/dev"):
                if name.startswith("davinci") or name in (
                    "davinci_manager", "devmm_svm", "hisi_hdc"
                ):
                    npu_devs.add(name)
        except OSError:
            pass
        result["npu_devices_in_dev"] = sorted(npu_devs)

        mounts_content = self._read_file("/proc/self/mounts")
        if mounts_content:
            interesting = [
                line for line in mounts_content.splitlines()
                if "overlay" in line or "davinci" in line or "ascend" in line.lower()
            ]
            if interesting:
                result["mounts_filtered"] = interesting
        result["note"] = "镜像 ID 需在宿主机执行 docker inspect 获取"
        return result


class WeightCollector:
    """权重文件 SHA256 哈希采集器"""

    TENSOR_SUFFIX = '.safetensors'
    TENSOR_ID_PATTERN = re.compile(r'(\d{5})-of-\d{5}' + re.escape(TENSOR_SUFFIX))

    def __init__(self, weight_dir: str, chunk_size: int = 32 * 1024 * 1024):
        self.collect_type = "weight"
        self.weight_dir = weight_dir
        self.chunk_size = chunk_size

    @staticmethod
    def _calculate_sha256(filepath, chunk_size):
        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            while True:
                data = f.read(chunk_size)
                if not data:
                    break
                sha256.update(data)
        return sha256.hexdigest()

    def _get_tensor_files(self):
        tensor_files = []
        for root, dirs, files in os.walk(self.weight_dir):
            for filename in files:
                filepath = os.path.join(root, filename)
                if os.path.isfile(filepath) and filename.endswith(self.TENSOR_SUFFIX):
                    if not os.path.islink(filepath):
                        tensor_files.append(filepath)
        return tensor_files

    def collect(self) -> CollectorResult:
        errors = []
        if not self.weight_dir or not os.path.isdir(self.weight_dir):
            errors.append(f"权重目录不存在: {self.weight_dir!r}")
            return CollectorResult({}, self.collect_type, errors)

        tensor_files = self._get_tensor_files()
        if not tensor_files:
            errors.append(f"权重目录下没有找到 {self.TENSOR_SUFFIX!r} 文件")
            return CollectorResult({}, self.collect_type, errors)

        max_workers = min(len(tensor_files), os.cpu_count() or 1)
        results = {}

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._calculate_sha256, tf, self.chunk_size): tf
                for tf in tensor_files
            }
            for future in as_completed(futures):
                tf = futures[future]
                basename = os.path.basename(tf)
                m = self.TENSOR_ID_PATTERN.search(basename)
                tensor_id = m.group(1) if m else basename
                try:
                    results[tensor_id] = future.result()
                except Exception as e:
                    results[tensor_id] = f"error: {e}"

        return CollectorResult(results, self.collect_type)


# ============================================================================
# 主采集逻辑
# ============================================================================

def collect_all(args) -> dict:
    """执行所有采集器，返回完整的 dump 字典"""
    dump_content = {}
    collection = {}
    all_secrets = sensitive_values(dict(os.environ))
    with COMMAND_FAILURE_LOCK:
        COMMAND_FAILURES.clear()

    def _run_collector(collector):
        """运行单个采集器并处理结果"""
        begin = len(COMMAND_FAILURES)
        name = collector.collect_type
        try:
            result = collector.collect()
        except Exception as exc:
            errors = [str(exc)]
            result = CollectorResult({}, name, errors)
        failures = list(COMMAND_FAILURES[begin:])
        errors = list(result.errors)

        def read_errors(value, path=''):
            if isinstance(value, dict):
                for key, item in value.items():
                    child = f'{path}/{key}'
                    if key in ('error', 'errors') and item:
                        errors.append(f'{child}: {item}')
                    elif key == 'collection_status' and item != 'success':
                        errors.append(f'{path}: {item}')
                    else:
                        read_errors(item, child)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    read_errors(item, f'{path}/{index}')

        read_errors(result.data)
        status = 'partial' if errors or failures else 'success'
        if not result.data and (errors or failures):
            status = 'failed'
        collection[name] = {'status': status, 'errors': errors,
                            'command_failures': failures}
        if name == 'env':
            collection[name]['scope'] = 'filtered' if args.filter else 'all'
            collection[name]['included_keys'] = sorted(result.data)
            collection[name]['critical_keys_in_scope'] = sorted(EnvCollector.CRITICAL_ENV)
        if name in ('npu', 'link', 'vnic', 'tls', 'hccl'):
            collection[name]['device_ids'] = list(getattr(collector, 'device_ids', []))
        for err in errors:
            warn('[{}] {}', name, redact_sensitive(err, all_secrets))
        if status != 'failed':
            all_secrets.update(sensitive_values(result.data))
            dump_content[name] = result.data

    # --- 始终采集的核心信息 ---
    info("{Color.BOLD}=== 开始采集环境信息 ==={Color.RESET}".format(Color=Color))

    info("采集系统信息...")
    _run_collector(SysCollector())

    info("采集硬件资源（CPU/内存/NUMA/PCIe/磁盘/内核参数）...")
    _run_collector(HardwareCollector())

    info("采集 NPU 运行态（健康状态/温度/功耗/占用/设备节点）...")
    _run_collector(NPUCollector())

    info("采集 Ascend 组件版本...")
    _run_collector(AscendCollector())

    info("采集环境变量...")
    _run_collector(EnvCollector(filter_env=args.filter))

    info("采集软件运行时（Python 包/推理进程/容器）...")
    _run_collector(RuntimeCollector())

    # --- 预解析 rank table（供 Ping/HCCL/Network 采集器复用） ---
    rank_table = None
    rank_error = None
    if args.rank_table_path:
        info("解析 rank table: {}", args.rank_table_path)
        try:
            rank_table = parse_rank_table(args.rank_table_path, args.scene or "mindie")
        except Exception as e:
            rank_error = str(e)
            warn("rank table 解析失败: {}", redact_sensitive(str(e), all_secrets))

    info("采集网络细节（网卡/路由/RDMA/端口连通性）...")
    _run_collector(NetworkCollector(rank_table=rank_table))

    # --- 可选：配置文件 ---
    if args.mies_config_path:
        info("采集 MindIE 服务配置: {}", args.mies_config_path)
        _run_collector(ConfigCollector(args.mies_config_path, "mies config"))

    if args.user_config_path:
        info("采集 user_config: {}", args.user_config_path)
        _run_collector(ConfigCollector(args.user_config_path, "user config"))

    if args.mindie_env_path:
        info("采集 mindie_env: {}", args.mindie_env_path)
        _run_collector(ConfigCollector(args.mindie_env_path, "mindie env"))

    # --- 可选：权重目录 ---
    if args.weight_dir:
        info("采集模型权重配置和哈希...")
        model_config_path = os.path.join(args.weight_dir, "config.json")
        _run_collector(ConfigCollector(model_config_path, "model config"))

        chunk_size = args.chunk_size * 1024 * 1024
        _run_collector(WeightCollector(args.weight_dir, chunk_size))

    # --- 可选：Ping/HCCL/HCCN（需要 rank table） ---
    if rank_table:
        info("采集 Ping 连通性...")
        _run_collector(PingCollector(rank_table))

        info("采集 HCCL 通信状态...")
        _run_collector(HCCLCollector(rank_table))

        info("采集 Link 状态...")
        _run_collector(HCCNCollector("link", "link"))

        info("采集 VNIC 状态...")
        _run_collector(HCCNCollector("vnic", "vnic"))

        info("采集 TLS 状态...")
        _run_collector(HCCNCollector("tls", "tls"))

    optional = {
        'mies config': args.mies_config_path,
        'user config': args.user_config_path,
        'mindie env': args.mindie_env_path,
        'model config': args.weight_dir,
        'weight': args.weight_dir,
    }
    for name, requested in optional.items():
        if name not in collection:
            collection[name] = {'status': 'skipped', 'reason': '未提供对应采集参数', 'errors': []}
    for name in ('ping', 'hccl', 'link', 'vnic', 'tls'):
        if name not in collection:
            collection[name] = {'status': 'failed' if rank_error else 'skipped',
                                'reason': 'rank table 解析失败' if rank_error else '未提供 rank table',
                                'errors': [rank_error] if rank_error else []}
    dump_content['_meta'] = {
        'schema_version': '1.1',
        'collection': collection,
        'status': 'partial' if any(v['status'] in ('failed', 'partial') for v in collection.values()) else 'success',
        'redaction': {'enabled': True, 'process_arguments': 'omitted',
                      'note': '敏感字段、已知密钥副本与常见文本模式已脱敏；任意 raw 文本仍需分享前复核。'},
    }
    return redact_sensitive(dump_content, all_secrets)


# ============================================================================
# 命令行入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="独立环境信息采集脚本 — 从 msprechecker 提取的 dump 功能",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  %(prog)s                                              # 采集默认信息
  %(prog)s -o /tmp/snapshot.json                        # 指定输出路径
  %(prog)s --filter                                     # 仅采集昇腾相关环境变量
  %(prog)s --mies-config-path /path/to/config.json      # 额外采集 MindIE 配置
  %(prog)s --rank-table-path rank_table.json --scene mindie  # 采集网络与 HCCL
  %(prog)s --weight-dir /path/to/weights --chunk-size 64     # 采集权重哈希
""",
    )

    parser.add_argument(
        "-o", "--output-path",
        default="./msprechecker_dumped.json",
        help="输出文件路径 (JSON 格式)。默认: ./msprechecker_dumped.json"
    )
    parser.add_argument(
        "--filter",
        action="store_true",
        help="仅采集昇腾相关的环境变量 (ASCEND/MINDIE/ATB_/HCCL_ 等)"
    )
    parser.add_argument("--mies-config-path", help="MindIE 服务 config.json 路径")
    parser.add_argument("--user-config-path", help="user_config.json 路径")
    parser.add_argument("--mindie-env-path", help="mindie_env.json 路径")
    parser.add_argument("--rank-table-path", help="rank table 文件路径")
    parser.add_argument(
        "--scene",
        help="部署场景，如 'mindie' 或 'vllm'。用于确定 rank table 的解析格式"
    )
    parser.add_argument("--weight-dir", help="模型权重目录路径")
    parser.add_argument(
        "--chunk-size",
        choices=[32, 64, 128, 256], type=int, default=32,
        help="计算权重 SHA256 时的块大小 (MB)。默认: 32"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    start_time = time.time()

    dump_content = collect_all(args)

    # 添加元数据
    dump_content.setdefault("_meta", {}).update({
        "tool": "msprechecker_dump.py",
        "version": __version__,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "hostname": platform.node(),
        "python_version": platform.python_version(),
        "collect_duration_seconds": round(time.time() - start_time, 2),
    })

    # 保存
    output_dir = os.path.dirname(os.path.abspath(args.output_path))
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output_path, 'w', encoding='utf-8') as f:
        json.dump(dump_content, f, indent=4, ensure_ascii=False)

    duration = round(time.time() - start_time, 2)
    info("{Color.BOLD}=== 采集完成 ==={Color.RESET}".format(Color=Color))
    info("采集项目: {}", len(dump_content) - 1)  # 减去 _meta
    info("耗时: {} 秒", duration)
    info("已保存至: {}", args.output_path)
    info("提示: 可使用 'msprechecker compare' 比较多个 dump 文件的差异")


if __name__ == "__main__":
    main()
