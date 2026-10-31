"""Whole-prof single-step behavior through real public workflow seams."""
import csv
import json
import sqlite3
import sys
import subprocess
import os
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import advisor_fallback as advisor
import cluster_fallback as cluster
import compare_fallback as compare
import detect_prof as detect
from lib.insight_data import Card
from test_db_support import build_cards, WINDOW_ROW, STEP_ROW


class WholeProfTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='whole_prof_')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def text_summary(self, card, ids):
        apo = Path(card) / 'ASCEND_PROFILER_OUTPUT'
        with (apo / 'step_trace_time.csv').open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['Step', 'Stage', 'Computing',
                                                   'Communication(Not Overlapped)', 'Free'])
            writer.writeheader()
            for step in ids:
                writer.writerow({'Step': step, 'Stage': 2000, 'Computing': 1000,
                                 'Communication(Not Overlapped)': 200, 'Free': 800})

    def test_blank_text_is_one_whole_prof_step_across_consumers(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW]), (1, 3, [WINDOW_ROW])])
        for card in cards:
            self.text_summary(card, ['', ' '])
        detail = detect.detect_card_format(cards[0])[2]
        self.assertEqual(detail['step_ids'], ['prof'])
        self.assertEqual(detail.get('analysis_scope'), 'whole_prof')
        self.assertEqual(detail['known_step_ids'], [])
        st = advisor.load_step_trace(str(Path(cards[0]) / 'ASCEND_PROFILER_OUTPUT'))
        self.assertEqual(st['steps'], 1)
        self.assertEqual(st['scope'], 'whole_prof')
        self.assertEqual(st['Stage'], 4000)
        compared = compare.find_cards(str(self.root))
        self.assertEqual(compared[0]['step_ids'], ['prof'])
        self.assertEqual(compared[0]['scope'], 'whole_prof')
        self.assertEqual(cluster.collect_card(cards[0])['steps'][0]['Step'], 'prof')

    def test_multiple_null_db_windows_collapse_to_one_prof(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW, WINDOW_ROW])])
        card = cluster.collect_card(cards[0])
        self.assertEqual(len(card['steps']), 1)
        self.assertEqual(card['steps'][0]['Step'], 'prof')
        self.assertEqual(card['steps'][0]['Stage'], 4000)
        st = advisor.load_step_trace(card['apo'])
        self.assertEqual(st['steps'], 1)
        self.assertEqual(st['scope'], 'whole_prof')

    def test_real_step_ids_are_not_collapsed(self):
        cards = build_cards(self.root, [(0, 2, [STEP_ROW, (3,) + STEP_ROW[1:]])])
        self.text_summary(cards[0], ['2', '3'])
        detail = detect.detect_card_format(cards[0])[2]
        self.assertEqual(detail['step_ids'], ['2', '3'])
        self.assertEqual(detail.get('analysis_scope'), 'step')
        self.assertEqual(advisor.load_step_trace(str(Path(cards[0]) / 'ASCEND_PROFILER_OUTPUT'))['steps'], 2)

    def test_insight_assigns_events_to_whole_prof(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW, WINDOW_ROW])])
        apo = Path(cards[0]) / 'ASCEND_PROFILER_OUTPUT'
        with closing(sqlite3.connect(apo / 'ascend_pytorch_profiler_0.db')) as c:
            c.execute('CREATE TABLE COMMUNICATION_OP(startNs,endNs,opName,groupName,connectionId,opId,waitNs)')
            c.execute('INSERT INTO COMMUNICATION_OP VALUES(2000000000,2000010000,1,2,3,4,0)')
            c.commit()
        profile = Card({'rank': 0, 'dir': cards[0]})
        self.addCleanup(profile.close)
        profile.load_events()
        self.assertEqual(profile.steps, [{'id': 'prof', 'start': 1000000000, 'end': 11000000000}])
        self.assertEqual(profile.comms[0]['step'], 'prof')
        self.assertEqual(profile.stats['prof']['Stage'], 4000)

    def test_analysis_only_is_usable(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW])])
        (Path(cards[0]) / 'ASCEND_PROFILER_OUTPUT' / 'ascend_pytorch_profiler_0.db').unlink()
        fmt, _, detail = detect.detect_card_format(cards[0])
        self.assertEqual(fmt, 'db')
        self.assertTrue(detail['capabilities']['fallback_advisor'])
        self.assertEqual(detail['step_ids'], ['prof'])

    def test_db_without_summary_uses_whole_prof_event_union(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW])])
        apo = Path(cards[0]) / 'ASCEND_PROFILER_OUTPUT'
        (apo / 'analysis.db').unlink()
        with closing(sqlite3.connect(apo / 'ascend_pytorch_profiler_0.db')) as c:
            c.executescript('CREATE TABLE ENUM_OVERLAP_ANALYSIS_TYPE(id,name);'
                            'INSERT INTO ENUM_OVERLAP_ANALYSIS_TYPE VALUES(0,"COMPUTE"),(1,"COMMUNICATION"),(2,"COMM_NOT_OVERLAP_COMP"),(3,"FREE");'
                            'CREATE TABLE OVERLAP_ANALYSIS(startNs,endNs,type);'
                            'INSERT INTO OVERLAP_ANALYSIS VALUES(1000000000,1000010000,0),(1000005000,1000015000,0),(1000015000,1000020000,2);')
        detail = detect.detect_card_format(cards[0])[2]
        self.assertTrue(detail['capabilities']['fallback_advisor'])
        st = advisor.load_step_trace(str(apo))
        self.assertEqual(st['scope'], 'whole_prof')
        self.assertEqual(st['Computing'], 15)
        self.assertEqual(st['Communication(Not Overlapped)'], 5)
        self.assertEqual(st['steps'], 1)

    def test_communication_entries_from_multiple_windows_are_not_overwritten(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW, WINDOW_ROW])])
        apo = Path(cards[0]) / 'ASCEND_PROFILER_OUTPUT'
        comm = {f'step{i}': {'collective': {'hcom_allreduce_1@group1': {
            'Communication Time Info': {'Elapse Time(ms)': elapsed}}}}
                for i, elapsed in [(2, 2), (3, 3)]}
        (apo / 'communication.json').write_text(json.dumps(comm), encoding='utf-8')
        db = cluster.write_cluster_db(str(self.root), [cluster.collect_card(cards[0])])
        with closing(sqlite3.connect(db)) as conn:
            rows = conn.execute('SELECT step,hccl_op_name,group_name,elapsed_time FROM ClusterCommunicationTime').fetchall()
        self.assertEqual(rows, [('prof', 'hcom_allreduce_1', 'group1', 2),
                                ('prof', 'hcom_allreduce_1', 'group1', 3)])

    def test_missing_metric_does_not_produce_normal_advice(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW])])
        self.text_summary(cards[0], [''])
        apo = str(Path(cards[0]) / 'ASCEND_PROFILER_OUTPUT')
        path = Path(apo) / 'step_trace_time.csv'
        path.write_text('Step,Stage,Computing,Communication(Not Overlapped),Free\n,2000,NaN,200,800\n', encoding='utf-8')
        result = advisor.analyze([{'rank': 0, 'dir': cards[0], 'apo': apo}])
        self.assertEqual(result['dominant'], '证据不足')
        self.assertIn('Computing', advisor.build_advice(result)[0][1])

    def test_real_db_step_boundaries_survive_missing_summary(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW])], with_step_time=True)
        apo = Path(cards[0]) / 'ASCEND_PROFILER_OUTPUT'
        (apo / 'analysis.db').unlink()
        detail = detect.detect_card_format(cards[0])[2]
        self.assertEqual(detail['analysis_scope'], 'step')
        self.assertEqual(detail['step_ids'], ['2'])

    def test_trace_real_steps_survive_missing_summary(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW])])
        apo = Path(cards[0]) / 'ASCEND_PROFILER_OUTPUT'
        (apo / 'analysis.db').unlink()
        (apo / 'ascend_pytorch_profiler_0.db').unlink()
        events = [{'ph': 'X', 'name': 'ProfilerStep#2', 'ts': 1000, 'dur': 100},
                  {'ph': 'X', 'name': 'ProfilerStep#3', 'ts': 1100, 'dur': 100}]
        (apo / 'trace_view.json').write_text(json.dumps({'traceEvents': events}), encoding='utf-8')
        detail = detect.detect_card_format(cards[0])[2]
        self.assertEqual(detail['analysis_scope'], 'step')
        self.assertEqual(detail['step_ids'], ['2', '3'])

    def test_whole_bounds_include_multiple_db_event_families(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW])])
        apo = Path(cards[0]) / 'ASCEND_PROFILER_OUTPUT'
        with closing(sqlite3.connect(apo / 'ascend_pytorch_profiler_0.db')) as c:
            c.executescript('DROP TABLE SESSION_TIME_INFO; '
                            'CREATE TABLE TASK(startNs,endNs); INSERT INTO TASK VALUES(200,300); '
                            'CREATE TABLE COMMUNICATION_OP(startNs,endNs); INSERT INTO COMMUNICATION_OP VALUES(100,400);')
        from lib import analysis_scope
        self.assertEqual(analysis_scope.whole_prof_bounds(str(apo))[:2], (100, 400))

    def test_blank_summary_does_not_erase_real_db_steps(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW])], with_step_time=True)
        detail = detect.detect_card_format(cards[0])[2]
        self.assertEqual(detail['analysis_scope'], 'step')
        self.assertEqual(detail['step_ids'], ['2'])

    def test_unknown_computing_is_not_compared_as_zero(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW]), (1, 3, [WINDOW_ROW])])
        apo = Path(cards[0]) / 'ASCEND_PROFILER_OUTPUT'
        (apo / 'step_trace_time.csv').write_text('Step,Stage,Computing,Communication(Not Overlapped),Free\n,2000,NaN,200,800\n', encoding='utf-8')
        compared = compare.find_cards(str(self.root))
        self.assertIsNone(compared[0]['trace']['Computing'])
        rows, insights = compare.compare_overall(*compared)
        self.assertNotIn('Computing Time', [row['Dimension'] for row in rows])
        self.assertNotIn('Computing Time', [row['dimension'] for row in insights])

    def test_db_same_name_communication_rows_are_preserved(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW, WINDOW_ROW])])
        apo = Path(cards[0]) / 'ASCEND_PROFILER_OUTPUT'
        with closing(sqlite3.connect(apo / 'analysis.db')) as c:
            c.executescript('CREATE TABLE CommAnalyzerTime(step,hccl_op_name,group_name,type,start_timestamp,elapse_time,transit_time,wait_time,synchronization_time,idle_time);'
                            'INSERT INTO CommAnalyzerTime VALUES("step","hcom_allreduce_1","group1","collective",100,2,1,1,0,0),'
                            '("step","hcom_allreduce_1","group1","collective",200,3,1,2,0,0);')
        db = cluster.write_cluster_db(str(self.root), [cluster.collect_card(cards[0])])
        with closing(sqlite3.connect(db)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*),SUM(elapsed_time) FROM ClusterCommunicationTime').fetchone(), (2, 5))
        profile = Card({'rank': 0, 'dir': cards[0]})
        self.addCleanup(profile.close)
        self.assertEqual(len(profile.comm_detail_candidates[('prof', 'hcom_allreduce_1')]), 2)
        event = {'step': 'prof', 'name': 'hcom_allreduce_1', 'start': 100000}
        self.assertEqual(profile.communication_detail(event)['Communication Time Info']['Elapse Time(ms)'], 2)

    def test_trace_events_outside_kernel_span_belong_to_whole_prof(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW])])
        apo = Path(cards[0]) / 'ASCEND_PROFILER_OUTPUT'
        (apo / 'ascend_pytorch_profiler_0.db').unlink()
        self.text_summary(cards[0], [''])
        (apo / 'kernel_details.csv').write_text('Name,Start Time(us),Duration(us),Accelerator Core\nMatMul,1000,100,AI_CORE\n', encoding='utf-8')
        events = [{'ph': 'M', 'name': 'process_name', 'pid': 1, 'args': {'name': 'Communication'}},
                  {'ph': 'X', 'name': 'hcom_allreduce_1', 'pid': 1, 'tid': 1, 'ts': 2000, 'dur': 100},
                  {'ph': 'X', 'name': 'Free', 'pid': 2, 'tid': 1, 'ts': 2500, 'dur': 100}]
        (apo / 'trace_view.json').write_text(json.dumps({'traceEvents': events}), encoding='utf-8')
        profile = Card({'rank': 0, 'dir': cards[0]})
        self.addCleanup(profile.close)
        profile.load_events()
        self.assertEqual(profile.comms[0]['step'], 'prof')
        self.assertEqual(profile.frees['prof'], [(2500000, 2600000)])

    def test_stage_only_report_has_no_fabricated_dominance(self):
        import report_generator as report
        detect_data = {'cards': [], 'coverage': {'observed_ranks': [0, 1], 'synthetic_step_ranks': [0, 1]}}
        advisor_data = {'data': {'dominant': '证据不足', 'per_rank': {
            '0': {'missing_required': ['Computing', 'Free', 'Communication(Not Overlapped)']}}}}
        times = [{'step': 'prof', 'rank': r, 'stage(us)': 1000, 'computing_ratio': 0,
                  'comm_ratio': 0, 'free_ratio': 0} for r in [0, 1]]
        result = report.sec_overview(detect_data, advisor_data, {'time_summary': times}, 'cluster')
        self.assertIn('不能确定时间结构或主导瓶颈', result)
        self.assertNotIn('计算占主导，属计算密集负载', result)

    def test_scope_cache_reuses_detection_and_invalidates_source_change(self):
        from lib import analysis_scope
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW])])
        self.text_summary(cards[0], [''])
        out = self.root / 'mw'
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/detect_prof.py'),
                                 '--path', str(self.root), '--output', str(out / 'detect_result.json')],
                                env={**os.environ, 'PYTHONUTF8': '1'}, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        analysis_scope.use_cache_file(str(out / 'analysis_scope_cache.json'))
        self.addCleanup(analysis_scope.use_cache_file, None)
        apo = str(Path(cards[0]) / 'ASCEND_PROFILER_OUTPUT')
        with patch.object(analysis_scope, '_load_steps_uncached', side_effect=AssertionError('repeat source scan')):
            self.assertEqual(analysis_scope.load_steps(apo)[0]['Step'], 'prof')
        csv_path = Path(apo) / 'step_trace_time.csv'
        stat = csv_path.stat()
        csv_path.write_text(csv_path.read_text(encoding='utf-8').replace('2000', '3000'), encoding='utf-8')
        os.utime(csv_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(analysis_scope.load_steps(apo)[0]['Stage'], 3000)

    def test_unknown_overlap_disables_masking_recipe(self):
        import recipe_fallback as recipe
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW])])
        apo = Path(cards[0]) / 'ASCEND_PROFILER_OUTPUT'
        (apo / 'step_trace_time.csv').write_text('Step,Stage,Computing,Communication(Not Overlapped),Free,Communication,Overlapped\n,2000,1000,200,800,300,NaN\n', encoding='utf-8')
        cluster.write_cluster_db(str(self.root), [cluster.collect_card(cards[0])])
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/recipe_fallback.py'), '--root', str(self.root)],
                                env={**os.environ, 'PYTHONUTF8': '1'}, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads((self.root / 'cluster_analysis_output/recipes_summary.json').read_text(encoding='utf-8'))
        self.assertIn('computational_op_masking', summary['recipes_unsupported'])

    def test_stage_only_workflow_keeps_unknown_and_skips_invalid_comparisons(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW]), (1, 3, [WINDOW_ROW])])
        for card in cards:
            (Path(card) / 'ASCEND_PROFILER_OUTPUT/analysis.db').unlink()
        out = self.root / 'mw'
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/run_workflow.py'),
                                 '--input', str(self.root), '--output-dir', str(out), '--skip-swimlane'],
                                env={**os.environ, 'PYTHONUTF8': '1'}, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout.decode('utf-8') + result.stderr.decode('utf-8'))
        state = json.loads((out / 'workflow_status.json').read_text(encoding='utf-8'))
        self.assertEqual(state['stages']['compare_fallback']['status'], 'unsupported')
        self.assertEqual(state['stages']['vendor_bridge_cluster']['status'], 'unsupported')
        report = (out / 'performance_report.html').read_text(encoding='utf-8')
        self.assertIn('证据不足', report)
        self.assertNotIn('计算占主导，属计算密集负载', report)

    def test_unknown_optional_overlap_skips_vendor_zero_filling(self):
        cards = build_cards(self.root, [(0, 2, [WINDOW_ROW]), (1, 3, [WINDOW_ROW])])
        for card in cards:
            with closing(sqlite3.connect(Path(card) / 'ASCEND_PROFILER_OUTPUT/analysis.db')) as c:
                c.execute('UPDATE StepTraceTime SET overlapped=NULL')
                c.commit()
        out = self.root / 'mw'
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/run_workflow.py'),
                                 '--input', str(self.root), '--output-dir', str(out), '--skip-swimlane'],
                                env={**os.environ, 'PYTHONUTF8': '1'}, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout.decode('utf-8') + result.stderr.decode('utf-8'))
        state = json.loads((out / 'workflow_status.json').read_text(encoding='utf-8'))
        self.assertEqual(state['stages']['vendor_bridge_cluster']['status'], 'unsupported')
        self.assertFalse((out / 'reports/cluster_analysis_report.html').exists())


if __name__ == '__main__':
    unittest.main()
