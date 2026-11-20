"""Synthetic observable profiles exercise localization and conservative causes."""
import csv
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


class InsightLocatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def locator(self):
        spec = importlib.util.find_spec('insight_locator')
        self.assertIsNotNone(spec, 'Insight locator module must provide observable diagnosis')
        import insight_locator
        return insight_locator

    def fixture(self):
        cards = []
        origin = 1_786_000_000_000_000_000
        for rank in (0, 1):
            card = self.root / ('card%d' % rank)
            apo = card / 'ASCEND_PROFILER_OUTPUT'
            apo.mkdir(parents=True)
            metadata = {'distributed_args': {'world_size': 4}, 'parallel_group_info': {
                'group_name_1': {'group_name': 'dp', 'global_ranks': [0, 1, 2, 3]}}}
            (card / 'profiler_metadata.json').write_text(json.dumps(metadata))
            db = sqlite3.connect(str(apo / ('ascend_pytorch_profiler_%d.db' % rank)))
            db.executescript('''
                CREATE TABLE STRING_IDS (id INTEGER,value TEXT);
                CREATE TABLE HOST_INFO (hostUid TEXT,hostName TEXT);
                CREATE TABLE META_DATA (name TEXT,value TEXT);
                CREATE TABLE SESSION_TIME_INFO (startTimeNs INTEGER,endTimeNs INTEGER);
                CREATE TABLE STEP_TIME (id INTEGER,startNs INTEGER,endNs INTEGER);
                CREATE TABLE COMMUNICATION_OP (opName INTEGER,startNs INTEGER,endNs INTEGER,connectionId INTEGER,groupName INTEGER,opId INTEGER,waitNs INTEGER);
                CREATE TABLE CANN_API (startNs INTEGER,endNs INTEGER,globalTid INTEGER,connectionId INTEGER,name INTEGER);
                CREATE TABLE PYTORCH_API (startNs TEXT,endNs TEXT,globalTid INTEGER,connectionId INTEGER,name INTEGER,sequenceNumber INTEGER);
                CREATE TABLE CONNECTION_IDS (id INTEGER,connectionId INTEGER);
                CREATE TABLE OVERLAP_ANALYSIS (id INTEGER,deviceId INTEGER,startNs INTEGER,endNs INTEGER,type INTEGER);
                CREATE TABLE TASK (startNs INTEGER,endNs INTEGER,deviceId INTEGER,connectionId INTEGER,globalTaskId INTEGER,streamId INTEGER);
                CREATE TABLE COMPUTE_TASK_INFO (name INTEGER,globalTaskId INTEGER);
            ''')
            db.executemany('INSERT INTO STRING_IDS VALUES (?,?)', [(1,'hcom_allReduce__909_9_1'),(2,'group_name_1'),(3,'HcclAllReduce'),(4,'aten::copy_')])
            db.execute('INSERT INTO HOST_INFO VALUES (?,?)', ('123','worker'))
            db.execute('INSERT INTO STEP_TIME VALUES (7,?,?)', (origin,origin+100_000_000))
            db.execute('INSERT INTO SESSION_TIME_INFO VALUES (?,?)', (origin,origin+100_000_000))
            # The short operation really starts later; end times converge.
            start = origin + (30_768_160 if rank else 10_000_000)
            db.execute('INSERT INTO COMMUNICATION_OP VALUES (1,?,?,50,2,1,?)', (start,origin+40_000_000,1_000_000 if rank else 20_000_000))
            host_start = origin + (29_000_000 if rank else 9_000_000)
            db.execute('INSERT INTO CANN_API VALUES (?,?,100,50,3)', (host_start,host_start+100_000))
            db.execute('INSERT INTO CONNECTION_IDS VALUES (3,50)')
            db.execute('INSERT INTO PYTORCH_API VALUES (?,?,100,3,4,9)', (str(host_start-2_000_000),str(host_start+100_000)))
            # A long Free and regular small gaps must not hide total influence.
            gaps = [(40_000_000,50_000_000),(60_000_000,61_000_000),(65_000_000,66_000_000),(70_000_000,71_000_000)]
            db.executemany('INSERT INTO OVERLAP_ANALYSIS VALUES (?,?,?, ?,3)', [(i,rank,origin+a,origin+b) for i,(a,b) in enumerate(gaps)])
            db.commit(); db.close()
            with (apo/'step_trace_time.csv').open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=['Step','Stage','Computing','Free']);writer.writeheader();writer.writerow({'Step':'7','Stage':100000,'Computing':30000,'Free':13000})
            fields=['Step Id','Stream ID','Name','Type','Accelerator Core','Start Time(us)','Duration(us)','Input Shapes','Input Data Types','aiv_mte2_ratio','aiv_mte3_ratio','aiv_vec_ratio','aiv_mte2_time(us)']
            with (apo/'kernel_details.csv').open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerow({'Step Id':'7','Stream ID':2,'Name':'aclnnMuls_Muls','Type':'Muls','Accelerator Core':'AI_VECTOR_CORE','Start Time(us)':'1786000000020000.000','Duration(us)':6000 if rank else 3000,'Input Shapes':'"596049920"','Input Data Types':'FLOAT','aiv_mte2_ratio':.9968,'aiv_mte3_ratio':.8,'aiv_vec_ratio':.3,'aiv_mte2_time(us)':5900 if rank else 2900})
            cards.append({'rank':rank,'dir':str(card),'usable':True,'world_size':4,'step_ids':['7']})
        return {'cards':cards,'coverage':{'observed_ranks':[0,1],'expected_world_size':4,'missing_ranks':[2,3]}}

    def test_observed_collective_has_one_row_with_ui_time_and_incomplete_scope(self):
        data=self.locator().analyze(self.fixture())
        self.assertEqual(data['schema_version'],1)
        self.assertEqual(len(data['communication']),1)
        row=data['communication'][0]
        for text in ['1卡','0卡','迭代 7','dp:Group group_name_1 Communication','30ms768us160ns','hcom_allReduce__909_9_1']:
            self.assertIn(text,row['location'])
        self.assertIn('候选',row['issue'])
        self.assertIn('20.768',row['impact'])
        self.assertIn('20.77%',row['impact'])
        self.assertIn('开始',row['cause'])
        self.assertTrue(any('2' in s and '3' in s for s in data['limitations']))

    def test_free_reports_exact_intervals_and_regular_gap_total(self):
        data=self.locator().analyze(self.fixture())
        self.assertTrue(data['free'])
        self.assertLessEqual(len(data['free']),3)
        self.assertIn('40ms0us0ns',data['free'][0]['location'])
        self.assertTrue(any('规律' in x['issue'] and '3.000ms' in x['impact'] for x in data['free']))

    def test_compute_compares_matching_shape_and_does_not_equate_ratio_with_bandwidth(self):
        data=self.locator().analyze(self.fixture())
        self.assertTrue(data['compute'])
        item=data['compute'][0]
        self.assertIn('4.77GB',item['cause'])
        self.assertIn('99.68%',item['cause'])
        self.assertIn('不能',item['cause'])
        self.assertIn('同形状',item['cause'])
        self.assertIn('3.000ms',item['impact'])

    def test_missing_profiles_are_supported_and_explained(self):
        data=self.locator().analyze({'cards':[{'rank':0,'dir':str(self.root),'usable':True}]})
        self.assertEqual(data['communication'],[])
        self.assertTrue(data['communication_reason'])
        self.assertEqual(data['compute'],[])
        self.assertEqual(data['free'],[])

    def test_session_origin_is_global_integer_and_not_step_or_counter_minimum(self):
        fixture=self.fixture()
        path=Path(fixture['cards'][1]['dir'])/'ASCEND_PROFILER_OUTPUT'/'ascend_pytorch_profiler_1.db'
        c=sqlite3.connect(str(path));c.execute('UPDATE SESSION_TIME_INFO SET startTimeNs=startTimeNs-123');c.commit();c.close()
        data=self.locator().analyze(fixture)
        self.assertIn('30ms768us283ns',data['communication'][0]['location'])
        self.assertIn('SESSION_TIME_INFO',data['coverage']['origin_basis'])

    def test_muls_scalar_input_keeps_minimum_traffic_and_hotspot_inclusion(self):
        fixture=self.fixture()
        for card in fixture['cards']:
            path=Path(card['dir'])/'ASCEND_PROFILER_OUTPUT'/'kernel_details.csv'
            with path.open() as source:
                rows=list(csv.DictReader(source))
            rows[0]['Input Shapes']='"596049920;"';rows[0]['Input Data Types']='FLOAT;FLOAT'
            fields=list(rows[0])
            rows.append(dict(rows[0],Name='other_huge_hotspot',**{'Duration(us)':15000,'Input Shapes':'2048'}))
            with path.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
        data=self.locator().analyze(fixture)
        self.assertTrue(any('Muls' in i['location'] and '4.77GB' in i['cause'] for i in data['compute']))

    def test_communication_wait_and_synchronization_overlap_are_not_added(self):
        fixture=self.fixture()
        for card in fixture['cards']:
            apo=Path(card['dir'])/'ASCEND_PROFILER_OUTPUT'
            value={'step7':{'collective':{'hcom_allReduce__909_9_1@private_hash':{'Communication Time Info':{
                'Wait Time(ms)':20,'Synchronization Time(ms)':20,'Transit Time(ms)':.25}}}}}
            (apo/'communication.json').write_text(json.dumps(value))
        data=self.locator().analyze(fixture)
        details=' '.join(data['communication'][0]['evidence']['causal_analysis'])
        self.assertIn('等待/同步',details)
        self.assertIn('不能相加',details)
        self.assertNotIn('private_hash',data['communication'][0]['location'])

    def test_distinct_group_id_with_same_semantic_label_is_not_merged(self):
        fixture=self.fixture()
        for card in fixture['cards']:
            root=Path(card['dir']);meta=json.loads((root/'profiler_metadata.json').read_text())
            meta['parallel_group_info']['group_name_2']={'group_name':'dp','global_ranks':[0,1]}
            (root/'profiler_metadata.json').write_text(json.dumps(meta))
            c=sqlite3.connect(str(next((root/'ASCEND_PROFILER_OUTPUT').glob('ascend_*_profiler_*.db'))))
            c.execute("INSERT INTO STRING_IDS VALUES (5,'group_name_2')")
            c.execute('INSERT INTO COMMUNICATION_OP SELECT opName,startNs+50000000,endNs+50000000,connectionId,5,2,waitNs FROM COMMUNICATION_OP')
            c.commit();c.close()
        data=self.locator().analyze(fixture)
        self.assertEqual(len(data['communication']),2)
        self.assertTrue(any('group_name_2' in row['location'] for row in data['communication']))

    def test_low_impact_non_memory_hotspot_without_difference_is_not_anomaly(self):
        fixture=self.fixture()
        for card in fixture['cards']:
            path=Path(card['dir'])/'ASCEND_PROFILER_OUTPUT'/'kernel_details.csv'
            with path.open() as source: rows=list(csv.DictReader(source))
            rows[0].update(Name='TinyAdd',**{'Duration(us)':100,'Input Shapes':'1024'})
            with path.open('w',newline='') as out:
                writer=csv.DictWriter(out,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        data=self.locator().analyze(fixture)
        self.assertEqual(data['compute'],[])

    def test_trace_only_origin_includes_counter_and_group_name_is_exact(self):
        fixture=self.fixture();origin=1_786_000_000_000_000_000
        for card in fixture['cards']:
            root=Path(card['dir']);apo=root/'ASCEND_PROFILER_OUTPUT'
            next(apo.glob('ascend_*_profiler_*.db')).unlink()
            meta=json.loads((root/'profiler_metadata.json').read_text())
            meta['parallel_group_info']['group_name_10']={'group_name':'tp','global_ranks':[0,1]}
            (root/'profiler_metadata.json').write_text(json.dumps(meta))
            offset=30768160 if card['rank'] else 10000000
            from decimal import Decimal
            ts=lambda value:str(Decimal(origin+value)/1000)
            events=[{'ph':'C','name':'freq','ts':ts(-1000),'args':{'MHz':1850}},
                {'ph':'X','name':'ProfilerStep#7','ts':ts(0),'dur':100000,'pid':1,'tid':1},
                {'ph':'X','name':'hcom_allReduce__909_9_1','ts':ts(offset),'dur':(40000000-offset)/1000,'pid':2,'tid':2},
                {'ph':'M','name':'process_name','pid':2,'args':{'name':'Communication'}},
                {'ph':'M','name':'thread_name','pid':2,'tid':2,'args':{'name':'Group group_name_10 Communication'}}]
            (apo/'trace_view.json').write_text(json.dumps(events))
        data=self.locator().analyze(fixture)
        self.assertEqual(data['coverage']['origin_ns'],origin-1000)
        self.assertIn('tp:Group group_name_10',data['communication'][0]['location'])
        self.assertIn('30ms769us160ns',data['communication'][0]['location'])

    def test_configuration_identity_includes_block_dimension(self):
        fixture=self.fixture()
        for card in fixture['cards']:
            path=Path(card['dir'])/'ASCEND_PROFILER_OUTPUT'/'kernel_details.csv'
            with path.open() as source: rows=list(csv.DictReader(source))
            rows[0]['Block Dim']=48 if card['rank'] else 24
            with path.open('w',newline='') as out:
                writer=csv.DictWriter(out,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        data=self.locator().analyze(fixture)
        self.assertIsNone(data['compute'][0]['evidence']['matching_rank'])

    def test_free_outside_profiled_steps_is_not_promoted(self):
        fixture=self.fixture()
        origin=1_786_000_000_000_000_000
        for card in fixture['cards']:
            path=Path(card['dir'])/'ASCEND_PROFILER_OUTPUT'/f'ascend_pytorch_profiler_{card["rank"]}.db'
            with closing(sqlite3.connect(path)) as conn:
                conn.execute('INSERT INTO OVERLAP_ANALYSIS VALUES (99,?,?,?,3)',
                             (card['rank'],origin-200_000_000,origin-1))
                conn.commit()
        data=self.locator().analyze(fixture)
        self.assertTrue(data['free'])
        self.assertTrue(all(row['evidence']['step']=='7' for row in data['free']))
        self.assertNotIn('迭代 未知',' '.join(row['location'] for row in data['free']))

    def test_db_parallel_group_metadata_matches_db_import(self):
        fixture=self.fixture()
        for card in fixture['cards']:
            path=Path(card['dir'])/'ASCEND_PROFILER_OUTPUT'/f'ascend_pytorch_profiler_{card["rank"]}.db'
            groups={'group_name_1':{'group_name':'db_dp','global_ranks':[0,1,2,3]}}
            with closing(sqlite3.connect(path)) as conn:
                conn.execute('INSERT INTO META_DATA VALUES (?,?)',('parallel_group_info',json.dumps(groups)))
                conn.commit()
        data=self.locator().analyze(fixture)
        self.assertIn('db_dp:Group group_name_1',data['communication'][0]['location'])

    def test_nonfinite_time_remains_unknown(self):
        from lib.insight_data import ns
        for value in ('NaN','Infinity','-Infinity',None,'N/A'):
            self.assertEqual(ns(value),0)

    def test_duplicate_free_intervals_do_not_inflate_total(self):
        fixture=self.fixture()
        origin=1_786_000_000_000_000_000
        for card in fixture['cards']:
            path=Path(card['dir'])/'ASCEND_PROFILER_OUTPUT'/f'ascend_pytorch_profiler_{card["rank"]}.db'
            with closing(sqlite3.connect(path)) as conn:
                conn.execute('INSERT INTO OVERLAP_ANALYSIS VALUES (100,?,?,?,3)',
                             (card['rank'],origin+60_000_000,origin+61_000_000))
                conn.commit()
        data=self.locator().analyze(fixture)
        self.assertTrue(any('3.000ms' in row['impact'] for row in data['free'] if '规律' in row['issue']))

    def test_duplicate_collective_export_still_reports_instance_once(self):
        fixture=self.fixture()
        for card in fixture['cards']:
            path=Path(card['dir'])/'ASCEND_PROFILER_OUTPUT'/f'ascend_pytorch_profiler_{card["rank"]}.db'
            with closing(sqlite3.connect(path)) as conn:
                conn.execute('INSERT INTO COMMUNICATION_OP SELECT opName,startNs,endNs,connectionId,groupName,2,waitNs FROM COMMUNICATION_OP')
                conn.commit()
        data=self.locator().analyze(fixture)
        self.assertEqual(len(data['communication']),1)

    def test_unresolved_groups_are_not_joined_by_placeholder(self):
        fixture=self.fixture()
        for card in fixture['cards']:
            path=Path(card['dir'])/'ASCEND_PROFILER_OUTPUT'/f'ascend_pytorch_profiler_{card["rank"]}.db'
            with closing(sqlite3.connect(path)) as conn:
                conn.execute('UPDATE STRING_IDS SET value=? WHERE id=2',(f'unknown_group_{card["rank"]}',))
                conn.commit()
        self.assertEqual(self.locator().analyze(fixture)['communication'],[])

    def test_shortest_duration_without_device_alignment_is_not_cause(self):
        fixture=self.fixture()
        # End convergence is lost: short duration alone must not yield a root-cause claim.
        path=Path(fixture['cards'][1]['dir'])/'ASCEND_PROFILER_OUTPUT'/'ascend_pytorch_profiler_1.db'
        c=sqlite3.connect(str(path));c.execute('UPDATE COMMUNICATION_OP SET endNs=startNs+1000000');c.commit();c.close()
        data=self.locator().analyze(fixture)
        self.assertIn('不收敛',data['communication'][0]['cause'])
        self.assertNotIn('确认根因',data['communication'][0]['cause'])


if __name__=='__main__':
    unittest.main()
