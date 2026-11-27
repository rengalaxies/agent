"""Verify batch-02 document contracts using synthetic, in-memory fixtures only.

This is not the future ImpactMap evaluation runner/scorer and supplies no cases,
human labels or measured product quality. Requires jsonschema 4.x, draft 2020-12.
"""
import copy
import csv
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
import json
import math
from pathlib import Path
import re
import sys

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CHECKS = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    CHECKS.append(name)


def read(path):
    return json.loads((ROOT / path).read_text())


validators = {}
for stem in ('case-input', 'reference-label', 'normalized-prediction'):
    schema = read(f'schemas/{stem}.schema.json')
    Draft202012Validator.check_schema(schema)
    validators[stem] = Draft202012Validator(schema, format_checker=FormatChecker())
    check(f'{stem}: metaschema valid', True)
    validators[stem].validate(read(f'templates/{stem}.template.json'))
    check(f'{stem}: empty draft accepted', True)


def accepts(stem, data, name):
    errors = list(validators[stem].iter_errors(data))
    check(name, not errors)


def rejects(stem, data, name):
    check(name, bool(list(validators[stem].iter_errors(data))))


# These repeated-digit hashes identify invented schema fixtures, never sources.
case = read('templates/case-input.template.json')
case.update(lifecycle='ready', case_id='SYNTHETIC-CONTRACT-ONLY', task='Schema validation fixture',
            repositories=[dict(repository_id='provider', service='svc', role='provider',
                               source_ref='synthetic-only', base_sha='0' * 40, head_sha='1' * 40,
                               tree_sha256='2' * 64, read_authorized=True)],
            operation_hints=[dict(provider_service='svc', method='GET', route='/example',
                                  basis_kind='task_text', basis_artifact_sha256='c' * 64)],
            policy_sha256='3' * 64, input_packet_sha256='4' * 64,
            budget=dict(wall_time_cap_seconds=1, freeze_manifest_ref='synthetic-only'))
accepts('case-input', case, 'ready input: fully populated synthetic fixture accepted')
empty_hints = copy.deepcopy(case)
empty_hints['operation_hints'] = []
accepts('case-input', empty_hints, 'ready no-API-change control: empty operation hints accepted')
bad = copy.deepcopy(case)
bad['repositories'][0]['base_sha'] = None
rejects('case-input', bad, 'ready provider: missing base SHA rejected')
bad = copy.deepcopy(case)
bad['repositories'][0]['head_sha'] = 'main'
rejects('case-input', bad, 'ready input: branch instead of commit rejected')
bad = copy.deepcopy(case)
bad['expected_consumers'] = ['leaked-gold']
rejects('case-input', bad, 'runner input: extra gold field rejected')
bad = copy.deepcopy(case)
bad['stratum'] = 'BREAKING_IN_PROFILE'
rejects('case-input', bad, 'runner input: stratum field rejected')
bad = copy.deepcopy(case)
bad['budget']['wall_time_cap_seconds'] = 0
rejects('case-input', bad, 'ready input: zero budget rejected')
bad = read('templates/case-input.template.json')
bad['lifecycle'] = 'ready'
rejects('case-input', bad, 'draft input cannot be relabelled ready without completion')

key = dict(provider_service='svc', method='GET', route='/example', consumer_service='client')
witness = dict(repository='consumer', phase='head', commit='5' * 40, path='client.py',
               line_start=1, line_end=1, quote_sha256='6' * 64)
label = read('templates/reference-label.template.json')
label.update(lifecycle='complete', expert_id='SYNTHETIC-NOT-A-HUMAN',
             completed_at='2026-11-14T00:00:00Z',
             profile=dict(membership='IN_PROFILE', boundary='none', rationale='Synthetic contract fixture'),
             scope_completeness=dict(search_complete=True, inventory_sha256='7' * 64,
                                     rationale='Synthetic contract fixture'),
             attestation=dict(confirmed_by_human=True, independent_before_outputs=True,
                              conflicts_of_interest='Synthetic fixture only; no real attestation'))
label['keys'] = [dict(key=key, label='AFFECTED', rationale='Synthetic only', witnesses=[witness],
                      expectation=dict(description='Synthetic only', artifact_ref='synthetic-only',
                                       artifact_sha256='8' * 64, basis='expert_contract_witness'))]
accepts('reference-label', label, 'complete independent label: synthetic structural fixture accepted')
bad = copy.deepcopy(label)
bad['attestation']['confirmed_by_human'] = False
rejects('reference-label', bad, 'complete label: unsigned human attestation rejected')
bad = copy.deepcopy(label)
bad['keys'][0]['witnesses'] = []
rejects('reference-label', bad, 'AFFECTED: missing witness rejected')
bad = copy.deepcopy(label)
bad['keys'][0]['expectation'] = None
rejects('reference-label', bad, 'AFFECTED: missing independent expectation rejected')
bad = copy.deepcopy(label)
bad['keys'][0]['witnesses'][0]['path'] = '../outside.py'
rejects('reference-label', bad, 'witness: parent path traversal rejected')
adjudicated = copy.deepcopy(label)
adjudicated['stage'] = 'adjudicated'
rejects('reference-label', adjudicated, 'complete adjudication: missing two source labels rejected')
adjudicated['source_labels'] = [dict(expert_id=e, artifact_ref=f'synthetic-{e}', artifact_sha256='9' * 64)
                                 for e in ('SYNTHETIC-A', 'SYNTHETIC-B')]
