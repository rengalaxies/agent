"""Recompute observed target resource maxima from safe /proc+cgroup samples."""
import json
from pathlib import Path
import statistics
import sys

source=Path(sys.argv[1])
target=Path(sys.argv[2])
rows=[json.loads(line) for line in source.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
assert len(rows)>100 and rows[-1]['epoch']>rows[0]['epoch']
phases={}
for name in sorted({r['phase'] for r in rows}):
    sample=[r for r in rows if r['phase']==name]
    cpu=[r['host_cpu_percent_capacity'] for r in sample if r['host_cpu_percent_capacity'] is not None and r['host_cpu_percent_capacity']>=0]
    phases[name]=dict(samples=len(sample),host_used_peak_mib=max(r['host_used_bytes'] for r in sample)/2**20,
        host_available_min_mib=min(r['host_available_bytes'] for r in sample)/2**20,
        host_cpu_peak_percent_total_capacity=max(cpu,default=0),
        observed_container_memory_sum_peak_mib=max(sum(c['memory_current'] for c in r['containers']) for r in sample)/2**20,
        root_disk_peak_gib=max(r['disk_used_bytes'] for r in sample)/2**30)
containers={}
for row in rows:
    for c in row['containers']:
        item=containers.setdefault(c['id'],dict(name=c['name'],project=c['project'],memory_peak=0,cpu_peak_percent_one_core=0,oom_kill=0))
        item['memory_peak']=max(item['memory_peak'],c['memory_peak'])
        if c['cpu_percent_one_core'] is not None and c['cpu_percent_one_core']>=0:
            item['cpu_peak_percent_one_core']=max(item['cpu_peak_percent_one_core'],c['cpu_percent_one_core'])
        item['oom_kill']=max(item['oom_kill'],c['oom_kill'])
summary=dict(scope='TARGET_VM_OBSERVED_SAMPLES',sample_count=len(rows),started_epoch=rows[0]['epoch'],finished_epoch=rows[-1]['epoch'],
    median_interval_seconds=statistics.median(b['epoch']-a['epoch'] for a,b in zip(rows,rows[1:])),
    sampling_interruptions=sum('sampling_interruption' in r for r in rows),phases=phases,
    host_used_peak_mib=max(r['host_used_bytes'] for r in rows)/2**20,
    host_available_min_mib=min(r['host_available_bytes'] for r in rows)/2**20,
    web_kernel_memory_peak_mib=max(c['memory_peak'] for c in containers.values() if c['project']=='agent-graph-demo')/2**20,
    observed_sandbox_kernel_memory_peak_mib=max(c['memory_peak'] for c in containers.values() if c['project']!='agent-graph-demo')/2**20,
    observed_containers=len(containers),observed_oom_kills=sum(c['oom_kill'] for c in containers.values()),
    root_disk_start_gib=rows[0]['disk_used_bytes']/2**30,root_disk_end_gib=rows[-1]['disk_used_bytes']/2**30,
    containers=containers,
    method=dict(host_memory='MemTotal minus MemAvailable from /proc/meminfo',
        host_cpu='delta /proc/stat, idle+iowait excluded; 100%=both VM CPUs',
        container_memory='cgroup v2 memory.current and retained memory.peak',
        container_cpu='delta cgroup cpu.stat usage_usec; 100%=one core',
        disk='shutil.disk_usage on root filesystem',
        limits='Observed sampled peaks, not a proof of all instantaneous maxima; very short containers may be missed. Negative counter-reset CPU intervals after restart excluded. Sampling overhead included.'))
target.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({k:v for k,v in summary.items() if k!='containers'},ensure_ascii=False,indent=2))
