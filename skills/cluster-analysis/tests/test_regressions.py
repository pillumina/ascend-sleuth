"""Regression fixtures are synthetic and contain no user profiling payload."""
import csv
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'vendor/prof-compare/scripts'))
import advisor_fallback as advisor
import cluster_fallback as cluster
import compare_fallback as compare
import detect_prof as detect
import recipe_fallback as recipes
import report_generator as report
from parsers import operator
from openpyxl import Workbook


def load_vendor(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'vendor/cluster-output-analysis/scripts' / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


extractor = load_vendor('cluster_extractor_test', 'cluster_data_extractor.py')
renderer = load_vendor('cluster_renderer_test', 'generate_cluster_report.py')


def csv_file(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def card(root, rank, db=False):
    p = root / f'host_{rank}_12345678901234567_ascend_pt'
    apo = p / 'ASCEND_PROFILER_OUTPUT'
    apo.mkdir(parents=True)
    (p / f'profiler_info_{rank}.json').write_text(json.dumps({'rank_id': str(rank), 'config': {'experimental_config': {'_export_type': ['text']}}}), encoding='utf-8')
    (p / 'profiler_metadata.json').write_text(json.dumps({'distributed_args': {'world_size': 4}}), encoding='utf-8')
    csv_file(apo / 'step_trace_time.csv', [{'Step': str(s), 'Computing': 1000, 'Communication(Not Overlapped)': 100 + rank * 100, 'Communication': 200, 'Free': 200, 'Stage': 2000, 'Preparing': 0} for s in range(5)])
    csv_file(apo / 'op_statistic.csv', [{'OP Type': 'Mul', 'Total Time(us)': 1000, 'Count': 5, 'Avg Time(us)': 200, 'Max Time(us)': 200}])
    csv_file(apo / 'kernel_details.csv', [{'Name': 'kernel', 'Duration(us)': 100, 'Accelerator Core': 'AI_CORE', 'Input Shapes': '1,4', 'Input Data Types': 'float16', 'Block Dim': 48}])
    if db:
        with closing(sqlite3.connect(apo / f'ascend_pytorch_profiler_{rank}.db')) as conn:
            conn.execute('CREATE TABLE sample (x INTEGER)')
            conn.commit()
    return p


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='技能 regression ')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def workflow(self, root, output, *flags):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
        return subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/run_workflow.py'), '--input', str(root), '--output-dir', str(output), '--no-native', '--skip-swimlane', *flags], capture_output=True, text=True, encoding='utf-8', env=env, timeout=60)

    def test_text_config_with_db_is_text(self):
        c = card(self.path, 0, db=True)
        fmt, _, detail = detect.detect_card_format(str(c))
        self.assertEqual(fmt, 'text')
        self.assertTrue(detail['has_db'])
        self.assertTrue(detail['capabilities']['fallback_advisor'])

    def test_rank_is_integer(self):
        self.assertEqual(detect.read_rank(str(card(self.path, 0))), 0)

    def test_corrupt_db_is_not_usable(self):
        c = card(self.path, 0)
        apo = c / 'ASCEND_PROFILER_OUTPUT'
        for f in apo.iterdir():
            f.unlink()
        (apo / 'ascend_pytorch_profiler_0.db').write_bytes(b'not sqlite')
        self.assertEqual(detect.detect_card_format(str(c))[0], 'none')

    def test_corrupt_cluster_db_not_cached(self):
        p = self.path / 'cluster_analysis_output'
        p.mkdir()
        (p / 'cluster_analysis.db').write_bytes(b'not sqlite')
        self.assertFalse(detect.check_cluster_output(str(self.path))['has_db'])

    def test_recipe_directory_is_not_completion(self):
        (self.path / 'cluster_analysis_output/recipes/slow_rank').mkdir(parents=True)
        self.assertFalse(detect.check_cluster_output(str(self.path))['recipes_done'])

    def test_direct_cluster_output_is_standalone(self):
        p = self.path / 'cluster_analysis_output'
        p.mkdir()
        csv_file(p / 'cluster_step_trace_time.csv', [{'Step': '0', 'Type': 'rank', 'Index': 0, 'Computing': 1000, 'Communication': 100, 'Free': 100, 'Stage': 1200}])
        r = self.workflow(p, self.path / 'out')
        d = json.loads((self.path / 'out/detect_result.json').read_text(encoding='utf-8'))
        self.assertEqual(d['mode'], 'cluster_output_only', r.stdout)

    def test_nested_root_closes_workflow(self):
        nested = self.path / 'input/inner'
        card(nested, 0)
        card(nested, 1)
        out = self.path / 'out'
        r = self.workflow(nested.parent, out)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((out / 'advisor/advisor.json').exists(), r.stdout)
        self.assertTrue((nested / 'cluster_analysis_output/recipes_summary.json').exists(), r.stdout)
        d = json.loads((out / 'detect_result.json').read_text(encoding='utf-8'))
        self.assertEqual(d['coverage']['missing_ranks'], [2, 3])
        self.assertEqual(d['coverage']['unique_step_count'], 5)

    def test_db_only_failure_is_nonzero_and_structured(self):
        c = card(self.path / 'input', 0, db=True)
        for f in (c / 'ASCEND_PROFILER_OUTPUT').glob('*.csv'):
            f.unlink()
        out = self.path / 'out'
        r = self.workflow(c.parent, out)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        s = json.loads((out / 'workflow_status.json').read_text(encoding='utf-8'))
        self.assertEqual(s['status'], 'failed')
        self.assertIn('DB', json.dumps(s))

    def test_empty_input_fails(self):
        p = self.path / 'empty'
        p.mkdir()
        self.assertNotEqual(self.workflow(p, self.path / 'out').returncode, 0)

    def test_cached_compare_respects_rank_parameters(self):
        root = self.path / 'input'
        card(root, 0)
        card(root, 1)
        out = self.path / 'out'
        self.assertEqual(self.workflow(root, out).returncode, 0)
        r = self.workflow(root, out, '--base-rank', '1', '--compare-rank', '0')
        self.assertEqual(r.returncode, 0, r.stdout)
        c = json.loads((out / 'compare/compare_analysis_result.json').read_text(encoding='utf-8'))
        self.assertEqual([c['base_card']['rank'], c['compare_card']['rank']], [1, 0])

    def test_advisor_aligns_cumulative_window(self):
        c = card(self.path, 0)
        res = advisor.analyze([{'rank': 0, 'apo': str(c / 'ASCEND_PROFILER_OUTPUT'), 'dir': str(c)}])
        texts = [s for _, s in advisor.build_advice(res) if 'Mul' in s]
        self.assertTrue(any('20.0%' in s for s in texts), texts)

    def test_missing_counters_do_not_become_no_bound(self):
        c = card(self.path, 0)
        findings, _, _ = advisor.load_kernel_findings(str(c / 'ASCEND_PROFILER_OUTPUT'))
        self.assertEqual(findings, [])

    def test_new_operator_does_not_crash_report(self):
        c = {'insights': {'operator': {'top_degraded': [{'Op Type': 'new', 'Diff Duration(ms)': 1, 'Diff Ratio': 'NEW'}]}}}
        rendered = report.sec_conclusions(None, None, c, 'cluster')
        self.assertIn('NEW', rendered)

    def test_compare_table_uses_ms(self):
        c = {'overall_metrics': [{'Dimension': 'E2E Time', 'Baseline(ms)': 527.76, 'Compare(ms)': 527.55, 'Diff(ms)': -.208, 'Diff Ratio': -.0004}]}
        rendered = report.sec_compare(c)
        self.assertIn('527.76', rendered)
        self.assertIn('基线(ms)', rendered)

    def test_communication_growth_does_not_mean_slower_e2e(self):
        rows = [{'Dimension': 'E2E Time', 'Baseline(ms)': 527.76, 'Compare(ms)': 527.55, 'Diff(ms)': -.208, 'Diff Ratio': -.0004}, {'Dimension': 'Uncovered Communication Time', 'Baseline(ms)': 137.6, 'Compare(ms)': 248.95, 'Diff(ms)': 111.355, 'Diff Ratio': .8093}]
        ins = compare.build_insights(rows, [], [], [], [])
        c = {'overall_metrics': rows, 'insights': ins, 'compare_card': {'rank': 3}}
        self.assertNotIn('整体更慢', report.sec_compare(c) + report.sec_conclusions(None, None, c, 'cluster'))

    def test_kernel_aggregation_preserves_shapes(self):
        a, b = card(self.path, 0), card(self.path, 1)
        csv_file(a / 'ASCEND_PROFILER_OUTPUT/kernel_details.csv', [{'Name': 'kernel', 'Duration(us)': 10, 'Input Shapes': s, 'Input Data Types': 'float16', 'Accelerator Core': 'AI_CORE'} for s in ('1,4', '2,4')])
        rows = compare.compare_kernel({'apo': str(a / 'ASCEND_PROFILER_OUTPUT')}, {'apo': str(b / 'ASCEND_PROFILER_OUTPUT')})
        self.assertEqual(len(rows), 2)
        self.assertEqual({r['Input Shape'] for r in rows}, {'1,4', '2,4'})

    def test_missing_kernel_csv_allows_partial_compare(self):
        a, b = card(self.path, 0), card(self.path, 1)
        (a / 'ASCEND_PROFILER_OUTPUT/kernel_details.csv').unlink()
        rows = compare.compare_kernel({'apo': str(a / 'ASCEND_PROFILER_OUTPUT')}, {'apo': str(b / 'ASCEND_PROFILER_OUTPUT')})
        self.assertEqual(rows, [])

    def test_operator_statistic_does_not_match_detail(self):
        wb = Workbook()
        ws = wb.active
        ws.title = 'OperatorCompareStatistic'
        ws.append(['No', 'Op', 'Base', 'Count', 'Comp', 'Count', 'Diff', 'Ratio'])
        ws.append([1, 'a', 10, 1, 20, 1, 10, 1])
        self.assertFalse(operator.parse_compare(wb)['available'])

    def test_concentration_uses_positive_increments(self):
        wb = Workbook()
        ws = wb.active
        ws.title = 'OperatorCompareStatistic'
        ws.append(['No', 'Op', 'Base', 'Count', 'Comp', 'Count', 'Diff', 'Ratio'])
        for i, diff in enumerate([10] * 11 + [-100]):
            ws.append([i, f'op{i}', 100, 1, 100 + diff, 1, diff, diff / 100])
        self.assertAlmostEqual(operator.parse_statistic(wb)['concentration'], 90.9, places=1)

    def test_fallback_communication_unit_and_base_info(self):
        cards = [cluster.collect_card(str(card(self.path, rank))) for rank in (0, 1)]
        cards[0]['comm'] = {'step0': {'collective': {'op@g': {'Communication Time Info': {'Elapse Time(ms)': 103.844799}}, 'Total Op Info': {'Communication Time Info': {'Elapse Time(ms)': 200}}}}}
        db = cluster.write_cluster_db(str(self.path), cards)
        data = extractor.extract_db_new(db)
        self.assertEqual(data.get('units', {}).get('communication_time'), 'ms')
        self.assertEqual(data.get('base_info', {}).get('world_size'), '4')
        self.assertNotIn('Total Op Info', [r['hccl_op_name'] for r in data['comm_time_ops']])
        data['step_summary'] = data.get('step_summary', {})
        dest = self.path / 'report.html'
        renderer.generate_single_report(data, str(ROOT / 'vendor/cluster-output-analysis/templates/cluster_analysis_report.html'), str(dest))
        self.assertIn('103.84', dest.read_text(encoding='utf-8'))

    def test_slow_rank_does_not_vote_across_groups(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.execute('CREATE TABLE ClusterCommunicationTime(step,rank_id,hccl_op_name,group_name,elapsed_time)')
        conn.executemany('INSERT INTO ClusterCommunicationTime VALUES(?,?,?,?,?)', [('0', 0, 'hcom_allReduce__1', 'g0', 1), ('0', 1, 'hcom_allReduce__2', 'g1', 2)])
        ctx = recipes.Ctx(conn.cursor(), {}, str(self.path), str(self.path / 'recipes'))
        rows, reason = recipes.recipe_slow_rank(ctx)
        self.assertFalse(rows)
        self.assertTrue(reason)

    def test_unknown_module_is_unavailable(self):
        c = card(self.path, 0)
        csv_file(c / 'ASCEND_PROFILER_OUTPUT/operator_details.csv', [{'Name': 'op', 'Device Total Duration(us)': 100, 'Call Stack': ''}])
        ctx = recipes.Ctx(None, {0: str(c)}, str(self.path), str(self.path))
        rows, reason = recipes.recipe_module_statistic(ctx)
        self.assertIsNone(rows)
        self.assertTrue(reason)

    def test_failed_rebuild_preserves_old_db(self):
        good = [cluster.collect_card(str(card(self.path, rank))) for rank in (0, 1)]
        target = Path(cluster.write_cluster_db(str(self.path), good))
        old = target.read_bytes()
        good[0]['comm'] = {'step0': {'collective': {'invalid': None}}}
        with self.assertRaises(AttributeError):
            cluster.write_cluster_db(str(self.path), good)
        self.assertEqual(target.read_bytes(), old)

    def test_cache_same_parameters_reuses(self):
        root = self.path / 'input'
        card(root, 0)
        card(root, 1)
        out = self.path / 'out'
        self.assertEqual(self.workflow(root, out).returncode, 0)
        self.assertEqual(self.workflow(root, out).returncode, 0)
        status = json.loads((out / 'workflow_status.json').read_text(encoding='utf-8'))
        self.assertTrue(status['cache_reused'])

    def test_compare_rejects_mismatched_steps(self):
        root = self.path / 'input'
        a, b = card(root, 0), card(root, 1)
        f = b / 'ASCEND_PROFILER_OUTPUT/step_trace_time.csv'
        rows = list(csv.DictReader(f.open(encoding='utf-8')))
        rows[-1]['Step'] = '99'
        csv_file(f, rows)
        r = self.workflow(root, self.path / 'out')
        self.assertNotEqual(r.returncode, 0, r.stdout)

    def test_time_recipe_excludes_stage_aggregate(self):
        cards = [cluster.collect_card(str(card(self.path, rank))) for rank in (0, 1)]
        path = cluster.write_cluster_db(str(self.path), cards)
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("INSERT INTO ClusterStepTraceTime SELECT step,'stage',99,computing,communication_not_overlapped,overlapped,communication,free,stage,bubble,communication_not_overlapped_and_exclude_receive,preparing,dp_index,pp_index,tp_index FROM ClusterStepTraceTime LIMIT 1")
            ctx = recipes.Ctx(conn.cursor(), {}, str(self.path), str(self.path))
            rows, _ = recipes.recipe_cluster_time_summary(ctx)
            self.assertEqual(len(rows), 10)

    def test_slow_rank_aligned_complete_group_votes(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.execute('CREATE TABLE CommunicationGroupMapping(rank_set,group_name,pg_name)')
        conn.execute("INSERT INTO CommunicationGroupMapping VALUES('(0,1)','g','pg')")
        conn.execute('CREATE TABLE ClusterCommunicationTime(step,rank_id,hccl_op_name,group_name,elapsed_time)')
        conn.executemany('INSERT INTO ClusterCommunicationTime VALUES(?,?,?,?,?)', [('0', 0, 'hcom_allReduce__1', 'g', 1), ('0', 1, 'hcom_allReduce__1', 'g', 2)])
        ctx = recipes.Ctx(conn.cursor(), {}, str(self.path), str(self.path / 'recipes'))
        rows, reason = recipes.recipe_slow_rank(ctx)
        self.assertEqual(rows[0]['rank'], 0)
        self.assertIsNone(reason)

    def test_numeric_missing_and_nonfinite_stay_unknown(self):
        from lib.common import to_f
        for v in ('N/A', 'nan', 'inf', None):
            self.assertIsNone(to_f(v, None))

    def test_utf8_bom_csv_header(self):
        from lib.common import read_csv_rows
        p = self.path / 'bom.csv'
        p.write_text('Step,Stage\n0,100\n', encoding='utf-8-sig')
        self.assertEqual(read_csv_rows(str(p))[0]['Step'], '0')

    def test_subprocess_start_failure_is_caught(self):
        import run_workflow
        rc, message = run_workflow.sh([str(self.path / 'missing.exe')])
        self.assertNotEqual(rc, 0)
        self.assertIn('Error', message)

    def test_subprocess_timeout_is_bounded(self):
        import run_workflow
        previous = run_workflow.COMMAND_TIMEOUT
        self.addCleanup(setattr, run_workflow, 'COMMAND_TIMEOUT', previous)
        run_workflow.COMMAND_TIMEOUT = .05
        rc, message = run_workflow.sh([sys.executable, '-c', 'import time; time.sleep(2)'])
        self.assertNotEqual(rc, 0)
        self.assertIn('TimeoutExpired', message)

    def test_partial_workflow_has_visible_failure(self):
        c = card(self.path / 'input', 0)
        (c / 'ASCEND_PROFILER_OUTPUT/kernel_details.csv').unlink()
        # 损坏的 trace_view.json：swimlane 具备数据源（运行），解析失败后
        # CSV 降级源为空 -> 阶段真实失败，必须以 partial/退出码 2 可见
        (c / 'ASCEND_PROFILER_OUTPUT/trace_view.json').write_text('{not-json', encoding='utf-8')
        out = self.path / 'out'
        r = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/run_workflow.py'), '--input', str(c), '--output-dir', str(out), '--no-native'], capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 2, r.stdout)
        status = json.loads((out / 'workflow_status.json').read_text(encoding='utf-8'))
        self.assertEqual(status['status'], 'partial')
        self.assertIn('分析未完整完成', (out / 'performance_report.html').read_text(encoding='utf-8'))

    def test_swimlane_without_any_data_source_is_unsupported(self):
        """DB-only（无 trace_view/kernel_details/api_statistic/operator_details）
        的卡：泳道记 unsupported 并注明原因，不算失败。"""
        c = card(self.path / 'input', 0)
        apo = c / 'ASCEND_PROFILER_OUTPUT'
        (apo / 'kernel_details.csv').unlink()
        out = self.path / 'out'
        r = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/run_workflow.py'), '--input', str(c), '--output-dir', str(out), '--no-native'], capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout)
        status = json.loads((out / 'workflow_status.json').read_text(encoding='utf-8'))
        self.assertEqual(status['stages']['swimlane_rank0']['status'], 'unsupported')

    def test_cache_invalidates_small_file_content_and_code(self):
        from lib.workflow_state import cache_key
        root = self.path / 'input'
        root.mkdir()
        p = root / 'metadata.json'
        p.write_text('{"a":1}', encoding='utf-8')
        stamp = p.stat()
        before = cache_key(str(root), str(self.path / 'out'), str(ROOT), {})
        p.write_text('{"a":2}', encoding='utf-8')
        os.utime(p, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assertNotEqual(before, cache_key(str(root), str(self.path / 'out'), str(ROOT), {}))

    def test_timeout_stops_owned_child_process(self):
        import run_workflow
        import time
        marker = self.path / 'should_not_exist'
        payload = 'import time; from pathlib import Path; time.sleep(1); Path(' + repr(str(marker)) + ').write_text("unexpected")'
        parent = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",' + repr(payload) + ']); time.sleep(5)'
        previous = run_workflow.COMMAND_TIMEOUT
        self.addCleanup(setattr, run_workflow, 'COMMAND_TIMEOUT', previous)
        run_workflow.COMMAND_TIMEOUT = .2
        rc, _ = run_workflow.sh([sys.executable, '-c', parent])
        self.assertNotEqual(rc, 0)
        time.sleep(1.2)
        self.assertFalse(marker.exists())

    def test_report_uses_normalized_cluster_root_before_original_input(self):
        outer = self.path / 'input'
        inner = outer / 'inner'
        correct = inner / 'cluster_analysis_output'
        correct.mkdir(parents=True)
        (outer / 'cluster_analysis_output').mkdir()
        mw = self.path / 'out'
        mw.mkdir()
        (mw / 'detect_result.json').write_text(json.dumps({'input': str(outer), 'cluster_root': str(inner), 'cluster_output': {'path': None, 'expected_path': str(correct)}}), encoding='utf-8')
        self.assertEqual(Path(report.cluster_dir(str(mw))), correct)


if __name__ == '__main__':
    unittest.main()
