"""Read-only adapters for Insight timeline evidence. All event times are integer ns."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sqlite3

from lib.common import iter_csv, read_json, to_f
from lib import prof_data
from lib import analysis_scope
from lib.config import COMM_NAME_PATTERN


def ns(value, unit='ns'):
    try:
        return int(Decimal(str(value).strip()) * (1000 if unit == 'us' else 1))
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return 0


def stamp(value):
    sign = '-' if value < 0 else ''
    milliseconds, remainder = divmod(abs(int(value)), 1_000_000)
    microseconds, nanoseconds = divmod(remainder, 1000)
    return f'{sign}{milliseconds}ms{microseconds}us{nanoseconds}ns'


def db_open(path):
    return prof_data.open_ro(path)


def query(conn, sql, args=()):
    if not conn:
        return []
    try:
        return [dict(row) for row in conn.execute(sql, args)]
    except sqlite3.Error:
        return []


def trace_metadata(path):
    """Metadata normally lives at the beginning or end; never load a trace body."""
    result = {'process': {}, 'thread': {}}
    if not path.is_file():
        return result
    decoder = json.JSONDecoder()
    with path.open('rb') as source:
        head = source.read(2 << 20)
        source.seek(max(0, path.stat().st_size - (2 << 20)))
        tail = source.read(2 << 20)
    for chunk in (head, tail):
        text = chunk.decode('utf-8', errors='replace')
        for match in re.finditer(r'\{\s*"(?:ph|name)"\s*:', text):
            try:
                event, _ = decoder.raw_decode(text, match.start())
            except (ValueError, json.JSONDecodeError):
                continue
            if event.get('ph') != 'M':
                continue
            name = (event.get('args') or {}).get('name', '')
            if event.get('name') == 'process_name':
                result['process'][event.get('pid')] = name
            elif event.get('name') == 'thread_name':
                result['thread'][(event.get('pid'), event.get('tid'))] = name
    return result


def iter_trace(path):
    # Existing parser uses bounded buffers, supports decimal ts strings and both
    # Chrome array and {traceEvents: [...]} exports without optional dependencies.
    from swimlane_analyzer import iter_trace_events
    yield from iter_trace_events(str(path))


class Card:
    def __init__(self, raw):
        self.rank = raw['rank']
        self.root = Path(raw['dir'])
        self.apo = self.root / 'ASCEND_PROFILER_OUTPUT'
        self.conn = None
        self.errors = []
        self.compute_source = 'kernel_details.csv'
        candidates = sorted(self.apo.glob('ascend_*_profiler_*.db'))
        candidates += sorted(self.apo.glob('msprof_*.db'))
        for path in candidates:
            try:
                candidate = db_open(path)
                if query(candidate, "SELECT name FROM sqlite_master WHERE name IN ('COMMUNICATION_OP','STEP_TIME','SESSION_TIME_INFO','OVERLAP_ANALYSIS','TASK')"):
                    self.conn = candidate
                    break
                candidate.close()
            except sqlite3.Error as exc:
                self.errors.append(str(exc))
        self.tables = {r['name'] for r in query(self.conn, "SELECT name FROM sqlite_master WHERE type='table'")}
        self.columns = {table:{r['name'] for r in query(self.conn,f'PRAGMA table_info({table})')}
                        for table in ('PYTORCH_API','CANN_API','COMPUTE_TASK_INFO')}
        self.strings = {r['id']: r['value'] for r in query(self.conn, 'SELECT id,value FROM STRING_IDS')}
        self.metadata = read_json(str(self.root / 'profiler_metadata.json'), {}) or {}
        self.groups = self.metadata.get('parallel_group_info', {})
        # DB imports use DB metadata in Insight, even when a TEXT export beside
        # it carries metadata from a different export or revision.
        for row in query(self.conn, "SELECT value FROM META_DATA WHERE name='parallel_group_info'"):
            try:
                groups = json.loads(row['value'])
                if isinstance(groups, dict) and groups:
                    self.groups = groups
            except (TypeError, ValueError):
                pass
        dist = self.metadata.get('distributed_args') or {}
        self.world = dist.get('world_size') or raw.get('world_size')
        host = query(self.conn, 'SELECT hostName,hostUid FROM HOST_INFO')
        self.host = (str(host[0]['hostName']) + str(host[0]['hostUid'])) if host else '已采集设备'
        self.trace = self.apo / 'trace_view.json'
        self.lanes = trace_metadata(self.trace)
        self.steps = [{'id': str(row['id']), 'start': ns(row['startNs']), 'end': ns(row['endNs'])}
                      for row in query(self.conn, 'SELECT id,startNs,endNs FROM STEP_TIME ORDER BY startNs')]
        self.analysis_rows = analysis_scope.load_steps(str(self.apo))
        self.analysis_scope = analysis_scope.scope_of(self.analysis_rows)
        self.stats = {str(row['Step']): row for row in self.analysis_rows}
        self.stats_source = self.analysis_rows[0]['_source'] if self.analysis_rows else None
        if not self.steps:
            self.steps = [{'id': row['Step'], 'start': row['_start_ns'], 'end': row['_end_ns']}
                          for row in self.analysis_rows if row.get('_start_ns') is not None]
        if self.analysis_scope == 'whole_prof':
            row = self.analysis_rows[0]
            self.steps = ([{'id': analysis_scope.WHOLE_PROF_STEP,
                            'start': row['_start_ns'], 'end': row['_end_ns']}]
                          if row.get('_start_ns') is not None else [])
        self.comm_details = {}
        self.comm_detail_candidates = defaultdict(list)
        export = read_json(str(self.apo / 'communication.json'), {}) or {}
        export = analysis_scope.normalize_communication(export, self.analysis_rows)
        for step, kinds in export.items():
            if not isinstance(kinds, dict):
                continue
            for operators in kinds.values():
                if not isinstance(operators, dict):
                    continue
                for name, detail in operators.items():
                    if isinstance(detail, dict):
                        original_name = detail.get('_original_operator_key', name).split('@')[0]
                        self._save_comm_detail(step.removeprefix('step'), original_name, detail)
        if not self.comm_detail_candidates:
            self._db_comm_details()
        starts = [ns(row['startTimeNs']) for row in query(self.conn, 'SELECT startTimeNs FROM SESSION_TIME_INFO')]
        self.session_start = min((v for v in starts if v > 0), default=None)
        self.trace_start = None
        self.comms = []
        self.frees = defaultdict(list)
        self.compute = {}

    def close(self):
        if self.conn:
            self.conn.close()

    def _db_comm_details(self):
        """communication.json 缺失时的通信导出明细回退（analysis.db，单位 ms）。"""
        rows = self.analysis_rows
        for r in prof_data.read_comm_time(str(self.apo)):
            step = analysis_scope.map_comm_step(r['step_id'], rows)
            self._save_comm_detail(step, str(r['op'] or '').split('@')[0], {
                'Communication Time Info': {'Wait Time(ms)': r['wait_ms'],
                                            'Transit Time(ms)': r['transit_ms'],
                                            'Elapse Time(ms)': r['elapse_ms'],
                                            'Start Timestamp(us)': r['start_timestamp']},
                'source': 'analysis.db:CommAnalyzerTime'})

    def _save_comm_detail(self, step, name, detail):
        key = (step, name)
        self.comm_detail_candidates[key].append(detail)
        if len(self.comm_detail_candidates[key]) == 1:
            self.comm_details[key] = detail
        else:
            self.comm_details.pop(key, None)

    def communication_detail(self, event):
        candidates = self.comm_detail_candidates.get((event['step'], event['name']), [])
        if len(candidates) == 1:
            return candidates[0]
        matches = [detail for detail in candidates
                   if ns((detail.get('Communication Time Info') or {}).get('Start Timestamp(us)'), 'us') == event['start']]
        # Multiple same-name instances must have a unique timestamp match.
        return matches[0] if len(matches) == 1 else {}

    def _db_compute(self):
        """kernel_details.csv 缺失时的计算热点回退：TASK⋈COMPUTE_TASK_INFO。

        流式聚合（不整表物化）；通信算子按 COMM_NAME_PATTERN 名称启发过滤，
        证据中标注方法来源；PMU 比例在 DB 路径不可用，相关字段留空。
        """
        if not self.conn or 'TASK' not in self.tables or 'COMPUTE_TASK_INFO' not in self.tables:
            return
        self.compute_source = 'main_db:TASK+COMPUTE_TASK_INFO'
        sql = '''SELECT t.startNs AS startNs, t.endNs AS endNs, t.streamId AS streamId,
                        t.taskType AS taskType, s.value AS sname,
                        c.inputShapes AS ishapes, c.inputDataTypes AS idtypes
                 FROM TASK t JOIN COMPUTE_TASK_INFO c ON t.globalTaskId=c.globalTaskId
                 LEFT JOIN STRING_IDS s ON c.name=s.id ORDER BY t.startNs'''
        try:
            cur = self.conn.execute(sql)
        except sqlite3.Error:
            return
        for row in cur:
            name = self.text(row['sname'])
            if not name or COMM_NAME_PATTERN.search(name):
                continue
            start = ns(row['startNs'])
            duration = ns(row['endNs']) - start
            if start <= 0 or duration <= 0:
                continue
            shape = self.text(row['ishapes'])
            dtype = self.text(row['idtypes'])
            core = str(row['taskType'])
            step = self.step_for(start)
            key = (step, name, shape, dtype, core, '', '', '')
            item = self.compute.setdefault(key, {'rank': self.rank, 'step': step,
                'name': name, 'shape': shape, 'dtype': dtype, 'core': core,
                'total': 0, 'count': 0, 'largest': 0, 'start': start,
                'stream': row['streamId'], 'row': {}})
            item['total'] += duration
            item['count'] += 1
            if duration > item['largest']:
                item.update(largest=duration, start=start, stream=row['streamId'], row={})

    def text(self, value):
        return self.strings.get(value, str(value or ''))

    def step_for(self, start):
        if self.analysis_scope == 'whole_prof' and not self.steps:
            return analysis_scope.WHOLE_PROF_STEP
        return next((row['id'] for row in self.steps if row['start'] <= start < row['end']), '未知')

    def stage_ns(self, step):
        stage = ns((self.stats.get(str(step)) or {}).get('Stage', 0), 'us')
        if stage:
            return stage
        return next((s['end'] - s['start'] for s in self.steps if s['id'] == str(step)), 0)

    def group(self, raw):
        label = self.text(raw)
        group = self.groups.get(label) or {}
        semantic = group.get('group_name') or ''
        # Internal hashes never enter the UI location.
        if not re.fullmatch(r'group_name_\d+', label):
            label = '未解析通信域'
        return (semantic + ':' if semantic else '') + 'Group ' + label + ' Communication', semantic, group.get('global_ranks', [])

    def load_events(self):
        for row in query(self.conn, 'SELECT * FROM COMMUNICATION_OP ORDER BY startNs'):
            start, end = ns(row['startNs']), ns(row['endNs'])
            lane, semantic, members = self.group(row.get('groupName'))
            self.comms.append({'rank': self.rank, 'step': self.step_for(start), 'name': self.text(row['opName']),
                               'start': start, 'end': end, 'wait': ns(row.get('waitNs')),
                               'connection': row.get('connectionId'), 'op_id': row.get('opId'),
                               'lane': lane, 'semantic': semantic, 'members': members})
        for row in query(self.conn, 'SELECT startNs,endNs FROM OVERLAP_ANALYSIS WHERE type=3 ORDER BY startNs'):
            start, end = ns(row['startNs']), ns(row['endNs'])
            for bounds in self.steps:
                left, right = max(start, bounds['start']), min(end, bounds['end'])
                if right > left:
                    self.frees[bounds['id']].append((left, right))
        if not self.conn and self.trace.is_file():
            self._trace_events()
        for step, pairs in list(self.frees.items()):
            merged = []
            for left, right in sorted(pairs):
                if merged and left <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
                else:
                    merged.append((left, right))
            self.frees[step] = merged
        self._csv_compute()
        if not self.compute and self.conn:
            self._db_compute()

    def _trace_events(self):
        trace_end = None
        for event in iter_trace(self.trace):
            if event.get('ph') in ('X','C') and event.get('ts') is not None:
                timestamp=ns(event['ts'],'us')
                if timestamp>0 and (self.trace_start is None or timestamp<self.trace_start):
                    self.trace_start=timestamp
            if event.get('dur') is None:
                continue
            start = ns(event.get('ts'), 'us')
            end = start + ns(event['dur'], 'us')
            trace_end = max(trace_end or end, end)
            name = event.get('name', '')
            tid, pid = event.get('tid'), event.get('pid')
            lane = self.lanes['thread'].get((pid, tid), '')
            process = self.lanes['process'].get(pid, '')
            if name.startswith('ProfilerStep#'):
                if self.analysis_scope != 'whole_prof':
                    self.steps.append({'id': name.split('#')[-1], 'start': start, 'end': end})
            elif name == 'Free':
                self.frees['未知'].append((start, end))
            elif name.startswith('hcom_') and process == 'Communication' and not lane.startswith('Plane'):
                args = event.get('args') or {}
                match=re.search(r'(?<![\w])group_name_\d+(?![\w])',lane)
                group=match.group() if match else None
                resolved = self.group(group)[0] if group else lane or '未解析通信域'
                self.comms.append({'rank': self.rank, 'step': '未知', 'name': name, 'start': start, 'end': end,
                                   'wait': ns(args.get('Wait Time(us)'), 'us'), 'connection': None,
                                   'lane': resolved, 'semantic': '', 'members': []})
        if self.analysis_scope == 'whole_prof' and self.trace_start is not None and trace_end is not None:
            self.steps = [{'id': analysis_scope.WHOLE_PROF_STEP,
                           'start': min([self.trace_start] + [s['start'] for s in self.steps]),
                           'end': max([trace_end] + [s['end'] for s in self.steps])}]
        for row in self.comms:
            row['step'] = self.step_for(row['start'])
        if self.frees.get('未知') and self.steps:
            unknown = self.frees.pop('未知')
            for start, end in unknown:
                for bounds in self.steps:
                    left, right = max(start, bounds['start']), min(end, bounds['end'])
                    if right > left:
                        self.frees[bounds['id']].append((left, right))

    def _csv_compute(self):
        for row in iter_csv(str(self.apo / 'kernel_details.csv')):
            if row.get('Accelerator Core') not in {'AI_CORE','AI_VECTOR_CORE','MIX_AIC','MIX_AIV'}:
                continue
            start = ns(row.get('Start Time(us)'), 'us')
            duration = ns(row.get('Duration(us)'), 'us')
            if start <= 0 or duration <= 0:
                continue
            step = (self.step_for(start) if self.analysis_scope == 'whole_prof'
                    else str(row.get('Step Id') or self.step_for(start)))
            key = (step,row.get('Name',''),row.get('Input Shapes',''),row.get('Input Data Types',''),row.get('Accelerator Core',''),
                   row.get('Input Formats',''),row.get('Block Dim',''),row.get('Mix Block Dim',''))
            item = self.compute.setdefault(key, {'rank': self.rank,'step':step,'name':row.get('Name',''),
                'shape':row.get('Input Shapes',''),'dtype':row.get('Input Data Types',''),'core':row.get('Accelerator Core',''),
                'total':0,'count':0,'largest':0,'start':start,'stream':row.get('Stream ID','?'),'row':row})
            item['total'] += duration
            item['count'] += 1
            if duration > item['largest']:
                item.update(largest=duration,start=start,stream=row.get('Stream ID','?'),row=row)

    def linked_host(self, event):
        rows = query(self.conn, 'SELECT * FROM CANN_API WHERE connectionId=?', (event['connection'],))
        if not rows:
            return None
        result = rows[0]
        result = {'start':ns(result['startNs']), 'end':ns(result['endNs']), 'name':self.text(result['name']), 'tid':result.get('globalTid')}
        pytorch = query(self.conn, '''SELECT p.* FROM PYTORCH_API p JOIN CONNECTION_IDS c ON p.connectionId=c.id
            WHERE c.connectionId=? ORDER BY CAST(p.startNs AS INTEGER) DESC''', (event['connection'],))
        if pytorch:
            row=pytorch[0]
            result['pytorch']={'start':ns(row['startNs']),'end':ns(row['endNs']),'name':self.text(row['name']),
                                'tid':row.get('globalTid'),'sequence':row.get('sequenceNumber')}
            parents=query(self.conn,'''SELECT p.*,s.value AS label FROM PYTORCH_API p JOIN STRING_IDS s ON p.name=s.id
                WHERE p.globalTid=? AND CAST(p.startNs AS INTEGER)<=? AND CAST(p.endNs AS INTEGER)>=?
                AND s.value LIKE 'c10d::%' ORDER BY CAST(p.endNs AS INTEGER)-CAST(p.startNs AS INTEGER) LIMIT 1''',
                (row.get('globalTid'),ns(row['startNs']),ns(row['endNs'])))
            if parents:
                parent=parents[0]
                result['pytorch_parent']={'start':ns(parent['startNs']),'end':ns(parent['endNs']),
                    'name':parent['label'],'tid':parent.get('globalTid')}
        return result

    def anchors(self, host, step):
        api=host.get('pytorch') or host
        table='PYTORCH_API' if host.get('pytorch') else 'CANN_API'
        lower=next((v['start'] for v in self.steps if v['id']==str(step)),api['start']-200_000_000)
        rows=query(self.conn,f'''SELECT startNs,endNs,name FROM {table} WHERE globalTid=?
            AND CAST(startNs AS INTEGER)>=? AND CAST(endNs AS INTEGER)<=? ORDER BY CAST(startNs AS INTEGER)''',
            (api['tid'],lower,api['start']))
        counters=defaultdict(int);out={}
        for row in rows:
            name=self.text(row['name']); counters[name]+=1
            out[(name,counters[name])]={'name':name,'ordinal':counters[name],'start':ns(row['startNs']),'end':ns(row['endNs'])}
        return out

    def preceding_device(self, event):
        rows=query(self.conn,'''SELECT t.startNs,t.endNs,t.streamId,c.name FROM TASK t JOIN COMPUTE_TASK_INFO c
            ON t.globalTaskId=c.globalTaskId WHERE t.endNs<=? ORDER BY t.endNs DESC LIMIT 1''',(event['start'],))
        if not rows:
            return None
        row=rows[0]
        return {'name':self.text(row['name']),'start':ns(row['startNs']),'end':ns(row['endNs']),'stream':row.get('streamId')}

    def interval_activity(self, start, end):
        """Union summary intervals; overlapping compute streams are not added."""
        rows=query(self.conn,'''SELECT startNs,endNs,type FROM OVERLAP_ANALYSIS
            WHERE endNs>? AND startNs<? AND type IN(0,3) ORDER BY startNs''',(start,end))
        intervals=defaultdict(list)
        for row in rows:
            intervals[row['type']].append((max(start,ns(row['startNs'])),min(end,ns(row['endNs']))))
        out={}
        for kind,pairs in intervals.items():
            total=0;bound=None
            for a,b in pairs:
                if bound is None or a>bound:
                    total+=b-a;bound=b
                elif b>bound:
                    total+=b-bound;bound=b
            out['computing_ns' if kind==0 else 'free_ns']=total
        return out

    def host_path(self, event, host, previous):
        """A same-instance prior collective followed by the last broadcast
        forms an observable boundary; this never invents a dependency edge."""
        api=host.get('pytorch_parent') or host.get('pytorch')
        if not api:
            return None
        python_filter=' AND p.type=50001' if 'type' in self.columns['PYTORCH_API'] else ''
        broadcasts=query(self.conn,'''SELECT p.startNs,p.endNs FROM PYTORCH_API p JOIN STRING_IDS s ON p.name=s.id
            WHERE p.globalTid=? AND CAST(p.startNs AS INTEGER)>=? AND CAST(p.endNs AS INTEGER)<=?
            AND s.value='HcclBroadcast' '''+python_filter+' ORDER BY CAST(p.endNs AS INTEGER) DESC LIMIT 1',
            (api['tid'],previous['end'],api['start']))
        start=ns(broadcasts[0]['endNs']) if broadcasts else previous['end']
        end=api['start']
        if end<=start:
            return None
        host_rows=query(self.conn,'''SELECT p.startNs,p.endNs,p.name FROM PYTORCH_API p
            WHERE CAST(p.startNs AS INTEGER)>=? AND CAST(p.endNs AS INTEGER)<=?'''+python_filter+' ORDER BY CAST(p.startNs AS INTEGER)',(start,end))
        busy=0;bound=0
        for row in host_rows:
            a,b=ns(row['startNs']),ns(row['endNs'])
            busy+=max(0,b-max(a,bound));bound=max(bound,b)
        cann=query(self.conn,'''SELECT s.value AS name,COUNT(*) AS count FROM CANN_API c JOIN STRING_IDS s ON c.name=s.id
            WHERE c.startNs>=? AND c.endNs<=? AND c.globalTid=? GROUP BY c.name''',(start,end,host['tid']))
        counts={row['name']:row['count'] for row in cann}
        free_intervals=[(max(start,a),min(end,b)) for a,b in self.frees.get(event['step'],[]) if b>start and a<end]
        return {'start_ns':start,'end_ns':end,'duration_ns':end-start,'boundary':
            ('前一同实例 '+previous['name']+' 后最后 HcclBroadcast 完成' if broadcasts else '前一同实例 '+previous['name']+' 完成'),
            'target_host':api['name'],'python_event_count':len(host_rows),'python_busy_union_ns':busy,
            'cann_event_count':sum(counts.values()),'cann_counts':counts,'cann_global_tid':host['tid'],
            'python_event_type':'50001 cpu_op' if python_filter else 'all available types',
            'free_interval_count':len(free_intervals),'free_examples_ns':[list(pair) for pair in sorted(free_intervals,key=lambda p:p[1]-p[0],reverse=True)[:3]],
            **self.interval_activity(start,end)}

    def free_cause(self, start, end):
        tasks=query(self.conn,'SELECT * FROM TASK WHERE startNs>=? ORDER BY startNs LIMIT 1',(end,))
        if tasks:
            row=tasks[0]
            api=query(self.conn,'SELECT * FROM CANN_API WHERE connectionId=?',(row.get('connectionId'),))
            if api:
                entry=api[0];name=self.text(entry['name'])
                if re.search(r'synchron|event|wait',name,re.I):
                    return f'后续任务关联 {name}，存在同步/依赖候选，需沿事件依赖确认。'
                if ns(entry['startNs'])>=start:
                    return f'后续任务关联 {name} 在空闲期间才开始下发，为 Host 下发不足候选；缺 Host 系统调度证据，不能确认 CPU 根因。'
                if ns(entry['endNs'])<=start:
                    return f'后续任务关联 {name} 在空闲前已完成下发，更接近 Device 依赖/同步候选；跨流事件证据不足。'
        return 'Device 未见计算/通信活动；缺少可关联的 Host API 或事件依赖，当前证据不足以区分 Host 下发不足与同步/依赖。'
