"""Real saved-result views: fail-closed scope, independent states and inert evidence."""
import json
import sqlite3
import unittest
from pathlib import Path
from tests.service import test_ui_scope
from tests.graph.test_output_contracts import result


class ViewTests(unittest.TestCase):
    setUp=test_ui_scope.ScopeTests.setUp
    open=test_ui_scope.ScopeTests.open
    claim=test_ui_scope.ScopeTests.claim
    finish=test_ui_scope.ScopeTests.finish

    def view(self,rid=None):
        from agent_service.ui_views import workspace_view
        data=self.store.ui_workspace(self.scope,rid)
        return workspace_view(data)

    def test_current_result_preserves_pins_checks_and_three_independent_states(self):
        self.finish()
        view=self.view(self.rid);html=view['result_html']
        for value in ['CURRENT','USEFUL','ANALYZED','PENDING','Reporting calls','Run the export',
                      '3333333333333333333333333333333333333333','4444444444444444444444444444444444444444',
                      '5555555555555555555555555555555555555555555555555555555555555555',
                      'client.py','5–7','Фрагмент исходника недоступен']:
            self.assertIn(value,html)
        self.assertIn('Последние 100',view['list_note_html'])
        self.assertNotIn('PRIVATE_',json.dumps(view))
        self.assertNotIn('href="http',html)

    def test_changed_operation_and_consumer_usage_remain_visible(self):
        self.finish()
        html=self.view(self.rid)['result_html']
        for value in ['PAGE_DEFAULT_CHANGED','100 → 20','GET /orders','POSSIBLE_TRUNCATION','SINGLE_REQUEST_OBSERVED']:
            self.assertIn(value,html)

    def test_known_owner_and_real_preliminary_output_render_without_losing_team_names(self):
        raw=json.loads((Path(__file__).resolve().parents[2]/'docs/product/ui-admin-2026-11-16/fixture-result.json').read_text())['analysis']['raw']
        # Expand this test's actual granted corpus, then bind trusted request to saved output.
        from agent_service.ui_scope import UIScope
        self.scope=UIScope('acme','prod','6'*64,('orders','reporting','archive','billing','audit'),(),self.scope.database)
        self.open(version=raw['resource_version']);job=self.store.claim_job('author')
        from tests.graph.test_output_contracts import request
        req=request();req.update(self.scope.receipt());req.update(request_id=raw['request_id'],trigger_kind='jira',pr=None,
            jira=dict(project='KAN',key='KAN-10',revision='author',updated_at='2026-11-16T00:00:00Z',text_fields={}),
            source_event=dict(event_id=raw['event_id'],resource_version=raw['resource_version']))
        self.store.stamp_ui_scope(job,req)
        self.store.complete_job(job,state='ANALYZED',result=raw,reason=raw['reason_code'],intent=None)
        html=self.view(self.rid)['result_html']
        self.assertIn('preliminary_impact_found',html)
        self.assertIn('team-data',html);self.assertIn('team-reporting',html)
        self.assertNotIn('Результат несовместим',html)
        archive=html.split('id="consumer-0"')[1].split('</li>')[0]
        reporting=html.split('id="consumer-1"')[1].split('</li>')[0]
        self.assertIn('#evidence-0',archive);self.assertNotIn('#evidence-1',archive)
        self.assertIn('#evidence-1',reporting);self.assertNotIn('#evidence-0',reporting)

    def test_list_exposes_authorized_publication_source_and_observation(self):
        self.finish()
        with self.store._connect() as c:c.execute("UPDATE intents SET state='UNKNOWN'")
        html=self.view()['list_html']
        for value in ['UNKNOWN','Публикация','bitbucket','pr','UTC']:self.assertIn(value,html)

    def test_nullable_gap_repository_remains_partial_but_foreign_repository_is_denied(self):
        raw=result(status='PARTIAL',reason_code='coverage_gaps',gaps=[dict(code='source_unavailable',repository=None)])
        self.finish(raw)
        html=self.view(self.rid)['result_html'];self.assertIn('Неполные данные',html)
        self.assertNotIn('None',html)
        self.open('v2');raw['gaps'][0]['repository']='secret-repo';self.finish(raw)
        self.assertIsNone(self.store.ui_workspace(self.scope,self.rid))

    def test_many_withheld_candidates_do_not_reveal_hidden_existence(self):
        empty=self.store.ui_listing(self.scope)
        raw=result();raw['installation_id']='foreign';self.finish(raw)
        with self.store._connect() as c:
            originals={table:dict(c.execute('SELECT * FROM '+table).fetchone()) for table in ('resources','jobs','ui_scope_receipts')}
            for n in range(1001):
                for table,original in originals.items():
                    row=dict(original)
                    if 'resource_id' in row:row['resource_id']=f'hidden#{n}'
                    if 'job_id' in row:row['job_id']=f'job-hidden-{n}'
                    c.execute('INSERT INTO '+table+' VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
        hidden=self.store.ui_listing(self.scope)
        self.assertEqual(hidden,empty)

    def test_finding_keeps_its_own_evidence_anchor(self):
        self.finish()
        html=self.view(self.rid)['result_html']
        finding=html.split('id="finding-0"')[1].split('</li>')[0]
        self.assertIn('#evidence-0',finding);self.assertNotIn('#evidence-1',finding)

    def test_current_failure_keeps_previous_result_stale_and_unknown_publication_separate(self):
        self.finish();self.open('v2');job=self.claim()
        self.store.complete_job(job,state='FAILED',result=None,reason='commit_unavailable',intent=None)
        with self.store._connect() as c:c.execute("UPDATE intents SET state='UNKNOWN'")
        html=self.view(self.rid)['result_html']
        for value in ['FAILED','STALE','UNKNOWN','commit_unavailable','Поколение результата','Исход публикации неизвестен']:
            self.assertIn(value,html)

    def test_empty_and_queued_do_not_claim_safety(self):
        view=self.view()
        self.assertIn('Нет доступных изменений',view['list_html'])
        job=self.claim()
        html=self.view(self.rid)['result_html']
        self.assertIn('Анализ ещё не выполнен',html)
        self.assertIn('RUNNING',html)
        self.assertIn('не означает отсутствия влияния',html)

    def test_partial_and_closed_are_not_general_success(self):
        self.finish(result(status='PARTIAL',reason_code='coverage_gaps',
                           gaps=[dict(code='source_unavailable',repository='reporting',path='client.py')]))
        html=self.view(self.rid)['result_html']
        for value in ['PARTIAL','source_unavailable','Неполные данные']:self.assertIn(value,html)
        with self.store._connect() as c:c.execute('UPDATE resources SET closed=1')
        html=self.view(self.rid)['result_html'];self.assertIn('CLOSED',html)
        self.assertIn('Ресурс закрыт',html)

    def test_incompatible_and_unknown_codes_are_not_rendered_as_useful(self):
        self.finish({'schema_version':'alien','reason_code':'invalid','secret':'PRIVATE_RAW'})
        with self.store._connect() as c:c.execute("UPDATE jobs SET state='FUTURE_JOB'")
        html=self.view(self.rid)['result_html']
        self.assertIn('Результат несовместим',html)
        self.assertIn('Неизвестный код',html);self.assertIn('FUTURE_JOB',html)
        self.assertNotIn('PRIVATE_RAW',html)

    def test_stored_html_and_paths_are_inert_and_direct_unknown_id_does_not_fall_back(self):
        raw=result(summary='<img src=x onerror=alert(1)>')
        raw['evidence'][0]['path']='../../private/<script>alert(1)</script>'
        self.finish(raw)
        html=self.view(self.rid)['result_html']
        self.assertNotIn('<img src=x',html);self.assertNotIn('<script>',html)
        self.assertIn('&lt;img',html);self.assertIn('&lt;script&gt;',html)
        self.assertIsNone(self.store.ui_workspace(self.scope,'foreign#1'))

    def test_reads_and_refresh_leave_service_database_unchanged(self):
        self.finish()
        def dump():
            c=sqlite3.connect(self.store.path)
            try:return '\n'.join(c.iterdump())
            finally:c.close()
        before=dump()
        for _ in range(3):self.view(self.rid)
        self.assertEqual(before,dump())

    def test_filtered_bounded_list_does_not_disclose_unstamped_rows(self):
        self.finish()
        self.open(rid='private-unstamped');self.finish(stamp=False)
        view=self.view()
        self.assertIn(self.rid,view['list_html'])
        self.assertNotIn('private-unstamped',view['list_html'])
        self.assertIn('не вся история',view['list_note_html'])
