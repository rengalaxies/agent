"""Byte-hashed input archive and curator full tracked manifests (guide v1).

Only curator_manifest reads all tracked blobs; method workers never call it.
Visible verification hashes only already permitted regular sources. For denied
or excluded entries the full digest remains a curator-attested opaque value.
"""
from __future__ import annotations
import io
import json
from pathlib import Path
import subprocess
import tarfile
import time
from agent_graph.git_sources import GitReader
from .common import canonical,sha


def entries(root,commit,refs):
    reader=GitReader(Path(root),deadline=time.monotonic()+60);tree=reader.resolve(commit,refs)
    proc=subprocess.run(reader.argv('ls-tree','-rz','--full-tree',tree),env=reader.env,capture_output=True,check=True,timeout=60)
    rows=[]
    for item in proc.stdout.split(b'\0'):
        if not item:continue
        meta,path=item.split(b'\t',1);mode,kind,oid=meta.decode('ascii').split()
        rows.append((mode,kind,oid,path.decode('utf-8')))
    return reader,rows


def curator_manifest(root,snapshots,refs=('refs/heads/*',)):
    """Curator-only, full repository read authorization required. Never follows links."""
    result=[]
    for phase,commit in snapshots:
        reader,rows=entries(root,commit,refs)
        for mode,kind,oid,path in rows:
            if mode=='160000':kind='gitlink';content=oid
            else:
                proc=subprocess.run(reader.argv('cat-file','blob',oid),env=reader.env,capture_output=True,check=True,timeout=60)
                reader.verify(oid,'blob',proc.stdout);content=sha(proc.stdout)
                kind='symlink' if mode=='120000' else 'blob'
            result.append([phase,commit,path,mode,kind,content])
    return sorted(result,key=lambda r:(r[0],r[2]))


def visible_tree_hash(registry,rid):
    repo=next(r for r in registry.policy.repositories if r.id==rid)
    snapshots=[('base',registry.base[rid]),('head',registry.head[rid])] if rid==registry.provider else [('head',registry.head[rid])]
    result=[]
    if any(g.get('repository')==rid for g in registry.gaps):return None
    for phase,commit in snapshots:
        reader,rows=entries(repo.root,commit,repo.allowed_refs)
        for mode,kind,oid,path in rows:
            source=registry.sources.get((rid,phase,commit,path))
            if mode not in ('100644','100755') or source is None:return None
            if source['blob']!=oid:raise ValueError('source_blob_mismatch')
            result.append([phase,commit,path,mode,'blob',source['sha256']])
    return sha(json.dumps(sorted(result,key=lambda r:(r[0],r[2])),ensure_ascii=False,separators=(',',':')).encode())


def packet_members(case,policy_bytes,registry):
    members={'task.txt':case['task'].encode(),'policy.json':policy_bytes,
             'hints.json':canonical(case['operation_hints']).encode(),'budget.json':canonical(case['budget']).encode(),
             'manifest.json':canonical(dict(case_id=case['case_id'],repositories=case['repositories'])).encode()}
    inventory=[]
    for n,(key,source) in enumerate(sorted(registry.sources.items())):
        name=f'sources/{n:05d}.txt';members[name]=source['text'].encode()
        inventory.append([*key,source['sha256'],name])
    members['inventory.json']=canonical(inventory).encode()
    return members


def write_packet(path,case,policy_bytes,registry):
    with tarfile.open(path,'w',format=tarfile.USTAR_FORMAT) as archive:
        for name,raw in sorted(packet_members(case,policy_bytes,registry).items()):
            info=tarfile.TarInfo(name);info.size=len(raw);info.mode=0o600;info.mtime=0
            archive.addfile(info,io.BytesIO(raw))
    return sha(Path(path).read_bytes())


def verify_packet(path,case,policy_bytes,registry):
    path=Path(path);limit=2*registry.policy.limits.max_corpus_bytes+2_000_000
    if path.stat().st_size>limit:raise ValueError('packet_size_limit')
    if sha(path.read_bytes())!=case['input_packet_sha256']:raise ValueError('packet_hash_mismatch')
    expected=packet_members(case,policy_bytes,registry)
    with tarfile.open(path,'r:') as archive:
        members=archive.getmembers()
        if len(members)!=len(expected) or {m.name for m in members}!=set(expected) or any(not m.isfile() for m in members):
            raise ValueError('unexpected_packet_entries')
        for member in members:
            if member.size!=len(expected[member.name]) or archive.extractfile(member).read()!=expected[member.name]:
                raise ValueError('packet_contents_mismatch')
