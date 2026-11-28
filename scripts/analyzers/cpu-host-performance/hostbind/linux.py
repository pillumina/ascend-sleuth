"""Read Linux host identities, per-task cpusets and explicit Ascend ownership."""
import os
from pathlib import Path
import re
import subprocess
from .planner import BindError
from .transaction import load_json
from analyzer.npu_affinity import cpu_list
from analyzer.npu_parser import device_id, logic_map, parse_npu_info, parse_npu_mapping, parse_npu_topology

ENV_KEYS=('RANK','LOCAL_RANK','WORLD_SIZE','LOCAL_WORLD_SIZE','GROUP_RANK',
          'ASCEND_RT_VISIBLE_DEVICES','ASCEND_VISIBLE_DEVICES','CUDA_VISIBLE_DEVICES')


def cpulist(value):
    if not re.fullmatch(r'\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*',value.strip()):raise BindError('Invalid CPU list')
    out=set()
    for part in value.strip().split(','):
        ends=list(map(int,part.split('-')));lo=ends[0];hi=ends[-1]
        if lo>hi or hi>1048575:raise BindError('Invalid CPU range')
        out.update(range(lo,hi+1))
    return sorted(out)


def parse_env(raw):
    result={}
    for pair in raw.split(b'\0'):
        key,sep,value=pair.partition(b'=')
        name=key.decode('ascii',errors='replace')
        if sep and name in ENV_KEYS and len(value)<=256:
            result[name]=value.decode('utf-8',errors='replace')
    return result


def parse_stat(raw):
    tail=raw.rsplit(')',1)[-1].split()
    if len(tail)<20 or not tail[19].isdigit():raise BindError('Invalid /proc stat')
    return dict(starttime=tail[19],ppid=int(tail[1]))


def command(argv):
    try:r=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,
                         text=True,encoding='utf-8',errors='replace',check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:raise BindError('%s: %s'%(argv,exc)) from exc
    if r.returncode:raise BindError('%s failed: %s'%(' '.join(argv),r.stderr.strip()))
    return r.stdout


def unescape_mount(value):
    return re.sub(r'\\([0-7]{3})',lambda m:chr(int(m[1],8)),value)


def effective_cpuset(cgroup, mountinfo, read):
    """Resolve task-specific v1/v2 mount roots; unknown permissions stay unknown."""
    for line in cgroup.splitlines():
        fields=line.split(':',2)
        if len(fields)!=3:continue
        hierarchy,controllers,rel=fields;version=2 if hierarchy=='0' else 1
        if version==1 and 'cpuset' not in controllers.split(','):continue
        if '..' in rel.split('/') or not rel.startswith('/'):raise BindError('Invalid cgroup path')
        matches=[]
        for mount in mountinfo.splitlines():
            left,sep,right=mount.partition(' - ');a=left.split();b=right.split()
            if not sep or len(a)<6 or len(b)<3:continue
            if version==2 and b[0]!='cgroup2':continue
            if version==1 and (b[0]!='cgroup' or 'cpuset' not in b[2].split(',')):continue
            root,point=map(unescape_mount,(a[3],a[4]))
            if root!='/' and rel!=root and not rel.startswith(root+'/'):continue
            tail=rel if root=='/' else rel[len(root):]
            matches.append((len(root),point,point.rstrip('/')+tail))
        if not matches:continue
        _,root,path=max(matches)
        while True:
            for name in ('cpuset.cpus.effective','cpuset.effective_cpus'):
                value=read(path+'/'+name)
                if value is not None:return cpulist(value) if value.strip() else []
            if version==1:
                value=read(path+'/cpuset.cpus')
                if value is None:return None
                if value.strip():return cpulist(value)
            else:
                value=read(path+'/cgroup.controllers')
                if value is None or 'cpuset' in value.split():return None
            if path.rstrip('/')==root.rstrip('/'):break
            path=path.rsplit('/',1)[0] or '/'
    return None


