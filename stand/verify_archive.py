"""Verify archive hashes, signatures and deterministic domain projections offline."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
from datamesh_release_protocol.stand.fixtures import catalog,ROUTES
from datamesh_release_protocol.stand.policy import project
from datamesh_release_protocol.stand.protocol import SignedMessage,verify

p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,default=Path('results/e4-local-manifest.json'));a=p.parse_args();manifest=json.loads(a.manifest.read_text());_,snapshots=catalog();checked=0
for item in manifest['files']:
    encoded=Path(item['archive']).read_bytes();assert hashlib.sha256(encoded).hexdigest()==item['archive_sha256']
    raw=gzip.decompress(base64.b64decode(encoded));assert len(raw)==item['raw_bytes'];assert hashlib.sha256(raw).hexdigest()==item['raw_sha256'];data=json.loads(raw)
    for row in data['trials']:
        if 'messages' not in row:continue
        for message in row['messages']:verify(SignedMessage.model_validate(message),data['public_keys'][message['vote']['domain_id']])
        expected=project(snapshots[row['outcome']],row['result']['run_id'],[],row['messages'],data['public_keys'],ROUTES,'deadline_expired' in row['projection']['reasons'])
        assert expected==row['projection'];checked+=1
    Path(item['raw_file']).write_bytes(raw)
print(json.dumps({'verified_signed_projection_trials':checked,'archives':len(manifest['files'])}))
