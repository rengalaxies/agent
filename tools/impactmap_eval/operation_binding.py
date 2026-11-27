"""Structural warning bindings, never labels/text interpretation/source extraction."""
from __future__ import annotations
from .common import pair


def names(value):
    if isinstance(value,dict):return names(value.get('service'))
    if isinstance(value,str):return [value] if value.strip() else []
    if isinstance(value,list):return [name for item in value for name in names(item)]
    return []


def refs(value):return [v for v in value if isinstance(v,str)] if isinstance(value,list) else []
def obj(value):return value if isinstance(value,dict) else {}
def entries(raw,key):return [v for v in raw.get(key,[]) if isinstance(v,dict)] if isinstance(raw.get(key),list) else []


class OperationBindings:
    def __init__(self,raw,registry):
        self.raw,self.registry=raw,registry
        self.evidence={e['id']:e for e in entries(raw,'evidence') if isinstance(e.get('id'),str)}
        self.rels={r['id']:r for r in entries(raw,'relationships') if r.get('kind')=='calls' and isinstance(r.get('id'),str)}
        self.claims={c['id']:c for c in entries(raw,'claims') if isinstance(c.get('id'),str)}
        self.deltas={}
        for delta in entries(raw,'deltas'):
            key=self.key(delta.get('operation'))
            if key is not None:self.deltas.setdefault(key,[]).append(delta)
        self.is_pr=raw.get('trigger_kind') in ('pr','replay') or bool(entries(raw,'deltas'))
        owners={}
        for check in entries(raw,'checks'):
            for claim in refs(check.get('claim_refs')):owners.setdefault(claim,set()).update(names(check.get('consumer')))
        self.consumers={n for r in self.rels.values() for n in names(r.get('source'))}
        for field,label in [('findings','consumer'),('checks','consumer'),('affected','service')]:
            self.consumers.update(n for row in entries(raw,field) for n in names(row.get(label)))
        self.provider_services={key[0] for key in self.deltas}
        self.provider_services.update(r['service'] for r in registry.repos.values() if r.get('role')=='provider')
        self.callsite_refs={}
        for finding in entries(raw,'findings'):
            site=finding.get('callsite')
            if not isinstance(site,dict):continue
            for consumer in names(finding.get('consumer')):
                own=self.consumer_refs(finding.get('evidence_refs'),consumer)
                self.callsite_refs.setdefault(consumer,set()).update(self.at_site(own,site))
        self.invalid_refs=set();self.proofs=[]
        for id,claim in self.claims.items():
            subject=obj(claim.get('subject'))
            if subject.get('kind')!='operation':continue
            key=self.key(subject);evidence_refs=refs(claim.get('evidence_refs'))
            for consumer in owners.get(id) or self.consumers:
                anchors=self.caller_refs(consumer,self.consumer_refs(evidence_refs,consumer))
                target=subject if key is not None and self.provider_support(key,evidence_refs) else None
                self.proofs.append(dict(claim=id,consumer=consumer,target=target,anchors=anchors))

    def key(self,operation):
        operation=obj(operation)
        if operation.get('kind','operation')!='operation':return None
        if not all(isinstance(operation.get(k),str) and operation[k] for k in ('service','method','route')):return None
        if operation['method'].upper() not in {'GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS'}:return None
        for field in ('installation_id','environment'):
            if self.raw.get(field) is not None and operation.get(field)!=self.raw[field]:return None
        try:return pair(dict(provider_service=operation['service'],method=operation['method'],route=operation['route'],consumer_service='_'))[:3]
        except (ValueError,TypeError):return None

    def consumer_refs(self,evidence_refs,consumer):
        return {r for r in refs(evidence_refs) if isinstance(self.evidence.get(r,{}).get('repository'),str)
                and self.evidence[r]['repository'] in self.registry.repos
                and self.registry.repos[self.evidence[r]['repository']]['service']==consumer}

    def at_site(self,evidence_refs,site):
        return {r for r in evidence_refs if self.evidence[r].get('repository')==site.get('repository')
                and self.evidence[r].get('path')==site.get('path')
                and type(site.get('line')) is int and type(self.evidence[r].get('start_line')) is int
                and type(self.evidence[r].get('end_line')) is int
                and self.evidence[r]['start_line']<=site['line']<=self.evidence[r]['end_line']}

    def caller_refs(self,consumer,evidence_refs):
        # A service may be both caller and provider. Its declaration citations
        # are not caller witnesses; only explicit callsite roles disambiguate.
        return evidence_refs & self.callsite_refs.get(consumer,set()) if consumer in self.provider_services else evidence_refs

    def valid_evidence(self,id):
        e=self.evidence.get(id,{})
        if e.get('origin')!='code':return False
        if any(v not in self.registry.repos for v in refs(e.get('visibility'))):return False
        start,end=e.get('start_line'),e.get('end_line')
        if type(start) is not int or type(end) is not int or not 1<=start<=end:return False
        for key,source in getattr(self.registry,'sources',{}).items():
            if key[0]!=e.get('repository') or key[2]!=e.get('commit') or key[3]!=e.get('path'):continue
            if source.get('sha256')!=e.get('content_sha256'):continue
            if e.get('blob') is not None and e['blob']!=source.get('blob'):continue
            if end<=len(source.get('text','').splitlines()):return True
        self.invalid_refs.add(id);return False

    def provider_support(self,key,evidence_refs):
        for delta in self.deltas.get(key,[]):
            for id in set(evidence_refs)&set(refs(delta.get('evidence_refs'))):
                repository=self.evidence.get(id,{}).get('repository')
                repo=self.registry.repos.get(repository,{}) if isinstance(repository,str) else {}
                if repo.get('service')==key[0] and self.valid_evidence(id):return True
        return False

    def _unique(self,choices):
        keys={self.key(op) for op,_ in choices}
        if not choices or None in keys or len(keys)!=1:return [(None,set())]
        return [(choices[0][0],set().union(*(support for _,support in choices)))]

    def _calls(self,consumer,own,relationship_ids=None):
        choices=[]
        for id,rel in self.rels.items():
            if relationship_ids is not None and id not in relationship_ids:continue
            if consumer not in names(rel.get('source')):continue
            shared=own&set(refs(rel.get('evidence_refs')))
            if not shared and not (relationship_ids is not None and not own):continue
            key=self.key(rel.get('target'))
            # Resolve ambiguity before the delta gate: dropping an off-delta
            # alternative would invent certainty for a shared call citation.
            target=rel.get('target') if key is not None and (not self.is_pr or key in self.deltas) else None
            choices.append((target,shared))
        return self._unique(choices)

    def resolve(self,consumer,evidence_refs,*,callsite=None,claim_ids=None,relationship_ids=None,split=False):
        own=self.consumer_refs(evidence_refs,consumer)
        if isinstance(callsite,dict):own=self.at_site(own,callsite)
        own=self.caller_refs(consumer,own)
        explicit=[id for id in claim_ids or [] if obj(self.claims.get(id,{}).get('subject')).get('kind')=='operation']
        if explicit:
            direct=[p for p in self.proofs if p['claim'] in explicit and p['consumer']==consumer]
            if not direct:return [(None,set())]
            result=[(None,set())] if any(not p['anchors']&own for p in direct) else []
            anchors=set().union(*(p['anchors']&own for p in direct))
            for anchor in sorted(anchors):
                result+=self._unique([(p['target'],{anchor}) for p in direct if anchor in p['anchors']])
            return result or [(None,set())]
        proofs=[p for p in self.proofs if p['consumer']==consumer and p['anchors']&own]
        if split and own:
            result=[]
            for anchor in sorted(own):
                matched=[(p['target'],{anchor}) for p in proofs if anchor in p['anchors']]
                result+=self._unique(matched) if matched else self._calls(consumer,{anchor},relationship_ids)
            return result
        if proofs:return self._unique([(p['target'],p['anchors']&own) for p in proofs])
        return self._calls(consumer,own,relationship_ids)
