"""DB-only 适配回归测试（合成 fixture，不含真实用户数据）。

覆盖 prof_plan 迁移文档 T01/T02 的核心行为：
- analysis.db::StepTraceTime 有效 step / NULL-step 采集窗两种 scope
- detect 逐卡 db_capabilities / db_step_scope / device_id（rank≠device）
- advisor / cluster / compare 的 TEXT 缺失 DB 回退
- 派生 cluster_analysis.db 的来源标记（ClusterBaseInfo / status_info）
- 采集窗比较口径 step_scope='capture_window'
"""
import csv
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import advisor_fallback as advisor
import cluster_fallback as cluster
import compare_fallback as compare
import detect_prof as detect

STEP_COLS = ('computing', 'communication_not_overlapped', 'overlapped', 'communication',
             'free', 'stage', 'bubble',
             'communication_not_overlapped_and_exclude_receive', 'preparing')


def make_analysis_db(apo, rows, with_device=True):
    cols = ('deviceId, ' if with_device else '') + 'step, ' + ', '.join(STEP_COLS)
    with apo.joinpath('analysis.db').open('wb'):
        pass
    conn = sqlite3.connect(apo / 'analysis.db')
    conn.execute(f'CREATE TABLE StepTraceTime ({cols})')
    marks = ('?, ' if with_device else '') + '?,' * (len(STEP_COLS) + 1)
    conn.executemany(f'INSERT INTO StepTraceTime VALUES ({marks.rstrip(",")})', rows)
    conn.commit()
    conn.close()


def make_main_db(apo, rank_id, device_id, with_step_time=False):
    path = apo / 'ascend_pytorch_profiler_0.db'
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE RANK_DEVICE_MAP (rankId INTEGER, deviceId INTEGER)')
    conn.execute('INSERT INTO RANK_DEVICE_MAP VALUES (?, ?)', (rank_id, device_id))
    conn.execute('CREATE TABLE HOST_INFO (hostUid TEXT, hostName TEXT)')
    conn.execute("INSERT INTO HOST_INFO VALUES ('100', 'test-host')")
    conn.execute('CREATE TABLE SESSION_TIME_INFO (startTimeNs INTEGER, endTimeNs INTEGER)')
    conn.execute('INSERT INTO SESSION_TIME_INFO VALUES (1000000000, 11000000000)')
    if with_step_time:
        conn.execute('CREATE TABLE STEP_TIME (id INTEGER, startNs INTEGER, endNs INTEGER)')
        conn.execute("INSERT INTO STEP_TIME VALUES (2, 1000000000, 6000000000)")
    conn.commit()
    conn.close()


def build_cards(root, rank_specs, with_device=True, with_step_time=False):
    """rank_specs: [(rank, device_id, step_rows)]；step_rows: [(step|None, metrics...)]"""
    cards = []
    for rank, device_id, step_rows in rank_specs:
        p = root / f'rank{rank}_{rank}_12345678901234567_ascend_pt'
        apo = p / 'ASCEND_PROFILER_OUTPUT'
        apo.mkdir(parents=True)
        (p / f'profiler_info_{rank}.json').write_text(
            json.dumps({'rank_id': str(rank),
                        'config': {'experimental_config': {'_export_type': ['db']}}}),
            encoding='utf-8')
        make_analysis_db(apo, [(device_id,) + r for r in step_rows], with_device=with_device)
        make_main_db(apo, rank, device_id, with_step_time=with_step_time)
        cards.append(str(p))
    return cards


STEP_ROW = (2, 1000.0, 200.0, 50.0, 300.0, 100.0, 2000.0, 0.0, 200.0, 10.0)
WINDOW_ROW = (None, 1000.0, 200.0, 50.0, 300.0, 100.0, 2000.0, 0.0, 200.0, 10.0)


class DbOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='db_support_test ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_detect_step_scope(self):
        build_cards(self.root, [(0, 4, [STEP_ROW]), (1, 5, [STEP_ROW])])
        fmt, fw, detail = detect.detect_card_format(str(self.root / 'rank0_0_12345678901234567_ascend_pt'))
        self.assertEqual(fmt, 'db')
        self.assertTrue(detail['capabilities']['fallback_advisor'])
        self.assertEqual(detail['db_step_scope'], 'step')
        self.assertEqual(detail['device_id'], 4)
        self.assertEqual(detail['step_ids'], ['2'])

    def test_detect_capture_window(self):
        build_cards(self.root, [(0, 2, [WINDOW_ROW]), (1, 3, [WINDOW_ROW])])
        _, _, detail = detect.detect_card_format(str(self.root / 'rank0_0_12345678901234567_ascend_pt'))
        self.assertEqual(detail['db_step_scope'], 'capture_window')
        self.assertEqual(detail['step_ids'], ['prof'])
        self.assertEqual(detail['known_step_ids'], [])
        self.assertEqual(detail['analysis_scope'], 'whole_prof')
        self.assertEqual(detail['db_window_count'], 1)
        self.assertTrue(detail['capabilities']['fallback_advisor'])

    def test_prof_data_step_trace(self):
        build_cards(self.root, [(0, 7, [STEP_ROW, (3, 1100.0, 210.0, 60.0, 310.0, 110.0, 2100.0, 0.0, 210.0, 11.0)])])
        apo = str(self.root / 'rank0_0_12345678901234567_ascend_pt' / 'ASCEND_PROFILER_OUTPUT')
        from lib import prof_data
        rows = prof_data.read_step_trace(apo)
        self.assertEqual([r['step_id'] for r in rows], ['2', '3'])
        self.assertEqual([r['scope_kind'] for r in rows], ['step', 'step'])
        self.assertEqual(rows[0]['metrics']['Stage'], 2000.0)
        rank_id, device_id, source = prof_data.read_rank_device(apo)
        self.assertEqual((rank_id, device_id), (0, 7))

    def test_advisor_db_fallback(self):
        build_cards(self.root, [(0, 4, [STEP_ROW]), (1, 5, [STEP_ROW])])
        cards = [{'rank': r, 'dir': str(self.root / f'rank{r}_{r}_12345678901234567_ascend_pt'),
                  'apo': str(self.root / f'rank{r}_{r}_12345678901234567_ascend_pt' / 'ASCEND_PROFILER_OUTPUT')}
                 for r in (0, 1)]
        res = advisor.analyze(cards)
        self.assertIsNotNone(res)
        st = res['per_rank'][0]
        self.assertEqual(st['source'], 'analysis.db:StepTraceTime')
        self.assertEqual(st['scope'], 'step')
        self.assertAlmostEqual(st['Stage'], 2000.0)

    def test_cluster_build_with_provenance(self):
        cards = []
        for rank, device_id, step_rows in [(0, 4, [STEP_ROW]), (1, 5, [STEP_ROW])]:
            p = self.root / f'rank{rank}_{rank}_12345678901234567_ascend_pt'
            build_cards(self.root, [(rank, device_id, step_rows)])
            c = cluster.collect_card(str(p))
            self.assertEqual(c['device_id'], device_id)
            self.assertEqual(c['step_source'], 'analysis.db:StepTraceTime')
            cards.append(c)
        conn = sqlite3.connect(':memory:')
        cluster.build_cluster_db(conn, cards)
        cur = conn.cursor()
        rows = cur.execute('SELECT step, type, "index" FROM ClusterStepTraceTime '
                           'ORDER BY "index"').fetchall()
        self.assertEqual(rows, [('2', 'rank', 0), ('2', 'rank', 1)])
        dev = dict(cur.execute('SELECT rankId, deviceId FROM RankDeviceMap').fetchall())
        self.assertEqual(dev, {0: 4, 1: 5})
        base = dict(cur.execute('SELECT key, value FROM ClusterBaseInfo').fetchall())
        self.assertEqual(base['step_source'], 'analysis.db:StepTraceTime')
        self.assertIn('whole supplied prof', base['step_id_semantics'])
        self.assertEqual(base['device_map_source'], 'main_db:RANK_DEVICE_MAP')
        conn.close()

    def test_cluster_window_labels(self):
        cards = []
        for rank, device_id in [(0, 2), (1, 3)]:
            build_cards(self.root, [(rank, device_id, [WINDOW_ROW])])
            p = self.root / f'rank{rank}_{rank}_12345678901234567_ascend_pt'
            c = cluster.collect_card(str(p))
            cards.append(c)
        conn = sqlite3.connect(':memory:')
        cluster.build_cluster_db(conn, cards)
        cur = conn.cursor()
        rows = cur.execute('SELECT DISTINCT step FROM ClusterStepTraceTime').fetchall()
        self.assertEqual(rows, [('prof',)])
        conn.close()

    def test_compare_window_scope(self):
        build_cards(self.root, [(0, 2, [WINDOW_ROW]), (1, 3, [WINDOW_ROW])])
        cards = compare.find_cards(str(self.root))
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]['scope'], 'whole_prof')
        self.assertEqual(cards[0]['step_ids'], ['prof'])

    def test_wal_aware_open(self):
        from lib import prof_data
        p = self.root / 'wal.db'
        conn = sqlite3.connect(p)
        conn.execute('CREATE TABLE t (x INTEGER)')
        conn.execute('INSERT INTO t VALUES (1)')
        conn.commit()
        conn.close()
        # 无 WAL -> immutable 也可读
        c = prof_data.open_ro(str(p))
        self.assertEqual(c.execute('SELECT x FROM t').fetchone()[0], 1)
        c.close()
        # 伪造 -wal 存在 -> 仍可读（mode=ro 路径）
        (self.root / 'wal.db-wal').write_bytes(b'')
        c = prof_data.open_ro(str(p))
        self.assertEqual(c.execute('SELECT x FROM t').fetchone()[0], 1)
        c.close()


if __name__ == '__main__':
    unittest.main()
