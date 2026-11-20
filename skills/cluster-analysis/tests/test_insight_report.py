"""The diagnosis report must locate evidence without exposing storage details."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
import sqlite3
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import report_generator as report


def diagnosis():
    item = {'location': '迭代 402 / 6卡 / dp:Group group_name_1 Communication / 2438ms768us160ns / hcom_allReduce__909_9_1',
            'issue': '已采集卡中到达最晚', 'impact': '额外等待 23.000ms（单卡迭代占比 4.2%）',
            'cause': '下发开始落后；完整通信域仍缺 8 卡',
            'evidence': {'source': 'private/raw/file.db'}}
    return {'schema_version': 1, 'summary': '主要问题是到达不齐与下发空隙。',
            'limitations': ['只覆盖 0–7 卡'], 'communication': [item],
            'compute': [], 'free': []}


class InsightReportTests(unittest.TestCase):
    def test_diagnosis_has_three_concise_sections(self):
        out = report.sec_conclusions(None, None, None, 'cluster', locator=diagnosis())
        for value in ('瓶颈定位与解决', '通信', '计算', 'Free', '2438ms768us160ns',
                      '下发开始落后', '只覆盖 0–7 卡'):
            self.assertIn(value, out)
        self.assertNotIn('private/raw/file.db', out)
        self.assertEqual(out.count('hcom_allReduce__909_9_1'), 1)
        self.assertIn('<h2>2. 结论与建议</h2>',out)

    def test_chinese_headers_preserve_raw_data_keys(self):
        out = report.html_table(['step', 'rank', 'free(us)', 'stage(us)',
                                 'rank6_total(ms)', 'wait_ratio', 'Input Shapes'],
                                [['402', 6, 42, 1000, 12, 0.5, '1024']])
        for value in ('迭代', '卡号', '空闲时间(μs)', '阶段时间(μs)',
                      '6卡累计时间(ms)', '等待占比', '输入形状'):
            self.assertIn(value, out)
        self.assertNotIn('<th>free(us)</th>', out)

    def test_duration_vote_does_not_prove_latest_arrival(self):
        summary = {'time_summary': [{'step': '1', 'rank': 0, 'stage(us)': 1000,
                    'computing(us)': 500, 'communication_not_overlapped(us)': 300,
                    'free(us)': 200, 'computing_ratio': 0.5, 'comm_ratio': 0.3,
                    'free_ratio': 0.2}],
                   'slow_rank': [{'rank': 0, 'vote_ratio': 1, 'votes': 5}]}
        out = report.sec_cluster(summary)
        self.assertNotIn('其前序计算/下发最慢', out)
        self.assertIn('候选', out)

    def test_compact_html_is_offline_and_escaped(self):
        data = diagnosis()
        data['communication'][0]['issue'] = '<script>bad()</script>'
        out = report.compact_diagnosis_html(data)
        self.assertIn('通信', out)
        self.assertIn('&lt;script&gt;bad()', out)
        self.assertNotIn('<script>bad()', out)
        self.assertNotIn('https://', out)
        self.assertNotIn('private/raw/file.db', out)

    def test_workflow_runs_locator_and_publishes_compact_report(self):
        from test_regressions import card
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = card(base / 'input', 0)
            output = base / 'out'
            env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, '-B', str(Path(report.__file__).with_name('run_workflow.py')),
                '--input', str(source), '--output-dir', str(output), '--no-native',
                '--skip-swimlane', '--skip-compare'], env=env, capture_output=True,
                encoding='utf-8', timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((output / 'insight_bottlenecks.json').is_file())
            self.assertTrue((output / 'insight_bottlenecks.md').is_file())
            self.assertTrue((output / 'insight_bottlenecks.html').is_file())
            state = json.loads((output / 'workflow_status.json').read_text(encoding='utf-8'))
            self.assertEqual(state['stages']['insight_locator']['status'], 'done')
            content = (output / 'performance_report.html').read_text(encoding='utf-8')
            self.assertIn('瓶颈定位与解决', content)
            self.assertIn('<a href="#conclusions">结论与建议</a>', content)

    def test_frequency_uses_recorded_frequency_instead_of_summed_core_cycles(self):
        from test_regressions import card, csv_file
        import recipe_fallback as recipes
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = card(base, 0)
            apo = source / 'ASCEND_PROFILER_OUTPUT'
            csv_file(apo / 'kernel_details.csv', [{'Name': 'MatMul',
                     'aic_total_cycles': 44400000, 'aicore_time(us)': 1000}])
            conn = sqlite3.connect(':memory:')
            self.addCleanup(conn.close)
            conn.execute('CREATE TABLE RankDeviceMap(rankId, profilePath)')
            conn.execute('INSERT INTO RankDeviceMap VALUES (?,?)', (0, str(source)))
            db = sqlite3.connect(apo / 'ascend_pytorch_profiler_0.db')
            db.execute('CREATE TABLE AICORE_FREQ(deviceId,timestampNs,freq)')
            db.executemany('INSERT INTO AICORE_FREQ VALUES (0,?,1850)', [(0,), (1000,)])
            db.commit()
            db.close()
            ctx = SimpleNamespace(cur=conn.cursor(), card_dirs={0: str(source)}, recipes_dir=str(base / 'recipes'))
            rows, reason = recipes.recipe_freq_analysis(ctx)
            self.assertIsNone(reason)
            median = next(r['value(MHz)'] for r in rows if r['metric'] == 'median')
            self.assertEqual(median, 1850)
            self.assertNotIn('samples',[r['metric'] for r in rows])

    def test_frequency_without_recorded_samples_is_unknown(self):
        from test_regressions import card, csv_file
        import recipe_fallback as recipes
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = card(base, 0)
            csv_file(source / 'ASCEND_PROFILER_OUTPUT/kernel_details.csv',
                     [{'Name': 'MatMul', 'aic_total_cycles': 44400000, 'aicore_time(us)': 1000}])
            conn = sqlite3.connect(':memory:')
            self.addCleanup(conn.close)
            conn.execute('CREATE TABLE RankDeviceMap(rankId,profilePath)')
            conn.execute('INSERT INTO RankDeviceMap VALUES (?,?)', (0, str(source)))
            ctx = SimpleNamespace(cur=conn.cursor(), card_dirs={0: str(source)}, recipes_dir=str(base / 'recipes'))
            rows, reason = recipes.recipe_freq_analysis(ctx)
            self.assertIsNone(rows)
            self.assertIn('实测', reason)


if __name__ == '__main__':
    unittest.main()
