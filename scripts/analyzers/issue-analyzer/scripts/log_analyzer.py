#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
log_analyzer.py — 昇腾现网问题日志通用分析脚本（零依赖，Python 3.7+）

为 issue-analyzer 技能预置的分析脚本，配合四层管线使用：
  L0 scan     目录清单：文件/大小/行数/首末时间戳/类型/host/device 识别
  L1 extract  错误提取：内置 19 个默认模式 + 关键字 + 自定义正则，支持时间窗过滤
  L2 stats    聚合分布：按模式/文件/时间桶统计 extract 产出的 hits
  L3 context  聚焦取证：指定行号（或正则第 N 次命中）的 ±N 行上下文
     verify   证据回验：逐条核对 evidence.json 中的 file:line:quote

用法示例：
  python log_analyzer.py scan --dir ./logs --out out/manifest.json --md out/manifest.md
  python log_analyzer.py extract --dir ./logs --since "2026-08-28 10:00" --until "2026-08-28 10:40" --keywords "hccl,rank" --out out/hits.json --md out/hits.md
  python log_analyzer.py stats --hits out/hits.json --bucket 10m --md out/stats.md
  python log_analyzer.py context --file ./logs/plog/device-3.log --line 1234 --before 15 --after 15
  python log_analyzer.py verify --evidence out/evidence.json --root ./logs --md out/verify_result.md

默认提取模式（--no-default 关闭）：fatal critical panic error segfault core_dump abort
signal_kill oom ecc watchdog timeout link_error device_abnormal exception assert_fail
numeric_anomaly disk_full ascend_code（形如 EE9999 的两位字母+四位数字错误码）

