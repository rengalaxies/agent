"""Lossless text-compatible archives for GitHub; no secret-bearing state files."""
import base64
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path

manifest={'format':'gzip-base64-1','files':[],'summaries':{}}
for profile in ('fast','standard'):
    path=Path('results/e4-local-'+profile+'.json');raw=path.read_bytes();data=json.loads(raw)
    encoded=base64.b64encode(gzip.compress(raw,mtime=0)).decode();archive=path.with_suffix('.json.gz.b64');archive.write_text(encoded+'\n')
    groups=defaultdict(list)
    for row in data['trials']:groups[row['case']].append(row)
    summary={k:v for k,v in data.items() if k!='trials'}
    summary['classes']={case:{'trials':len(rows),'passed':sum(r['passed'] for r in rows),'max_elapsed_s':max((r['elapsed_s'] for r in rows if 'elapsed_s' in r),default=None)} for case,rows in sorted(groups.items())}
    manifest['summaries'][profile]=summary
    manifest['files'].append({'archive':str(archive),'raw_file':str(path),'raw_bytes':len(raw),'raw_sha256':hashlib.sha256(raw).hexdigest(),'archive_sha256':hashlib.sha256((encoded+'\n').encode()).hexdigest()})
Path('results/e4-local-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print(json.dumps({'profiles':{p:{'trials':s['trial_count'],'elapsed_s':s['elapsed_s'],'classes':s['classes']} for p,s in manifest['summaries'].items()}},indent=2))
