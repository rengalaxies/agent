"""Independent controlled-world R6-R8 qualification; never issues deployment grants."""
import copy
import json
from pathlib import Path
import tempfile
from lab.runtime.core import Stop, digest, discover, enforce_grant, stage_candidate, tree_digest
from lab.evaluator.verify import suite_digest


def grounds(root, candidate, inputs, authority):
    """All material local grounds. Live deployment state is intentionally outside CI scope."""
    return digest({'source':discover(root)['snapshot_digest'], 'candidate':tree_digest(candidate),
                   'suite':suite_digest(), 'runtime':tree_digest(Path(root)/'lab/runtime'),
                   'inputs':inputs, 'authority':authority})


def qualify(root, output):
    checks = {}
    def check(name, fn):
        try:
            evidence=fn();checks[name]={'status':'PASS','evidence':evidence}
        except Exception as exc:
            checks[name]={'status':'FAIL','error_class':type(exc).__name__}
    def denied(fn):
        try:fn()
        except Stop:return
        raise AssertionError('forbidden action accepted')
    def scope():
        grant={'grant_id':'ci','issuer':'independent-ci','expires_at':'2099-01-01T00:00:00+00:00',
               'environment_id':'lab','action_kinds':['transition'],'exact_scope':['S1'],'context_digest':'x'}
        enforce_grant(grant,'transition','S1','lab','x')
        for a,o,e,c in [('shell','S1','lab','x'),('transition','S2','lab','x'),('transition','S1','prod','x'),('transition','S1','lab','old')]:
            denied(lambda:enforce_grant(grant,a,o,e,c))
        denied(lambda:enforce_grant(grant,'transition','S1','lab','x',['ci']))
        denied(lambda:enforce_grant({**grant,'expires_at':'2000-01-01T00:00:00+00:00'},'transition','S1','lab','x'))
        with tempfile.TemporaryDirectory() as tmp:
            for path in ['../escape','lab/evaluator/expectations.json','lab/app/service.py']:
                denied(lambda:stage_candidate(root,Path(tmp)/'candidate',{'patches':[{'path':path,'content':'bad'}]}))
        return {'denied':['action','object','environment','stale_context','revoked','expired','path_escape','evaluator_write','app_write']}
    check('R6_exact_scope',scope)
    def coverage():
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'lab/app';path.mkdir(parents=True)
            (path/'rare.py').write_text('def monthly(db):\n db.execute("SELECT amount_rub FROM orders")\n')
            result=discover(tmp)
            assert any(d['target_ref'].endswith('#monthly') and d['owner']=='UNKNOWN' for d in result['dependencies'])
            assert result['coverage_gaps']
            (path/'rare.py').unlink()
            empty=discover(tmp)
            assert empty['coverage_gaps'] and not empty['dependencies']
        return {'control_world':'one rare literal SQL reader, no telemetry, missing catalog; then empty source',
                'rare_reader_found':True,'missing_owner':'UNKNOWN','empty_discovery':'coverage gaps retained, no compatibility verdict'}
    check('R7_known_world_unknowns',coverage)
    def freshness():
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);source=base/'source';candidate=base/'candidate'
            for folder in ['lab/app','lab/contracts','lab/catalog','lab/runtime']:(source/folder).mkdir(parents=True)
            files=['lab/app/a.py','lab/contracts/a.json','lab/catalog/topology.json','lab/runtime/controller.py']
            for f in files:(source/f).write_text('{}')
            candidate.mkdir();(candidate/'patch.sql').write_text('SELECT 1;')
            inputs={'snapshot':'ci-fixture-v1'};authority={'grant':'g','revision':1}
            before=grounds(source,candidate,inputs,authority)
            for f in files:
                (source/f).write_text('{"changed":true}')
                assert grounds(source,candidate,inputs,authority)!=before
                (source/f).write_text('{}')
            assert grounds(source,candidate,{'snapshot':'v2'},authority)!=before
            assert grounds(source,candidate,inputs,{'grant':'g','revision':2})!=before
            (candidate/'patch.sql').write_text('SELECT 2;')
            assert grounds(source,candidate,inputs,authority)!=before
        return {'invalidated_by':['source','contract','topology','runtime','data_input','authority','candidate'],
                'suite_digest':suite_digest(),'deployment_freshness':'NOT_QUALIFIED'}
    check('R8_material_grounds',freshness)
    report={'outcome':'PASS' if all(c['status']=='PASS' for c in checks.values()) else 'FAIL',
            'scope':'controlled CI world only; dispatcher race tests recorded separately', 'checks':checks,
            'automatic_application':'BLOCKED; no grant issued; candidate verifier remains financial-only'}
    Path(output).write_text(json.dumps(report,indent=2)+'\n');return report
