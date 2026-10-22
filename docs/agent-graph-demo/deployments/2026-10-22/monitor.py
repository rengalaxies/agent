"""Temporary target-host measurement; /proc and cgroup v2, no credentials."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

output = Path(sys.argv[1])
phase_file = Path('/var/lib/agent-graph-demo/acceptance-phase')
previous_cpu = None
previous_groups = {}
started = time.monotonic()
with output.open('w') as log:
    while time.monotonic() - started < 2400:
        now = time.time()
        cpu = [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
        idle = cpu[3] + cpu[4]
        total = sum(cpu)
        host_cpu = None
        if previous_cpu:
            delta = total - previous_cpu[0]
            host_cpu = 100 * (delta - (idle - previous_cpu[1])) / delta if delta else 0
        previous_cpu = total, idle
        mem = {line.split(':')[0]: int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()}
        phase = phase_file.read_text().strip() if phase_file.exists() else 'idle'
        row = dict(epoch=now, phase=phase, host_cpu_percent_capacity=host_cpu,
                   host_used_bytes=mem['MemTotal']-mem['MemAvailable'], host_available_bytes=mem['MemAvailable'],
                   disk_used_bytes=shutil.disk_usage('/').used, containers=[])
        try:
            ids = subprocess.check_output(['docker','ps','-q'],text=True,timeout=5).split()
            containers = json.loads(subprocess.check_output(['docker','inspect',*ids],text=True,timeout=5)) if ids else []
            for c in containers:
                labels = c['Config'].get('Labels',{})
                project = labels.get('com.docker.compose.project','')
                if project != 'agent-graph-demo' and not project.startswith('agent-graph-demo-sbx-'):
                    continue
                pid = c['State']['Pid']
                relative = Path(f'/proc/{pid}/cgroup').read_text().split('0::',1)[1].strip()
                group = Path('/sys/fs/cgroup') / relative.lstrip('/')
                usage = dict(line.split() for line in (group/'cpu.stat').read_text().splitlines())
                events = dict(line.split() for line in (group/'memory.events').read_text().splitlines())
                used_cpu = int(usage['usage_usec'])
                old = previous_groups.get(c['Id'])
                percent = (used_cpu-old[1]) / ((now-old[0])*1_000_000)*100 if old else None
                previous_groups[c['Id']] = now,used_cpu
                row['containers'].append(dict(id=c['Id'],name=c['Name'],project=project,
                    memory_current=int((group/'memory.current').read_text()),
                    memory_peak=int((group/'memory.peak').read_text()),
                    cpu_percent_one_core=percent,oom_kill=int(events.get('oom_kill',0))))
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            row['sampling_interruption']=type(exc).__name__
        log.write(json.dumps(row)+'\n');log.flush()
        time.sleep(0.5)
