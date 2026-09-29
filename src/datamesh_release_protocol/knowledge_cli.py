"""Offline metadata operations, using deployment-owned authority configuration."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from .knowledge import Authority, KnowledgeRecord, KnowledgeStore
from .knowledge_release import KnowledgeReleaseEngine
from .models import DataContract


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorities',type=Path,required=True)
    parser.add_argument('--ledger',type=Path,required=True)
    sub=parser.add_subparsers(dest='operation',required=True)
    p=sub.add_parser('propose');p.add_argument('--record',type=Path,required=True);p.add_argument('--actor',required=True);p.add_argument('--at',required=True)
    for op in ('confirm','revoke'):
        p=sub.add_parser(op);p.add_argument('--record-id',required=True);p.add_argument('--actor',required=True);p.add_argument('--evidence',required=True);p.add_argument('--at',required=True)
    p=sub.add_parser('impact');p.add_argument('--product',required=True);p.add_argument('--fields',nargs='*',default=[]);p.add_argument('--at',required=True)
    p=sub.add_parser('snapshot');p.add_argument('--proposal',required=True);p.add_argument('--old',type=Path,required=True);p.add_argument('--new',type=Path,required=True);p.add_argument('--at',required=True)
    p=sub.add_parser('resolve');p.add_argument('--snapshot',required=True)
    p=sub.add_parser('release');p.add_argument('--snapshot',required=True);p.add_argument('--run',required=True);p.add_argument('--at',required=True)
    sub.add_parser('journal')
    sub.add_parser('pending')
    p=sub.add_parser('ack');p.add_argument('--release-id',required=True);p.add_argument('--actor',required=True);p.add_argument('--evidence',required=True);p.add_argument('--at',required=True)
    args=parser.parse_args()
    store=KnowledgeStore([Authority.model_validate(a) for a in json.loads(args.authorities.read_text())],args.ledger)
    at=datetime.fromisoformat(args.at) if hasattr(args,'at') else None
    if args.operation=='propose':result=store.propose_record(KnowledgeRecord.model_validate_json(args.record.read_text()),args.actor,at)
    elif args.operation=='confirm':result=store.confirm_record(args.record_id,args.actor,args.evidence,at)
    elif args.operation=='revoke':result=store.revoke_record(args.record_id,args.actor,args.evidence,at)
    elif args.operation=='impact':result=store.list_impact(args.product,args.fields,at)
    elif args.operation=='snapshot':result=store.build_snapshot(args.proposal,DataContract.model_validate_json(args.old.read_text()),DataContract.model_validate_json(args.new.read_text()),at)
    elif args.operation=='resolve':result=store.resolve_snapshot(args.snapshot)
    elif args.operation=='journal':result=store.release_journal()
    elif args.operation=='pending':result=store.pending_publications()
    elif args.operation=='ack':
        snapshot=store.resolve_snapshot(store._release_commits[args.release_id]['result']['snapshot_id'])
        if not store._authorized(args.actor,snapshot.old_contract.owner_domain,'product'): raise PermissionError('producer authority required')
        result=store.acknowledge_publication(args.release_id,args.evidence,at)
    else:result=KnowledgeReleaseEngine(store).run(args.snapshot,args.run,at)
    print(json.dumps(result.model_dump(mode='json') if hasattr(result,'model_dump') else result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
