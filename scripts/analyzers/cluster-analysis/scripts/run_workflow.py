#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cluster-analysis 端到端 workflow 编排器。

用法：
  python run_workflow.py --input <prof路径>            # 单卡目录或多卡根目录
  python run_workflow.py --input <集群输出或Prof> --force  # 重算派生结果
  python run_workflow.py --input <...> --no-native     # 禁用原生 CLI，全部使用内置实现

默认原生优先：探测到 msprof-analyze 时各阶段优先用原生 CLI，失败或产物不合规
自动回退内置 fallback 实现（fallback 同时负责归一化总报告契约所需的中间件）。

阶段（依赖顺序执行；仅输入/参数/代码指纹一致的完整缓存可复用）：
  1 detect    探测输入：单卡/多卡、数据格式、已有输出件 -> detect_result.json
  2 advisor   专家建议 all 场景（单卡=单卡 advisor；多卡=对全部卡一次 advisor）
              -> advisor/advisor.md + advisor.json
  3 cluster   多卡且缺 cluster_analysis_output 时生成（位于 prof 根目录，
              与各卡目录同级）-> cluster_analysis_output/
  4 recipes   集群输入使用同一时间汇总与 23+1 个 recipe
              已提供集群输出时 -> <中间件>/cluster_summary/
  5 compare   多卡：自动选通信占比最大/最小两卡做性能比对
              -> compare/compare_analysis_result.json + performance_comparison_result_*.xlsx
  6 prof-compare  使用内置 prof-compare 生成双卡比对子报告
              -> reports/compare_analysis_report.html（有 xlsx 时）
  7 swimlane  每张卡泳道 TopN 最长算子 + 全算子 7 列统计；多卡生成横向比对
              -> swimlane/swimlane_rank{N}.{md,json} + swimlane_compare.md
  8 report    生成总 HTML 报告（信息概览优先、左侧固定导航、章节可折叠、
              按需嵌入 prof-compare、无卡片清单）
              -> performance_report.html（与全部中间件同目录）
