"""Offline ImpactMap baseline on pinned sources; never polls, fetches or publishes externally.

Run with PYTHONPATH=src:. python -m tools.benchmark_impactmap --output NEW_DIR.
Fresh application state is not a claim of cold OS caches. Raw spans are nested;
exclusive durations subtract direct children. RSS is a cumulative process peak.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager, nullcontext
import csv
from datetime import datetime, timezone
import functools
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

from agent_graph import core_identity
from agent_graph.contracts import Policy
from agent_service.core_analyzer import CoreAnalyzer

ROOT = Path(__file__).resolve().parents[1]
VOLATILE = frozenset({'timings', 'checked_at', 'started_at', 'finished_at', 'assessed_at'})
CPU_FIELDS = ('self_user_s', 'self_system_s', 'child_user_s', 'child_system_s')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def semantic(value):
    """Only volatile timing metadata is excluded; identities, evidence and freshness stay."""
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


def rss_bytes(value, system=None):
    system = system or platform.system()
    return int(value * (1024 if system == 'Linux' else 1)) if system in ('Linux', 'Darwin') else None


def usage():
    own = resource.getrusage(resource.RUSAGE_SELF)
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    return dict(self_user_s=own.ru_utime, self_system_s=own.ru_stime,
                child_user_s=child.ru_utime, child_system_s=child.ru_stime,
                self_peak_rss_bytes=rss_bytes(own.ru_maxrss),
                children_peak_rss_bytes=rss_bytes(child.ru_maxrss))


class SpanRecorder:
    def __init__(self, *, clock=time.perf_counter, usage=usage):
        self.clock, self.usage = clock, usage
        self.spans, self.stack = [], []

    @contextmanager
    def span(self, stage):
        row = dict(span_id=len(self.spans), parent_id=self.stack[-1]['span_id'] if self.stack else None,
                   depth=len(self.stack), stage=stage, error_type=None)
        self.spans.append(row)
        row['_children'] = dict(wall_s=0.0, **{k: 0.0 for k in CPU_FIELDS})
        start, before = self.clock(), self.usage()
        self.stack.append(row)
        try:
            yield
        except BaseException as exc:
            row['error_type'] = type(exc).__name__  # never exc.args, policy, source text or env
            raise
        finally:
            elapsed, after = self.clock() - start, self.usage()
            self.stack.pop()
            child = row.pop('_children')
            row['wall_s'] = elapsed
            row['exclusive_wall_s'] = max(0.0, elapsed - child['wall_s'])
            for key in CPU_FIELDS:
                row[key] = max(0.0, after[key] - before[key])
                row['exclusive_' + key] = max(0.0, row[key] - child[key])
            for key in ('self_peak_rss_bytes', 'children_peak_rss_bytes'):
                row[key] = after[key]
            if self.stack:
                parent = self.stack[-1]['_children']
                parent['wall_s'] += elapsed
                for key in CPU_FIELDS:
                    parent[key] += row[key]


def context_counts(context):
    sources = list(context['sources'].values())
    python = [s for s in sources if s['path'].endswith('.py')]
    return dict(
        basis_sha256=context['basis'],
        repositories_configured=len(context['snapshots']),
        repositories_available=sum(s.get('tree') is not None for s in context['snapshots']),
        snapshots=[{k: s.get(k) for k in ('repository', 'mode', 'commit', 'tree')} for s in context['snapshots']],
        files_read=len(sources), inventory_entries=len(context['inventory']),
        text_lines=sum(len(s['text'].splitlines()) for s in sources),
        python_files=len(python), python_physical_lines=sum(len(s['text'].splitlines()) for s in python),
        python_nonblank_noncomment_lines=sum(bool(line.strip()) and not line.lstrip().startswith('#')
                                            for s in python for line in s['text'].splitlines()),
        bytes_read=context['metrics']['bytes_read'], scan_passes=context['metrics']['scan_passes'],
        operations=len(context['graph']['operations']), dependencies=len(context['graph']['dependencies']),
        coverage=context['coverage'], gap_counts=dict(Counter(g['code'] for g in context['graph']['gaps'])))


@contextmanager
def instrument(meter, contexts):
    """Single-threaded benchmark process only. No global wrapper survives this scope."""
    from agent_graph import engine
    from agent_graph.graph_store import GraphStore

    originals = []

    def wrap(owner, name, label, observer=None):
        original = getattr(owner, name)
        originals.append((owner, name, original))

        @functools.wraps(original)
        def measured(*args, **kwargs):
            if label:
                with meter.span(label):
                    result = original(*args, **kwargs)
            else:
                result = original(*args, **kwargs)
            if observer:
                with meter.span('inventory_metrics'):
                    observer(result)
            return result

        setattr(owner, name, measured)

    try:
        wrap(engine, 'collect', 'collect')
        wrap(engine, 'extract', 'extract')
        wrap(GraphStore, 'sync_code', 'graph_sync')
        wrap(engine.Graph, 'prepare_context', None, lambda c: contexts.append(context_counts(c)))
        yield
    finally:
        for owner, name, original in reversed(originals):
            setattr(owner, name, original)


def validate_manifest(manifest):
    fields = {'schema_version', 'provenance', 'policy', 'base_revisions', 'head_revisions',
              'provider_repository', 'pr_id'}
    if set(manifest) != fields or manifest['schema_version'] != 'impactmap-benchmark-input-1':
        raise ValueError('benchmark_invalid_manifest')
    if manifest['provenance'] not in ('author_fixture', 'author_pilot_on_vm', 'author_pilot_snapshot',
                                     'authorized_external', 'controlled_generated'):
        raise ValueError('benchmark_invalid_provenance')
    if manifest['policy'].get('model') is not None:
        raise ValueError('benchmark_model_must_be_off')
    policy = Policy.model_validate(manifest['policy'])
    if any(r.snapshot != 'git' for r in policy.repositories):
        raise ValueError('benchmark_requires_git_pins')
    from agent_graph.sources import pins

    expected = {r.id for r in policy.repositories}
    for revisions in (manifest['base_revisions'], manifest['head_revisions']):
        if set(revisions) != expected:
            raise ValueError('benchmark_incomplete_revision_map')
        pins(policy, revisions)
    if manifest['provider_repository'] not in expected or not isinstance(manifest['pr_id'], int) or manifest['pr_id'] < 1:
        raise ValueError('benchmark_invalid_provider')
    return policy


def run_case(manifest, state_root, *, instrumented=True):
    policy = validate_manifest(manifest)
    state_root = Path(state_root)
    state_root.mkdir(parents=True, mode=0o700, exist_ok=False)
    meter, contexts, samples = SpanRecorder(), [], []
    from agent_service.analysis import build_request, view_from_result
    from agent_service.connectors.base import marker_line
    from agent_service.jira_presentation import summary_doc
    from agent_service.publisher import DirectorySink, doc_digest, resource_marker, result_doc

    analyzer = None
    provider = manifest['provider_repository']
    subject = dict(provider='bitbucket', repository_id=provider, pr_id=manifest['pr_id'],
                   base_sha=manifest['base_revisions'][provider], head_sha=manifest['head_revisions'][provider])
    try:
        with instrument(meter, contexts) if instrumented else nullcontext():
            with meter.span('pipeline'):
                with meter.span('setup'):
                    analyzer = CoreAnalyzer(policy.model_dump(), state_root / 'core', code_version='benchmark-static')
                    sink = DirectorySink(state_root / 'local-publication')
                with meter.span('initial_index'):
                    analyzer.reconcile_graph(manifest['base_revisions'])
                for mode in ('first_analysis', 'warm_repeat'):
                    with meter.span(mode):
                        request = build_request(
                            installation_id=policy.installation_id, environment=policy.environment,
                            request_id='benchmark-' + mode, trigger_kind='pr', event_id='benchmark-' + mode,
                            resource_version=digest(subject), subject=subject,
                            repository_revisions=manifest['head_revisions'], settings=analyzer.request_settings(),
                            deadline='2099-01-01T00:00:00Z')
                        with meter.span('analysis'):
                            document = analyzer.analyze(request, attachments={'mainline_revisions': manifest['base_revisions']},
                                                        cancelled=lambda: False)
                        with meter.span('render'):
                            view = view_from_result(document, request)
                            doc = result_doc(view, snapshot={**subject, 'repository': provider}, kind='pr',
                                             generation=1, gaps=[])
                            doc['jira_summary'] = summary_doc(view, document, kind='pr', gaps=[], earlier=[])
                        rid = 'bitbucket:benchmark/pilot#' + str(manifest['pr_id'])
                        marker = marker_line(resource_marker(policy.installation_id, rid), doc_digest(doc), 1)
                        with meter.span('local_publication_create'):
                            comment_id = sink.create_comment(rid, doc, marker)
                        with meter.span('local_publication_update'):
                            sink.update_comment(rid, comment_id, doc, marker)
                        samples.append(dict(mode=mode, semantic_sha256=digest(semantic(document)),
                                            result=dict(status=document['status'], reason_code=document['reason_code'],
                                                        findings=len(document['findings']), deltas=len(document['deltas']),
                                                        affected_services=len(document['affected']),
                                                        gap_counts=dict(Counter(g['code'] for g in document['gaps'])))))
                with meter.span('canonical_facts'):
                    facts = analyzer._parts()[1].canonical_facts(analyzer.graph.scope)
                    fact_digest = digest(facts)
                    relationships = dict(Counter(f[1] for f in facts))
    finally:
        if analyzer:
            analyzer.close()
    return dict(samples=samples, spans=meter.spans, contexts=contexts,
                graph_facts_sha256=fact_digest, graph_relationships=relationships,
                network=dict(status='NOT_RUN_OFFLINE'), polling=dict(status='NOT_RUN_OFFLINE'),
                live_publication=dict(status='NOT_RUN', measured_backend='local DirectorySink; no queue/HTTP'))


def environment():
    try:
        ram = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    except (ValueError, OSError):
        ram = None
    return dict(python=sys.version, system=platform.system(), machine=platform.machine(),
                platform=platform.platform(), logical_cpus=os.cpu_count(), ram_bytes=ram,
                packages={p: version(p) for p in ('pydantic', 'PyYAML')},
                rss_scope='ru_maxrss lifetime high-water mark, not stage-local or summed process-tree RSS',
                child_cpu_scope='RUSAGE_CHILDREN reaped descendants only',
                wall_scope='perf_counter; includes instrumentation overhead; inventory_metrics separately visible')


def source_identity():
    def git(*args):
        return subprocess.check_output(['git', '-C', str(ROOT), *args], stderr=subprocess.DEVNULL, text=True).strip()

    return dict(commit=git('rev-parse', 'HEAD'), working_tree_dirty=bool(git('status', '--porcelain')),
                tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), core=core_identity(),
                git_version=git('--version'))


def public_manifest(manifest):
    policy = validate_manifest(manifest)
    safe_policy = policy.model_dump()
    for repo in safe_policy['repositories']:
        repo['root'] = '<local-repository:' + repo['id'] + '>'
    return dict(schema_version='impactmap-benchmark-manifest-1',
                policy_without_roots_sha256=digest(safe_policy), limits=policy.limits.model_dump(),
                pins=[dict(repository=r.id, service=r.service,
                           base=manifest['base_revisions'][r.id], head=manifest['head_revisions'][r.id])
                      for r in policy.repositories], provenance=manifest['provenance'],
                source=source_identity(), environment=environment(), model='OFF',
                cache_protocol='new worker and SQLite state per repetition; warm repeat in same worker; OS caches uncontrolled',
                semantics_ignored_fields=sorted(VOLATILE))


def worker(manifest, output):
    measured = run_case(manifest, output / 'measured')
    reference = run_case(manifest, output / 'reference', instrumented=False)
    equality = ([s['semantic_sha256'] for s in measured['samples']] == [s['semantic_sha256'] for s in reference['samples']]
                and measured['graph_facts_sha256'] == reference['graph_facts_sha256'])
    return dict(measured=measured,
                reference=dict(samples=reference['samples'], graph_facts_sha256=reference['graph_facts_sha256']),
                semantics_equal=equality)


def execute(manifest, output, repeats):
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    safe = public_manifest(manifest)
    (output / 'manifest.json').write_text(json.dumps(safe, indent=2) + '\n')
    # Private validated input is necessary for isolated workers, never part of exported measurements.
    private = output / 'private'
    private.mkdir(mode=0o700)
    input_path = private / 'input.json'
    input_path.write_text(canonical(manifest))
    input_path.chmod(0o600)
    rows = []
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'SYSTEMROOT', 'TEMP', 'TMP')}
    env.update(PYTHONPATH=str(ROOT / 'src') + os.pathsep + str(ROOT), PYTHONDONTWRITEBYTECODE='1')
    with (output / 'measurements.jsonl').open('w') as raw:
        for index in range(repeats):
            try:
                proc = subprocess.run([sys.executable, '-m', 'tools.benchmark_impactmap', '--worker',
                                       '--manifest', str(input_path), '--output', str(private / f'worker-{index}')],
                                      env=env, cwd=ROOT, capture_output=True, text=True, timeout=1800)
            except subprocess.TimeoutExpired:
                row = dict(error_code='worker_timeout', semantics_equal=False)
            except (OSError, subprocess.SubprocessError):
                row = dict(error_code='worker_start_failed', semantics_equal=False)
            else:
                if proc.returncode:
                    row = dict(error_code='worker_failed', semantics_equal=False)
                else:
                    try:
                        row = json.loads(proc.stdout)
                        if (not isinstance(row, dict) or not isinstance(row.get('semantics_equal'), bool)
                                or not isinstance(row.get('measured', {}).get('spans'), list)
                                or not isinstance(row.get('measured', {}).get('samples'), list)):
                            raise ValueError('invalid_worker_output')
                    except (ValueError, AttributeError, TypeError):
                        row = dict(error_code='worker_output_invalid', semantics_equal=False)
            row['repetition'] = index + 1
            rows.append(row)
            raw.write(canonical(row) + '\n')
            raw.flush()
    spans = [dict(repetition=row['repetition'], **s) for row in rows if 'measured' in row for s in row['measured']['spans']]
    with (output / 'spans.csv').open('w', newline='') as f:
        if spans:
            writer = csv.DictWriter(f, fieldnames=list(spans[0]))
            writer.writeheader()
            writer.writerows(spans)
    summary = dict(schema_version='impactmap-benchmark-summary-1', observed_utc=datetime.now(timezone.utc).isoformat(),
                   independent_worker_processes=repeats, performance_observations=sum(len(r.get('measured', {}).get('samples', [])) for r in rows),
                   all_semantics_equal=all(r['semantics_equal'] for r in rows),
                   worker_errors=sum('error_code' in r for r in rows), network='NOT_RUN_OFFLINE',
                   polling='NOT_RUN_OFFLINE', external_publication='NOT_RUN', p95=None,
                   p95_reason='small repeated author corpus; no production quantile claim')
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, choices=range(1, 31), default=3)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.worker:
            manifest = json.loads(args.manifest.read_text())
            value = worker(manifest, args.output)
        elif args.manifest:
            manifest = json.loads(args.manifest.read_text())
            validate_manifest(manifest)
            value = execute(manifest, args.output, args.repeats)
        else:
            if args.output.exists():
                raise ValueError('benchmark_output_exists')
            from examples.orders_reporting.stand import build_stand

            # Setup lives beside reports, separate from the measured worker phases.
            import tempfile
            with tempfile.TemporaryDirectory(prefix='impactmap-baseline-') as tmp:
                stand = build_stand(Path(tmp) / 'stand')
                manifest = dict(schema_version='impactmap-benchmark-input-1', provenance='author_fixture',
                                policy=stand.policy(), base_revisions=stand.revisions(),
                                head_revisions=stand.revisions(orders='pr-7'), provider_repository='orders', pr_id=7)
                value = execute(manifest, args.output, args.repeats)
        print(canonical(value))
        return 0 if value.get('all_semantics_equal', value.get('semantics_equal', True)) else 1
    except Exception as exc:
        print(canonical(dict(error_code='benchmark_failed', error_type=type(exc).__name__)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