时间戳识别：自动识别常见格式（含 [2026-08-28 10:23:45.123]、2026-08-28-10:23:45、
syslog 式 Aug 28 10:23:45 等）。无时间戳的行（如 Python 栈续行）在时间窗过滤时
继承上文最近的时间戳，不会被误伤。
"""

import argparse
import gzip
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict, deque
from datetime import datetime

VERSION = '1.0.0'

try:
    sys.stdout.reconfigure(errors='replace')
    sys.stderr.reconfigure(errors='replace')
except Exception:
    pass


# ---------------------------------------------------------------- 时间戳识别

TS_SPECS = [
    (re.compile(r'(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?)'),
     ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S']),
    (re.compile(r'(\d{4}-\d{2}-\d{2}-\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?)'),
     ['%Y-%m-%d-%H:%M:%S.%f', '%Y-%m-%d-%H:%M:%S']),
    (re.compile(r'(\d{4}/\d{2}/\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?)'),
     ['%Y/%m/%d %H:%M:%S.%f', '%Y/%m/%d %H:%M:%S']),
    (re.compile(r'(\d{4}\.\d{2}\.\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?)'),
     ['%Y.%m.%d %H:%M:%S.%f', '%Y.%m.%d %H:%M:%S']),
    (re.compile(r'\b([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\b'),
     ['%b %d %H:%M:%S', '%b  %d %H:%M:%S']),
]

TS_PRECHECK = re.compile(
    r'\d{4}[-/.]\d{2}[-/.]\d{2}|\b[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}')


def _try_parse(s, fmts):
    for fmt in fmts:
        t = s
        if '.' in t:
            head, _, frac = t.partition('.')
            frac = re.sub(r'\D.*$', '', frac)[:6]
            t = head + ('.' + frac if frac else '')
            if '%f' not in fmt:
                t = head
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            continue
    return None


def find_ts(line):
    """在行中查找时间戳。返回 (raw字符串, datetime)，找不到返回 (None, None)。"""
    if not TS_PRECHECK.search(line):
        return None, None
    for rx, fmts in TS_SPECS:
        m = rx.search(line)
        if not m:
            continue
        raw = m.group(1)
        dt = _try_parse(raw, fmts)
        if dt is None:
            continue
        if dt.year == 1900:
            dt = dt.replace(year=datetime.now().year)
        return raw, dt
    return None, None


def parse_time_arg(s):
    fmts = ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M',
            '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d']
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        '无法解析时间 %r（支持 2026-08-28[ 10:23[:45]]）' % s)


# ---------------------------------------------------------------- 文件工具

SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.svn'}


def open_text(path, encoding='utf-8'):
    if path.lower().endswith('.gz'):
        return io.TextIOWrapper(gzip.open(path, 'rb'), encoding=encoding,
                                errors='replace')
    return open(path, 'r', encoding=encoding, errors='replace')


def _read_sample(path, nbytes=65536):
    try:
        if path.lower().endswith('.gz'):
            with gzip.open(path, 'rb') as f:
                return f.read(nbytes)
        with open(path, 'rb') as f:
            return f.read(nbytes)
    except OSError:
        return b''


def detect_encoding(path):
    sample = _read_sample(path)
    if not sample:
        return 'utf-8'
    for enc in ('utf-8', 'gbk'):
        try:
            sample.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return 'utf-8'


def is_binary(path):
    sample = _read_sample(path, 8192)
    if not sample:
        return False
    return b'\x00' in sample


def count_lines(path):
    n = 0
    opener = gzip.open if path.lower().endswith('.gz') else open
    with opener(path, 'rb') as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            n += chunk.count(b'\n')
    return n


def read_head_lines(path, encoding, nlines=300):
    lines = []
    with open_text(path, encoding) as f:
        for i, line in enumerate(f):
            lines.append(line)
            if i + 1 >= nlines:
                break
    return lines


def read_tail_lines(path, encoding, nlines=300, tail_bytes=262144):
    if path.lower().endswith('.gz'):
        with open_text(path, encoding) as f:
            dq = deque(maxlen=nlines)
            for line in f:
                dq.append(line)
        return list(dq)
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        if size > tail_bytes:
            f.seek(size - tail_bytes)
            f.readline()
        chunk = f.read()
    return chunk.decode(encoding, errors='replace').splitlines()[-nlines:]


def iter_files(root, depth=None):
    root = os.path.abspath(root)
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        cur = dirpath.rstrip(os.sep).count(os.sep)
        if depth is not None and cur - base_depth >= depth:
            dirnames[:] = []
        for fn in sorted(filenames):
            yield os.path.join(dirpath, fn)


def human_size(n):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return '%d%s' % (n, unit) if unit == 'B' else '%.1f%s' % (n, unit)
        n /= 1024.0


# ---------------------------------------------------------------- 类型识别

TYPE_RULES = [
    ('kernel', re.compile(r'dmesg|messages|kern\.log|syslog|journal', re.I)),
    ('device', re.compile(r'device[-_]\d+', re.I)),
    ('host', re.compile(r'host[-_]', re.I)),
    ('plog', re.compile(r'plog', re.I)),
    ('slog', re.compile(r'slog', re.I)),
    ('hccl', re.compile(r'hccl', re.I)),
    ('framework', re.compile(
        r'train|torchrun|mindspore|deepspeed|megatron|rank[-_]?\d+|worker|'
        r'master|nohup|launcher|agent', re.I)),
    ('service', re.compile(r'mindie|vllm|serving|server|api|access', re.I)),
]


def guess_type(path):
    p = path.replace('\\', '/').lower()
    for name, rx in TYPE_RULES:
        if rx.search(p):
            return name
    if p.endswith(('.log', '.txt', '.out', '.err')) or p.endswith('.log.gz'):
        return 'log'
    return 'other'


def guess_host_device(path):
    p = path.replace('\\', '/')
    host = device = None
    m = re.search(r'(\d{1,3}(?:\.\d{1,3}){3})', p)
    if m:
        host = m.group(1)
    m = re.search(r'device[-_](\d+)', p, re.I)
    if m:
        device = int(m.group(1))
    return host, device


# ---------------------------------------------------------------- 默认模式

DEFAULT_PATTERNS = [
    ('fatal', r'\bFATAL\b|\[FATAL\]'),
    ('critical', r'\bCRITICAL\b|\[CRITICAL\]'),
    ('panic', r'[Kk]ernel panic|\bpanic\b'),
    ('error', r'\[ERROR\]|\bERROR\b|\bError\b'),
    ('segfault', r'Segmentation fault|SIGSEGV|segfault'),
    ('core_dump', r'[Cc]ore[ -]?[Dd]ump|coredump'),
    ('abort', r'SIGABRT|\b[Aa]bort(?:ed|ing)?\b'),
    ('signal_kill', r'SIGKILL|SIGTERM|Killed process|\bkilled\b'),
    ('oom', r'[Oo]ut of [Mm]emory|\bOOM\b|oom-?killer|oom_kill'),
    ('ecc', r'\bECC\b|\becc\b'),
    ('watchdog', r'[Ww]atchdog'),
    ('timeout', r'[Tt]imeout|TIMEOUT|timed out'),
    ('link_error', r'link\s+(?:is\s+)?(?:down|abnormal|error|fail)|'
                   r'LINK\s+DOWN|[Ll]ink\s+status.{0,20}(?:down|abnormal|error|fail)'),
    ('device_abnormal', r'[Dd]evice.{0,30}(?:abnormal|fault|offline|reset|'
                        r'unavailable|busy|not available)|\bNPU\b.{0,30}'
                        r'(?:abnormal|fault|offline|reset)'),
    ('exception', r'\bException\b|[Tt]raceback|[A-Za-z]+(?:Error|Exception)\b'),
    ('assert_fail', r'Assertion|[Aa]ssert(?:ion)? failed|ASSERT'),
    ('numeric_anomaly', r'\bNaN\b|\bnan\b|\bInf\b|\bINF\b'),
    ('disk_full', r'[Nn]o space left on device'),
    ('ascend_code', r'(?<![A-Za-z0-9])[A-Z]{2}\d{4}(?![A-Za-z0-9])'),
]


def build_patterns(args):
    """返回 [(name, 原始正则串, 已编译), ...]。"""
    patterns = []
    if not args.no_default:
        for name, rx in DEFAULT_PATTERNS:
            patterns.append((name, rx, re.compile(rx)))
    for kw_group in (getattr(args, 'keywords', None) or []):
        for k in re.split(r'[,;，；]', kw_group):
            k = k.strip()
            if k:
                patterns.append(('kw:' + k, re.escape(k),
                                 re.compile(re.escape(k), re.I)))
    for spec in (getattr(args, 'patterns', None) or []):
        if ':' not in spec:
            sys.exit('错误: --patterns 需要 name:regex 格式，收到 %r' % spec)
        name, rx = spec.split(':', 1)
        name = re.sub(r'\W', '_', name.strip())
        if not name:
            sys.exit('错误: --patterns 的 name 为空: %r' % spec)
        try:
            patterns.append((name, rx, re.compile(rx)))
        except re.error as e:
            sys.exit('错误: 正则编译失败 %s: %s' % (spec, e))
    if not patterns:
        sys.exit('错误: 没有可用的提取模式（--no-default 且未提供 --keywords/--patterns）')
    return patterns


# ---------------------------------------------------------------- 输出工具

def write_text(path, text):
    if not path:
        return
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def write_json_file(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))


def announce_written(*paths):
    paths = [p for p in paths if p]
    if paths:
        print('\n已写入: ' + ' | '.join(paths))


def md_escape(s, limit=None):
    s = (s or '').replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ')
    if limit and len(s) > limit:
        s = s[:limit] + '...'
    return s


def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def print_counter(title, counter, top=20, extra_fmt=None):
    print('\n%s（共 %d 项）:' % (title, len(counter)))
    for name, cnt in counter.most_common(top):
        extra = extra_fmt(name) if extra_fmt else ''
        print('  %-28s %8d%s' % (name, cnt, extra))


def bucket_key(dt, bucket):
    if bucket == '1m':
        return dt.strftime('%Y-%m-%d %H:%M')
    if bucket == '10m':
        return dt.strftime('%Y-%m-%d %H:') + '%02d' % (dt.minute // 10 * 10)
    if bucket == '1h':
        return dt.strftime('%Y-%m-%d %H:00')
    return dt.strftime('%Y-%m-%d')


# ---------------------------------------------------------------- L0 scan

def cmd_scan(args):
    files = []
    for path in iter_files(args.dir, args.depth):
        try:
            st = os.stat(path)
        except OSError:
            continue
        rel = os.path.relpath(path, args.dir).replace('\\', '/')
        rec = {
            'file': rel,
            'abs_path': os.path.abspath(path),
            'type': guess_type(path),
            'size_bytes': st.st_size,
            'size_human': human_size(st.st_size),
        }
        rec['host'], rec['device'] = guess_host_device(path)
        if is_binary(path):
            rec['binary'] = True
            rec['lines'] = None
            rec['first_ts'] = rec['last_ts'] = None
        else:
            rec['binary'] = False
            rec['encoding'] = detect_encoding(path)
            if args.skip_line_count or st.st_size > 1024 * 1024 * 1024:
                rec['lines'] = None
            else:
                try:
                    rec['lines'] = count_lines(path)
                except OSError:
                    rec['lines'] = None
            rec['first_ts'] = rec['last_ts'] = None
            try:
                for line in read_head_lines(path, rec['encoding']):
                    raw, dt = find_ts(line)
                    if dt:
                        rec['first_ts'] = raw
                        rec['_first_dt'] = dt.isoformat(' ')
                        break
                for line in reversed(read_tail_lines(path, rec['encoding'])):
                    raw, dt = find_ts(line)
                    if dt:
                        rec['last_ts'] = raw
                        rec['_last_dt'] = dt.isoformat(' ')
                        break
            except OSError:
                pass
        files.append(rec)

    type_counter = Counter(r['type'] for r in files)
    total_size = sum(r['size_bytes'] for r in files)
    dts = [r['_first_dt'] for r in files if r.get('_first_dt')]
    dts += [r['_last_dt'] for r in files if r.get('_last_dt')]
    manifest = {
        'generated_at': now_str(),
        'tool': 'log_analyzer.py %s' % VERSION,
        'root': os.path.abspath(args.dir),
        'total_files': len(files),
        'total_size_bytes': total_size,
        'total_size_human': human_size(total_size),
        'time_span': [min(dts), max(dts)] if dts else None,
        'type_distribution': dict(type_counter),
        'files': files,
    }

    print('=== L0 日志清单 scan ===')
    print('根目录: %s' % manifest['root'])
    print('文件总数: %d（二进制 %d 个）| 总大小: %s'
          % (len(files), sum(1 for r in files if r['binary']),
             manifest['total_size_human']))
    print('时间跨度: %s' % (' ~ '.join(manifest['time_span'])
                            if manifest['time_span'] else '未识别到时间戳'))
    print_counter('按类型分布', type_counter, top=10)
    largest = sorted(files, key=lambda r: r['size_bytes'], reverse=True)[:10]
    print('\n最大的 10 个文件:')
    for r in largest:
        print('  %-10s %10s  %s' % (r['type'], r['size_human'], r['file']))

    for r in files:
        r.pop('_first_dt', None)
        r.pop('_last_dt', None)

    if args.out or args.md:
        rows = ['# 日志清单（manifest）',
                '',
                '- 生成时间: %s' % manifest['generated_at'],
                '- 根目录: `%s`' % manifest['root'],
                '- 文件总数: %d | 总大小: %s | 时间跨度: %s'
                % (len(files), manifest['total_size_human'],
                   ' ~ '.join(manifest['time_span']) if manifest['time_span'] else '未识别'),
                '',
                '| 日志文件 | 类型 | 大小 | 行数 | 首时间戳 | 末时间戳 | host | device |',
                '|---|---|---|---|---|---|---|---|']
        for r in files:
            rows.append('| `%s` | %s | %s | %s | %s | %s | %s | %s |' % (
                md_escape(r['file']), r['type'], r['size_human'],
                r['lines'] if r['lines'] is not None else '-',
                r['first_ts'] or '-', r['last_ts'] or '-',
                r['host'] or '-', r['device'] if r['device'] is not None else '-'))
        write_text(args.md, '\n'.join(rows) + '\n')
        write_json_file(args.out, manifest)
        announce_written(args.out, args.md)


# ---------------------------------------------------------------- L1 extract

def iter_log_files(args):
    seen = set()
    if args.files:
        for p in args.files:
            if p not in seen:
                seen.add(p)
                yield p
    if args.dir:
        for path in iter_files(args.dir, args.depth):
            if path not in seen:
                seen.add(path)
                yield path


def cmd_extract(args):
    since = parse_time_arg(args.since) if args.since else None
    until = parse_time_arg(args.until) if args.until else None
    if until and args.until and len(args.until.strip()) <= 10:
        until = until.replace(hour=23, minute=59, second=59, microsecond=999999)

    patterns = build_patterns(args)
    master = re.compile('|'.join('(?:%s)' % rx for _, rx, _ in patterns))

    hits = []
    per_pattern = Counter()
    per_file = Counter()
    per_hour = Counter()
    scanned = binary_skipped = files_with_hits = 0

    for path in iter_log_files(args):
        if is_binary(path):
            binary_skipped += 1
            continue
        scanned += 1
        rel = (os.path.relpath(path, args.dir).replace('\\', '/')
               if args.dir else path.replace('\\', '/'))
        enc = detect_encoding(path)
        last_raw = last_dt = None
        file_hits = 0
        try:
            with open_text(path, enc) as f:
                for lineno, rawline in enumerate(f, 1):
                    line = rawline.rstrip('\r\n')
                    raw, dt = find_ts(line)
                    if dt:
                        last_raw, last_dt = raw, dt
                    if not master.search(line):
                        continue
                    if since or until:
                        eff_dt = dt or last_dt
                        if eff_dt is None:
                            continue
                        if since and eff_dt < since:
                            continue
                        if until and eff_dt > until:
                            continue
                    matched = [name for name, _rx, cre in patterns
                               if cre.search(line)]
                    if not matched:
                        continue
                    hits.append({
                        'file': rel,
                        'line': lineno,
                        'ts': raw or last_raw,
                        'ts_inherited': raw is None,
                        'patterns': matched,
                        'text': line[:args.max_chars],
                    })
                    file_hits += 1
                    for name in matched:
                        per_pattern[name] += 1
                    per_file[rel] += 1
                    eff = dt or last_dt
                    if eff:
                        per_hour[eff.strftime('%Y-%m-%d %H:00')] += 1
                    if args.top and file_hits >= args.top:
                        break
        except OSError as e:
            print('警告: 读取失败 %s: %s' % (rel, e), file=sys.stderr)
        if file_hits:
            files_with_hits += 1
        if len(hits) >= args.max_total:
            print('提示: 达到 --max-total=%d，停止扫描' % args.max_total,
                  file=sys.stderr)
            break

    result = {
        'generated_at': now_str(),
        'tool': 'log_analyzer.py %s' % VERSION,
        'source_dir': os.path.abspath(args.dir) if args.dir else None,
        'time_window': [args.since, args.until],
        'files_scanned': scanned,
        'files_with_hits': files_with_hits,
        'total_hits': len(hits),
        'patterns_used': [name for name, _rx, _c in patterns],
        'hits': hits,
    }

    print('=== L1 错误提取 extract ===')
    print('扫描文件: %d（跳过二进制 %d）| 含命中文件: %d | 命中总数: %d'
          % (scanned, binary_skipped, files_with_hits, len(hits)))
    if since or until:
        print('时间窗: %s ~ %s' % (args.since or '(起点)', args.until or '(终点)'))
    print_counter('按模式 TOP 20', per_pattern)
    print_counter('按文件 TOP 15', per_file, top=15)
    if per_hour:
        print_counter('按小时分布 TOP 20', per_hour)

    if args.out or args.md:
        write_json_file(args.out, result)
        rows = ['# 错误提取结果（hits）',
                '',
                '- 生成时间: %s | 时间窗: %s ~ %s | 命中总数: %d'
                % (result['generated_at'], args.since or '-', args.until or '-',
                   len(hits)),
                '',
                '| 证据位置 | 时间 | 模式 | 日志原文 |',
                '|---|---|---|---|']
        for h in hits[:args.md_rows]:
            ts = h['ts'] or '-'
            if h['ts_inherited']:
                ts += '*'
            rows.append('| `%s:%d` | %s | %s | %s |' % (
                md_escape(h['file']), h['line'], md_escape(ts, 30),
                md_escape(','.join(h['patterns']), 40),
                md_escape(h['text'], 150)))
        if len(hits) > args.md_rows:
            rows.append('')
            rows.append('> 仅显示前 %d 条，全部 %d 条见 JSON 文件。'
                        % (args.md_rows, len(hits)))
        write_text(args.md, '\n'.join(rows) + '\n')
        announce_written(args.out, args.md)


# ---------------------------------------------------------------- L2 stats

def cmd_stats(args):
    with open(args.hits, encoding='utf-8') as f:
        data = json.load(f)
    hits = data['hits'] if isinstance(data, dict) and 'hits' in data else data
    if not isinstance(hits, list):
        sys.exit('错误: hits 文件格式不符（需要列表或含 hits 数组的对象）')

    by_pattern = Counter()
    pat_files = defaultdict(set)
    by_file = Counter()
    file_pats = defaultdict(Counter)
    by_bucket = Counter()
    no_ts = 0
    for h in hits:
        for p in h.get('patterns', []):
            by_pattern[p] += 1
            pat_files[p].add(h.get('file', '?'))
        f_ = h.get('file', '?')
        by_file[f_] += 1
        for p in h.get('patterns', []):
            file_pats[f_][p] += 1
        ts = h.get('ts')
        dt = None
        if ts:
            _raw, dt = find_ts(ts)
        if dt:
            by_bucket[bucket_key(dt, args.bucket)] += 1
        else:
            no_ts += 1
    if no_ts:
        by_bucket['(无时间戳)'] = no_ts

    print('=== L2 聚合分布 stats ===')
    print('hits 总数: %d | 时间桶: %s' % (len(hits), args.bucket))
    print_counter('按模式', by_pattern, top=30,
                  extra_fmt=lambda n: '（%d 个文件）' % len(pat_files[n]))
    print_counter('按文件', by_file, top=20)
    print_counter('按时间桶（%s）' % args.bucket, by_bucket, top=30)

    if args.md:
        rows = ['# 聚合分布（stats）',
                '',
                '- 生成时间: %s | hits 总数: %d | 时间桶: %s'
                % (now_str(), len(hits), args.bucket),
                '',
                '## 按模式',
                '',
                '| 模式 | 命中数 | 涉及文件数 |',
                '|---|---|---|']
        for name, cnt in by_pattern.most_common():
            rows.append('| %s | %d | %d |' % (name, cnt, len(pat_files[name])))
        rows += ['', '## 按文件', '', '| 文件 | 命中数 | 主要模式 |', '|---|---|---|']
        for name, cnt in by_file.most_common():
            top_pats = ','.join('%s:%d' % pc
                                for pc in file_pats[name].most_common(3))
            rows.append('| `%s` | %d | %s |' % (md_escape(name), cnt,
                                                 md_escape(top_pats, 60)))
        rows += ['', '## 按时间桶（%s）' % args.bucket, '',
                 '| 时间桶 | 命中数 |', '|---|---|']
        for name, cnt in sorted(by_bucket.items()):
            rows.append('| %s | %d |' % (name, cnt))
        write_text(args.md, '\n'.join(rows) + '\n')
        print('\n已写入: %s' % args.md)
    if args.out:
        write_json_file(args.out, {
            'generated_at': now_str(),
            'total': len(hits),
            'by_pattern': dict(by_pattern),
            'by_file': dict(by_file),
            'by_bucket_%s' % args.bucket: dict(by_bucket),
        })


# ---------------------------------------------------------------- L3 context

def cmd_context(args):
    if not args.line and not args.regex:
        sys.exit('错误: 需要 --line N 或 --regex R 之一')
    if args.line and args.regex:
        sys.exit('错误: --line 与 --regex 只能选一个')
    enc = detect_encoding(args.file)
    rx = re.compile(args.regex) if args.regex else None
    nth = args.nth if args.nth and args.nth > 0 else 1

    ring = deque(maxlen=args.before)
    found = None
    match_count = 0
    after_lines = []
    try:
        with open_text(args.file, enc) as f:
            lineno = 0
            while True:
                rawline = f.readline()
                if not rawline:
                    break
                lineno += 1
                line = rawline.rstrip('\r\n')
                if found is not None:
                    if len(after_lines) < args.after:
                        after_lines.append((lineno, line))
                    else:
                        break
                    continue
                if args.line:
                    if lineno == args.line:
                        found = (lineno, line)
                        continue
                elif rx.search(line):
                    match_count += 1
                    if match_count == nth:
                        found = (lineno, line)
                        continue
                ring.append((lineno, line))
    except OSError as e:
        sys.exit('错误: 读取失败 %s: %s' % (args.file, e))

    if found is None:
        if args.regex:
            print('未找到第 %d 次命中正则 %r（该文件共命中 %d 次）'
                  % (nth, args.regex, match_count))
        else:
            print('行号 %d 超出文件范围' % args.line)
        sys.exit(1)
    target_lineno, target_line = found

    print('=== L3 上下文 context ===')
    print('文件: %s' % args.file)
    print('目标: 第 %d 行%s' % (target_lineno,
          ('（正则 %r 第 %d 次命中）' % (args.regex, nth)) if rx else ''))
    raw, _dt = find_ts(target_line)
    if raw:
        print('目标行时间戳: %s' % raw)
    print('---')
    for lineno, line in ring:
        print('  %7d | %s' % (lineno, line[:args.max_chars]))
    print('> %7d | %s' % (target_lineno, target_line[:args.max_chars]))
    for lineno, line in after_lines:
        print('  %7d | %s' % (lineno, line[:args.max_chars]))
    print('---')
    print('提示: 引用证据时使用 %s:%d（路径相对日志包根目录）'
          % (args.file, target_lineno))


# ---------------------------------------------------------------- verify

def norm_text(s):
    return ' '.join((s or '').split())


def cmd_verify(args):
    with open(args.evidence, encoding='utf-8') as f:
        data = json.load(f)
    items = data.get('evidence', []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        sys.exit('错误: evidence 文件需要是列表或含 evidence 数组的对象')

    def resolve(path):
        if os.path.exists(path):
            return path
        if args.root and not os.path.isabs(path):
            joined = os.path.join(args.root, path)
            if os.path.exists(joined):
                return joined
        return None

    results = []
    for it in items:
        rec = dict(it)
        path = it.get('file')
        line_no = int(it.get('line', 0) or 0)
        quote = it.get('quote', '') or ''
        actual = None
        err = None
        real = resolve(path) if path else None
        if real is None:
            err = '文件不存在'
        elif line_no <= 0:
            err = '行号无效'
        else:
            try:
                enc = detect_encoding(real)
                with open_text(real, enc) as f:
                    cur = 0
                    while True:
                        l = f.readline()
                        if not l:
                            break
                        cur += 1
                        if cur == line_no:
                            actual = l.rstrip('\r\n')
                            break
                    if actual is None:
                        err = '行号超出文件范围'
            except OSError as e:
                err = str(e)
        if err:
            rec['result'] = 'FAIL'
            rec['error'] = err
        else:
            a, q = norm_text(actual), norm_text(quote)
            if q and q == a:
                rec['result'] = 'PASS'
            elif q and (q in a or a in q):
                rec['result'] = 'PARTIAL'
            else:
                rec['result'] = 'FAIL'
        rec['actual'] = (actual or '')[:args.max_chars]
        results.append(rec)

    summary = Counter(r['result'] for r in results)
    print('=== 证据回验 verify ===')
    print('证据总数: %d | PASS: %d | PARTIAL: %d | FAIL: %d'
          % (len(results), summary.get('PASS', 0),
             summary.get('PARTIAL', 0), summary.get('FAIL', 0)))
    for r in results:
        flag = {'PASS': '✓', 'PARTIAL': '≈', 'FAIL': '✗'}[r['result']]
        print('  [%s %s] %s:%s %s' % (flag, r['result'], r.get('file'),
                                      r.get('line'), r.get('error', '')))
        if r['result'] != 'PASS':
            print('      引用: %s' % (r.get('quote', '')[:120]))
            print('      实际: %s' % r.get('actual', '')[:120])

    out = {
        'generated_at': now_str(),
        'summary': {'total': len(results),
                    'pass': summary.get('PASS', 0),
                    'partial': summary.get('PARTIAL', 0),
                    'fail': summary.get('FAIL', 0)},
        'results': results,
    }
    if args.out:
        write_json_file(args.out, out)
    if args.md:
        rows = ['# 证据回验结果', '',
                '- 生成时间: %s' % out['generated_at'],
                '- 总数 %d | PASS %d | PARTIAL %d | FAIL %d'
                % (out['summary']['total'], out['summary']['pass'],
                   out['summary']['partial'], out['summary']['fail']),
                '',
                '| 结果 | 编号 | 证据位置 | 说明 |',
                '|---|---|---|---|']
        for r in results:
            note = r.get('error') or md_escape(r.get('note', ''), 60)
            rows.append('| %s | %s | `%s:%s` | %s |' % (
                r['result'], r.get('id', '-'), md_escape(r.get('file', '')),
                r.get('line', '-'), note))
        write_text(args.md, '\n'.join(rows) + '\n')
    if args.out or args.md:
        announce_written(args.out, args.md)


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='log_analyzer.py',
        description='昇腾现网问题日志通用分析脚本（issue-analyzer 预置脚本）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('用法示例：')[1] if '用法示例：' in __doc__ else None)
    ap.add_argument('--version', action='version',
                    version='log_analyzer.py %s' % VERSION)
    sub = ap.add_subparsers(dest='command', required=True)

    p = sub.add_parser('scan', help='L0 目录清单：文件/大小/行数/首末时间戳/类型')
    p.add_argument('--dir', required=True, help='日志包根目录')
    p.add_argument('--depth', type=int, default=None, help='目录遍历深度限制')
    p.add_argument('--skip-line-count', action='store_true',
                   help='跳过行数统计（大包提速）')
    p.add_argument('--out', help='manifest JSON 输出路径')
    p.add_argument('--md', help='manifest Markdown 输出路径')
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser('extract', help='L1 错误提取：默认模式+关键字+自定义正则+时间窗')
    p.add_argument('--dir', help='日志包根目录（与 --files 至少一个）')
    p.add_argument('--files', nargs='+', help='明确指定日志文件列表')
    p.add_argument('--depth', type=int, default=None)
    p.add_argument('--since', help='时间窗起点，如 "2026-08-28 10:00"')
    p.add_argument('--until', help='时间窗终点（只给日期时自动取当天末）')
    p.add_argument('--keywords', action='append', default=[],
                   help='关键字（逗号分隔，可多次），如 --keywords "hccl,rank"')
    p.add_argument('--patterns', action='append', default=[],
                   help='自定义正则 name:regex（可多次）')
    p.add_argument('--no-default', action='store_true', help='关闭默认模式')
    p.add_argument('--top', type=int, default=500,
                   help='每文件最多保留命中数（0=不限，默认500）')
    p.add_argument('--max-total', type=int, default=50000,
                   help='全局命中上限（默认50000）')
    p.add_argument('--max-chars', type=int, default=300,
                   help='命中行文本截断长度（默认300）')
    p.add_argument('--out', help='hits JSON 输出路径')
    p.add_argument('--md', help='hits Markdown 输出路径')
    p.add_argument('--md-rows', type=int, default=200,
                   help='Markdown 表格最多行数（默认200）')
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser('stats', help='L2 聚合分布：按模式/文件/时间桶统计 hits')
    p.add_argument('--hits', required=True, help='extract 输出的 hits JSON')
    p.add_argument('--bucket', choices=['1m', '10m', '1h', '1d'],
                   default='10m', help='时间桶粒度（默认10m）')
    p.add_argument('--md', help='stats Markdown 输出路径')
    p.add_argument('--out', help='stats JSON 输出路径')
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser('context', help='L3 聚焦取证：指定行的 ±N 行上下文')
    p.add_argument('--file', required=True, help='日志文件路径')
    p.add_argument('--line', type=int, help='目标行号')
    p.add_argument('--regex', help='目标正则（与 --line 二选一）')
    p.add_argument('--nth', type=int, default=1, help='正则第 N 次命中（默认1）')
    p.add_argument('--before', type=int, default=15, help='前文行数（默认15）')
    p.add_argument('--after', type=int, default=15, help='后文行数（默认15）')
    p.add_argument('--max-chars', type=int, default=500,
                   help='单行截断长度（默认500）')
    p.set_defaults(func=cmd_context)

    p = sub.add_parser('verify', help='证据回验：逐条核对 evidence.json')
    p.add_argument('--evidence', required=True,
                   help='evidence.json 路径（列表或 {evidence:[...]}）')
    p.add_argument('--root', help='日志包根目录（file 为相对路径时用于解析）')
    p.add_argument('--out', help='回验结果 JSON 输出路径')
    p.add_argument('--md', help='回验结果 Markdown 输出路径')
    p.add_argument('--max-chars', type=int, default=300,
                   help='实际行内容截断长度（默认300）')
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)
    if args.command in ('extract',) and not args.dir and not args.files:
        ap.error('extract 需要 --dir 或 --files')
    args.func(args)


if __name__ == '__main__':
    main()