"""
import argparse
import glob
import os
from pathlib import Path
import shutil
import subprocess
import sys
import json
import time
import signal

from lib.common import read_json
from lib.cluster_source import source_signature
from lib.config import MW_NAME, PROF_COMPARE_REPORT, VENDOR_RC_SKIP
from lib.workflow_state import WorkflowState, cache_key, write_json

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SKILL_DIR, 'scripts')
STATE = None
COMMAND_TIMEOUT = 300
SCOPE_CACHE_FILE = None


def sh(cmd, cwd=None, timeout=None):
    print('[run] ' + ' '.join(os.path.relpath(c, SKILL_DIR)
                              if os.path.isabs(c) and c.startswith(SKILL_DIR) else c
                              for c in cmd))
    stage = None
    if len(cmd) > 1 and str(cmd[1]).endswith('.py'):
        stage = os.path.basename(cmd[1]).replace('.py', '')
        if stage == 'vendor_bridge':
            stage += '_' + cmd[2]
        if stage == 'swimlane_analyzer' and '--rank' in cmd:
            stage += '_rank' + cmd[cmd.index('--rank') + 1]
    try:
        env = dict(os.environ)
        env.pop('CLUSTER_ANALYSIS_SCOPE_CACHE', None)
        if SCOPE_CACHE_FILE and stage != 'detect_prof':
            env['CLUSTER_ANALYSIS_SCOPE_CACHE'] = SCOPE_CACHE_FILE
        p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                             text=True, encoding='utf-8', errors='replace',
                             start_new_session=os.name != 'nt')
        try:
            stdout, stderr = p.communicate(timeout=timeout or COMMAND_TIMEOUT)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'],
                               capture_output=True, timeout=10)
            else:
                os.killpg(p.pid, signal.SIGKILL)
            p.kill() if p.poll() is None else None
            p.communicate(timeout=10)
            raise
    except (OSError, subprocess.TimeoutExpired) as e:
        out = f'{type(e).__name__}: {e}'
        print('  | ERROR: ' + out)
        if STATE:
            if stage:
                STATE.record(stage, 'failed', out)
            else:
                STATE.data['warnings'].append(out)
        return 1, out
    out = ((stdout or '') + (stderr or '')).strip()
    if out:
        for line in out.splitlines()[-25:]:
            print('  | ' + line)
    if STATE:
        if stage:
            status = 'done' if p.returncode == 0 else 'failed'
            if stage == 'vendor_bridge_compare' and p.returncode == VENDOR_RC_SKIP:
                status = 'unsupported'
            STATE.record(stage, status, out)
        elif p.returncode:
            STATE.data['warnings'].append(out[-1500:])
    return p.returncode, out


def script(name):
    return os.path.join(SCRIPTS, name)


def detect_msprof_cli():
    exe = shutil.which('msprof-analyze')
    return exe


def select_compare_cards(root, base_rank=None, compare_rank=None):
    """复用 compare_fallback 的选卡逻辑：通信占比最小=baseline，最大=compare。

    返回 (baseline_card, compare_card, tag) 或 None（不可选卡时）。
    """
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    try:
        import compare_fallback as cf
    except Exception as e:
        print(f'[compare] 选卡模块不可用：{e}')
        return None
    cards = cf.find_cards(root)
    if len(cards) < 2:
        print(f'[compare] 可用卡数 {len(cards)} < 2，跳过原生 compare')
        return None
    by_ratio = sorted(cards, key=lambda c: (c['comm_ratio'],
                                            c['trace']['Communication(Not Overlapped)']))
    min_card, max_card = by_ratio[0], by_ratio[-1]
    if base_rank is not None:
        cand = [c for c in cards if c['rank'] == base_rank]
        if not cand:
            print(f'[compare] --base-rank {base_rank} 不存在，跳过原生 compare')
            return None
        min_card = cand[0]
    if compare_rank is not None:
        cand = [c for c in cards if c['rank'] == compare_rank]
        if not cand:
            print(f'[compare] --compare-rank {compare_rank} 不存在，跳过原生 compare')
            return None
        max_card = cand[0]
    return min_card, max_card, f"{max_card['rank']}_{min_card['rank']}"


def pick_native_xlsx(out_dir):
    """在原生产出目录中查找 compare xlsx，优先 performance_comparison_result 命名。"""
    hits = []
    for dirpath, _, filenames in os.walk(out_dir):
        for fn in filenames:
            if fn.lower().endswith('.xlsx'):
                hits.append(os.path.join(dirpath, fn))
    if not hits:
        return None
    pref = [h for h in hits
            if os.path.basename(h).lower().startswith('performance_comparison_result')]
    return (pref or hits)[0]


def native_compare(cli, root, cmp_dir, base_rank=None, compare_rank=None):
    """原生 msprof-analyze compare：选卡 -> 原生比对 -> 归一化 xlsx 命名。

    返回 True 表示原生 xlsx 已就位；失败/产物缺失返回 False（调用方回退内置实现）。
    """
    sel = select_compare_cards(root, base_rank, compare_rank)
    if not sel:
        return False
    min_card, max_card, tag = sel
    out_dir = os.path.join(cmp_dir, 'native')
    os.makedirs(out_dir, exist_ok=True)
    print(f"[compare] 原生 compare：baseline rank {min_card['rank']} vs "
          f"compare rank {max_card['rank']}")
    rc, _ = sh([cli, 'compare', '-d', min_card['dir'], '-c', max_card['dir'], '-o', out_dir],
               cwd=root)
    if rc != 0:
        print('[compare] 原生 compare 失败，回退内置实现')
        return False
    src = pick_native_xlsx(out_dir)
    if not src:
        print('[compare] 原生输出未找到 xlsx，回退内置实现')
        return False
    dst = os.path.join(cmp_dir, f'performance_comparison_result_{tag}.xlsx')
    shutil.copyfile(src, dst)
    # 清理历史比对的 xlsx，只保留本次选卡结果
    for old in glob.glob(os.path.join(cmp_dir, 'performance_comparison_result_*.xlsx')):
        if os.path.abspath(old) != os.path.abspath(dst):
            try:
                os.remove(old)
            except OSError:
                pass
    print(f'[compare] 原生 xlsx 已归一化：{dst}')
    return True


def execute_workflow():
    global SCOPE_CACHE_FILE
    from lib import analysis_scope
    SCOPE_CACHE_FILE = None
    analysis_scope.use_cache_file(None)
    global STATE, COMMAND_TIMEOUT
    ap = argparse.ArgumentParser(
        description='cluster-analysis 端到端性能分析 workflow',
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument('--input', required=True, help='卡级 Prof、集群根目录或已有 cluster_analysis_output')
    ap.add_argument('--output-dir', default=None,
                    help=f'中间件与报告目录（默认 <prof根>/{MW_NAME}）')
    ap.add_argument('--force', action='store_true', help='重算派生结果，保留用户提供的集群输出')
    ap.add_argument('--top-num', type=int, default=20, help='cluster/泳道 TopN（默认 20）')
    ap.add_argument('--base-rank', type=int, default=None, help='比对基准卡（默认自动选通信占比最小）')
    ap.add_argument('--compare-rank', type=int, default=None, help='比对目标卡（默认自动选通信占比最大）')
    ap.add_argument('--msprof-cli', action='store_true',
                    help='（兼容保留）原生优先已默认启用，此开关等价于缺省行为')
    ap.add_argument('--no-native', action='store_true',
                    help='禁用原生 msprof-analyze，所有阶段直接使用内置 fallback 实现')
    ap.add_argument('--skip-recipes', action='store_true')
    ap.add_argument('--skip-compare', action='store_true')
    ap.add_argument('--skip-swimlane', action='store_true')
    ap.add_argument('--skip-report', action='store_true')
    ap.add_argument('--report-mode', choices=['single', 'cluster', 'compare'], default=None,
                    help='覆盖报告模式（默认按探测结果）')
    ap.add_argument('--timeout', type=float, default=300, help='每个子命令的超时秒数（默认300）')
    ap.add_argument('--recipe-timeout', type=float, default=7200,
                    help='已提供集群输出时的 recipe 超时秒数（默认7200）')
    args = ap.parse_args()

    root = os.path.abspath(args.input)
    if not os.path.isdir(root):
        print(f'ERROR: 输入路径不存在: {root}')
        return 1
    mw = os.path.abspath(args.output_dir) if args.output_dir else os.path.join(root, MW_NAME)
    os.makedirs(mw, exist_ok=True)
    STATE = WorkflowState(mw, root)
    COMMAND_TIMEOUT = args.timeout
    if args.timeout <= 0 or args.recipe_timeout <= 0 or args.top_num <= 0:
        STATE.data['errors'].append('timeout, recipe-timeout and top-num must be positive')
        return 1
    params = {k: v for k, v in vars(args).items() if k not in ('input', 'output_dir', 'force')}
    STATE.key = cache_key(root, mw, SKILL_DIR, params)
    previous = read_json(os.path.join(mw, 'workflow_cache.json')) or {}
    previous_state = read_json(os.path.join(mw, 'workflow_status.json')) or {}
    if not isinstance(previous, dict):
        previous = {}
    if not isinstance(previous_state, dict):
        previous_state = {}
    cache_valid = previous.get('status') == 'complete' and previous.get('key') == STATE.key
    if not cache_valid:
        print('[cache] 输入、参数或脚本已变化（或无完整缓存），重新生成分析产物')
        args.force = True
    STATE.data['cache_reused'] = cache_valid and not args.force
    if args.force:
        managed = ['advisor', 'swimlane', 'compare', 'reports', 'performance_report.html',
                   'detect_result.json', 'workflow_status.json', 'insight_bottlenecks.json',
                   'insight_bottlenecks.md', 'insight_bottlenecks.html']
        old_paths = [os.path.join(mw, name) for name in managed if os.path.exists(os.path.join(mw, name))]
        if old_paths:
            history = os.path.join(mw, '_history', str(time.time_ns()))
            os.makedirs(history)
            for old in old_paths:
                shutil.move(old, os.path.join(history, os.path.basename(old)))
            STATE.data['previous_outputs'] = history
    want_native = not args.no_native
    cli = detect_msprof_cli() if want_native else None
    if not want_native:
        print('[cli] 已禁用原生（--no-native），使用内置 fallback 实现')
    elif cli:
        print('[cli] 原生优先已启用：可用则原生，失败自动回退内置实现')
    else:
        print('[cli] msprof-analyze 未安装，使用内置 fallback 实现')

    # ---------- 1 detect ----------
    detect_json = os.path.join(mw, 'detect_result.json')
    # Detection is cheap and always refreshed (including corrupt/stale caches).
    rc, _ = sh([sys.executable, script('detect_prof.py'),
                '--path', root, '--output', detect_json])
    if rc != 0:
        print('ERROR: 探测失败')
        return 1
    det = read_json(detect_json)
    if not isinstance(det, dict):
        print('ERROR: detect_result.json 无法读取，无法继续（可尝试 --force 重跑）')
        return 1
    SCOPE_CACHE_FILE = os.path.join(mw, 'analysis_scope_cache.json')
    analysis_scope.use_cache_file(SCOPE_CACHE_FILE)
    mode = 'cluster' if det.get('mode') == 'cluster_output_only' else det.get('mode', 'single')
    cards = [c for c in det.get('cards', []) if c.get('usable')]
    cl = det.get('cluster_output') or {}
    cl_exists = mode == 'cluster' and bool(cl.get('db_path') or cl.get('step_csv'))
    cluster_signature = source_signature(cl.get('db_path'), cl.get('step_csv')) if cl_exists else []
    generated = (cl_exists and bool(cards) and cl.get('db_path') and not cl.get('step_csv')
                 and cluster_signature == previous_state.get('generated_cluster_db'))
    if det.get('mixed_framework'):
        print('ERROR: ' + det['error'])
        return 1
    print(f'[detect] mode={mode} cards={len(cards)}')
    STATE.data['coverage'] = det.get('coverage', {})
    if not cl_exists and cl.get('source_files') and (mode != 'single' or not cards):
        message = '已有集群输出缺少可读的 Rank × Step 摘要，请检查集群数据源'
        STATE.data['errors'].append(message)
        print('ERROR: ' + message)
        return 1
    if not cards and not cl_exists:
        message = det.get('error') or '找不到可用的卡级 Prof 采集目录。'
        STATE.data['errors'].append(message)
        print(f'ERROR: {message}')
        return 1

    root = det.get('cluster_root') or (cards[0]['dir'] if mode == 'single' else root)
    STATE.data['normalized_root'] = root
    # 分析级能力门槛（替代原"所有卡必须有 step CSV"的全局门槛）：
    # 有 step CSV 或 analysis.db StepTraceTime（有效 step 或采集窗）即可进入基础链路；
    # 无任何 step 能力的卡仅跳过依赖 step 的分析，不阻断其他卡。
    no_step_cards = [c['rank'] for c in cards
                     if not c.get('capabilities', {}).get('fallback_advisor')]
    advisor_available = len(cards) > len(no_step_cards)
    if cards and not advisor_available and not cl_exists:
        message = ('所有卡均无有效摘要或可推导的整段 prof 时间范围；'
                   '请提供 step_trace_time.csv、analysis.db 等 CSV/DB 数据或可读事件/会话时间。')
        STATE.data['errors'].append(message)
        STATE.record('preflight', 'failed', message)
        print('ERROR: ' + message)
        return 1
    if no_step_cards:
        message = (f'rank {no_step_cards} 无 step/window 摘要（CSV 与 analysis.db 均缺），'
                   f'相关卡级分析将降级或跳过，不影响其他卡。')
        STATE.data['warnings'].append(message)
        print('WARN: ' + message)
    db_only = [c['rank'] for c in cards
               if c.get('db_step_scope') and not c.get('available_artifacts', {}).get('text')]
    if db_only:
        print(f"[preflight] DB-only 卡 {db_only}：使用 analysis.db 适配（无 CSV 依赖）")
    STATE.record('preflight', 'done',
                 ('step capability check passed' if advisor_available else 'using cluster aggregate')
                 + (f'; db_only ranks={db_only}' if db_only else ''))
    whole_prof_ranks = [c['rank'] for c in cards if c.get('synthetic_step')]
    if whole_prof_ranks:
        print(f'[scope] rank {whole_prof_ranks}：整个 prof 作为一个汇总 step（prof），使用共享内置口径')
        STATE.data['step_policy'] = 'unsegmented_prof_is_one_synthetic_step'
        STATE.data['whole_prof_ranks'] = whole_prof_ranks
        STATE.data['backend_policy'] = 'built-in normalization for whole-prof scope'
        # Native versions may invent step0 or ignore empty steps. Use one policy
        # for the entire run instead of mixing native and normalized outputs.
        cli = None
    capabilities = {}
    if cli and cards:
        for command in ('advisor', 'cluster', 'compare'):
            if command in ('cluster', 'compare') and mode != 'cluster':
                continue
            rc, _ = sh([cli, command, '--help'])
            capabilities[command] = rc == 0
        STATE.data['native_capabilities'] = capabilities

    for sub in ('advisor', 'swimlane', 'compare', 'reports'):
        os.makedirs(os.path.join(mw, sub), exist_ok=True)

    # ---------- 2 advisor（单卡=单卡 advisor；多卡=对全部卡一次 advisor） ----------
    adv_md = os.path.join(mw, 'advisor', 'advisor.md')
    if not advisor_available:
        STATE.record('advisor_fallback', 'unsupported', '缺少可用卡级时间摘要')
    elif args.force or not os.path.isfile(adv_md) or not isinstance(read_json(os.path.join(mw, 'advisor', 'advisor.json')), dict):
        target = root if mode == 'cluster' else (cards[0]['dir'] if cards else root)
        if cli and capabilities.get('advisor'):  # 原生 CLI 产出 mstt_advisor_* 文件，仅供留档
            sh([cli, 'advisor', 'all', target, '-o', os.path.join(mw, 'advisor')])
        # 始终用内置实现归一化出 advisor.md + advisor.json（总报告契约）
        rc, _ = sh([sys.executable, script('advisor_fallback.py'),
                    '--root', target, '--output', os.path.join(mw, 'advisor')])
        if rc != 0:
            print('WARN: advisor 阶段失败，报告将以缺省内容继续')
    else:
        print('[skip] advisor 已存在')
        STATE.record('advisor_fallback', 'reused')

    # ---------- 3 cluster（多卡且缺失时生成） ----------
    if mode == 'cluster' and (not cl_exists or (generated and args.force)):
        from detect_prof import check_cluster_output
        done = False
        if cli and capabilities.get('cluster'):
            rc, _ = sh([cli, 'cluster', 'analysis', '-d', root, '--top_num', str(args.top_num)],
                       cwd=root)
            cl = check_cluster_output(root)
            done = rc == 0 and bool(cl.get('db_path') or cl.get('step_csv'))
        if not done:
            rc, _ = sh([sys.executable, script('cluster_fallback.py'), '--root', root]
                       + (['--force'] if args.force else []))
            if rc != 0:
                print('ERROR: 集群时间汇总无法生成')
                return 1
            cl = check_cluster_output(root)
            generated = True
        else:
            STATE.record('cluster_fallback', 'done', '使用原生集群分析产物')
            generated = False
            if not args.skip_recipes:
                for recipe in ('cluster_time_summary', 'communication_time_sum', 'slow_rank',
                               'slow_link', 'communication_bottleneck', 'free_analysis',
                               'compute_op_sum', 'hccl_sum'):
                    sh([cli, 'cluster', 'analysis', '-d', root, recipe, '--top_num', str(args.top_num)])
                cl = check_cluster_output(root)
    else:
        print('[skip] cluster_analysis_output 已存在' if mode == 'cluster'
              else '[skip] 单卡无需 cluster 阶段')
        STATE.record('cluster_fallback', 'reused' if mode == 'cluster' else 'skipped')

    # ---------- 4 recipes（已有集群输出按来源只读，先发布基础耗时汇总） ----------
    if mode == 'cluster':
        db_path, step_csv = cl.get('db_path'), cl.get('step_csv')
        signature = source_signature(db_path, step_csv)
        separate = not generated or args.skip_recipes
        report_data_dir = os.path.join(mw, 'cluster_summary') if separate else cl['path']
        if separate:
            work_path = Path(mw).resolve()
            derived_path = Path(report_data_dir).resolve()
            input_path = Path(cl['path']).resolve()
            if derived_path in (input_path, *input_path.parents):
                report_data_dir = os.path.join(mw, 'cluster_report_data')
                derived_path = Path(report_data_dir).resolve()
            if derived_path.parent != work_path or derived_path in (input_path, *input_path.parents):
                raise ValueError('集群汇总产物目录与源目录冲突')
        cl['report_data_dir'] = report_data_dir
        det['cluster_output'] = cl
        summary_file = os.path.join(report_data_dir, 'recipes_summary.json')
        summary = read_json(summary_file) or {}
        if not args.force and summary.get('time_summary') and (
                summary.get('source_signature') == signature if separate else cl.get('recipes_done')):
            STATE.record('recipe_fallback', 'reused')
        else:
            STATE.data['cache_reused'] = False
            if separate and derived_path.is_dir():
                history = (work_path / '_history' / str(time.time_ns())).resolve()
                if work_path not in history.parents:
                    raise ValueError('集群汇总历史目录位于中间件目录之外')
                history.mkdir(parents=True)
                shutil.move(report_data_dir, history / derived_path.name)
            recipe_cmd = [sys.executable, script('recipe_fallback.py'), '--root', root,
                          '--top-num', str(args.top_num)]
            if separate:
                recipe_cmd += ['--output-dir', report_data_dir]
                if db_path:
                    recipe_cmd += ['--cluster-db', db_path]
                if step_csv:
                    recipe_cmd += ['--step-csv', step_csv]
                if args.skip_recipes:
                    recipe_cmd.append('--summary-only')
            sh(recipe_cmd, timeout=args.recipe_timeout if separate else None)
            summary = read_json(summary_file) or {}
        if separate and (summary.get('source_signature') != signature or signature != source_signature(db_path, step_csv)):
            STATE.data['errors'].append('集群汇总未生成，或集群源在分析期间发生变化')
            return 1
        summary_rows = summary.get('time_summary') or []
        if not summary_rows:
            STATE.data['errors'].append('集群报告缺少可用的 Rank × Step 时间汇总')
            return 1
        if generated:
            STATE.data['generated_cluster_db'] = source_signature(db_path, step_csv)
        det['cluster_coverage'] = {
            'rank_count': len({row['rank'] for row in summary_rows}),
            'step_count': len({row['step'] for row in summary_rows}),
            'rank_step_samples': len(summary_rows),
        }
        STATE.data['cluster_coverage'] = det['cluster_coverage']
        write_json(detect_json, det)
    else:
        STATE.record('recipe_fallback', 'skipped')

    # ---------- 5 compare（多卡：通信占比最大/最小两卡） ----------
    cmp_json = os.path.join(mw, 'compare', 'compare_analysis_result.json')
    cmp_ok = False
    compare_reused = False
    compare_data_available = True
    if mode == 'cluster' and len(cards) >= 2 and not args.skip_compare:
        from compare_fallback import find_cards as find_comparable_cards
        compare_data_available = len(find_comparable_cards(root)) >= 2
        if not compare_data_available:
            STATE.record('compare_fallback', 'unsupported',
                         'fewer than two ranks have valid Stage and uncovered communication metrics')
            STATE.data['warnings'].append('双卡比较证据不足：需要两卡有效 Stage 与未掩盖通信指标；已保留其他分析。')
    if mode == 'cluster' and len(cards) >= 2 and not args.skip_compare and compare_data_available:
        cached_compare = read_json(cmp_json) or {}
        selected = select_compare_cards(root, args.base_rank, args.compare_rank)
        expected_pair = [selected[0]['rank'], selected[1]['rank']] if selected else None
        actual_pair = [cached_compare.get('base_card', {}).get('rank'), cached_compare.get('compare_card', {}).get('rank')]
        if args.force or not cached_compare.get('overall_metrics') or actual_pair != expected_pair:
            cmp_dir = os.path.join(mw, 'compare')
            rank_args = (['--base-rank', str(args.base_rank)]
                         if args.base_rank is not None else []) + \
                        (['--compare-rank', str(args.compare_rank)]
                         if args.compare_rank is not None else [])
            native_ok = False
            if cli and capabilities.get('compare'):
                native_ok = native_compare(cli, root, cmp_dir,
                                           base_rank=args.base_rank,
                                           compare_rank=args.compare_rank)
            if native_ok:
                # 原生 xlsx 已就位，仅补产总报告所需中间件 JSON
                rc, _ = sh([sys.executable, script('compare_fallback.py'), '--root', root,
                            '--output', cmp_dir, '--json-only'] + rank_args)
                if rc != 0 or not os.path.isfile(cmp_json):
                    print('[compare] 中间件 JSON 补产失败，回退完整内置实现')
                    native_ok = False
            if native_ok:
                rc = 0
                print('[compare] 原生 compare 成功：xlsx 来自 msprof-analyze，'
                      'JSON 由内置实现补产')
            else:
                rc, _ = sh([sys.executable, script('compare_fallback.py'), '--root', root,
                            '--output', cmp_dir] + rank_args)
            cmp_ok = rc == 0 and os.path.isfile(cmp_json)
        else:
            cmp_ok = True
            compare_reused = True
            print('[skip] compare 已存在')
            STATE.record('compare_fallback', 'reused')
    else:
        if mode == 'cluster' and len(cards) < 2 and not args.skip_compare:
            STATE.record('compare_fallback', 'unsupported', '需要两张可比对的卡级 Prof')
        print('[skip] compare（已禁用或缺少两张可比对的卡级 Prof）')

    STATE.record('vendor_bridge_compare', 'skipped')

    # ---------- 7 swimlane（每卡 TopN + 全算子统计；多卡横向比对） ----------
    if not args.skip_swimlane and cards:
        sw_dir = os.path.join(mw, 'swimlane')
        swimlane_cards = []
        for c in cards:
            if not c.get('capabilities', {}).get('swimlane'):
                # 无任何泳道数据源（trace_view.json / kernel_details.csv /
                # api_statistic.csv / operator_details.csv，如 DB-only）：
                # 记录 unsupported 而不是让逐卡脚本各自失败
                print(f"[skip] rank {c['rank']} 泳道：无 trace_view.json 及降级 CSV 数据源"
                      f"（DB-only 数据不含泳道证据）")
                STATE.record(f'swimlane_rank{c["rank"]}', 'unsupported',
                             'swimlane requires trace_view.json or csv lanes (kernel_details/api_statistic/operator_details); none present')
                continue
            swimlane_cards.append(c)
        for c in swimlane_cards:
            md = os.path.join(sw_dir, f"swimlane_rank{c['rank']}.md")
            if args.force or not os.path.isfile(md):
                rc, _ = sh([sys.executable, script('swimlane_analyzer.py'),
                            '--card', c['dir'], '--rank', str(c['rank']),
                            '--output', sw_dir])
                if rc != 0:
                    print(f"WARN: rank {c['rank']} 泳道分析失败")
            else:
                print(f"[skip] rank {c['rank']} 泳道已存在")
        if mode == 'cluster' and len(swimlane_cards) > 1:
            sh([sys.executable, script('swimlane_analyzer.py'),
                '--compare-dir', sw_dir])

    # Raw DB/trace evidence is required for concrete Insight locations.  This
    # stage is independent of aggregate recipes and works for single cards too.
    if cards:
        rc, _ = sh([sys.executable, script('insight_locator.py'),
                    '--detect', detect_json, '--output', mw])
        if rc != 0:
            print('WARN: Insight 瓶颈定位失败，当前统计不足以代替精确定位')
    else:
        STATE.record('insight_locator', 'unsupported', '无卡级 Prof 的原始定位证据')

    failures = [name for name, entry in STATE.data['stages'].items() if entry['status'] == 'failed']
    if failures:
        STATE.data['errors'].append('Failed stages: ' + ', '.join(failures))
    # Publish stage/coverage state before rendering the visible report banner.
    STATE.data['status'] = 'partial' if failures else 'complete'
    write_json(os.path.join(mw, 'workflow_status.json'), STATE.data)
    # ---------- 8 report（概览优先 / 左侧导航 / 折叠 / 子报告嵌入） ----------
    if not args.skip_report:
        rmode = args.report_mode or mode
        out_html = os.path.join(mw, 'performance_report.html')
        rc, _ = sh([sys.executable, script('report_generator.py'),
                    '--middleware', mw, '--mode', rmode, '--output', out_html])
        if rc != 0:
            print('ERROR: 总报告生成失败')
            return 1
        print(f'\n{"部分完成" if failures else "完成"}：{out_html}')
    return 2 if failures else 0


def main():
    global STATE
    STATE = None
    rc = 1
    try:
        rc = execute_workflow()
        return rc
    except Exception as e:
        message = f'{type(e).__name__}: {e}'
        print('ERROR: ' + message, file=sys.stderr)
        if STATE:
            STATE.data['errors'].append(message)
        return 1
    finally:
        if STATE:
            STATE.finish(rc)


if __name__ == '__main__':
    sys.exit(main())
