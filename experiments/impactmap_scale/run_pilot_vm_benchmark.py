"""Repeat the existing Cloud.ru PR4 author-pilot benchmark on its host.

Only the benchmark program is sent over SSH; only numerical metrics and hashes
are returned. Existing mirrors are read; a new TemporaryDirectory holds all
benchmark state and is removed. Never exports source/config/Git objects.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]

REMOTE_MEASURE = r'''
import tempfile,sqlite3
cfg=json.loads(Path('/etc/agent-bitbucket/service.json').read_text())
p=json.loads(Path(cfg['core']['policy_path']).read_text())
assert p.get('model') is None
if PIN_OVERRIDE is None:
 q=sqlite3.connect(Path(cfg['state_path']).as_uri()+'?mode=ro',uri=True)
 records=q.execute("select snapshot from resources where resource_id like '%#4'").fetchall();q.close()
 assert len(records)==1, 'ambiguous_pilot_resource'
 s=json.loads(records[0][0])
else:
 s=dict(repository_id=PIN_OVERRIDE['provider_repository'],pr_id=PIN_OVERRIDE['pr_id'])
provider=s['repository_id'];base={};head={};repos=[]
for r in p['repositories']:
 gd=Path(r['root']);gd=gd if (gd/'objects').is_dir() else gd/'.git'
 tip=subprocess.check_output(['git','--git-dir',str(gd),'rev-parse','refs/heads/main'],text=True).strip()
 base[r['id']]=head[r['id']]=tip
 repos.append(dict(id=r['id'],service=r['service'],root=r['root'],snapshot='git',revision=tip))
 for key in ('include','allowed_refs'):
  if key in r:repos[-1][key]=r[key]
 if r['id']==provider:provider_dir=gd
if PIN_OVERRIDE is None:
 base[provider]=subprocess.check_output(['git','--git-dir',str(provider_dir),'merge-base',s['destination_tip_sha'],s['head_sha']],text=True).strip()
 head[provider]=s['head_sha']
else:
 base=dict(PIN_OVERRIDE['base_revisions']);head=dict(PIN_OVERRIDE['head_revisions'])
m=dict(schema_version='impactmap-benchmark-input-1',provenance='author_pilot_on_vm',policy=dict(installation_id=p['installation_id'],environment=p['environment'],subject='offline-benchmark',capabilities=['read_context','maintain','propose','report_check'],repositories=repos,addresses=p['addresses'],requirements=p.get('requirements',[]),limits=p.get('limits',{})),base_revisions=base,head_revisions=head,provider_repository=provider,pr_id=s['pr_id'])
with tempfile.TemporaryDirectory(prefix='impactmap-benchmark-isolated-') as tmp:
 result=worker(m,Path(tmp))
result['environment']=environment()
result['source']={'loaded_runtime_commit':json.loads(Path('/var/lib/agent-bitbucket/run/loaded.json').read_text())['commit'],'core':core_identity(),'tool_sha256':TOOL_SHA}
result['pins']=[dict(repository=r['id'],service=r['service'],base=base[r['id']],head=head[r['id']]) for r in repos]
result['policy_without_roots_sha256']=digest({**m['policy'],'repositories':[{**r,'root':'<redacted-local-root>'} for r in repos]})
result['limits']=Policy.model_validate(m['policy']).limits.model_dump()
print(canonical(result))
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-config', required=True)
    parser.add_argument('--host', default='dm-p1-ui')
    parser.add_argument('--remote-python', default='/opt/agent-bitbucket/current/venv/bin/python')
    parser.add_argument('--pins-from', type=Path, help='Use saved public base/head pins instead of following live PR4')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, choices=range(1, 31), default=3)
    args = parser.parse_args(argv)
    if (not re.fullmatch(r'[A-Za-z0-9_.@-]+', args.host) or args.host.startswith('-')
            or not re.fullmatch(r'/[A-Za-z0-9_/.-]+', args.remote_python)):
        parser.error('invalid host or remote Python path')
    try:
        args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
        code = (ROOT / 'tools/benchmark_impactmap.py').read_text()
        pins = json.loads(args.pins_from.read_text()) if args.pins_from else None
        if pins is not None and (set(pins) != {'schema_version', 'provider_repository', 'pr_id',
                                              'base_revisions', 'head_revisions'}
                                 or pins['schema_version'] != 'impactmap-pilot-pins-1'):
            raise ValueError('invalid_pinned_manifest')
        setup = "import sys\nsys.path[:0]=['/opt/agent-bitbucket/current/app/src','/opt/agent-bitbucket/current/app']\n"
        payload = (setup + '\nPIN_OVERRIDE=' + repr(pins)
                   + "\n__name__='benchmark_embedded'\n__file__='/tmp/benchmark_impactmap_embedded.py'\nTOOL_SHA="
                   + repr(hashlib.sha256(code.encode()).hexdigest()) + "\nexec(compile("
                   + repr(code) + ",__file__,'exec'))\n" + REMOTE_MEASURE)
        rows, first_pins = [], None
        with (args.output / 'measurements.jsonl').open('w') as f:
            for i in range(args.repeats):
                start = time.perf_counter()
                try:
                    proc = subprocess.run(['ssh', '-F', args.ssh_config, args.host,
                                           'sudo -n ' + args.remote_python + ' -'],
                                          input=payload, text=True, capture_output=True, timeout=1800)
                    if proc.returncode:
                        raise RuntimeError('remote failed')
                    row = json.loads(proc.stdout)
                    row.update(repetition=i + 1, ssh_roundtrip_wall_s=time.perf_counter() - start)
                    if first_pins is None:
                        first_pins = row['pins']
                    elif row['pins'] != first_pins:
                        row.update(error_code='input_pins_changed', semantics_equal=False)
                except (subprocess.SubprocessError, OSError, ValueError, KeyError, RuntimeError):
                    # stderr/stdout from a failed remote process can contain sensitive data.
                    row = dict(repetition=i + 1, error_code='remote_benchmark_failed', semantics_equal=False)
                rows.append(row)
                f.write(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n')
                f.flush()
        spans = [dict(repetition=r['repetition'], **s) for r in rows if 'measured' in r
                 for s in r['measured']['spans']]
        with (args.output / 'spans.csv').open('w', newline='') as f:
            if spans:
                writer = csv.DictWriter(f, fieldnames=list(spans[0]))
                writer.writeheader()
                writer.writerows(spans)
        summary = dict(observed_utc=datetime.now(timezone.utc).isoformat(),
                       independent_worker_processes=args.repeats,
                       all_semantics_equal=all(r['semantics_equal'] for r in rows),
                       worker_errors=sum('error_code' in r for r in rows),
                       performance_observations=sum(len(r.get('measured', {}).get('samples', [])) for r in rows),
                       source_transfer='NOT_PERFORMED',
                       network='SSH transport roundtrip recorded separately; includes remote execution, not HTTP latency',
                       polling='NOT_RUN_OFFLINE', live_publication='NOT_RUN', p95=None,
                       state='temporary isolated state removed after each worker; production state untouched')
        (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(summary))
        return 0 if summary['all_semantics_equal'] else 1
    except Exception as exc:
        print(json.dumps(dict(error_code='remote_benchmark_setup_failed', error_type=type(exc).__name__)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
