"""Thirty-second settled idle sample; stdout contains metrics only."""
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import time

pid = int(subprocess.check_output(['docker','inspect','-f','{{.State.Pid}}','agent-graph-demo-web-1']))
relative = Path(f'/proc/{pid}/cgroup').read_text().split('0::',1)[1].strip()
group = Path('/sys/fs/cgroup') / relative.lstrip('/')
rows=[]
previous=None
for _ in range(61):
    now=time.time()
    cpu=[int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    total=sum(cpu); idle=cpu[3]+cpu[4]
    mem={s.split(':')[0]:int(s.split()[1])*1024 for s in Path('/proc/meminfo').read_text().splitlines()}
    row=dict(epoch=now,used_mib=(mem['MemTotal']-mem['MemAvailable'])/2**20,
             available_mib=mem['MemAvailable']/2**20,web_current_mib=int((group/'memory.current').read_text())/2**20,
             root_used_gib=shutil.disk_usage('/').used/2**30,cpu_percent=None)
    if previous:
        row['cpu_percent']=100*((total-previous[0])-(idle-previous[1]))/(total-previous[0])
    previous=total,idle
    rows.append(row)
    time.sleep(0.5)
print(json.dumps(dict(scope='TARGET_VM_SETTLED_IDLE',samples=rows,duration_seconds=rows[-1]['epoch']-rows[0]['epoch'],
    host_used_peak_mib=max(r['used_mib'] for r in rows),host_used_median_mib=statistics.median(r['used_mib'] for r in rows),
    host_cpu_peak_percent_capacity=max(r['cpu_percent'] or 0 for r in rows),
    host_cpu_median_percent_capacity=statistics.median(r['cpu_percent'] for r in rows if r['cpu_percent'] is not None),
    web_current_peak_mib=max(r['web_current_mib'] for r in rows),root_used_peak_gib=max(r['root_used_gib'] for r in rows)),indent=2))
