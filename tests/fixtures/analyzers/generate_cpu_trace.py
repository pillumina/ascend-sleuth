#!/usr/bin/env python3
"""Generate explicitly synthetic 256-CPU/8-NUMA/8-NPU evidence and offline report.

No Linux interfaces are read or modified. Refuses to overwrite existing output.
"""
import argparse
import json
import sys
import tarfile
from pathlib import Path

if __package__ in (None,''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts' / 'analyzers' / 'cpu-host-performance'))
from analyzer.analyze_cpu_trace import run_analysis


def generate(output, include_environment=True):
    output=Path(output)
    capture=output/'synthetic_capture'/'cpu_trace'
    capture.mkdir(parents=True,exist_ok=False)
    hb=capture/'hostbound';hb.mkdir()
    def write(name,text):
        p=capture/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
    def js(name,obj):write('hostbound/'+name,json.dumps(obj,ensure_ascii=False))
    events=[]
    def ev(ts,cpu,event,**fields):
        rest=' '.join('%s=%s'%(k,v) for k,v in fields.items())
        events.append((ts,cpu,'test-1 [%03d] .... %.9f: %s: %s'%(cpu,ts,event,rest)))
    def sw(ts,cpu,prev,nxt,state='S'):
        ev(ts,cpu,'sched_switch',prev_pid=prev,next_pid=nxt,prev_comm='t%d'%prev,next_comm='t%d'%nxt,prev_state=state)
    processes=[];threads=[]
    def process(pid,ppid,name,cmd,cgroup='/ascend/job',kernel=False):
        processes.append({'tgid':pid,'ppid':ppid,'name':name,'cmdline':cmd,'cgroup':cgroup,'starttime':pid*100,'kernel_thread':kernel,
                          'namespace_pids':[pid], 'allowed_cpus':list(range(256)), 'mems_allowed_list':'0-7',
                          'numa_maps': {'available': True, 'node_pages': {str(max(0,min(7,pid-4000))): 100}, 'node_kb': {}},
                          'cgroup_cpu':[{'path':'/sys/fs/cgroup'+cgroup,'version':2,'cpuset.cpus.effective':'0-255','cpu.max':'400000 100000' if cgroup=='/ascend/job' else 'max 100000','cpu.stat':'nr_periods 200\nnr_throttled 10\nthrottled_usec 10000'}]})
    def thread(tid,tgid,name,cpus):
        threads.append({'tid':tid,'tgid':tgid,'ppid':next(p['ppid'] for p in processes if p['tgid']==tgid),'name':name,
                        'starttime':tid*100,'last_cpu':cpus[0],'allowed_cpus':cpus,'mems_allowed_list':'0-7','state':'S',
                        'namespace_pids':[tid], 'cpuset_cpus_effective':list(range(256)), 'utime_ticks':100,'stime_ticks':20})
    process(3000,1,'python3','python -m vllm.entrypoints.openai.api_server')
    thread(3000,3000,'python3',[2,3])
    process(3100,3000,'EngineCore','vllm EngineCore');thread(3100,3100,'EngineCore',[4,5])
    for n in range(8):
        p=4000+n;t=5000+n;cpu=n*32
        process(p,3100,'python3','vllm worker --rank %d'%n);thread(p,p,'python3',list(range(cpu,cpu+32)));thread(t,p,'acl_thread',list(range(cpu,cpu+16)))
        # NPU0 demonstrates a compliant process; the rest deliberately have a
        # broad effective affinity so the guarded proposal path is exercised.
        if n:
            threads[-2]['allowed_cpus'] = list(range(256))
            threads[-1]['allowed_cpus'] = list(range(256))
        process(8000+n,1,'kworker' if n==4 else 'backup-agent','background synthetic CPU task','/system.slice/backup',kernel=n==4)
        thread(9000+n,8000+n,'kworker' if n==4 else 'backup',list(range(cpu,cpu+16)))
        for sec in range(10):
            at=1000+sec
            sw(at,cpu,0 if sec==0 or n!=4 else 9000+n,9000+n)
            ev(at+.02,cpu,'sched_waking',pid=t,target_cpu=cpu,comm='acl_thread')
            ev(at+.021,cpu,'sched_wakeup',pid=t,target_cpu=cpu,comm='acl_thread')
            sw(at+.06,cpu,9000+n,t,'R+' if sec==0 else 'S')
            sw(at+.11,cpu,t,9000+n,'R+')
            sw(at+.14,cpu,9000+n,t)
            sw(at+.2,cpu,t,9000+n if n==4 else 0)
            ev(at+.01,cpu,'irq_handler_entry',irq=32+n,name='hns3-rxtx');ev(at+.015,cpu,'irq_handler_exit',irq=32+n)
            ev(at+.025,cpu,'softirq_entry',vec=3,action='NET_RX');ev(at+.04,cpu,'softirq_exit',vec=3)
            if n != 4:
                if sec == 0: ev(at,cpu,'cpu_idle',cpu_id=cpu,state=-1)
                ev(at+.2,cpu,'cpu_idle',cpu_id=cpu,state=1)
                ev(at+1,cpu,'cpu_idle',cpu_id=cpu,state=-1)
        sw(1010,cpu,9000+n if n==4 else 0,0)
        write('hostbound/pid_%d_status.txt'%p,'Name:\tpython3\nTgid:\t%d\nPid:\t%d\nThreads:\t2\nCpus_allowed_list:\t%d-%d\n'%(p,p,cpu,cpu+31))
        write('hostbound/pid_%d_threads.txt'%p,'PID TID PSR %%CPU STAT COMMAND\n%d %d %d 0 S python3\n%d %d %d 0 S acl_thread\n'%(p,p,cpu,p,t,cpu))
        write('hostbound/pid_%d_thread_affinity.txt'%p,"pid %d's current affinity list: %d-%d\npid %d's current affinity list: %d-%d\n"%(p,cpu,cpu+31,t,cpu,cpu+15))
        write('hostbound/pid_%d_starttime.txt'%p,str(p*100))
        write('hostbound/pid_%d_cpuset_effective.txt'%p,'0-255')
    for c in range(256):
        if c%32==0:continue
        pid=10000+c;process(pid,1,'service-%d'%c,'synthetic background work','/system.slice/normal');thread(pid,pid,'service-%d'%c,[c])
        fraction=.95 if c==129 else .05+(c%7)*.015
        for sec in range(10):
            sw(1000+sec,c,0,pid);sw(1000+sec+fraction,c,pid,0)
            if sec == 0: ev(1000,c,'cpu_idle',cpu_id=c,state=-1)
            ev(1000+sec+fraction,c,'cpu_idle',cpu_id=c,state=1)
            ev(1001+sec,c,'cpu_idle',cpu_id=c,state=-1)
            if c==129:
                ev(1000+sec+.1,c,'irq_handler_entry',irq=88,name='nvme0q1');ev(1000+sec+.3,c,'irq_handler_exit',irq=88)
                ev(1000+sec+.4,c,'softirq_entry',vec=4,action='BLOCK');ev(1000+sec+.65,c,'softirq_exit',vec=4)
        sw(1010,c,0,0)
    process(6000,4000,'python3','python dataloader.py');thread(6000,6000,'pt_data_worker',[6,7])
    process(6500,1,'tokenizer','tokenizer independent service');thread(6500,6500,'tokenizer',[8,9])
    ev(1002.2,2,'sched_process_fork',parent_pid=5000,child_pid=7000,child_comm='short_helper')
    sw(1002.21,2,0,7000);sw(1002.24,2,7000,0);ev(1002.25,2,'sched_process_exit',pid=7000,comm='short_helper')
    policies=[]
    for n in range(8):
        policies.append({'id':'policy%d'%(n*32),'cpus':list(range(n*32,n*32+32)),'unit':'kHz','related_cpus':'%d-%d'%(n*32,n*32+31),
                         'scaling_cur_freq':2600000,'cpuinfo_max_freq':2600000,'scaling_min_freq':1000000,'scaling_max_freq':2600000,'scaling_governor':'ondemand'})
        for at,value in [(1000.1,1200000 if n==4 else 2400000),(1005,1200000 if n==4 else 2600000),(1009,2600000)]:
            ev(at,3,'cpu_frequency',cpu_id=n*32,state=value)
    events.append((1000,0,'test-1 [000] .... 1000.000000000: tracing_mark_write: CPU_HOST_WINDOW_START'))
    events.append((1010,0,'test-1 [000] .... 1010.000000000: tracing_mark_write: CPU_HOST_WINDOW_END'))
    write('trace.txt','# SYNTHETIC TEST DATA, not a server capture\n'+'\n'.join(e[2] for e in sorted(events,key=lambda x:(x[0],x[1])))+'\n')
    write('metadata.txt','collect_tool: synthetic_generator\ndata_origin: SYNTHETIC_TEST_DATA\ntrace_clock: mono\nfrequency_trace_unit: kHz\nnproc: 256\nhostbound_pid: 3000\nkernel: synthetic-openEuler-fixture\nhostname: SYNTHETIC-NOT-A-REAL-HOST\nminimal_mode: 0\n')
    write('cpu_online.txt','0-255');write('trace_overrun.txt','0');write('hostbound/collection_cpus.txt','0-255')
    write('numa.txt','\n'.join('== /sys/devices/system/node/node%d/cpulist ==\n%d-%d'%(n,n*32,n*32+31) for n in range(8)))
    write('hostbound/numactl.txt','\n'.join('node %d cpus: %s'%(n,' '.join(map(str,range(n*32,n*32+32)))) for n in range(8)))
    write('hostbound/lscpu_parse.txt','# CPU,Core,Socket,Node,Online\n'+'\n'.join('%d,%d,%d,%d,Y'%(c,c,c//128,c//32) for c in range(256)))
    write('hostbound/npu_smi_info.txt','\n'.join('| %d 0 | %d | python3 | 26415 |'%(n,4000+n) for n in range(8)))
    write('hostbound/npu_smi_info_start.txt',(hb/'npu_smi_info.txt').read_text(encoding='utf-8'))
    write('hostbound/npu_smi_map.txt','| NPU ID | Chip ID | Chip Logic ID |\n'+'\n'.join('| %d | 0 | %d |'%(n,n) for n in range(8)))
    write('hostbound/npu_smi_topology.txt','NPU CPU Affinity\n'+'\n'.join('NPU%d X HCCS %d-%d'%(n,n*32,n*32+31) for n in range(8)))
    write('hostbound/host_context.txt','execution_context=host\nboot_id=SYNTHETIC-NOT-A-REAL-BOOT-ID\n')
    js('numa_topology.json', {'schema_version': 1, 'online_cpus': list(range(256)), 'online_nodes': list(range(8)),
        'distance_node_order': list(range(8)), 'nodes': [{'node': n, 'cpus': list(range(n*32,n*32+32)),
        'distance': [10 if x==n else 20 for x in range(8)], 'memory_kb': {'MemTotal': 134217728,'MemFree': 67108864}, 'errors': {}} for n in range(8)]})
    js('process_start.json',{'ts':999.9,'processes':processes,'threads':threads})
    finish=json.loads(json.dumps(processes))
    for p in finish:
        if p['cgroup']=='/ascend/job':
            p['cgroup_cpu'][0].update({'cpu.stat':'nr_periods 300\nnr_throttled 14\nthrottled_usec 90000',
                'memory.current':str(62*1024**3), 'memory.max':str(64*1024**3),
                'pids.current':'180', 'pids.max':'2048'})
    js('process_end.json',{'ts':1010.1,'processes':finish,'threads':threads})
    js('frequency_start.json',{'ts':999.95,'policies':policies});js('frequency_end.json',{'ts':1010.01,'policies':policies})
    write('hostbound/frequency_samples.jsonl','\n'.join(json.dumps({'ts':1000+i,'policies':[dict(p,scaling_cur_freq=1200000 if p['id']=='policy128' and i<9 else 2600000) for p in policies]}) for i in range(11)))
    eventnames=['sched/sched_switch','sched/sched_wakeup','sched/sched_wakeup_new','sched/sched_migrate_task','sched/sched_process_fork','sched/sched_process_exec','sched/sched_process_exit','irq/irq_handler_entry','irq/irq_handler_exit','irq/softirq_entry','irq/softirq_exit','power/cpu_frequency','power/cpu_idle']
    js('capabilities.json',{'events':{e:{'exists':True,'writable':True,'requested':True,'enabled':True} for e in eventnames}})
    js('device_windows.json',{'clock':'mono','data_origin':'SYNTHETIC_TEST_DATA','windows':[{'npu_id':4,'start':1000.021,'end':1000.06,'kind':'synthetic_device_gap'}]})
    # Resource evidence is synthetic too; exercise memory, storage and PSI paths.
    for phase,ts,used,idle,avail,sectors,io_ms,stall in [
            ('start',1000,10000,90000,16000000,1000,100,100),
            ('end',1010,16000,94000,8000000,1201000,9600,1000100)]:
        raw={'/proc/stat':'cpu %d 0 0 %d 0 0 0 0\n'%(used,idle),
             '/proc/loadavg':'64.00 48.00 32.00 20/2000 12345\n',
             '/proc/meminfo':'MemTotal: 536870912 kB\nMemAvailable: %d kB\nMemFree: 1000000 kB\nSwapTotal: 16777216 kB\nSwapFree: 8000000 kB\n'%avail,
             '/proc/vmstat':'pswpin %d\npswpout %d\noom_kill 0\n'%(100 if phase=='start' else 300,100 if phase=='start' else 500),
             '/proc/diskstats':'259 0 nvme0n1 1000 0 %d 300 2000 0 100000 400 0 %d 1000\n'%(sectors,io_ms),
             '/proc/pressure/cpu':'some avg10=0.5 avg60=0.4 avg300=0.3 total=%d\n'%(stall//20),
             '/proc/pressure/memory':'some avg10=5.0 avg60=2.0 avg300=1.0 total=%d\n'%stall,
             '/proc/pressure/io':'some avg10=10.0 avg60=3.0 avg300=1.0 total=%d\n'%stall}
        js('resource_'+phase+'.json',{'ts':ts,'clock':'boottime','files':{key:{'text':value,'status':'COLLECTED'} for key,value in raw.items()}})
    write('hostbound/resources/df_blocks.txt','Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/nvme0n1 3750000000 3650000000 100000000 98% /data\n')
    write('hostbound/resources/df_inodes.txt','Filesystem Inodes IUsed IFree IUse% Mounted on\n/dev/nvme0n1 1000000 980000 20000 98% /data\n')
    write('hostbound/resources/lsblk.txt','NAME="nvme0n1" SIZE="3840000000000" TYPE="disk" ROTA="0" MOUNTPOINT="/data"\n')
    # The fixture declares synthetic file generation, never vendor execution.
    for filename, value in [('interrupts.txt','CPU0\n32: 1 synthetic'),('softirqs.txt','CPU0\nNET_RX: 1'),
                            ('proc_stat.txt','cpu 1 0 1 8 0 0 0 0'),('schedstat.txt','version 15\ncpu0 0 0 0 0 0 0 100 10 1')]:
        write(filename,value)
    manifest = {'schema_version': 1, 'data_origin':'SYNTHETIC_TEST_DATA', 'entries': []}
    paths = [('cpu_topology','hostbound/numa_topology.json'),('npu_info','hostbound/npu_smi_info.txt'),
             ('npu_mapping','hostbound/npu_smi_map.txt'),('npu_topology','hostbound/npu_smi_topology.txt'),
             ('processes','hostbound/process_start.json'),('processes','hostbound/process_end.json'),
             ('numa_process','hostbound/process_end.json'),('frequency','hostbound/frequency_samples.jsonl'),
             ('irq','interrupts.txt'),('softirq','softirqs.txt'),('proc_stat','proc_stat.txt'),('schedstat','schedstat.txt'),
             ('idle','trace.txt'),('trace','trace.txt'),('resources','hostbound/resource_start.json'),('resources','hostbound/resource_end.json'),('resources','hostbound/resources/df_blocks.txt'),('resources','hostbound/resources/df_inodes.txt'),('resources','hostbound/resources/lsblk.txt')]
    environment_sources = {}
    if include_environment:
        manifest['entries'].append({
            'category': 'environment_host', 'requested': True,
            'raw_path': 'hostbound/environment/host/thp.txt', 'raw_exists': False,
            'status': 'UNSUPPORTED', 'failure_reason': '合成示例中的 THP 接口不可用',
            'source': '/sys/kernel/mm/transparent_hugepage/enabled',
        })
        for name, category, source, text in (
                ('host/os_release.txt', 'environment_host', '/etc/os-release', 'PRETTY_NAME="Synthetic Linux"\n'),
                ('host/numa_balancing.txt', 'environment_host', '/proc/sys/kernel/numa_balancing', '1\n'),
                ('ascend/runtime.txt', 'environment_ascend', '/usr/local/Ascend/cann/runtime/version.info', 'version=0.0.synthetic\n')):
            path = 'hostbound/environment/' + name
            write(path, text)
            paths.append((category, path))
            environment_sources[path] = source
        target = {'pid': 4000, 'starttime': 400000}
        for field, source, text in (
                ('exe', 'exe', '/synthetic/venv/bin/python3'),
                ('environment', 'environ', 'LOCAL_RANK=0\nOMP_NUM_THREADS=8'),
                ('limits', 'limits', 'Max open files            1024                 4096                 files'),
                ('libraries', 'maps', '/synthetic/Ascend/lib/libhccl.so')):
            target[field] = {'status': 'COLLECTED', 'source': '/proc/4000/' + source, 'reason': '', 'text': text}
        js('environment/pid_4000.json', target)
        paths.append(('environment_process', 'hostbound/environment/pid_4000.json'))
    for category,path in paths:
        manifest['entries'].append({'category':category,'requested':True,'command':['synthetic_fixture_generator'],
            'command_exists':True,'returncode':0,'raw_path':path,'raw_exists':True,'empty':False,
            'parse_success':None,'parsed_count':None,'started_at':None,'ended_at':None,'failure_reason':'','status':'COLLECTED'})
        if path in environment_sources:
            manifest['entries'][-1]['source'] = environment_sources[path]
    write('collection_manifest.json',json.dumps(manifest,ensure_ascii=False))
    archive=output/'synthetic_256_capture.tar.gz'
    with tarfile.open(str(archive),'w:gz') as tf:tf.add(str(capture),arcname='cpu_trace')
    run_analysis(str(archive),str(output),quiet=False)
    return archive


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',required=True)
    generate(ap.parse_args().output)
