"""Gold-blind bounded first-attempt workers. Author development mode is explicit."""
from __future__ import annotations
import argparse
import base64
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from .common import ROOT,canonical,digest,load_input,read,sha,validate,write
from .normalizer import empty_prediction,normalize_core


def lexical(case,registry,output,configuration):
    output=Path(output);files={};runs=[];bundles={}
    for i,(key,source) in enumerate(registry.sources.items()):
        path=output/'snapshots'/str(i)/'source.txt';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(source['text']);files[str(path)]=(key,source)
    if case['operation_hints']:
        for hint in case['operation_hints']:
            argv=['rg','--fixed-strings','--line-number','--no-heading','--json','-e',hint['route'],'--',*files]
            if not files:continue
            proc=subprocess.run(argv,capture_output=True,text=True,check=False)
            runs.append(dict(argv=argv,exit_code=proc.returncode,stdout=proc.stdout,stderr=proc.stderr))
            (output/f'rg-{len(runs)-1}.stdout.log').write_text(proc.stdout)
            (output/f'rg-{len(runs)-1}.stderr.log').write_text(proc.stderr)
            for line in proc.stdout.splitlines():
                try:record=json.loads(line)
                except ValueError:runs[-1]['parse_error']=True;continue
                if record.get('type')!='match':continue
                hit=record['data'];key,source=files[hit['path']['text']];repo,phase,commit,path=key
                if repo==registry.provider:continue
                pairkey=dict(provider_service=hint['provider_service'],method=hint['method'],route=hint['route'],consumer_service=source['service'])
                b=bundles.setdefault(canonical(pairkey),dict(key=pairkey,witnesses=[],raw_refs=[],notes='Literal hit; no claim this is an HTTP call or a broken consumer.'))
                w=registry.witness(repo,phase,commit,path,hit['line_number'],hit['line_number'])
                if w not in b['witnesses']:b['witnesses'].append(w)
                b['raw_refs'].append(f'/runs/{len(runs)-1}/line/{hit["line_number"]}/{repo}/{path}')
    raw=dict(rg_version=subprocess.check_output(['rg','--version'],text=True).splitlines()[0],runs=runs,
             reason='query_not_identified' if not case['operation_hints'] else 'literal_search_only_not_absence_proof')
    p=empty_prediction(case['case_id'],'lexical_search_ls1',configuration,sha((canonical(raw)+'\n').encode()))
    p['candidates']=list(bundles.values())
    p['status']='USEFUL' if bundles else 'ABSTAINED'
    for gap in registry.gaps:p['limitations'].append(dict(code=gap['code'],scope=gap.get('repository') or 'inventory'))
    if registry.gaps:p['status']='PARTIAL'
    if any(r['exit_code'] not in (0,1) or r.get('parse_error') for r in runs):p.update(status='FAILED',output_valid=False,error_code='rg_failed')
    validate('normalized-prediction',p);return p,raw


def _worker(case_path,policy_path,method,output):
    case,policy,registry=load_input(case_path,policy_path)
    write(output/'validation.json',dict(input_packet_sha256=case['input_packet_sha256'],policy_sha256=case['policy_sha256'],coverage=registry.coverage()))
    from .registration import components
    identity=components()
    configuration=digest(dict(evaluator_sha=identity['evaluator_sha'],protocol_sha256=identity['protocol_sha256'],normalization_version=identity['normalization_version'],policy_sha256=case['policy_sha256'],input_packet_sha256=case['input_packet_sha256'],method=method))
    if method=='lexical_search_ls1':
        p,raw=lexical(case,registry,output,configuration)
    else:
        from agent_service.core_analyzer import CoreAnalyzer
        from agent_service.analysis import build_request,view_from_result
        from agent_service.publisher import result_doc
        analyzer=CoreAnalyzer(policy,output/'core',code_version='evaluation-static')
        try:
            analyzer.reconcile_graph(registry.base)
            subject=dict(provider='bitbucket',repository_id=registry.provider,pr_id=1,
                         base_sha=registry.base[registry.provider],head_sha=registry.head[registry.provider])
            request=build_request(installation_id=analyzer.policy.installation_id,environment=analyzer.policy.environment,
                request_id=case['case_id'],trigger_kind='pr',event_id=case['case_id'],resource_version=digest(subject),subject=subject,
                repository_revisions=registry.head,settings=analyzer.request_settings(),
                deadline=datetime.fromtimestamp(time.time()+case['budget']['wall_time_cap_seconds'],timezone.utc).isoformat())
            raw=analyzer.analyze(request,attachments={'mainline_revisions':registry.base},cancelled=lambda:False)
            payload=(json.dumps(raw,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=True)+'\n').encode()
            (output/'payload.json').write_bytes(payload)
            p=normalize_core(raw,case,registry,configuration=configuration,raw_sha=sha(payload))
            write(output/'normalized.json',p)
            view=view_from_result(raw,request)
            if not view.compatible:p.update(output_valid=False,error_code='result_request_mismatch')
            write(output/'presentation.json',result_doc(view,snapshot=subject,kind='pr',generation=1,gaps=[]))
            write(output/'request.json',request)
        finally:analyzer.close()
    raw_bytes=(json.dumps(raw,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=True)+'\n').encode();(output/'payload.json').write_bytes(raw_bytes)
    p['raw_artifact_sha256']=sha(raw_bytes);validate('normalized-prediction',p)
    write(output/'normalized.json',p);write(output/'coverage.json',registry.coverage())