class LinuxHost:
    def __init__(self, proc='/proc', sys='/sys'):
        self.proc=Path(proc);self.sys=Path(sys)

    @staticmethod
    def read(path):
        try:return Path(path).read_text(encoding='utf-8',errors='replace').strip()
        except (FileNotFoundError,PermissionError,OSError):return None

    def context(self):
        if os.name!='posix' or not hasattr(os,'sched_getaffinity'):raise BindError('Live operations require Linux')
        container=Path('/.dockerenv').exists() or Path('/run/.containerenv').exists()
        try:
            r=subprocess.run(['systemd-detect-virt','--container','--quiet'],timeout=3,check=False,
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            container=container or r.returncode==0
        except FileNotFoundError:pass
        except subprocess.TimeoutExpired:raise BindError('Container detection timed out')
        return dict(boot_id=self.read(self.proc/'sys/kernel/random/boot_id'),
                    pid_namespace=os.readlink(str(self.proc/'self/ns/pid')),
                    init_pid_namespace=os.readlink(str(self.proc/'1/ns/pid')),
                    execution_context='container' if container else 'host')

    def stat(self,pid):
        return parse_stat((self.proc/str(pid)/'stat').read_text(encoding='utf-8',errors='replace'))

    def ceiling(self,tid):
        cg=self.read(self.proc/str(tid)/'cgroup');mi=self.read(self.proc/'self/mountinfo')
        return effective_cpuset(cg,mi,self.read) if cg is not None and mi is not None else None

    def identity(self,pid,tid):
        try:
            before=self.stat(pid);birth=self.stat(tid)['starttime']
            status=(self.proc/str(pid)/'task'/str(tid)/'status').read_text()
            tgid=re.search(r'^Tgid:\s*(\d+)',status,re.M)
            if not tgid or int(tgid[1])!=pid:raise BindError('TGID mismatch')
            ceiling=self.ceiling(tid)
            if self.stat(pid)!=before or self.stat(tid)['starttime']!=birth:raise BindError('Task changed during inspection')
            return dict(pid=pid,tid=tid,process_starttime=before['starttime'],thread_starttime=birth,
                        ppid=before['ppid'],ceiling=ceiling)
        except FileNotFoundError as exc:raise ProcessLookupError('PID/TID exited') from exc

    @staticmethod
    def get_affinity(tid):return set(os.sched_getaffinity(tid))

    @staticmethod
    def set_affinity(tid,cpus):os.sched_setaffinity(tid,cpus)

    @staticmethod
    def set_process_affinity(pid, cpus):
        command(['taskset', '-apc', cpu_list(cpus), str(pid)])

    def members(self, actions, main_only=False):
        births={a['pid']:str(a['process_starttime']) for a in actions};stats={}
        candidates = births if main_only else [int(path.name) for path in self.proc.glob('[0-9]*')
                                                if path.name.isdigit()]
        for pid in candidates:
            try:stats[pid]=self.stat(pid)
            except (OSError,BindError):continue
        roots={p for p,b in births.items() if p in stats and stats[p]['starttime']==b}
        result=[]
        for pid in roots if main_only else stats:
            current=pid;seen=set()
            while current in stats and current not in seen and current not in roots:
                seen.add(current);current=stats[current]['ppid']
            if current not in roots:continue
            try:
                for task in (self.proc/str(pid)/'task').iterdir():
                    tid=int(task.name);result.append((pid,tid,self.stat(tid)['starttime']))
            except FileNotFoundError:continue
        return result

    def topology(self,npu_cpus):
        online=cpulist((self.sys/'devices/system/cpu/online').read_text())
        cpu_node={};siblings={}
        for node in (self.sys/'devices/system/node').glob('node[0-9]*'):
            number=int(node.name[4:])
            for c in cpulist((node/'cpulist').read_text()):cpu_node[str(c)]=number
        for c in online:
            raw=self.read(self.sys/('devices/system/cpu/cpu%d/topology/thread_siblings_list'%c))
            siblings[str(c)]=cpulist(raw) if raw else []
        return dict(online=online,cpu_node=cpu_node,siblings=siblings,npu_cpus=npu_cpus)

    def npu(self,selection):
        if selection.get('topology_json'):
            data=load_json(selection['topology_json'])
            if data.get('id_space')!='global_logic' or not data.get('verified_by'):
                raise BindError('Manual topology needs id_space=global_logic and verified_by')
            pools={str(int(k)):cpulist(v) if isinstance(v,str) else sorted(set(v))
                   for k,v in data['npu_cpus'].items()}
            if not selection.get('workers'):raise BindError('Manual topology requires explicit --worker NPU:PID mappings')
            ownership={int(k):sorted(v) for k,v in selection['workers'].items()}
            return pools,ownership
        raw_map=command(['npu-smi','info','-m'])
        return self.decode_npu(raw_map, command(['npu-smi','info','-t','topo']),
                               command(['npu-smi','info']), selection.get('workers',{}))

    @staticmethod
    def decode_npu(raw_map, raw_topology, raw_info, expected=None, allow_missing_affinity=False):
        try:
            ids = logic_map(raw_map)
        except ValueError as exc:
            raise BindError(str(exc)) from exc
        if not ids:raise BindError('Unrecognized npu-smi logic map header')
        parsed = parse_npu_topology(raw_topology)
        if raw_topology.strip() and not parsed['devices'] and re.search(r'CPU\s+Affinity',raw_topology,re.I):
            raise BindError('Unreadable NPU CPU affinity table')
        pools={}
        for key, row in [(str(r['npu']),r) for r in parsed['devices']] + [
                (str(r['device_id']),r) for r in parse_npu_mapping(raw_map)['devices']]:
            if int(key) not in ids.values() or row.get('invalid_affinity'):
                raise BindError('Invalid topology ID or CPU affinity')
            if row['cpu_affinity']:
                values=cpulist(row['cpu_affinity'])
                if key in pools and pools[key]!=values:raise BindError('Conflicting topology rows')
                pools[key]=values
        if not allow_missing_affinity and set(map(int,pools))!=set(ids.values()):
            raise BindError('Incomplete/unsupported NPU CPU affinity; use verified --topology-json')
        for logic in ids.values():
            pools.setdefault(str(logic),[])
        info=parse_npu_info(raw_info)
        if info['errors']:raise BindError('Unrecognized/partial NPU process table: '+str(info['errors']))
        ownership={}
        for row in info['processes']:
            try:
                logic = device_id(row, ids)
            except ValueError as exc:
                raise BindError(str(exc)) from exc
            ownership.setdefault(row['pid'],set()).add(logic)
        ownership={k:sorted(v) for k,v in ownership.items()}
        for pid,npus in (expected or {}).items():
            if ownership.get(int(pid))!=npus:raise BindError('Explicit worker contradicts current NPU process table')
        return pools,ownership

    def snapshot(self,selection):
        context=self.context()
        if context['execution_context']!='host':raise BindError('Run on the physical host, outside containers')
        pools,ownership=self.npu(selection)
        all_stats={}
        for path in self.proc.glob('[0-9]*'):
            try:all_stats[int(path.name)]=self.stat(int(path.name))
            except (OSError,BindError,ValueError):continue
        def under(pid,roots):
            seen=set()
            while pid in all_stats and pid not in seen:
                if pid in roots:return True
                seen.add(pid);pid=all_stats[pid]['ppid']
            return False
        selected={int(pid) for pid in selection.get('workers',{})} if selection.get('workers') else set(ownership)
        if selection.get('main_pids'):
            requested = set(selection['main_pids'])
            if not requested <= selected:
                raise BindError('Main PID missing from current NPU ownership: %s' % sorted(requested - selected))
            selected = requested
        if selection.get('pids'):selected={p for p in selected if under(p,set(selection['pids']))}
        if selection.get('process_regex'):
            regex=re.compile(selection['process_regex']);filtered=set()
            for p in selected:
                try:text=(self.proc/str(p)/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
                except OSError:continue
                if regex.search(text+' '+(self.read(self.proc/str(p)/'comm') or '')):filtered.add(p)
            selected=filtered
        if not selected:raise BindError('No selected NPU workers; check host PIDs / process filter')
        processes=[]
        for pid in sorted(selected):
            initial=all_stats[pid];directory=self.proc/str(pid)
            # Rank/device keys only: credentials and unrelated environment never enter a plan.
            try:env=parse_env((directory/'environ').read_bytes())
            except PermissionError:env={}
            threads=[]
            for task in sorted((directory/'task').iterdir(),key=lambda p:int(p.name)):
                tid=int(task.name);ident=self.identity(pid,tid)
                threads.append(dict(tid=tid,starttime=ident['thread_starttime'],
                    name=(task/'comm').read_text(errors='replace').strip(),
                    affinity=sorted(self.get_affinity(tid)),ceiling=ident['ceiling']))
            if not threads or self.stat(pid)!=initial:raise BindError('Process changed during discovery; retry: %s'%pid)
            processes.append(dict(pid=pid,ppid=initial['ppid'],starttime=initial['starttime'],
                npus=ownership.get(pid,[]),env=env,name=self.read(directory/'comm') or '',threads=threads))
        return dict(context=context,topology=self.topology(pools),selection=selection,processes=processes)
