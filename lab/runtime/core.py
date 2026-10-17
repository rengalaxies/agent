"""Small explicit trust boundary for the experiment's agent pipeline.

The model only emits data. No shell/tool execution or evaluator source is exposed.
The operator, not model output, supplies grants and invokes the separate dispatcher.
"""
from __future__ import annotations
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from decimal import Decimal

DEFAULT_ENDPOINT = 'https://foundation-models.api.cloud.ru/v1'
ALLOWED_PATCHES = frozenset({'lab/sql/expand.sql'})
MAX_FILE = 100_000


def now():
    return datetime.now(timezone.utc).isoformat()


def json_exact(value):
    if isinstance(value, (Decimal, uuid.UUID)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError('Unsupported audit type: ' + type(value).__name__)


def digest(value):
    return hashlib.sha256(json.dumps(value, default=json_exact, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def tree_digest(root):
    root = Path(root)
    return digest({str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts})


class Stop(RuntimeError):
    pass


class Audit:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'audit.jsonl'
        self.previous = '0' * 64
        if self.path.exists():
            rows = self.path.read_text().splitlines()
            if rows:
                self.previous = json.loads(rows[-1])['record_digest']

    def record(self, action, **fields):
        row = {'at': now(), 'action': action, 'previous_digest': self.previous, **fields}
        row['record_digest'] = digest(row)
        with self.path.open('a') as stream:
            stream.write(json.dumps(row, default=json_exact, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        self.previous = row['record_digest']
        return row


def discover(root, environment_id='lab', max_age_seconds=900):
    """Restricted static adapters. Sources imply links, never completeness.

    Repository mtime is not a freshness guarantee: snapshots hash content at collection.
    Catalog confirmation timestamps are checked independently of source scan timestamps.
    """
    root = Path(root)
    evidence, dependencies, gaps = [], [], [
        'Static supported syntax only; dynamic SQL and external consumers may be absent.',
        'No live traces supplied; lack of telemetry never removes a static dependency.',
        'Repository snapshot does not prove deployed code or broker state.']
    catalog_path = root / 'lab/catalog/owners.json'
    owners = json.loads(catalog_path.read_text()) if catalog_path.exists() else {'bindings': []}
    bindings = owners.get('bindings', [])
    source_paths = []
    for folder in ('lab/app', 'lab/sql', 'lab/catalog', 'lab/contracts'):
        path = root / folder
        if path.exists():
            source_paths.extend(p for p in path.rglob('*') if p.suffix in {'.py', '.sql', '.json', '.yaml', '.yml'} and '__pycache__' not in p.parts)
    for path in sorted(source_paths):
        if path.is_symlink() or path.stat().st_size > MAX_FILE:
            gaps.append(f'Unsupported source omitted: {path.relative_to(root)}')
            continue
        content = path.read_text()
        relative = str(path.relative_to(root))
        item = {'evidence_id': digest({'path': relative, 'content': content})[:24],
                'source_type': path.suffix[1:], 'object_ref': relative,
                'environment_id': environment_id, 'observed_at': now(), 'collected_at': now(),
                'digest': hashlib.sha256(content.encode()).hexdigest(),
                'validity': 'CURRENT_REPOSITORY_SNAPSHOT', 'max_age_seconds': max_age_seconds,
                'permitted_scope': 'read-only repository lab/app and lab/catalog', 'content': content}
        evidence.append(item)
        # Evidence records point to exact source line. Do not infer a consumer only from its name.
        for number, line in enumerate(content.splitlines(), 1):
            if re.search(r'\b(FROM|JOIN)\s+[\w.]*orders\b', line, re.I):
                dependencies.append({'source_ref': 'postgres:orders', 'target_ref': relative,
                    'relation_type': 'SQL_READ_REFERENCE', 'evidence_ids': [item['evidence_id']],
                    'line': number, 'direction': 'source-to-reader', 'validity': item['validity'],
                    'contract': 'orders amount semantics', 'confirmation': 'STATIC_REFERENCE',
                    'coverage_note': 'Reference only; not proof of execution.'})
        if path.suffix == '.py':
            try:
                module = ast.parse(content)
            except SyntaxError:
                gaps.append(f'Unparseable Python source: {relative}')
                continue
            for function in (n for n in ast.walk(module) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
                for call in (n for n in ast.walk(function) if isinstance(n, ast.Call)):
                    method = getattr(call.func, 'attr', '')
                    kwargs = {k.arg: k.value.value for k in call.keywords if isinstance(k.value, ast.Constant)}
                    if method == 'queue_bind' and 'queue' in kwargs and 'exchange' in kwargs:
                        dependencies.append({'source_ref': kwargs['exchange'], 'target_ref': kwargs['queue'],
                            'relation_type': 'BROKER_BINDING', 'routing_key': kwargs.get('routing_key', 'DYNAMIC'),
                            'evidence_ids': [item['evidence_id']], 'line': call.lineno,
                            'direction': 'exchange-to-queue', 'validity': item['validity'],
                            'contract': kwargs.get('routing_key', 'UNKNOWN_DYNAMIC'),
                            'confirmation': 'CODE_DECLARATION', 'coverage_note': 'Conditional code is not proof of active binding.'})
                    if method == 'execute' and call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
                        sql = call.args[0].value
                        refs = re.findall(r'\b(?:FROM|JOIN)\s+([\w.]+)', sql, re.I)
                        for ref in refs:
                            dependencies.append({'source_ref': 'postgres:' + ref, 'target_ref': relative + '#' + function.name,
                                'relation_type': 'SQL_READ_REFERENCE', 'evidence_ids': [item['evidence_id']], 'line': call.lineno,
                                'direction': 'source-to-reader', 'validity': item['validity'], 'contract': ref,
                                'confirmation': 'STATIC_REFERENCE', 'coverage_note': 'Literal SQL reference; dynamic SQL not resolved.'})
        if path.suffix == '.json':
            try:
                definition = json.loads(content)
            except ValueError:
                continue
            if isinstance(definition, dict):
                for binding in definition.get('bindings', []):
                    if not isinstance(binding, dict) or not all(k in binding for k in ('source', 'destination')):
                        continue
                    dependencies.append({'source_ref': binding['source'], 'target_ref': binding['destination'],
                        'relation_type': 'BROKER_BINDING', 'routing_key': binding.get('routing_key'),
                        'evidence_ids': [item['evidence_id']], 'direction': 'exchange-to-queue',
                        'validity': item['validity'], 'contract': binding.get('routing_key', 'UNKNOWN'),
                        'confirmation': 'DECLARED_BINDING', 'coverage_note': 'No live broker reconciliation.'})
    for dep in dependencies:
        matches = [b for b in bindings if b.get('environment_id') == environment_id and
                   b.get('object_ref') == dep['target_ref']]
        teams = sorted(set(b['team_id'] for b in matches if b.get('team_id')))
        dep['owner'] = teams[0] if len(teams) == 1 else ('CONFLICT' if teams else 'UNKNOWN')
        dep['owner_evidence'] = matches
        dep['owner_freshness'] = 'UNKNOWN'
        if matches:
            try:
                fresh = all(time.time() - datetime.fromisoformat(b['confirmed_at']).timestamp() <= 86400 for b in matches)
                dep['owner_freshness'] = 'CURRENT' if fresh else 'STALE'
            except (KeyError, ValueError):
                pass
    return {'environment_id': environment_id, 'evidence': evidence, 'dependencies': dependencies,
            'coverage_gaps': gaps, 'snapshot_digest': digest([(e['object_ref'], e['digest']) for e in evidence])}


class LLM:
    def __init__(self, audit, max_calls=2, max_seconds=180, max_tokens=64000, max_cost_usd=None):
        self.audit, self.max_calls, self.max_seconds = audit, max_calls, max_seconds
        self.max_tokens, self.max_cost_usd = max_tokens, max_cost_usd
        self.calls, self.tokens, self.cost = 0, 0, 0
        self.started = time.monotonic()
        self.model = os.environ.get('CLOUDRU_LLM_MODEL', '')
        self.key = os.environ.get('CLOUDRU_FOUNDATION_API_KEY', '')
        self.endpoint = os.environ.get('CLOUDRU_LLM_BASE_URL', DEFAULT_ENDPOINT).rstrip('/')
        self.usage = []

    def call(self, role, system, context):
        if not self.key or not self.model:
            raise Stop('Missing CLOUDRU_FOUNDATION_API_KEY and/or CLOUDRU_LLM_MODEL; IAM credentials are not an inference API key.')
        if self.endpoint != DEFAULT_ENDPOINT:
            raise Stop('Endpoint outside qualified Cloud.ru Foundation Models scope.')
        remaining = self.max_seconds - (time.monotonic() - self.started)
        if self.calls >= self.max_calls or remaining <= 0 or self.tokens >= self.max_tokens:
            raise Stop('Agent budget exhausted; partial artifacts retained.')
        input_rate = os.environ.get('CLOUDRU_INPUT_USD_PER_MILLION')
        output_rate = os.environ.get('CLOUDRU_OUTPUT_USD_PER_MILLION')
        if self.max_cost_usd is not None and (not input_rate or not output_rate):
            raise Stop('Cost cap requested but verified model price is not configured.')
        context_text = json.dumps(context, ensure_ascii=False)
        input_bound = len(context_text.encode()) + len(system.encode()) + 256
        output_bound = min(3000, self.max_tokens - self.tokens - input_bound)
        if output_bound <= 0:
            raise Stop('Conservative input/output token budget exhausted before request.')
        # UTF-8 byte bound plus message overhead conservatively bounds ordinary tokenizer input.
        # Conservative upper bound avoids starting a call whose maximum charge exceeds budget.
        if self.max_cost_usd is not None and self.cost + (input_bound * float(input_rate) + output_bound * float(output_rate)) / 1e6 > self.max_cost_usd:
            raise Stop('Insufficient remaining cost budget for next bounded call.')
        payload = {'model': self.model, 'temperature': 0, 'max_tokens': output_bound,
                   'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': context_text}]}
        self.calls += 1
        self.audit.record('llm_request', role=role, model=self.model, context_digest=digest(context), call=self.calls)
        req = urllib.request.Request(self.endpoint + '/chat/completions', data=json.dumps(payload).encode(),
                                     headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=min(90, remaining)) as response:
                result = json.loads(response.read(1_000_001))
            usage = result.get('usage', {})
            if 'total_tokens' not in usage:
                raise Stop('Provider omitted token usage; cannot continue within measured token budget.')
            self.tokens += int(usage['total_tokens'])
            self.usage.append(usage)
            if input_rate and output_rate:
                self.cost += (usage.get('prompt_tokens', 0)*float(input_rate) + usage.get('completion_tokens', 0)*float(output_rate))/1e6
            self.audit.record('llm_response', role=role, usage=usage, cost_usd=self.cost if input_rate and output_rate else 'NOT_MEASURED')
            if self.tokens > self.max_tokens:
                raise Stop('Token budget reached; response retained only in provider usage audit.')
            content = result['choices'][0]['message']['content']
            content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content.strip())
            return json.loads(content)
        except Stop:
            raise
        except Exception as exc:
            # Provider errors can echo request bodies/credentials. Store only exception class.
            raise Stop('LLM call failed: ' + type(exc).__name__) from None


def stage_candidate(root, destination, proposal):
    root, destination = Path(root), Path(destination)
    patches = proposal.get('patches', [])
    if not patches or len(patches) > len(ALLOWED_PATCHES):
        raise Stop('Executor must provide a nonempty bounded patch list.')
    seen = set()
    for patch in patches:
        name = patch.get('path')
        if name not in ALLOWED_PATCHES or name in seen or not isinstance(patch.get('content'), str) or len(patch['content'].encode()) > MAX_FILE:
            raise Stop('Patch violates explicit path/content scope.')
        seen.add(name)
    if destination.exists():
        raise Stop('Candidate directory already exists; refusing overwrite.')
    for folder in ('lab/app', 'lab/sql', 'lab/catalog', 'lab/contracts'):
        origin = root / folder
        if origin.exists():
            if any(p.is_symlink() for p in origin.rglob('*')):
                raise Stop('Symlink in candidate inputs is forbidden.')
            shutil.copytree(origin, destination / folder, ignore=shutil.ignore_patterns('__pycache__'))
    changed = []
    for patch in patches:
        target = destination / patch['path']
        before = target.read_text() if target.exists() else ''
        if before == patch['content']:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(patch['content'])
        changed.append({'path': patch['path'], 'before_digest': hashlib.sha256(before.encode()).hexdigest(),
                        'after_digest': hashlib.sha256(patch['content'].encode()).hexdigest()})
    if not changed:
        raise Stop('No effective patch generated; reference implementation is not an agent-produced repair.')
    return {'candidate_digest': tree_digest(destination), 'patches': changed,
            'transition_plan': proposal.get('transition_plan', []), 'assumptions': proposal.get('assumptions', [])}


def enforce_grant(grant, action, object_ref, environment_id, context_digest, revoked=()):
    if not isinstance(grant, dict) or grant.get('grant_id') in revoked:
        raise Stop('Grant absent or revoked.')
    try:
        valid_until = datetime.fromisoformat(grant['expires_at']).timestamp()
    except (KeyError, ValueError, TypeError):
        raise Stop('Invalid grant expiration.') from None
    if valid_until <= time.time() or grant.get('environment_id') != environment_id:
        raise Stop('Grant expired or environment differs.')
    if action not in grant.get('action_kinds', []) or object_ref not in grant.get('exact_scope', []):
        raise Stop('Action/object outside exact grant scope.')
    if grant.get('context_digest') != context_digest or not grant.get('issuer'):
        raise Stop('Grant context is stale or issuer is missing.')


def update_inbox(path, change_id, revision, diff_digest, discovery, status, **details):
    path = Path(path)
    previous = json.loads(path.read_text()) if path.exists() else []
    for card in previous:
        if card['change_id'] == change_id:
            card['active'] = False
            card['closure_reason'] = 'SUPERSEDED_REVISION_OR_REASSESSMENT'
    teams = {}
    for dep in discovery['dependencies']:
        teams.setdefault(dep['owner'], []).append(dep)
    for team, links in teams.items():
        new_card = {'change_id': change_id, 'revision': revision, 'diff_digest': diff_digest,
            'team_id': team, 'active': True, 'status': status, 'updated_at': now(),
            'objects': [x['target_ref'] for x in links], 'grounds': links,
            'what_changes': details.get('intent'), 'requirement': 'Business amount must be conserved; v1 meaning preserved.',
            'reproduced': details.get('reproduced', 'NOT_RUN'), 'patches': details.get('patches', []),
            'verification': details.get('verification', 'NOT_RUN'), 'executed': details.get('executed', []),
            'human_decision': 'Resolve UNKNOWN/CONFLICT/STALE owners and issue separate exact action grant.',
            'coverage_gaps': discovery['coverage_gaps']}
        same = next((c for c in previous if c['change_id'] == change_id and c['revision'] == revision and c['diff_digest'] == diff_digest and c['team_id'] == team), None)
        if same is None:
            previous.append(new_card)
        else:
            same.clear()
            same.update(new_card)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(previous, indent=2, ensure_ascii=False))
    return previous
