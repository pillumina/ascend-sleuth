#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compare_dumps.py — Ascend 环境 dump JSON 比对工具

支持比对 2 个或多个 dump JSON 文件，输出差异报告（HTML / JSON / 终端文本）。

设计要点（保证对不同 JSON 结构的鲁棒性）：
1. 递归扁平化：将任意嵌套的 dict/list/scalar 展平为 path->value，不依赖固定 schema
2. section 感知：按顶层 key 分组差异，即使某个 section 在一侧不存在也能处理
3. 智能截断：输出时截断超长值（如 LS_COLORS），但 JSON 输出保留完整值
4. 多文件支持：支持 2+ 文件，每个 path 收集所有文件中的值
5. 容错：单个文件解析失败不影响其他文件
6. 分类：自动将差异分类为 system / ascend / env / config / network / weight / other

用法:
    python3 compare_dumps.py file1.json file2.json
    python3 compare_dumps.py file1.json file2.json file3.json --html report.html
    python3 compare_dumps.py file1.json file2.json --json diff.json
    python3 compare_dumps.py file1.json file2.json --text
"""

import os
import sys
import json
import argparse
import re
from html import escape
from collections import defaultdict, OrderedDict
from datetime import datetime

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
# 颜色
# ============================================================================
class C:
    R = "\033[91m"
    Y = "\033[93m"
    G = "\033[92m"
    B = "\033[96m"
    D = "\033[90m"
    BOLD = "\033[1m"
    RST = "\033[0m"

def pinfo(msg):
    print(f"{C.G}[INFO]{C.RST} {msg}")

def pwarn(msg):
    print(f"{C.Y}[WARN]{C.RST} {msg}", file=sys.stderr)

# ============================================================================
# 扁平化
# ============================================================================

MISSING = object()


def top_section(path):
    """Decode the first typed bracket segment without splitting literal keys."""
    if path == '$':
        return ''
    return str(json.JSONDecoder().raw_decode(path[2:])[0])


def path_keys(path):
    """Decode typed path segments, keeping array indices distinct from field names."""
    keys = []
    index = 1
    decoder = json.JSONDecoder()
    while index < len(path):
        if path[index] != '[':
            raise ValueError('invalid typed path')
        key, end = decoder.raw_decode(path, index + 1)
        if end >= len(path) or path[end] != ']':
            raise ValueError('invalid typed path')
        if isinstance(key, str):
            keys.append(key)
        index = end + 1
    return keys


def redact_comparison(result, secrets=None):
    """Redact payload values without treating file IDs or statistic keys as data fields."""
    safe = dict(result)
    safe['meta'] = {label: redact_sensitive(meta, secrets) for label, meta in result['meta'].items()}
    safe['skipped_files'] = redact_sensitive(result.get('skipped_files', []), secrets)

    def values_for(path, values):
        keys = path_keys(path)
        private = any(SENSITIVE_KEY.search(key) for key in keys)
        process_args = any(key in ('cmd', 'cmdline', 'ps_raw') for key in keys)
        return {label: (value if value is MISSING else
                        MASKED_VALUE if private or process_args else
                        redact_sensitive(value, secrets)) for label, value in values.items()}

    safe['all_diffs'] = {path: values_for(path, values) for path, values in result.get('all_diffs', {}).items()}
    safe['diffs'] = {}
    for category, group in result['diffs'].items():
        safe['diffs'][category] = {}
        for kind, items in group.items():
            safe['diffs'][category][kind] = [dict(item, values=values_for(item['path'], item['values'])) for item in items]
    return safe


def flatten(data, prefix="$", sep=None):
    """
    递归扁平化任意 JSON 结构为 {path: value} 字典。
    dict 用 ["JSON escaped key"]，list 用 [index]，根为 $。
    叶子节点（str/int/bool/None）直接作为值。
    空字典 {} 和空列表 [] 保留原类型，不与字符串混淆。
    """
    result = {}

    if isinstance(data, dict):
        if not data:
            result[prefix] = {}
        else:
            for k, v in data.items():
                path = f"{prefix}[{json.dumps(k, ensure_ascii=False)}]"
                result.update(flatten(v, path))
    elif isinstance(data, list):
        if not data:
            result[prefix] = []
        else:
            for i, v in enumerate(data):
                path = f"{prefix}[{i}]"
                result.update(flatten(v, path))
    else:
        result[prefix] = data

    return result


def truncate(value, max_len=120):
    """截断超长值用于显示"""
    if value is MISSING:
        return "<missing>"
    if value is None:
        return "null"
    s = str(value)
    if len(s) > max_len:
        return s[:max_len] + f"... ({len(s)} chars)"
    return s


def value_repr(value):
    """获取值的可比较表示"""
    if value is MISSING:
        return ('missing', '')
    return (type(value).__name__, json.dumps(value, sort_keys=True, ensure_ascii=False))


# ============================================================================
# 比对引擎
# ============================================================================

class DumpComparator:
    """比对多个 dump JSON 文件"""

    # 顶层 section 分类
    SECTION_CATEGORIES = {
        "system": "system",
        "hardware": "hardware",
        "ascend": "ascend",
        "npu": "npu",
        "runtime": "runtime",
        "network": "network",
        "env": "env",
        "mies config": "config",
        "user config": "config",
        "mindie env": "config",
        "model config": "config",
        "weight": "weight",
        "ping": "network",
        "hccl": "network",
        "link": "network",
        "vnic": "network",
        "tls": "network",
        "_meta": "meta",
    }

    def __init__(self, file_paths):
        self.file_paths = file_paths
        self.file_labels = [os.path.basename(p) for p in file_paths]
        self.dumps = {}
        self.flat_dumps = {}
        self.sections_per_file = {}
        self.meta_per_file = {}
        self.loaded_paths = []
        self.skipped_files = []

    def load_files(self):
        """加载所有 JSON 文件，容错处理"""
        self.dumps.clear()
        self.flat_dumps.clear()
        self.sections_per_file.clear()
        self.meta_per_file.clear()
        self.loaded_paths = []
        self.skipped_files = []
        used_labels = set()
        basenames = [os.path.basename(p) for p in self.file_paths]
        for index, path in enumerate(self.file_paths):
            base = os.path.basename(path)
            label = base if basenames.count(base) == 1 else f"[{index + 1}] {base}"
            while label in used_labels:
                label = '[' + label + ']'
            used_labels.add(label)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    raw = f.read()
                # 尝试修复常见的 JSON 格式问题（markdown 转义等）
                data = self._try_parse_json(raw)
                if data is None:
                    raise ValueError('JSON 解析失败')
                if not isinstance(data, dict):
                    raise ValueError('dump 顶层必须为 JSON object')
                flat = flatten(data)
                self.dumps[label] = data
                self.flat_dumps[label] = flat
                self.sections_per_file[label] = set(data.keys())
                meta = data.get("_meta", {})
                self.meta_per_file[label] = meta if isinstance(meta, dict) else {}
                self.loaded_paths.append(path)
                pinfo(f"已加载 {label}: {len(self.flat_dumps[label])} 个路径")
            except Exception as e:
                pwarn(f"加载 {label} 失败: {e}")
                self.skipped_files.append({'path': path, 'label': label, 'error': str(e)})

        if len(self.dumps) < 2:
            pwarn("需要至少 2 个有效文件进行比对")
            return False
        return True

    def _try_parse_json(self, raw):
        """尝试解析 JSON，处理常见的格式问题"""
        # 直接解析
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # 尝试修复 markdown 转义（\_ -> _, \: -> :）
        fixed = raw.replace('\\_', '_').replace('\\:', ':')
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # 尝试去除多余空行后解析
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        try:
            return json.loads('\n'.join(lines))
        except json.JSONDecodeError as e:
            pwarn(f"JSON 解析最终失败: {e}")
            return None

    def compare(self):
        """执行比对，返回结构化差异结果"""
        all_paths = set()
        for flat in self.flat_dumps.values():
            all_paths.update(flat.keys())

        # 排除 _meta 路径
        compare_paths = {p for p in all_paths if top_section(p) != "_meta"}

        # 收集每个路径在所有文件中的值
        path_values = {}
        for path in compare_paths:
            values = {}
            for label, flat in self.flat_dumps.items():
                if path in flat:
                    values[label] = flat[path]
                else:
                    values[label] = MISSING
            path_values[path] = values

        # 过滤出有差异的路径
        diffs = {}
        identical_count = 0
        for path, values in path_values.items():
            reprs = {label: value_repr(v) for label, v in values.items()}
            unique_vals = set(reprs.values())
            if len(unique_vals) > 1:
                diffs[path] = values
            else:
                identical_count += 1

        # 按 section 分类
        categorized = self._categorize_diffs(diffs)

        # 计算 section 一致性
        section_stats = self._calc_section_stats(compare_paths, path_values)

        # 相似度
        total = len(compare_paths)
        similarity = round(identical_count / total * 100, 1) if total > 0 else 0

        result = {
            "status": "partial" if self.skipped_files else "success",
            "requested_files": self.file_paths,
            "skipped_files": self.skipped_files,
            "files": list(self.dumps),
            "file_paths": self.loaded_paths,
            "meta": self.meta_per_file,
            "total_paths": total,
            "identical_paths": identical_count,
            "diff_count": len(diffs),
            "similarity": similarity,
            "sections": self.sections_per_file,
            "section_stats": section_stats,
            "diffs": categorized,
            "all_diffs": diffs,
        }

        return redact_comparison(result, sensitive_values(self.dumps))

    def _categorize_diffs(self, diffs):
        """将差异按 section 和子类别分类"""
        categorized = defaultdict(lambda: {
            "modified": [],
            "only_in": [],
        })

        for path, values in diffs.items():
            section = top_section(path)
            category = self.SECTION_CATEGORIES.get(section, "other")

            # 判断是修改还是仅在一侧
            present_labels = [l for l, v in values.items() if v is not MISSING]
            absent_labels = [l for l, v in values.items() if v is MISSING]

            if absent_labels:
                # 某些文件中缺失
                categorized[category]["only_in"].append({
                    "path": path,
                    "present_in": present_labels,
                    "absent_in": absent_labels,
                    "values": {l: v for l, v in values.items() if v is not MISSING},
                })
            else:
                # 所有文件都有但值不同
                categorized[category]["modified"].append({
                    "path": path,
                    "values": values,
                })

        return dict(categorized)

    def _calc_section_stats(self, all_paths, path_values):
        """计算每个 section 的一致性统计"""
        section_stats = defaultdict(lambda: {"total": 0, "identical": 0, "diff": 0})

        for path in all_paths:
            top = top_section(path)
            section_stats[top]["total"] += 1
            reprs = {l: value_repr(v) for l, v in path_values[path].items()}
            if len(set(reprs.values())) == 1:
                section_stats[top]["identical"] += 1
            else:
                section_stats[top]["diff"] += 1

        return dict(section_stats)


# ============================================================================
# 文本输出
# ============================================================================

def output_text(result):
    """输出终端文本格式报告"""
    result = redact_comparison(result)
    labels = result["files"]
    if result.get("skipped_files"):
        print("PARTIAL: skipped inputs:", redact_sensitive(result["skipped_files"]))
    print(f"\n{C.BOLD}{'='*60}{C.RST}")
    print(f"{C.BOLD}  Ascend Dump 对比报告{C.RST}")
    print(f"{C.BOLD}{'='*60}{C.RST}\n")

    # 文件信息
    for i, label in enumerate(labels):
        meta = result["meta"].get(label, {})
        host = meta.get("hostname", "?")
        ts = meta.get("timestamp", "?")
        print(f"  文件 {chr(65+i)}: {label}")
        print(f"         主机: {host}  时间: {ts}")

    print(f"\n  总路径数: {result['total_paths']}")
    print(f"  一致: {C.G}{result['identical_paths']}{C.RST}")
    print(f"  差异: {C.R}{result['diff_count']}{C.RST}")
    print(f"  相似度: {C.BOLD}{result['similarity']}%{C.RST}\n")

    # Section 统计
    print(f"{C.BOLD}  Section 统计:{C.RST}")
    for section, stats in sorted(result["section_stats"].items()):
        status = f"{C.G}OK{C.RST}" if stats["diff"] == 0 else f"{C.Y}{stats['diff']} 差异{C.RST}"
        print(f"    {section:20s}  {stats['total']:3d} 项  一致 {stats['identical']:3d}  {status}")

    # 分类差异
    for category in ["hardware", "system", "npu", "ascend", "runtime", "env", "config", "network", "weight", "other"]:
        if category not in result["diffs"]:
            continue
        cat_data = result["diffs"][category]
        total = len(cat_data["modified"]) + len(cat_data["only_in"])
        if total == 0:
            continue

        cat_names = {
            "hardware": "硬件资源", "system": "系统设置", "npu": "NPU 运行态",
            "ascend": "Ascend 组件", "runtime": "软件运行时", "env": "环境变量",
            "config": "配置文件", "network": "网络", "weight": "权重",
            "other": "其他"
        }
        print(f"\n{C.BOLD}  [{cat_names.get(category, category)}] {total} 项差异{C.RST}")

        # 修改的值
        for item in cat_data["modified"]:
            path = item["path"]
            vals = item["values"]
            print(f"\n  {C.Y}~ {path}{C.RST}")
            for label, val in vals.items():
                print(f"    {label}: {truncate(val)}")

        # 仅在一侧的
        for item in cat_data["only_in"]:
            path = item["path"]
            present = item["present_in"]
            absent = item["absent_in"]
            print(f"\n  {C.R}- {path}{C.RST}")
            print(f"    存在: {', '.join(present)}  缺失: {', '.join(absent)}")
            for label, val in item["values"].items():
                print(f"    {label}: {truncate(val)}")

    print(f"\n{C.BOLD}{'='*60}{C.RST}")


# ============================================================================
# JSON 输出
# ============================================================================

def output_json(result, output_path):
    """输出 JSON 格式"""
    # 序列化差异结果
    result = redact_comparison(result)
    serializable = {
        "status": result.get("status", "success"),
        "requested_files": result.get("requested_files", result["file_paths"]),
        "skipped_files": result.get("skipped_files", []),
        "files": result["files"],
        "file_paths": result["file_paths"],
        "meta": result["meta"],
        "summary": {
            "total_paths": result["total_paths"],
            "identical_paths": result["identical_paths"],
            "diff_count": result["diff_count"],
            "similarity": result["similarity"],
        },
        "section_stats": result["section_stats"],
        "diffs": {},
    }

    for category, data in result["diffs"].items():
        serializable["diffs"][category] = {
            "modified": [
                {
                    "path": item["path"],
                    "values": {l: v for l, v in item["values"].items()},
                }
                for item in data["modified"]
            ],
            "only_in": [
                {
                    "path": item["path"],
                    "present_in": item["present_in"],
                    "absent_in": item["absent_in"],
                    "values": {l: v for l, v in item["values"].items()},
                }
                for item in data["only_in"]
            ],
        }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False, default=str)
    pinfo(f"JSON 报告已保存: {output_path}")


# ============================================================================
# HTML 输出
# ============================================================================

def output_html(result, output_path):
    """生成自包含 HTML 报告"""
    result = redact_comparison(result)
    labels = result["files"]
    n_files = len(labels)

    # 获取文件信息
    file_infos = []
    for i, label in enumerate(labels):
        meta = result["meta"].get(label, {})
        file_infos.append({
            "label": label,
            "host": meta.get("hostname", "?"),
            "timestamp": meta.get("timestamp", "?"),
            "python": meta.get("python_version", "?"),
        })

    # 统计各类别差异
    cat_stats = {}
    for cat in ["hardware", "system", "npu", "ascend", "runtime", "env", "config", "network", "weight", "other"]:
        if cat in result["diffs"]:
            d = result["diffs"][cat]
            cat_stats[cat] = len(d["modified"]) + len(d["only_in"])
        else:
            cat_stats[cat] = 0

    total_diffs = result["diff_count"]
    similarity = result["similarity"]

    # 生成差异行 HTML
    def diff_rows(category):
        if category not in result["diffs"]:
            return '<div class="empty-state"><div class="icon">✅</div>无差异</div>'

        cat_data = result["diffs"][category]
        rows = []

        # 修改的值
        for item in cat_data["modified"]:
            path = item["path"]
            vals = item["values"]
            cells = ""
            for label in labels:
                v = vals.get(label)
                if v is MISSING:
                    cells += f'<td><span class="val-missing">—</span></td>'
                else:
                    tv = escape(truncate(v, 80))
                    cells += f'<td><code class="val-diff">{tv}</code></td>'
            rows.append(f'<tr class="diff-modified"><td><code>{escape(path)}</code></td>{cells}</tr>')

        # 仅在一侧
        for item in cat_data["only_in"]:
            path = item["path"]
            cells = ""
            for label in labels:
                if label in item["values"]:
                    v = item["values"][label]
                    tv = escape(truncate(v, 80))
                    cells += f'<td><code class="val-present">{tv}</code></td>'
                else:
                    cells += f'<td><span class="val-missing">— (缺失)</span></td>'
            rows.append(f'<tr class="diff-only"><td><code>{escape(path)}</code></td>{cells}</tr>')

        header = f'<tr><th>路径</th>' + ''.join(f'<th>{escape(l)}</th>' for l in labels) + '</tr>'
        return f'<table><thead>{header}</thead><tbody>{"".join(rows)}</tbody></table>'

    # Section 统计行
    section_rows = ""
    for section in sorted(result["section_stats"].keys()):
        stats = result["section_stats"][section]
        status_color = "#22c55e" if stats["diff"] == 0 else "#f59e0b"
        status_text = "一致" if stats["diff"] == 0 else f"{stats['diff']} 差异"
        in_all = all(section in result["sections"].get(l, set()) for l in labels)
        presence = "全部存在" if in_all else "部分缺失"
        section_rows += f'<tr><td><code>{escape(section)}</code></td><td>{stats["total"]}</td><td>{stats["identical"]}</td><td style="color:{status_color};font-weight:600;">{status_text}</td><td>{presence}</td></tr>'

    # 文件卡片
    file_cards = ""
    for i, fi in enumerate(file_infos):
        letter = chr(65 + i)
        file_cards += f'''
        <div class="file-card">
          <div class="f-label">文件 {letter}</div>
          <div class="f-host">{escape(str(fi['host']))}</div>
          <div class="f-meta">📅 {escape(str(fi['timestamp']))}<br>🐍 Python {escape(str(fi['python']))}<br>📄 {escape(str(fi['label']))}</div>
        </div>'''
        if i < n_files - 1:
            file_cards += '<div class="vs-badge">VS</div>'

    # 统计卡片
    stat_cards = ""
    cat_names = {
        "hardware": "硬件资源", "system": "系统", "npu": "NPU 运行态",
        "ascend": "Ascend", "runtime": "软件运行时", "env": "环境变量",
        "config": "配置", "network": "网络", "weight": "权重", "other": "其他"
    }
    for cat, name in cat_names.items():
        count = cat_stats.get(cat, 0)
        color = "#22c55e" if count == 0 else "#f59e0b" if count < 10 else "#ef4444"
        stat_cards += f'<div class="stat-card"><div class="stat-num" style="color:{color}">{count}</div><div class="stat-label">{name}</div></div>'

    stat_cards += f'<div class="stat-card"><div class="stat-num" style="color:#22c55e">{result["identical_paths"]}</div><div class="stat-label">一致项</div></div>'

    # 差异详情 sections
    cat_sections = ""
    for cat, name in cat_names.items():
        count = cat_stats.get(cat, 0)
        if count == 0 and cat not in result["diffs"]:
            continue
        cat_sections += f'''
    <div class="section">
      <div class="section-title"><span>{name}</span><span class="count">{count} 项差异</span></div>
      {diff_rows(cat)}
    </div>'''

    # 相似度颜色
    if similarity >= 90:
        sim_color = "#22c55e"
        sim_text = "高度一致"
    elif similarity >= 70:
        sim_color = "#f59e0b"
        sim_text = "基本一致"
    elif similarity >= 40:
        sim_color = "#f59e0b"
        sim_text = "存在差异"
    else:
        sim_color = "#ef4444"
        sim_text = "差异显著"

    # 整体评估
    if total_diffs == 0:
        assessment = '<div class="banner ok">✅ <div><strong>完全一致：</strong>当前有效输入中的可比较字段一致；不代表环境健康或脱敏值相同。</div></div>'
    elif similarity >= 80:
        assessment = f'<div class="banner ok">✅ <div><strong>{sim_text}：</strong>相似度 {similarity}%，{total_diffs} 项差异，相似度仅表示字段一致比例，关键差异的影响仍需单独核验。</div></div>'
    elif similarity >= 50:
        assessment = f'<div class="banner warn">⚠️ <div><strong>{sim_text}：</strong>相似度 {similarity}%，{total_diffs} 项差异，需关注关键配置差异。</div></div>'
    else:
        assessment = f'<div class="banner fail">🔴 <div><strong>{sim_text}：</strong>相似度仅 {similarity}%，{total_diffs} 项差异，需结合采集范围与具体字段判断影响。</div></div>'

    if result.get('skipped_files'):
        skipped = escape(json.dumps(result['skipped_files'], ensure_ascii=False))
        assessment = '<div class="banner warn">部分输入未参与比对：' + skipped + '</div>' + assessment

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ascend 环境对比报告</title>
<style>
:root {{
  --ok: #22c55e; --ok-bg: #f0fdf4;
  --warn: #f59e0b; --warn-bg: #fffbeb;
  --fail: #ef4444; --fail-bg: #fef2f2;
  --info: #3b82f6; --info-bg: #eff6ff;
  --ink: #1e293b; --muted: #64748b;
  --border: #e2e8f0; --bg: #f8fafc; --card: #fff;
  --radius: 10px; --shadow: 0 1px 3px rgba(0,0,0,0.08);
  --mono: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; background: var(--bg); color: var(--ink); line-height: 1.6; font-size: 15px; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
.header {{ background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%); color: #fff; border-radius: var(--radius); padding: 2.5rem; margin-bottom: 1.5rem; box-shadow: var(--shadow); }}
.header h1 {{ font-size: 1.8rem; font-weight: 700; margin-bottom: 0.3rem; }}
.header .subtitle {{ opacity: 0.85; font-size: 0.95rem; margin-bottom: 1.5rem; }}
.file-info-grid {{ display: flex; gap: 1rem; align-items: stretch; flex-wrap: wrap; }}
.file-card {{ background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); border-radius: 8px; padding: 1rem 1.2rem; flex: 1; min-width: 200px; }}
.file-card .f-label {{ font-size: 0.72rem; opacity: 0.7; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.3rem; }}
.file-card .f-host {{ font-size: 1.05rem; font-weight: 700; word-break: break-all; }}
.file-card .f-meta {{ font-size: 0.78rem; opacity: 0.8; margin-top: 0.3rem; }}
.vs-badge {{ width: 45px; height: 45px; border-radius: 50%; background: rgba(255,255,255,0.15); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 0.8rem; flex-shrink: 0; align-self: center; }}
.similarity-bar {{ margin-top: 1.5rem; background: rgba(255,255,255,0.1); border-radius: 8px; padding: 1rem 1.2rem; }}
.similarity-bar .sim-label {{ font-size: 0.82rem; opacity: 0.85; margin-bottom: 0.4rem; display: flex; justify-content: space-between; }}
.similarity-track {{ height: 8px; background: rgba(255,255,255,0.2); border-radius: 4px; overflow: hidden; }}
.similarity-fill {{ height: 100%; border-radius: 4px; background: linear-gradient(90deg, #ef4444 0%, #f59e0b 50%, #22c55e 100%); }}
.stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.8rem; margin-bottom: 1.5rem; }}
.stat-card {{ background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 1rem; box-shadow: var(--shadow); text-align: center; }}
.stat-card .stat-num {{ font-size: 1.8rem; font-weight: 700; }}
.stat-card .stat-label {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase; margin-top: 0.2rem; }}
.section {{ background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.5rem; margin-bottom: 1.5rem; box-shadow: var(--shadow); }}
.section-title {{ font-size: 1.1rem; font-weight: 700; margin-bottom: 1rem; display: flex; align-items: center; justify-content: space-between; border-bottom: 2px solid var(--border); padding-bottom: 0.6rem; }}
.section-title .count {{ font-size: 0.8rem; font-weight: 600; padding: 0.15em 0.6em; border-radius: 12px; background: var(--info-bg); color: var(--info); }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
th {{ text-align: left; padding: 0.5rem 0.7rem; color: var(--muted); font-weight: 600; font-size: 0.78rem; border-bottom: 2px solid var(--border); white-space: nowrap; }}
td {{ padding: 0.45rem 0.7rem; border-bottom: 1px solid var(--border); vertical-align: top; }}
td code {{ font-family: var(--mono); font-size: 0.82em; padding: 0.1em 0.3em; border-radius: 3px; background: var(--bg); }}
tr.diff-modified {{ background: var(--warn-bg); }}
tr.diff-modified td:first-child {{ border-left: 3px solid var(--warn); }}
tr.diff-only {{ background: var(--info-bg); }}
tr.diff-only td:first-child {{ border-left: 3px solid var(--info); }}
.val-diff {{ color: #92400e; }}
.val-present {{ color: var(--ok); }}
.val-missing {{ color: var(--fail); font-style: italic; }}
.banner {{ border-radius: 8px; padding: 0.8rem 1rem; margin-bottom: 1rem; font-size: 0.88rem; display: flex; align-items: flex-start; gap: 0.5rem; }}
.banner.ok {{ background: var(--ok-bg); border: 1px solid #bbf7d0; color: #166534; }}
.banner.warn {{ background: var(--warn-bg); border: 1px solid #fde68a; color: #92400e; }}
.banner.fail {{ background: var(--fail-bg); border: 1px solid #fecaca; color: #991b1b; }}
.banner.info {{ background: var(--info-bg); border: 1px solid #bfdbfe; color: #1e40af; }}
.empty-state {{ text-align: center; padding: 1.5rem; color: var(--muted); font-size: 0.9rem; }}
.empty-state .icon {{ font-size: 1.8rem; margin-bottom: 0.3rem; opacity: 0.4; }}
.footer {{ text-align: center; color: var(--muted); font-size: 0.82rem; padding: 2rem 0; }}
@media (max-width: 768px) {{ .container {{ padding: 1rem; }} .header {{ padding: 1.5rem; }} .file-info-grid {{ flex-direction: column; }} .vs-badge {{ margin: 0 auto; }} .stats-grid {{ grid-template-columns: 1fr 1fr; }} table {{ font-size: 0.78rem; }} }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>Ascend 环境对比报告</h1>
  <div class="subtitle">{n_files} 个文件比对 · {total_diffs} 项差异 · 相似度 {similarity}%</div>
  <div class="file-info-grid">
    {file_cards}
  </div>
  <div class="similarity-bar">
    <div class="sim-label">
      <span>环境相似度</span>
      <span><strong style="color:{sim_color}">{similarity}%</strong> · {sim_text}</span>
    </div>
    <div class="similarity-track">
      <div class="similarity-fill" style="width: {similarity}%"></div>
    </div>
  </div>
</div>

<div class="stats-grid">
  {stat_cards}
</div>

{assessment}

<div class="section">
  <div class="section-title"><span>📊 Section 统计</span></div>
  <table>
    <thead><tr><th>Section</th><th>总路径数</th><th>一致</th><th>差异</th><th>存在性</th></tr></thead>
    <tbody>
      {section_rows}
    </tbody>
  </table>
</div>

{cat_sections}

<div class="footer">本报告由 compare_dumps.py {__version__} 生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>

</div>
</body>
</html>'''

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    pinfo(f"HTML 报告已保存: {output_path}")


# ============================================================================
# 主入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Ascend 环境 dump JSON 比对工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  %(prog)s env1.json env2.json                          # 终端输出
  %(prog)s env1.json env2.json --html report.html       # HTML 报告
  %(prog)s env1.json env2.json --json diff.json         # JSON 报告
  %(prog)s env1.json env2.json env3.json --html r.html  # 三文件比对
""",
    )

    parser.add_argument(
        "files",
        nargs="+",
        help="2 个或多个 dump JSON 文件路径"
    )
    parser.add_argument(
        "--html", metavar="PATH",
        help="输出 HTML 报告到指定路径"
    )
    parser.add_argument(
        "--json", metavar="PATH",
        help="输出 JSON 格式差异报告到指定路径"
    )
    parser.add_argument(
        "--text", action="store_true",
        help="输出终端文本格式（默认）"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    if len(args.files) < 2:
        pwarn("需要至少 2 个文件进行比对")
        sys.exit(1)

    comparator = DumpComparator(args.files)
    if not comparator.load_files():
        sys.exit(1)

    result = comparator.compare()

    # 默认输出文本
    output_text(result)

    if args.json:
        output_json(result, args.json)

    if args.html:
        output_html(result, args.html)


if __name__ == "__main__":
    main()
