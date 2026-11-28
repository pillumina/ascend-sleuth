#!/usr/bin/env python3
"""Phase 0: PROF data detection & triage.

Detects single/multi-card layout, data format (db/text), framework,
existing analysis outputs, and produces a workflow plan.

Modes:
  single              单卡数据
  cluster             多卡数据（有可用卡目录）
  cluster_output_only 仅有集群输出件，使用集群模式生成总报告
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from lib.cluster_source import DB_NAMES, STEP_CSV, STEP_TABLES, db_tables, open_db
from contextlib import closing

from lib.common import is_junk, read_json, read_csv_rows
from lib import prof_data
from lib import analysis_scope

CARD_DIR_PATTERN = re.compile(r'.*_ascend_(pt|ms)$')
PROF_DIR_PATTERN = re.compile(r'^PROF_\d{6}_\d{17}_\w+$')


def limited_walk(root, max_depth=4):
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == '.' else rel.count(os.sep) + 1
        if depth >= max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if not is_junk(d)]
        yield dirpath, dirnames, filenames


def find_card_dirs(root):
    """Find card directories: *_ascend_pt / *_ascend_ms, or dirs containing
    ASCEND_PROFILER_OUTPUT directly."""
    if os.path.isdir(os.path.join(root, 'ASCEND_PROFILER_OUTPUT')):
        return [os.path.abspath(root)]
    cards = []
    for dirpath, dirnames, filenames in limited_walk(root, max_depth=4):
        for d in dirnames:
            if CARD_DIR_PATTERN.match(d):
                cards.append(os.path.join(dirpath, d))
    # Include renamed card directories as well as conventional names.
    for dirpath, dirnames, filenames in limited_walk(root, max_depth=3):
        if 'ASCEND_PROFILER_OUTPUT' in dirnames:
            cards.append(dirpath)
    return sorted(set(cards))


def read_rank(card_dir):
    for fn in os.listdir(card_dir):
        if is_junk(fn):
            continue
        m = re.match(r'^profiler_info_(\d+)\.json$', fn)
        if m:
            try:
                with open(os.path.join(card_dir, fn), encoding='utf-8') as f:
                    data = json.load(f)
                return int(data.get('rank_id', m.group(1)))
            except Exception:
                return int(m.group(1))
    # fallback: rank from profiler db filename
    apo = os.path.join(card_dir, 'ASCEND_PROFILER_OUTPUT')
    if os.path.isdir(apo):
        for fn in os.listdir(apo):
            m = re.match(r'^ascend_pytorch_profiler_(\d+)\.db$', fn)
            if m:
                return int(m.group(1))
            m = re.match(r'^ascend_mindspore_profiler_(\d+)\.db$', fn)
            if m:
                return int(m.group(1))
    return None


def read_metadata(card_dir):
    for fn in ('profiler_metadata.json',):
        p = os.path.join(card_dir, fn)
        if os.path.isfile(p):
            try:
                with open(p, encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def detect_card_format(card_dir):
    """Return (format, framework, details) for one card."""
    apo = os.path.join(card_dir, 'ASCEND_PROFILER_OUTPUT')
    files = {}
    if os.path.isdir(apo):
        for fn in os.listdir(apo):
            if is_junk(fn) or fn.endswith(('-shm', '-wal')):
                continue
            files[fn] = os.path.getsize(os.path.join(apo, fn))
    framework = 'pytorch' if any('pytorch' in f for f in files) else (
        'mindspore' if any('mindspore' in f for f in files) else None)
    if framework is None:
        framework = 'pytorch' if card_dir.endswith('_ascend_pt') else (
            'mindspore' if card_dir.endswith('_ascend_ms') else 'unknown')
    db_errors = []
    valid_dbs = []
    for fn, size in files.items():
        if fn.endswith('.db') and re.match(r'^(ascend_(pytorch|mindspore)_profiler_|msprof_)', fn) and size:
            try:
                uri = Path(apo, fn).resolve().as_uri() + '?mode=ro&immutable=1'
                with closing(sqlite3.connect(uri, uri=True)) as conn:
                    if conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                        valid_dbs.append(fn)
            except sqlite3.Error as e:
                db_errors.append(f'{fn}: {e}')
    has_db = bool(valid_dbs)
    has_insight_db = 'mindstudio_insight_data.db' in files and files.get('mindstudio_insight_data.db', 0) > 0
    text_keys = ('kernel_details.csv', 'op_statistic.csv', 'operator_details.csv',
                 'api_statistic.csv', 'step_trace_time.csv', 'trace_view.json')
    has_text = any(files.get(k, 0) > 0 for k in text_keys)
    export_type = []
    for fn in sorted(os.listdir(card_dir)):
        if fn.startswith('profiler_info') and fn.endswith('.json'):
            info = read_json(os.path.join(card_dir, fn)) or {}
            config = info.get('config') or {}
            export_type = (config.get('experimental_config') or {}).get('_export_type', [])
            if isinstance(export_type, str):
                export_type = [export_type]
            export_type = [str(v).lower() for v in export_type] if isinstance(export_type, list) else []
            break
    step_rows = analysis_scope.load_steps(apo)
    valid_steps = bool(step_rows) and all(
        analysis_scope.number(r.get('Stage')) is not None and
        analysis_scope.number(r.get('Stage')) > 0 for r in step_rows)
    empty_profiler_db = any(re.match(r'^ascend_(pytorch|mindspore)_profiler_\d+\.db$', f)
                            and files[f] == 0 for f in files)
    # DB 适配能力探测（WAL 感知只读）：analysis.db StepTraceTime / CommAnalyzer*
    # 与主 DB 元数据表；TEXT 缺失时这些能力支撑基础分析链路。
    db_caps = prof_data.db_capabilities(apo) if os.path.isdir(apo) else {}
    # analysis-only is a valid source; a main profiler DB is not required.
    has_db = has_db or bool(db_caps.get('step_summary'))
    db_step_scope = None
    if db_caps.get('step_summary'):
        db_step_scope = ('step' if db_caps.get('step_rows') else 'capture_window')
    if has_text and ('text' in export_type or not has_db):
        fmt = 'text'
    elif has_db:
        fmt = 'db'
    elif has_text:
        fmt = 'text'
    elif has_insight_db:
        fmt = 'insight_db'
    else:
        fmt = 'none'
    has_step_summary = valid_steps
    _, device_id, device_source = prof_data.read_rank_device(apo)
    capabilities = {'fallback_advisor': has_step_summary,
                    'fallback_compare': has_step_summary,
                    'fallback_cluster': has_step_summary,
                    # swimlane 数据源：trace_view.json 或任一 CSV 降级源
                    'swimlane': any(files.get(k, 0) > 0 for k in
                                    ('trace_view.json', 'kernel_details.csv',
                                     'api_statistic.csv', 'operator_details.csv'))}
    detail = {'apo_files': {k: v for k, v in files.items()},
              'empty_profiler_db': empty_profiler_db,
              'has_insight_db': has_insight_db,
              'has_db': has_db, 'has_text': has_text,
              'export_type': export_type, 'db_errors': db_errors,
              'step_ids': sorted({str(r['Step']) for r in step_rows if r.get('Step') is not None}),
              'known_step_ids': sorted({str(r['Step']) for r in step_rows if r['_scope'] == 'step'}),
              'analysis_scope': analysis_scope.scope_of(step_rows),
              'synthetic_step': analysis_scope.scope_of(step_rows) == 'whole_prof',
              '_analysis_rows': step_rows,
              'capabilities': capabilities}
    if db_caps:
        detail['db_capabilities'] = db_caps
        detail['db_step_scope'] = db_step_scope
        detail['db_window_count'] = db_caps.get('window_rows', 0)
    if device_id is not None:
        detail['device_id'] = device_id
        detail['device_id_source'] = device_source
    return fmt, framework, detail


def check_cluster_output(root):
    """Inspect existing cluster_analysis_output under root."""
    out = {'exists': False, 'path': None, 'has_db': False, 'tables': [],
           'text_files': [], 'recipes_done': False, 'recipe_files': []}
    direct = any(os.path.isfile(os.path.join(root, fn)) for fn in (*DB_NAMES, STEP_CSV))
    p = root if direct else os.path.join(root, 'cluster_analysis_output')
    if not os.path.isdir(p):
        return out
    out['exists'] = True
    out['path'] = p
    out['source_files'] = [fn for fn in (*DB_NAMES, STEP_CSV) if os.path.isfile(os.path.join(p, fn))]
    for name in DB_NAMES:
        db = os.path.join(p, name)
        if not os.path.isfile(db) or os.path.getsize(db) == 0:
            continue
        try:
            with closing(open_db(db)) as conn:
                tables = db_tables(conn)
                has_steps = any(conn.execute(f'SELECT 1 FROM "{tables[t.lower()]}" LIMIT 1').fetchone()
                                for t in STEP_TABLES if t.lower() in tables)
            if has_steps:
                out.update(has_db=True, db_path=db, tables=list(tables.values()))
                break
        except sqlite3.Error as e:
            out['error'] = str(e)
    for fn in os.listdir(p):
        if is_junk(fn):
            continue
        if fn == STEP_CSV and read_csv_rows(os.path.join(p, fn)):
            out['text_files'].append(fn)
            out['step_csv'] = os.path.join(p, fn)
    rdir = os.path.join(p, 'recipes')
    if os.path.isdir(rdir):
        out['recipe_files'] = [f for f in os.listdir(rdir) if not is_junk(f)]
    summary = read_json(os.path.join(p, 'recipes_summary.json'))
    if isinstance(summary, dict):
        statuses = [r for cat in summary.get('categories', []) for r in cat.get('recipes', [])]
        out['recipes_done'] = len(statuses) == 23 and all(r.get('status') in ('done', 'unsupported') for r in statuses)
    return out


def check_existing_outputs(root):
    res = {'advisor': [], 'compare': []}
    for dirpath, dirnames, filenames in limited_walk(root, max_depth=3):
        for fn in filenames:
            if is_junk(fn):
                continue
            if fn.startswith('mstt_advisor_'):
                res['advisor'].append(os.path.join(dirpath, fn))
            elif fn.startswith('performance_comparison_result_'):
                res['compare'].append(os.path.join(dirpath, fn))
    return res


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--path', required=True, help='PROF input path (card dir or multi-card root)')
    parser.add_argument('--output', required=True, help='output json path')
    parser.add_argument('--skill-dir', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = parser.parse_args()

    root = os.path.abspath(args.path)
    if not os.path.isdir(root):
        print(f'ERROR: path not found: {root}', file=sys.stderr)
        sys.exit(1)

    card_dirs = find_card_dirs(root)
    cards = []
    scope_cache = {'version': 1, 'cards': {}}
    for cd in card_dirs:
        rank = read_rank(cd)
        fmt, fw, detail = detect_card_format(cd)
        apo = os.path.join(cd, 'ASCEND_PROFILER_OUTPUT')
        scope_cache['cards'][os.path.normcase(os.path.abspath(apo))] = {
            'signature': analysis_scope.input_signature(apo), 'rows': detail['_analysis_rows']}
        meta = read_metadata(cd)
        dist = meta.get('distributed_args', {}) if isinstance(meta, dict) else {}
        cards.append({
            'rank': rank if rank is not None else len(cards),
            'dir': cd,
            'format': fmt,
            'framework': fw,
            'usable': fmt != 'none',
            'world_size': dist.get('world_size'),
            'empty_profiler_db': detail['empty_profiler_db'],
            'has_insight_db': detail['has_insight_db'],
            'export_type': detail['export_type'],
            'available_artifacts': {'db': detail['has_db'], 'text': detail['has_text']},
            'capabilities': detail['capabilities'],
            'step_ids': detail['step_ids'],
            'known_step_ids': detail['known_step_ids'],
            'analysis_scope': detail['analysis_scope'],
            'synthetic_step': detail['synthetic_step'],
            'warnings': detail['db_errors'],
        })
        if detail.get('db_capabilities'):
            cards[-1]['db_capabilities'] = detail['db_capabilities']
            cards[-1]['db_step_scope'] = detail.get('db_step_scope')
            cards[-1]['db_window_count'] = detail.get('db_window_count', 0)
        if detail.get('device_id') is not None:
            cards[-1]['device_id'] = detail['device_id']
            cards[-1]['device_id_source'] = detail['device_id_source']
    cards.sort(key=lambda c: c['rank'])

    frameworks = {c['framework'] for c in cards if c['framework']}
    mixed = len([f for f in frameworks if f in ('pytorch', 'mindspore')]) > 1
    usable_n = len([c for c in cards if c['usable']])
    mode = 'cluster' if usable_n > 1 else 'single'

    parents = {os.path.dirname(c['dir']) for c in cards if c['usable']}
    card_root = next(iter(parents)) if len(parents) == 1 and root not in card_dirs else root
    cluster = check_cluster_output(root)
    if not (cluster['has_db'] or cluster['text_files']) and card_root != root:
        nested = check_cluster_output(card_root)
        if nested['has_db'] or nested['text_files'] or not cluster.get('source_files'):
            cluster = nested
    has_data = bool(cluster['has_db'] or cluster['text_files'])
    if has_data:
        mode = 'cluster' if usable_n else 'cluster_output_only'
    cluster_root = card_root if mode in ('cluster', 'cluster_output_only') else None
    cluster['expected_path'] = os.path.join(card_root, 'cluster_analysis_output')

    existing = check_existing_outputs(root)

    if mode == 'cluster_output_only':
        steps = {'cluster': 'reuse supplied aggregate', 'recipes': 'run supported recipes',
                 'report_mode': 'cluster'}
    else:
        steps = {
            'advisor': 'run per card',
            'swimlane': 'run per card',
            'cluster': ('skip: output exists' if cluster and cluster['exists'] and (
                cluster['has_db'] or cluster['text_files']) else 'generate') if mode == 'cluster' else 'skip: single card',
            'recipes': ('check and run missing' if not (cluster and cluster['recipes_done'])
                        else 'skip: already done') if mode == 'cluster' else 'skip: single card',
            'compare': 'select max/min comm-ratio cards and compare' if mode == 'cluster' else 'skip: single card',
            'report_mode': mode,
        }

    result = {
        'input': root,
        'mode': mode,
        'mixed_framework': mixed,
        'cards': cards,
        'cluster_root': cluster_root,
        'cluster_output': cluster,
        'existing_outputs': existing,
        'steps': steps,
    }
    observed = sorted({c['rank'] for c in cards if c['usable']})
    expected = sorted({int(c['world_size']) for c in cards if c.get('world_size')})
    world = max(expected) if expected else None
    result['coverage'] = {'observed_ranks': observed, 'expected_world_size': world,
                          'missing_ranks': sorted(set(range(world)) - set(observed)) if world else [],
                          'unique_step_count': len({s for c in cards for s in c['step_ids']}),
                          'rank_step_samples': sum(len(c['step_ids']) for c in cards),
                          'known_step_count': len({s for c in cards for s in c['known_step_ids']}),
                          'synthetic_step_ranks': sorted({c['rank'] for c in cards if c['synthetic_step']}),
                          'analysis_scopes': sorted({c['analysis_scope'] for c in cards if c['analysis_scope']}),
                          'db_window_count': sum(c.get('db_window_count', 0) for c in cards),
                          'db_step_scopes': sorted({c.get('db_step_scope') for c in cards
                                                    if c.get('db_step_scope')}),
                          'device_ids': {str(c['rank']): c['device_id'] for c in cards
                                         if c.get('device_id') is not None},
                          'world_size_conflict': len(expected) > 1}
    if mixed:
        result['error'] = 'PyTorch and MindSpore data mixed in one root; analyze separately.'

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(os.path.join(os.path.dirname(os.path.abspath(args.output)), 'analysis_scope_cache.json'),
              'w', encoding='utf-8') as f:
        json.dump(scope_cache, f, ensure_ascii=False, indent=2)

    print(f"mode={mode} cards={len(cards)} formats={[c['format'] for c in cards]}")
    if mode == 'cluster_output_only':
        print('仅有集群输出件，将生成集群总报告，跳过卡级分析。')
    if cluster:
        print(f"cluster_output exists={cluster['exists']} recipes_done={cluster['recipes_done']}")
    for c in cards:
        scope = f" db_scope={c['db_step_scope']}" if c.get('db_step_scope') else ''
        dev = f" device={c['device_id']}" if c.get('device_id') is not None else ''
        print(f"  rank={c['rank']} fmt={c['format']} fw={c['framework']} usable={c['usable']}{scope}{dev}")
    print(f'written: {args.output}')


if __name__ == '__main__':
    main()
