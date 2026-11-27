"""Verify portable receipts; --private also rescoring against original author inputs."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[3]
REPORT = Path(__file__).resolve().parent

def read(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(private=False):
    index = read(REPORT / 'raw-index.json')
    receipts = {(r['case_id'], r['method']): r for r in read(REPORT / 'receipts.json')}
    assert len(index) == len(receipts) == 80
    for item in index:
        norm = REPORT / item['normalized_file']
        receipt = receipts[item['case_id'], item['method']]
        assert sha(norm) == item['normalized_sha256'] == receipt['normalized_sha256']
        prediction = read(norm)
        assert prediction['raw_artifact_sha256'] == item['raw_envelope_sha256'] == receipt['raw_artifact_sha256']
        if item['exact_raw_file']:
            raw = REPORT / item['exact_raw_file']
            assert sha(raw) == item['raw_envelope_sha256']
            payload = read(raw)
            assert payload['case_id'] == item['case_id'] and payload['method'] == item['method']
            assert hashlib.sha256(payload['payload_utf8'].encode()).hexdigest() == payload['payload_sha256']
    prior = read(ROOT / 'research/evaluation/batch06/campaign-manifest.json')
    campaign = read(REPORT / 'campaign-manifest.json')
    for key in ('inputs_sha256', 'method_case_order', 'seed', 'wall_time_cap_seconds'):
        assert campaign[key] == prior[key], key
    assert campaign['post_tuning'] is True
    for name, expected in read(REPORT / 'historical-hashes.json').items():
        assert sha(ROOT / name) == expected, name
    summary = read(REPORT / 'summary.json')
    assert summary['real_experts'] == 0 and summary['authored_cases'] == 40
    assert summary['independent_research_status'] == 'NOT_REGISTERED / NOT_RUN'
    assert read(REPORT / 'readiness.json')['status'] != 'REGISTERED_READY'
    commit = read(REPORT / 'execution.json')['tested_core_commit']
    for path in sorted((ROOT / 'src/agent_graph').rglob('*.py')):
        relative = path.relative_to(ROOT).as_posix()
        assert path.read_bytes() == subprocess.check_output(['git', 'show', commit + ':' + relative], cwd=ROOT), relative
    assert campaign['core_identity'] == read(REPORT / 'candidate-freeze.json')['core_identity']
    if private:
        from tools.impactmap_eval.common import load_input
        from tools.impactmap_eval.scoring import score_case, aggregate
        corpus = ROOT / 'work/batch06/development-v2'
        records = {method: [] for method in ('impactmap_static', 'lexical_search_ls1')}
        for case_id in sorted(campaign['inputs_sha256']):
            source = corpus / 'inputs' / case_id
            case, policy, registry = load_input(source / 'case.json', source / 'policy.json')
            assert sha(source / 'case.json') == campaign['inputs_sha256'][case_id]
            oracle = read(corpus / 'author-oracles' / (case_id + '.json'))
            for method in records:
                prediction = read(REPORT / 'normalized' / case_id / (method + '.json'))
                records[method].append(score_case(prediction, oracle, registry, development=True))
        catalogue = read(corpus / 'author-catalogue.json')
        for method, values in records.items():
            assert aggregate(values, catalogue) == summary['methods'][method], method
        for item in index:
            assert sha(ROOT / item['private_original']) == item['raw_envelope_sha256']
    return dict(status='PASS', receipts=80, exact_core_envelopes=40, historical_files=225,
                unchanged_inputs_and_order=True, private_rescoring=private, independent_research='NOT_RUN')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--private', action='store_true')
    print(json.dumps(verify(parser.parse_args().private)))