accepts('reference-label', adjudicated, 'adjudication: two structural source refs accepted')
bad = copy.deepcopy(adjudicated)
bad['keys'][0]['label'] = 'UNRESOLVED'
rejects('reference-label', bad, 'complete adjudicated gold: unresolved key rejected')

prediction = read('templates/normalized-prediction.template.json')
prediction.update(lifecycle='complete', raw_artifact_sha256='a' * 64,
                  configuration_sha256='b' * 64, output_valid=True, status='PARTIAL',
                  candidates=[dict(key=key, witnesses=[witness], raw_refs=['/findings/0'], notes='Synthetic')])
accepts('normalized-prediction', prediction, 'PARTIAL output: concrete candidate retained')
bad = copy.deepcopy(prediction)
bad['invalid_candidates'] = [dict(candidate_id='arbitrary-local-id', raw_ref='/findings/0', reason='unbound')]
rejects('normalized-prediction', bad, 'unbound candidate: arbitrary ID without canonical consumer bundle rejected')
bad = copy.deepcopy(prediction)
bad['tp'] = 1
rejects('normalized-prediction', bad, 'normalized output: premature gold verdict field rejected')
bad = copy.deepcopy(prediction)
bad['raw_artifact_sha256'] = None
rejects('normalized-prediction', bad, 'complete output: missing raw artifact hash rejected')

rows = list(csv.DictReader((ROOT / 'catalogue-blueprint.csv').open()))
check('catalogue: 40 unique planning slots', len(rows) == len({r['slot_id'] for r in rows}) == 40)
check('catalogue: exact 20/10/4/6 quotas', Counter(r['stratum'] for r in rows) == {
    'BREAKING_IN_PROFILE': 20, 'COMPATIBLE_IN_PROFILE': 10,
    'NO_CONSUMERS_IN_PROFILE': 4, 'OUT_OF_PROFILE': 6})
check('catalogue: no collected case, provenance or expert fabricated', all(
    r['state'] == 'PLANNED_NOT_COLLECTED' and not any(r[k] for k in
        ('case_id', 'origin_group_id', 'provenance', 'expert_a', 'expert_b')) for r in rows))
freeze = read('templates/freeze-manifest.template.json')
check('freeze: unregistered and unapproved', freeze['status'] == 'NOT_REGISTERED'
      and freeze['thresholds']['status'] == 'PROPOSED_NOT_APPROVED'
      and freeze['thresholds']['approved_by'] is None and not freeze['experts'])

# Arithmetic examples validate protocol identities, not evaluator implementation.
G, P, M, U = {'a', 'b'}, {'a', 'b', 'decoy'}, {'a'}, {'ambiguous'}
tp, fp, fn = len(M), len(P) - len(M) + len(U), len(G) - len(M)
check('strict illustrative arithmetic includes invalid witness FP and FN', (tp, fp, fn) == (1, 3, 1))
check('FAR 10 percent on 14 controls permits at most one case',
      max(k for k in range(15) if 10 * k <= 14) == 1)
check('recall exact boundary: 18/20 passes; 17/20 fails', 10 * 2 <= 18 + 2 and not 10 * 3 <= 17 + 3)
check('precision exact boundary: 17 TP/3 FP passes; 17 TP/4 FP fails', 17 * 3 <= 3 * 17 and not 17 * 4 <= 3 * 17)
minimum_n = math.ceil(math.log(0.05) / math.log(0.9))
check('one-sided exact zero-error illustration requires n=29', minimum_n == 29
      and 1 - 0.05 ** (1 / 29) <= 0.1 and 1 - 0.05 ** (1 / 28) > 0.1)


def wilson(k, n):
    z = 1.95996398454
    p = k / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [centre - half, centre + half]


intervals = {f'{k}/{n}': wilson(k, n) for k, n in [(18, 20), (17, 20), (1, 14)]}
check('Wilson illustrations agree with rounded text',
      [round(100 * x, 1) for x in intervals['18/20']] == [69.9, 97.2]
      and [round(100 * x, 1) for x in intervals['17/20']] == [64.0, 94.8]
      and [round(100 * x, 1) for x in intervals['1/14']] == [1.3, 31.5])
for p in ROOT.rglob('*.md'):
    for target in re.findall(r'\]\(([^)]+)\)', p.read_text()):
        if target.startswith(('http://', 'https://', '#')):
            continue
        path = Path(target) if target.startswith('/') else p.parent / target
        check(f'local link: {p.relative_to(ROOT)} -> {target}', path.exists())

report = dict(status='PASS', observed_utc=datetime.now(timezone.utc).isoformat(),
              scope='schema and document verification with synthetic fixtures only; no quality experiment',
              python=sys.version, jsonschema=version('jsonschema'), checks=CHECKS,
              check_count=len(CHECKS), illustrative_wilson_intervals=intervals,
              illustrative_exact_upper_0_of_14=1 - 0.05 ** (1 / 14),
              schema_limitations='Cross-file semantics, true independence and human attestations are not established by this check.')
(ROOT / 'verification/contract-checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(f'PASS: {len(CHECKS)} contract, catalogue, arithmetic and local-link checks; no empirical data produced')
