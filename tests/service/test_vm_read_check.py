"""VM checker consumes real queue delivery receipts and production sink layout."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_service.config import ServiceConfig, build
from agent_service.connectors.jira import JiraConnector, issue_version, DEFAULT_FIELDS
from agent_service.connectors.base import Snapshot, marker_line
from agent_service.envelope import canonical, digest
from agent_service.publisher import doc_digest, resource_marker
from tools.agent_service.box import config, release
from tests.service.helpers import orders_result

HELPER = Path(__file__).resolve().parents[2] / 'docs/implementation/autonomous-mvp/jira-bootstrap-2026-11-02/vm_check.py'


class VMReadCheckTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        spec = importlib.util.spec_from_file_location('vm_read_check', HELPER)
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)
        self.service_config = ServiceConfig.model_validate(dict(installation_id='fixture', environment='test',
            state_path=str(self.root / 'service/service.sqlite'), publication='dry_run',
            dry_run_dir=str(self.root / 'dry-run'), jira=dict(base_url='https://api.atlassian.com/ex/jira/d0b47b8d-4655-4cb1-9f81-30573fd372c3',
                project_keys=['KAN'], bot_account_id='synthetic-owner', webhook_secret_env='JIRA_WEBHOOK_SECRET',
                auth={'kind':'basic', 'email_env':'JIRA_EMAIL', 'token_env':'JIRA_API_TOKEN'})))
        self.cfg = SimpleNamespace(publication='dry_run', model=None, jira=self.service_config.jira,
                                   installation_id='fixture', environment='test')
        self.secrets = dict(JIRA_EMAIL='synthetic@example.invalid', JIRA_API_TOKEN='synthetic-token')
        self.store, _, backends = build(self.service_config, env_secret=lambda name: self.secrets.get(name, 'synthetic-webhook'))
        self.sink = backends['jira']
        self.version = issue_version({}, DEFAULT_FIELDS)
        self.manifest = {'code': {'commit': self.helper.SHA}, 'release_id': 'release234-fixture'}
        for i in range(1, 4):
            rid = f'jira:{i}'
            self.store.apply_snapshot(resource_id=rid, provider='jira', kind='jira', version=self.version,
                                      snapshot={'key':f'KAN-{i}'}, event_id=f'fixture-{i}')
            job = self.store.claim_job('fixture')
            request = dict(request_id=f"{job['job_id']}:{job['attempts']}", installation_id='fixture',
                environment='test', trigger_kind='jira', repository_revisions={'reporting':'c'*40, 'orders':'b'*40},
                source_event={'event_id':job['event_id'], 'resource_version':self.version})
            result = orders_result(request, schema_version='2.1')
            result.update(profile='http-requests-6', code_version=self.manifest['release_id'])
            doc = dict(title='synthetic', status_line='ABSTAINED', sections=[])
            body_hash = doc_digest(doc)
            marker = resource_marker('fixture', rid)
            self.store.complete_job(job, state='ANALYZED', result=result, reason='intent_unclear',
                intent=dict(kind='result', body=canonical(doc), body_digest=body_hash, marker=marker))
            intent = self.store.claim_intent('fixture')
            self.store.mark_sending(intent, operation='create', comment_id=None)
            cid = self.sink.create_comment(rid, doc, marker_line(marker, body_hash, 1))
            self.store.intent_delivered(intent, comment_id=cid, comment_digest=body_hash, wrote=True)

    def run_helper(self):
        def mapped_path(value):
            text = str(value)
            if text.startswith('/var/lib/agent-service'):
                return self.root / text.removeprefix('/var/lib/agent-service').lstrip('/')
            return Path(value)
        output = io.StringIO()
        with patch.object(self.helper, 'Path', mapped_path), \
                patch.object(sys, 'path', list(sys.path)), \
                patch.object(sys, 'argv', ['vm_check', 'results']), \
                patch.object(release, 'verify_tree', return_value=(self.manifest, self.helper.MANIFEST)), \
                patch.object(config, 'load', return_value=self.cfg), \
                patch.object(config, 'read_secrets', return_value=self.secrets), \
                patch.object(JiraConnector, 'fetch', side_effect=lambda rid: Snapshot(rid, 'jira', self.version, {})), \
                contextlib.redirect_stdout(output):
            self.helper.main()
        return json.loads(output.getvalue())

    def test_production_sink_path_and_current_delivery_are_accepted(self):
        self.assertEqual(self.sink.root, self.root / 'dry-run/jira')
        result = self.run_helper()
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['issues']), 3)

    def test_stale_or_tampered_sink_is_not_accepted_as_current(self):
        path = self.sink.root / (digest('jira:1')[:24] + '.json')
        original = json.loads(path.read_text())
        changes = [dict(id='different-comment'), dict(doc={'title':'tampered'}),
                   dict(marker=marker_line(resource_marker('fixture','jira:1'), doc_digest(original['doc']), 0))]
        for change in changes:
            with self.subTest(change=change):
                path.write_text(json.dumps({**original, **change}))
                with self.assertRaises(self.helper.CheckError):
                    self.run_helper()

    def test_partial_or_wrong_request_result_is_rejected_even_with_done_job(self):
        with self.store._connect() as db:
            original = json.loads(db.execute("SELECT result FROM jobs WHERE resource_id='jira:1'").fetchone()[0])
        for change in ({'schema': 'wrong'}, {'request_id': 'wrong-request'}, {'installation_id': 'another'}):
            with self.subTest(change=change):
                with self.store._tx() as db:
                    db.execute("UPDATE jobs SET result=? WHERE resource_id='jira:1'", (json.dumps({**original, **change}),))
                with self.assertRaises(self.helper.CheckError):
                    self.run_helper()
