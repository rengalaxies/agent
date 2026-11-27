"""Controlled Git scale corpora. Generated oracles are not independent quality data.

No analyzed source is executed. The generator reuses the deterministic plumbing
of examples/orders_reporting; output must be new, source objects stay in work/.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess

from examples.orders_reporting.stand import _git, _tree, git_env
from agent_graph.contracts import Limits, Policy, canonical

VERSION = '1.0'
DEFAULT_SEED = 20261114
OPERATIONS = 8
LIMITS = dict(max_files=2048, max_file_bytes=65536, max_corpus_bytes=8_000_000, scan_seconds=60.0)
HOST = 'https://scale-provider.test'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n')


def _stats(files):
    inventory = []
    for path, text in sorted(files.items()):
        raw, lines = text.encode(), text.splitlines()
        inventory.append(dict(path=path, bytes=len(raw), sha256=_sha(raw),
                              python_physical_lines=len(lines),
                              python_nonblank_noncomment_lines=sum(bool(l.strip()) and not l.lstrip().startswith('#') for l in lines)))
    return dict(files=len(inventory), bytes=sum(i['bytes'] for i in inventory),
                python_physical_lines=sum(i['python_physical_lines'] for i in inventory),
                python_nonblank_noncomment_lines=sum(i['python_nonblank_noncomment_lines'] for i in inventory),
                inventory=inventory)


def _api(default=100, operation=0, removed=False):
    lines = ['from fastapi import FastAPI', 'app = FastAPI()', '']
    for i in range(OPERATIONS):
        if removed and i == operation:
            continue
        value = default if i == operation else 100
        lines += [f'@app.get("/items/{i}")', f'def items_{i}(page_size: int = {value}):',
                  '    return list(range(1000))[:page_size]', '']
    return '\n'.join(lines) + '\n'


def _client(repo, operations, path='client.py'):
    lines = ['import requests', f'BASE_URL = "{HOST}"', '']
    expected = []
    for op in operations:
        lines += [f'def read_{op:02d}():']
        line = len(lines) + 1
        lines += [f'    response = requests.get(BASE_URL + "/items/{op}", timeout=10)',
                  '    return response.json()', '']
        expected.append(dict(provider='provider', method='GET', route=f'/items/{op}',
                             consumer=f'consumer_{repo:02d}', repository=f'r{repo:02d}',
                             path=path, line=line, usage='SINGLE_REQUEST_OBSERVED'))
    return '\n'.join(lines) + '\n', expected


def _noise(lines, seed, repository, part):
    result = ['# Controlled arithmetic Python; never executed by the benchmark.']
    for index in range(lines // 6):
        salt = int.from_bytes(hashlib.sha256(f'{seed}:{repository}:{part}:{index}'.encode()).digest()[:4], 'big') % 997 + 1
        result += [f'def normalize_{part:03d}_{index:03d}(value):', f'    scaled = value + {salt}',
                   '    limited = scaled % 1009', '    if limited < 500:',
                   f'        return limited + {salt % 19}', '    return limited']
    result += [f'reference_{part:03d}_{i} = {seed % 1000 + i}' for i in range(lines % 6)]
    return '\n'.join(result) + '\n'


def _replace_file(repo, env, tree, name, content):
    entries = _git(repo, env, 'ls-tree', tree).splitlines()
    entries = [e for e in entries if e.split('\t', 1)[1] != name]
    blob = _git(repo, env, 'hash-object', '-w', '--stdin', data=content.encode())
    entries.append(f'100644 blob {blob}\t{name}')
    return _git(repo, env, 'mktree', data=('\n'.join(sorted(entries)) + '\n').encode())


def _commit(repo, env, tree, branch, message, parent=None):
    args = ['commit-tree', tree, '-m', message]
    if parent:
        args += ['-p', parent]
    commit = _git(repo, env, *args)
    _git(repo, env, 'update-ref', f'refs/heads/{branch}', commit)
    return commit


def suite_specs():
    return [dict(name=name, repositories=repos, python_lines=lines, calls_per_consumer=calls)
            for name, repos, lines, calls in [
                ('repos5-lines50k', 5, 50_000, 1), ('repos10-lines100k', 10, 100_000, 1),
                ('repos10-lines50k', 10, 50_000, 1), ('repos5-lines100k', 5, 100_000, 1),
                ('repos5-lines50k-dense', 5, 50_000, 8), ('repos5-lines1k-anchor', 5, 1_000, 1)]]


def generate_corpus(output, *, repositories, python_lines, seed=DEFAULT_SEED, calls_per_consumer=1):
    output = Path(output)
    if output.exists():
        raise FileExistsError('corpus_output_exists')
    if (type(repositories) is not int or not 3 <= repositories <= 30 or type(python_lines) is not int
            or not 1 <= python_lines <= 200_000 or type(seed) is not int or not 0 <= seed <= 2**32 - 1
            or type(calls_per_consumer) is not int or not 1 <= calls_per_consumer <= OPERATIONS):
        raise ValueError('corpus_invalid_parameters')
    active = min(3, repositories - 2)
    files, dependencies = {}, []
    for r in range(repositories):
        if r == 0:
            files[r] = {'api.py': _api()}
        elif r <= active:
            text, edges = _client(r, range(calls_per_consumer))
            files[r] = {'client.py': text}
            dependencies.extend(edges)
        else:
            files[r] = {'extension.py': 'def unrelated(value):\n    return value + 1\n'}
    minimum = sum(_stats(f)['python_nonblank_noncomment_lines'] for f in files.values())
    if python_lines < minimum:
        raise ValueError('corpus_target_below_structural_minimum')
    remaining = python_lines - minimum
    for r in range(repositories):
        count = remaining // repositories + (r < remaining % repositories)
        for part, start in enumerate(range(0, count, 480)):
            files[r][f'noise/part_{part:03d}.py'] = _noise(min(480, count - start), seed, r, part)
    all_stats = {r: _stats(f) for r, f in files.items()}
    totals = {k: sum(v[k] for v in all_stats.values()) for k in ('files', 'bytes', 'python_physical_lines', 'python_nonblank_noncomment_lines')}
    if (totals['bytes'] > LIMITS['max_corpus_bytes'] or totals['files'] > LIMITS['max_files']
            or any(i['bytes'] > LIMITS['max_file_bytes'] for v in all_stats.values() for i in v['inventory'])):
        raise ValueError('corpus_exceeds_declared_limits')
    output.mkdir(parents=True, mode=0o700)
    home = output / 'git-home'
    home.mkdir()
    (home / 'gitconfig').write_text('')
    env = git_env(home)
    paths, trees, base, records = {}, {}, {}, []
    for r in range(repositories):
        rid = f'r{r:02d}'
        repo = output / 'repositories' / rid
        repo.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', '--initial-branch=main', str(repo)], env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        _git(repo, env, 'config', 'core.autocrlf', 'false')
        tree = _tree(repo, env, files[r])
        commit = _commit(repo, env, tree, 'main', f'scale-v{VERSION} seed={seed} {rid}: main')
        paths[r], trees[r], base[rid] = repo, tree, commit
        records.append(dict(repository=rid, service='provider' if r == 0 else f'consumer_{r:02d}',
                            root=f'repositories/{rid}', main_commit=commit, main_tree=tree, **all_stats[r]))
    updates, independent, versions = [], [], []
    parent = base['r00']
    for step in range(1, 11):
        tree = _replace_file(paths[0], env, trees[0], 'api.py', _api(100 - step))
        head = _commit(paths[0], env, tree, f'change-{step:02d}', f'scale-v{VERSION}: head update {step}', parent)
        updates.append(dict(sequence=step, pr_id=1, provider_repository='r00', base_sha=base['r00'],
                            parent_sha=parent, head_sha=head, event_id=f'head-update-{step:02d}'))
        parent = head
        other = _commit(paths[0], env, tree, f'pr-{step:02d}', f'scale-v{VERSION}: independent PR {step}', base['r00'])
        independent.append(dict(sequence=step, pr_id=step, provider_repository='r00', base_sha=base['r00'],
                                parent_sha=base['r00'], head_sha=other, event_id=f'independent-pr-{step:02d}'))
        versions += [dict(repository='r00', branch=f'change-{step:02d}', commit=head, tree=tree),
                     dict(repository='r00', branch=f'pr-{step:02d}', commit=other, tree=tree)]
    last = repositories - 1
    text, added = _client(last, [0], path='extension.py')
    added_tree = _replace_file(paths[last], env, trees[last], 'extension.py', text)
    added_head = _commit(paths[last], env, added_tree, 'consumer-added', 'scale-v1: previously unrelated consumer', base[f'r{last:02d}'])
    removed_text, removed_remaining = _client(1, range(1, calls_per_consumer))
    removed_tree = _replace_file(paths[1], env, trees[1], 'client.py', removed_text)
    removed_head = _commit(paths[1], env, removed_tree, 'consumer-removed', 'scale-v1: remove operation-0 call', base['r01'])
    gone_tree = _replace_file(paths[0], env, trees[0], 'api.py', _api(removed=True))
    gone_head = _commit(paths[0], env, gone_tree, 'operation-removed', 'scale-v1: remove operation-0', base['r00'])
    versions += [dict(repository=f'r{last:02d}', branch='consumer-added', commit=added_head, tree=added_tree),
                 dict(repository='r01', branch='consumer-removed', commit=removed_head, tree=removed_tree),
                 dict(repository='r00', branch='operation-removed', commit=gone_head, tree=gone_tree)]
    head = {**base, 'r00': updates[0]['head_sha']}
    scenarios = dict(baseline=dict(head_revisions=head),
                     new_consumer=dict(head_revisions={**head, f'r{last:02d}': added_head}),
                     removed_consumer=dict(head_revisions={**head, 'r01': removed_head}),
                     operation_removed=dict(head_revisions={**base, 'r00': gone_head}),
                     partial_access=dict(head_revisions=head, unavailable_repository='r01',
                                         fault='configured source absent; not a credential revocation test'))
    oracle = dict(schema_version='impactmap-controlled-oracle-1', provenance='controlled_generated_not_independent',
                  operations=[dict(provider='provider', method='GET', route=f'/items/{i}') for i in range(OPERATIONS)],
                  expected_dependencies=dependencies, new_consumer_dependencies=added,
                  removed_consumer_remaining_dependencies=removed_remaining,
                  removed_consumer_key=dict(consumer='consumer_01', route='/items/0'),
                  note='Generation records for topology checks; not human TP/FP/FN labels or proof of runtime compatibility.')
    _write_json(output / 'oracle.json', oracle)
    policy = dict(installation_id='scale-controlled', environment='offline', subject='scale-verifier',
                  capabilities=['read_context', 'maintain', 'propose', 'report_check'],
                  repositories=[dict(id=r['repository'], service=r['service'], root=r['root'],
                                     snapshot='git', revision=r['main_commit'], include=['*.py'], allowed_refs=['refs/heads/*']) for r in records],
                  addresses=[dict(service='provider', base_url=HOST)], limits=dict(LIMITS))
    manifest = dict(schema_version='impactmap-scale-corpus-1',
                    generator=dict(version=VERSION, seed=seed, sha256=_sha(Path(__file__).read_bytes())),
                    parameters=dict(repositories=repositories, python_lines=python_lines, calls_per_consumer=calls_per_consumer,
                                    active_consumers=active, operations=OPERATIONS),
                    profile='http-requests-6', provenance='controlled_generated',
                    effective_limits=dict(LIMITS), product_default_limits=Limits().model_dump(),
                    totals=totals, repositories=records, versions=versions,
                    known_dependency_callsites=len(dependencies), base_revisions=base, policy=policy, scenarios=scenarios,
                    oracle_sha256=_sha((output / 'oracle.json').read_bytes()),
                    streams={family: {str(n): seq[:n] for n in (1, 5, 10)}
                             for family, seq in [('head_updates', updates), ('independent_prs', independent)]})
    _write_json(output / 'corpus-manifest.json', manifest)
    _write_json(output / 'benchmark-input.json', load_benchmark_input(output))
    return manifest


def load_benchmark_input(corpus_root, scenario='baseline'):
    root = Path(corpus_root).resolve()
    manifest = json.loads((root / 'corpus-manifest.json').read_text())
    policy = copy.deepcopy(manifest['policy'])
    selection = manifest['scenarios'][scenario]
    for repo in policy['repositories']:
        relative = Path(repo['root'])
        path = (root / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(root):
            raise ValueError('corpus_root_escape')
        repo['root'] = str(root / 'unavailable' / repo['id']) if selection.get('unavailable_repository') == repo['id'] else str(path)
    return dict(schema_version='impactmap-benchmark-input-1', provenance='controlled_generated', policy=policy,
                base_revisions=manifest['base_revisions'], head_revisions=selection['head_revisions'],
                provider_repository='r00', pr_id=1)


def _dependency_projection(context):
    operations = {o['id']: o for o in context['graph']['operations']}
    return sorted([dict(provider=operations[d['operation_id']]['service'], method=operations[d['operation_id']]['method'],
                        route=operations[d['operation_id']]['path'], consumer=d['consumer'], repository=d['repository'],
                        path=d['path'], line=d['call_line'], usage=d['usage']) for d in context['graph']['dependencies']], key=canonical)


def finding_projection(graph, base, analysis):
    head = graph.context(analysis['context_used_id'])
    deps = {d['id']: d for c in (base, head) for d in c['graph']['dependencies']}
    deps.update({d['id']: d for d in analysis.get('removed_dependencies', [])})
    ops = {o['id']: o for c in (base, head) for o in c['graph']['operations']}
    result = []
    for finding in analysis['findings']:
        dep = deps[finding['dependency_id']]
        op = ops[dep['operation_id']]
        witnesses = []
        for citation in finding['evidence']:
            context = base if citation['source_id'] in base['sources'] else head
            graph.get_evidence(context['id'], citation)
            source = context['sources'][citation['source_id']]
            witnesses.append(dict(repository=source['repository'], path=source['path'],
                                  phase='base' if context is base else 'head',
                                  start_line=citation['start_line'], end_line=citation['end_line'],
                                  quote_sha256=_sha(citation['quote'].encode())))
        result.append(dict(provider=op['service'], method=op['method'], route=op['path'], consumer=finding['consumer'],
                           code=finding['code'], usage=finding['usage'], repository=finding['callsite']['repository'],
                           path=finding['callsite']['path'], line=finding['callsite']['line'],
                           dependency_freshness=finding['dependency_freshness'], witnesses=sorted(witnesses, key=canonical)))
    return sorted(result, key=canonical)


def _expected_findings(dependencies, *, code='POSSIBLE_TRUNCATION', freshness='CURRENT'):
    return sorted([{**d, 'code': code, 'dependency_freshness': freshness}
                   for d in dependencies if d['route'] == '/items/0'], key=canonical)


def _without_witnesses(findings):
    # Expected pairs/locations are generation records, not extractor-derived citations.
    return sorted([{k: v for k, v in f.items() if k != 'witnesses'} for f in findings], key=canonical)


def verify_corpus(corpus_root, state_root):
    from agent_graph.engine import Graph
    from agent_graph.graph_store import GraphStore
    from agent_graph.graph_query import GraphQuery
    from agent_graph.store import Store
    from tools.benchmark_impactmap import context_counts

    root, state = Path(corpus_root), Path(state_root)
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    manifest = json.loads((root / 'corpus-manifest.json').read_text())
    oracle_bytes = (root / 'oracle.json').read_bytes()
    if _sha(oracle_bytes) != manifest['oracle_sha256']:
        raise ValueError('corpus_oracle_hash_mismatch')
    oracle = json.loads(oracle_bytes)
    inp = load_benchmark_input(root)
    policy = Policy.model_validate(inp['policy'])
    store = Store(state / 'graph')
    try:
        graph, gs = Graph(policy, store), GraphStore(store)
        base = graph.prepare_context(revisions=inp['base_revisions'])
        actual = _dependency_projection(base)
        expected = sorted(oracle['expected_dependencies'], key=canonical)
        actual_operations = sorted([dict(provider=o['service'], method=o['method'], route=o['path'])
                                    for o in base['graph']['operations']], key=canonical)
        actual_inventory = {(s['repository'], s['path'], s['sha256'], len(s['text'].encode()),
                             len(s['text'].splitlines()), sum(bool(l.strip()) and not l.lstrip().startswith('#')
                                                             for l in s['text'].splitlines()))
                            for s in base['sources'].values()}
        expected_inventory = {(r['repository'], i['path'], i['sha256'], i['bytes'],
                               i['python_physical_lines'], i['python_nonblank_noncomment_lines'])
                              for r in manifest['repositories'] for i in r['inventory']}
        counts = context_counts(base)
        gs.sync_code(base)
        entities = gs.entities(graph.scope)
        rel_id = next(r['id'] for r in gs.relationships(graph.scope).values() if r['kind'] == 'calls'
                      and entities[r['source']].get('service') == 'consumer_01'
                      and entities[r['target']].get('route') == '/items/0')
        baseline = graph.analyze_change(base['id'], revisions=inp['head_revisions'])
        located = finding_projection(graph, base, baseline)
        baseline_match = _without_witnesses(located) == _expected_findings(expected)
        add_input = load_benchmark_input(root, 'new_consumer')
        added = graph.analyze_change(base['id'], revisions=add_input['head_revisions'])
        added_projection = finding_projection(graph, base, added)
        added_head = graph.context(added['context_used_id'])
        expected_added = sorted(expected + oracle['new_consumer_dependencies'], key=canonical)
        added_dependencies_match = _dependency_projection(added_head) == expected_added
        added_findings_match = _without_witnesses(added_projection) == _expected_findings(expected_added)
        last = f"consumer_{manifest['parameters']['repositories'] - 1:02d}"
        new_found = not any(d['consumer'] == last for d in actual) and any(
            f['consumer'] == last and f['route'] == '/items/0' and f['code'] == 'POSSIBLE_TRUNCATION' for f in added_projection)
        gs.sync_code(added_head)
        removed = graph.prepare_context(revisions=load_benchmark_input(root, 'removed_consumer')['head_revisions'])
        # Re-rendering client.py shifts the surviving functions; use the head's
        # generation records rather than retaining their old line numbers.
        expected_removed = ([d for d in expected if d['consumer'] != 'consumer_01']
                            + oracle['removed_consumer_remaining_dependencies'])
        removed_dependencies_match = _dependency_projection(removed) == sorted(expected_removed, key=canonical)
        gs.sync_code(removed)
        query = GraphQuery.for_policy(gs, policy)
        removed_status = query.relationship(rel_id)['status']
        current_entities = gs.entities(graph.scope)
        active_pairs = {(current_entities[r['source']]['service'], current_entities[r['target']]['service'],
                         current_entities[r['target']]['method'], current_entities[r['target']]['route'])
                        for r in gs.relationships(graph.scope).values() if r['kind'] == 'calls'
                        and query.relationship(r['id'])['status'] == 'ACTIVE'}
        expected_pairs = {(d['consumer'], d['provider'], d['method'], d['route']) for d in expected_removed}
        gs.sync_code(base)
        partial_input = load_benchmark_input(root, 'partial_access')
        partial_policy = Policy.model_validate(partial_input['policy'])
        partial = Graph(partial_policy, store).prepare_context(revisions=partial_input['head_revisions'])
        gs.sync_code(partial)
        stale = GraphQuery.for_policy(gs, partial_policy).relationship(rel_id)
        gone = graph.analyze_change(base['id'], revisions=load_benchmark_input(root, 'operation_removed')['head_revisions'])
        gone_findings = finding_projection(graph, base, gone)
        operation_removed_verified = (_without_witnesses(gone_findings)
                                      == _expected_findings(expected, code='OPERATION_REMOVED', freshness='CURRENT')
                                      and len(gone['deltas']) == 1 and gone['deltas'][0]['code'] == 'OPERATION_REMOVED')
        result = dict(schema_version='impactmap-corpus-verification-1', provenance='controlled_not_independent_quality',
                      counts=counts, counts_match_manifest=all(counts[k] == manifest['totals'][v] for k, v in [
                          ('files_read', 'files'), ('bytes_read', 'bytes'), ('python_physical_lines', 'python_physical_lines'),
                          ('python_nonblank_noncomment_lines', 'python_nonblank_noncomment_lines')]),
                      base_oracle_match=actual == expected,
                      operations_oracle_match=actual_operations == sorted(oracle['operations'], key=canonical),
                      source_inventory_match=actual_inventory == expected_inventory,
                      located_baseline_findings=located, baseline_findings_oracle_match=baseline_match,
                      new_consumer_detected=new_found, new_consumer_findings=added_projection,
                      new_consumer_findings_oracle_match=added_findings_match,
                      added_head_dependencies_match=added_dependencies_match,
                      removed_head_dependencies_match=removed_dependencies_match,
                      remaining_persistent_calls_match=active_pairs == expected_pairs,
                      removed_call_retracted=removed_status == 'RETRACTED', removed_status=removed_status,
                      partial_access_visible=partial['coverage'] == 'PARTIAL' and any(g['code'] == 'commit_unavailable' for g in partial['graph']['gaps']),
                      partial_available_repositories=sum(s['tree'] is not None for s in partial['snapshots']),
                      partial_gap_codes=sorted({g['code'] for g in partial['graph']['gaps']}),
                      stale_preserved=stale['status'] == 'STALE' and 'source_unavailable' in stale['freshness']['reasons'],
                      stale_status=stale['status'], operation_removed_verified=operation_removed_verified,
                      removed_operation_findings=gone_findings,
                      removed_comparative_coverage=gone['coverage'],
                      removed_head_coverage=gone['head_coverage'],
                      resolved_removed_calls=gone['resolved_removed_calls'])
        result['verification_passed'] = all(result[k] for k in ['counts_match_manifest', 'base_oracle_match',
            'operations_oracle_match', 'source_inventory_match',
            'baseline_findings_oracle_match', 'new_consumer_findings_oracle_match', 'added_head_dependencies_match',
            'removed_head_dependencies_match', 'remaining_persistent_calls_match', 'operation_removed_verified',
            'new_consumer_detected', 'removed_call_retracted', 'partial_access_visible', 'stale_preserved'])
        _write_json(state / 'verification.json', result)
        return result
    finally:
        store.close()


def verify_noise_pair(anchor, large, state_root):
    from agent_graph.engine import Graph
    from agent_graph.store import Store

    root = Path(state_root)
    root.mkdir(parents=True, exist_ok=False)
    projections = []
    for index, corpus in enumerate((anchor, large)):
        inp = load_benchmark_input(corpus)
        store = Store(root / f'graph-{index}')
        try:
            graph = Graph(Policy.model_validate(inp['policy']), store)
            base = graph.prepare_context(revisions=inp['base_revisions'])
            analysis = graph.analyze_change(base['id'], revisions=inp['head_revisions'])
            projections.append(finding_projection(graph, base, analysis))
        finally:
            store.close()
    result = dict(same_located_findings=projections[0] == projections[1], finding_count=len(projections[0]),
                  compared_fields='provider,method,route,consumer,code,usage,repository,path,line,dependency_freshness and witness repository/path/phase/lines/quote hashes; each citation checked against pinned source',
                  excluded='commit/source/receipt identifiers differ with unrelated corpus content; no claim of equal provenance')
    _write_json(root / 'comparison.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--suite', action='store_true')
    parser.add_argument('--repositories', type=int, default=5)
    parser.add_argument('--python-lines', type=int, default=50_000)
    parser.add_argument('--calls-per-consumer', type=int, default=1)
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.suite:
            args.output.mkdir(parents=True, exist_ok=False)
            results = []
            for spec in suite_specs():
                spec = dict(spec)
                name = spec.pop('name')
                result = generate_corpus(args.output / name, seed=args.seed, **spec)
                record = dict(name=name, parameters=result['parameters'], totals=result['totals'])
                if args.verify:
                    record['verification_passed'] = verify_corpus(args.output / name, args.output / (name + '-verification'))['verification_passed']
                results.append(record)
            _write_json(args.output / 'suite.json', results)
            print(canonical(results))
            return 0 if all(r.get('verification_passed', True) for r in results) else 1
        manifest = generate_corpus(args.output, repositories=args.repositories, python_lines=args.python_lines,
                                   calls_per_consumer=args.calls_per_consumer, seed=args.seed)
        result = dict(parameters=manifest['parameters'], totals=manifest['totals'])
        if args.verify:
            result['verification_passed'] = verify_corpus(args.output, args.output.with_name(args.output.name + '-verification'))['verification_passed']
        print(canonical(result))
        return 0 if result.get('verification_passed', True) else 1
    except Exception as exc:
        print(canonical(dict(error_code='corpus_preparation_failed', error_type=type(exc).__name__)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
