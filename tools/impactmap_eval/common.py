"""Shared public-input contracts. No reference/catalogue is read by method workers."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from agent_graph.contracts import Policy
from agent_graph.sources import collect
from agent_graph.output_contracts import normalize_route

ROOT=Path(__file__).resolve().parents[2]
EVAL=ROOT/'research/evaluation'
FIELDS=('provider_service','method','route','consumer_service')


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(value):return sha(canonical(value).encode())
def read(path):return json.loads(Path(path).read_text())
def write(path,value):Path(path).write_text(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2)+'\n')


def validate(kind,value):
    schema=read(EVAL/'schemas'/f'{kind}.schema.json')
    Draft202012Validator(schema,format_checker=FormatChecker()).validate(value)


def pair(key):
    return (key['provider_service'],key['method'].upper(),normalize_route(key['route']),key['consumer_service'])


def packet_hash(path):
    return sha(Path(path).read_bytes())


class Registry:
    def __init__(self,case,policy):
        self.case=case;self.policy=Policy.model_validate(policy)
        ids=[r['repository_id'] for r in case['repositories']]
        providers=[r for r in case['repositories'] if r['role']=='provider']
        if len(set(ids))!=len(ids) or set(ids)!={r.id for r in self.policy.repositories} or len(providers)!=1:
            raise ValueError('repository_scope_mismatch')
        if self.policy.model is not None or any(r.snapshot!='git' for r in self.policy.repositories):
            raise ValueError('requires_model_off_pinned_git')
        self.provider=providers[0]['repository_id'];self.repos={r['repository_id']:r for r in case['repositories']}
        for repo in self.policy.repositories:
            declared=self.repos[repo.id]
            if not declared['read_authorized'] or declared['service']!=repo.service or declared['source_ref']!=repo.id:
                raise ValueError('authorization_or_service_mismatch')
        self.head={r['repository_id']:r['head_sha'] for r in case['repositories']}
        self.base={**self.head,self.provider:providers[0]['base_sha']}
        self.sources={};self.contexts=[];self.gaps=[]
        for phase,revisions in [('base',self.base),('head',self.head)]:
            result=collect(self.policy,revisions);self.contexts.append(result)
            for gap in result['gaps']:
                if phase=='head' or gap.get('repository')==self.provider:self.gaps.append({**gap,'phase':phase})
            for source in result['sources'].values():
                if phase=='base' and source['repository']!=self.provider:continue
                self.sources[(source['repository'],phase,source['commit'],source['path'])]=source

    def get(self,witness):
        key=(witness['repository'],witness['phase'],witness['commit'],witness['path'])
        source=self.sources.get(key)
        if source is None and witness['phase']=='base':
            repo=self.repos.get(witness['repository'],{})
            if repo.get('base_sha')==repo.get('head_sha')==witness['commit']:
                source=self.sources.get((key[0],'head',key[2],key[3]))
        return source

    def witness(self,repository,phase,commit,path,start,end):
        w=dict(repository=repository,phase=phase,commit=commit,path=path,line_start=start,line_end=end)
        source=self.get(w)
        if not source or not (1<=start<=end<=len(source['text'].splitlines())):raise ValueError('invalid_witness_range')
        w['quote_sha256']=sha('\n'.join(source['text'].splitlines()[start-1:end]).encode())
        return w

    def valid(self,w):
        try:
            return self.witness(w['repository'],w['phase'],w['commit'],w['path'],w['line_start'],w['line_end'])['quote_sha256']==w['quote_sha256']
        except (KeyError,TypeError,ValueError):return False

    def tree_hash(self,rid):
        from .packets import visible_tree_hash
        return visible_tree_hash(self,rid)

    def coverage(self):
        return dict(coverage='PARTIAL' if self.gaps else 'COMPLETE_WITHIN_PROFILE',files=len(self.sources),
                    bytes=sum(len(s['text'].encode()) for s in self.sources.values()),gaps=self.gaps)


def load_input(case_path,policy_path):
    case=read(case_path);validate('case-input',case)
    if case['lifecycle']!='ready':raise ValueError('case_not_ready')
    policy=read(policy_path)
    if sha(Path(policy_path).read_bytes())!=case['policy_sha256']:
        raise ValueError('input_hash_mismatch')
    registry=Registry(case,policy)
    if any(registry.tree_hash(r['repository_id']) not in (None,r['tree_sha256']) for r in case['repositories']):
        raise ValueError('inventory_hash_mismatch')
    from .packets import verify_packet
    verify_packet(Path(case_path).with_name('input-packet.tar'),case,Path(policy_path).read_bytes(),registry)
    return case,policy,registry
