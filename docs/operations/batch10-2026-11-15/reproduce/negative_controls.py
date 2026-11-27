"""Saved-evidence guards reject corruption, missing scenarios and forged counts."""
from pathlib import Path
import hashlib,importlib.util,json,shutil,tempfile
REPORT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('batch10_verifier',REPORT/'reproduce/verify.py');v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
results=[]
for case in ('corrupt_manifest','missing_scenario','duplicate_scenario','zero_test_count'):
    with tempfile.TemporaryDirectory(prefix='impactmap10-negative-') as temporary:
        clone=Path(temporary)/'report';shutil.copytree(REPORT,clone);v.REPORT=clone
        if case=='corrupt_manifest':
            target=clone/'candidate-manifest.json';target.write_bytes(target.read_bytes()+b'corrupt');expected='artifact_hash:'
        elif case in ('missing_scenario','duplicate_scenario'):
            target=clone/'linux/install-acceptance-v3.json';data=json.loads(target.read_text())
            if case=='missing_scenario':data['scenarios'].pop()
            else:data['scenarios'][-1]=data['scenarios'][0]
            target.write_text(json.dumps(data));expected='acceptance_scenario_set'
        else:
            target=clone/'linux/status.json';data=json.loads(target.read_text())
            next(s for s in data['stages'] if s['name']=='full-tests-release')['tests']=0
            target.write_text(json.dumps(data));expected='full_test_count'
        if case!='corrupt_manifest':
            hashes=json.loads((clone/'artifact-hashes.json').read_text());hashes[str(target.relative_to(clone))]=hashlib.sha256(target.read_bytes()).hexdigest()
            (clone/'artifact-hashes.json').write_text(json.dumps(hashes))
        try:v.verify()
        except ValueError as exc:
            assert str(exc).startswith(expected),(case,str(exc));results.append(dict(case=case,rejected=True,reason=str(exc)))
        else:raise AssertionError('invalid_evidence_accepted:'+case)
print(json.dumps(dict(status='PASS',controls=results),sort_keys=True))