def run_method(case_path,policy_path,method,output,*,development=False,freeze_path=None):
    # There is intentionally no flag that upgrades an unsigned development series.
    if not development:
        from .registration import readiness
        if freeze_path is None or readiness(read(freeze_path),case_path=case_path)['status']!='REGISTERED_READY':
            raise ValueError('independent_registration_required')
    if method not in ('impactmap_static','lexical_search_ls1'):raise ValueError('unknown_method')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    case=read(case_path);validate('case-input',case)
    cap=case['budget']['wall_time_cap_seconds']
    if case['lifecycle']!='ready' or cap is None or not (0<cap<=1800):raise ValueError('invalid_assigned_budget')
    if not development:
        from .registration import claim_attempt
        claim_attempt(read(freeze_path),case['case_id'],method)
    start=time.perf_counter();started=datetime.now(timezone.utc).isoformat()
    env={k:v for k,v in os.environ.items() if k in ('PATH','SYSTEMROOT','TEMP','TMP')}
    env.update(PYTHONPATH=os.pathsep.join([str(ROOT/'src'),str(ROOT),os.environ.get('PYTHONPATH','')]),PYTHONDONTWRITEBYTECODE='1')
    error=None;stdout='';stderr='';returncode=None;stdout_bytes=b'';stderr_bytes=b''
    def captured(value):return value.encode() if isinstance(value,str) else (value or b'')
    try:
        proc=subprocess.run([sys.executable,'-m','tools.impactmap_eval.runner','--worker','--case',str(Path(case_path).resolve()),
            '--policy',str(Path(policy_path).resolve()),'--method',method,'--output',str(output.resolve())],cwd=ROOT,env=env,capture_output=True,timeout=cap)
        stdout_bytes,stderr_bytes,returncode=captured(proc.stdout),captured(proc.stderr),proc.returncode
        if returncode:error='worker_failed'
    except subprocess.TimeoutExpired as exc:
        error='wall_time_cap_exceeded';stdout_bytes=captured(exc.stdout);stderr_bytes=captured(exc.stderr)
    except OSError:error='worker_launch_failed'
    stdout=stdout_bytes.decode('utf-8','replace');stderr=stderr_bytes.decode('utf-8','replace')
    (output/'stdout.log').write_bytes(stdout_bytes);(output/'stderr.log').write_bytes(stderr_bytes)
    if (output/'normalized.json').exists():p=read(output/'normalized.json')
    else:
        p=empty_prediction(case['case_id'],method,digest(case),sha(b''))
        if method=='impactmap_static' and (output/'payload.json').exists():
            class DiagnosticScope:
                repos={r['repository_id']:r for r in case['repositories']}
            try:p=normalize_core(read(output/'payload.json'),case,DiagnosticScope(),configuration=digest(case))
            except Exception:pass # raw bytes stay in immutable envelope, no TP credit
    if error:p.update(output_valid=False,status='FAILED',error_code=error)
    if not (output/'payload.json').exists():(output/'payload.json').write_bytes(b'')
    finished=datetime.now(timezone.utc).isoformat()
    envelope=dict(case_id=case['case_id'],method=method,attempt=dict(id=1,kind='primary'),started_at=started,finished_at=finished,
        wall_s=time.perf_counter()-start,wall_time_cap_seconds=cap,returncode=returncode,error_code=error,stdout=stdout,stderr=stderr,
        stdout_bytes_base64=base64.b64encode(stdout_bytes).decode(),stderr_bytes_base64=base64.b64encode(stderr_bytes).decode(),payload_utf8=(output/'payload.json').read_text(),payload_sha256=sha((output/'payload.json').read_bytes()))
    write(output/'raw.json',envelope) # immutable attempt record, not merely parsed payload
    p['raw_artifact_sha256']=sha((output/'raw.json').read_bytes());write(output/'normalized.json',p)
    receipt=dict(case_id=case['case_id'],method=method,attempt=dict(id=1,kind='primary'),development=development,
        started_at=started,finished_at=finished,wall_s=time.perf_counter()-start,wall_time_cap_seconds=cap,
        returncode=returncode,error_code=error,input_case_sha256=sha(Path(case_path).read_bytes()),policy_sha256=sha(Path(policy_path).read_bytes()),
        normalized_sha256=sha((output/'normalized.json').read_bytes()),raw_artifact_sha256=sha((output/'raw.json').read_bytes()),
        stderr_sha256=sha(stderr_bytes),stdout_sha256=sha(stdout_bytes),gold_received=False,input_validated=(output/'validation.json').exists())
    write(output/'receipt.json',receipt);return receipt


def main():
    p=argparse.ArgumentParser();p.add_argument('--worker',action='store_true');p.add_argument('--case',type=Path,required=True)
    p.add_argument('--policy',type=Path,required=True);p.add_argument('--method',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--development',action='store_true');p.add_argument('--freeze',type=Path);a=p.parse_args()
    try:
        if a.worker:_worker(a.case,a.policy,a.method,a.output)
        else:run_method(a.case,a.policy,a.method,a.output,development=a.development,freeze_path=a.freeze)
        return 0
    except Exception as exc:
        print(canonical(dict(error_code='evaluation_worker_failed',error_type=type(exc).__name__)));return 1


if __name__=='__main__':raise SystemExit(main())
