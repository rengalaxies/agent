"""Read-only VM evidence. No Service/ServiceStore, worker, publisher or DB write.

Use release292's staged venv with -I -B, as root. Secret values stay in memory.
API mode exchanges/revokes its own App token; all other HTTP requests are GET.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

SHA = '292db6b55b4144a11080fa7813095478702c69ef'
MANIFEST = '9e4287cea0db42f4e64dc23e1ef3231ad12c2029ee9d283660d52f2f09205299'
NAME = 'agent-service-0.1.0-g292db6b55b41-linux-x86_64-cp312'
KEYS = {'KAN-1', 'KAN-2', 'KAN-3'}
PERMS = {'metadata': 'read', 'contents': 'read', 'pull_requests': 'read', 'issues': 'write'}


class CheckError(Exception):
    def __init__(self, code):
        self.code = code


def require(ok, code):
    if not ok:
        raise CheckError(code)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['api', 'results'])
    parser.add_argument('--release', type=Path, default=Path('/opt/agent-service/releases') / NAME)
    parser.add_argument('--box-config', type=Path, default=Path('/etc/agent-service/box.yaml'))
    args = parser.parse_args()
    root = args.release.resolve()
    sys.path[:0] = [str(root / 'app/src'), str(root / 'app')]
    from tools.agent_service.box.release import verify_tree
    from tools.agent_service.box.config import load, read_secrets
    from agent_service.connectors.github import API_VERSION, GitHubAppAuth
    from agent_service.connectors.jira import BasicAuth, JiraConnector
    from agent_service.connectors.base import parse_marker
    from agent_service.envelope import digest
    from agent_service.http import HttpClient
    from agent_service.publisher import doc_digest, resource_marker
    from agent_service.analysis import view_from_result

    manifest, manifest_hash = verify_tree(root)
    require(manifest['code']['commit'] == SHA and manifest_hash == MANIFEST, 'wrong_release')
    cfg = load(args.box_config)
    require(cfg.publication == 'dry_run' and cfg.model is None, 'not_dryrun_model_off')
    require(cfg.jira is not None and cfg.jira.project_keys == ['KAN'], 'wrong_project')
    require(cfg.jira.base_url == 'https://api.atlassian.com/ex/jira/d0b47b8d-4655-4cb1-9f81-30573fd372c3', 'wrong_gateway')
    require(cfg.jira.auth.kind == 'basic', 'wrong_jira_auth')
    secrets = read_secrets(Path('/etc/agent-service/secrets.env'))
    jira = JiraConnector(HttpClient(cfg.jira.base_url),
                         BasicAuth(secrets[cfg.jira.auth.email_env], secrets[cfg.jira.auth.token_env]),
                         project_keys=cfg.jira.project_keys, bot_account_id=cfg.jira.bot_account_id,
                         webhook_secret=b'unused-read-only', clock=time.time)
    if args.mode == 'results':
        state = Path('/var/lib/agent-service/service/service.sqlite')
        require(state.is_file(), 'state_missing')
        db = sqlite3.connect(state.resolve().as_uri() + '?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        output = []
        try:
            db.execute('BEGIN')
            require(db.execute("SELECT count(*) FROM resources WHERE provider='github'").fetchone()[0] == 0,
                    'pr_resources_present')
            for row in db.execute("SELECT r.*,j.state AS job_state,j.result,j.resource_version AS job_version, "
                                  "j.job_id,j.attempts,j.event_id "
                                  "FROM resources r LEFT JOIN jobs j ON j.resource_id=r.resource_id "
                                  "AND j.generation=r.generation WHERE r.provider='jira'"):
                snap = json.loads(row['snapshot'])
                if snap.get('key') not in KEYS:
                    continue
                result = json.loads(row['result']) if row['result'] else None
                require(result is not None, 'analysis_missing:' + snap['key'])
                require(not row['closed'] and row['job_state'] == 'DONE', 'analysis_not_delivered:' + snap['key'])
                request = dict(request_id=f"{row['job_id']}:{row['attempts']}", installation_id=cfg.installation_id,
                               environment=cfg.environment, trigger_kind='jira', source_event=dict(
                                   event_id=row['event_id'], resource_version=row['job_version']))
                view = view_from_result(result, request)
                require(view.compatible, 'invalid_or_mismatched_result:' + snap['key'])
                require(result['trigger_kind'] == 'jira' and result['profile'] == 'http-requests-6', 'wrong_analysis')
                require(result['code_version'] == manifest['release_id'], 'wrong_analysis_release')
                require(result['status'] in {'USEFUL', 'PARTIAL', 'ABSTAINED'}, 'analysis_failed')
                require(result.get('model') is None and result['costs']['model_calls'] == 0, 'model_was_used')
                require(any(u['code'] == 'jira_without_diff' for u in result['unknowns']), 'missing_no_diff_boundary')
                current = jira.fetch(row['resource_id'])
                require(not current.closed and current.version == row['version'] == row['job_version']
                        == result['resource_version'], 'stale_analysis:' + snap['key'])
                sink = Path('/var/lib/agent-service/dry-run/jira') / (digest(row['resource_id'])[:24] + '.json')
                require(sink.is_file(), 'dryrun_sink_missing:' + snap['key'])
                local = json.loads(sink.read_text())
                marker, body_digest, generation = parse_marker(local['marker'])
                require(local['resource_id'] == row['resource_id'] and local['id'] == row['comment_id']
                        and marker == resource_marker(cfg.installation_id, row['resource_id'])
                        and generation == row['published_generation'] == row['generation']
                        and body_digest == row['comment_digest'] == doc_digest(local['doc']), 'stale_or_wrong_sink')
                output.append(dict(key=snap['key'], resource_id=row['resource_id'], generation=row['generation'],
                                   comment_id=row['comment_id'], version=row['version'], status=result['status'],
                                   reason_code=result['reason_code'], affected=[a['service']['service']
                                       for a in result['affected']], checks=len(result['checks']),
                                   evidence=len(result['evidence'])))
        finally:
            db.close()
        require({v['key'] for v in output} == KEYS, 'existing_issues_missing')
        print(json.dumps({'ok': True, 'level': 'ANALYSIS_EXECUTED_NOT_QUALITY',
                          'issues': sorted(output, key=lambda v: v['key'])}, indent=2))
        return

    identity = jira._call('GET', '/rest/api/3/myself').json()
    require(identity.get('active') is True and identity.get('accountId') == cfg.jira.bot_account_id,
            'jira_owner_identity_mismatch')
    require(jira._call('GET', '/rest/api/3/project/KAN').json().get('key') == 'KAN', 'jira_project_mismatch')
    permissions = ('BROWSE_PROJECTS', 'ADD_COMMENTS', 'EDIT_OWN_COMMENTS')
    data = jira._call('GET', '/rest/api/3/mypermissions',
                     query={'projectKey': 'KAN', 'permissions': ','.join(permissions)}).json()
    require(all(data.get('permissions', {}).get(p, {}).get('havePermission') is True for p in permissions),
            'jira_permissions_missing')
    issues, token, seen_tokens = [], None, set()
    for _ in range(20):
        query = dict(jql='project in (KAN) ORDER BY updated ASC', maxResults=100, fields='project,updated')
        if token:
            query['nextPageToken'] = token
        page = jira._call('GET', '/rest/api/3/search/jql', query=query).json()
        require(isinstance(page, dict) and isinstance(page.get('issues'), list)
                and type(page.get('isLast')) is bool, 'full_listing_invalid')
        issues.extend(page['issues'])
        token = page.get('nextPageToken')
        if page['isLast']:
            require(token in (None, ''), 'full_listing_incomplete')
            break
        require(isinstance(token, str) and bool(token) and token not in seen_tokens, 'full_listing_incomplete')
        seen_tokens.add(token)
    else:
        raise CheckError('full_listing_incomplete')
    require(KEYS <= {i['key'] for i in issues}, 'expected_issues_not_accessible')
    comments = {}
    for issue in issues:
        if issue['key'] not in KEYS:
            continue
        items, start = [], 0
        for _ in range(10):
            page = jira._call('GET', '/rest/api/3/issue/' + issue['id'] + '/comment',
                              query={'startAt': start, 'maxResults': 100, 'orderBy': 'created'}).json()
            batch = page['comments']
            items.extend({'id': c['id'], 'body': c.get('body')} for c in batch)
            start += len(batch)
            if start >= page['total']:
                break
            require(bool(batch), 'comment_listing_incomplete')
        else:
            raise CheckError('comment_listing_incomplete')
        comments[issue['key']] = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
    client = HttpClient(cfg.github.api_base)
    auth = GitHubAppAuth(client, cfg.github.auth.app_id, cfg.github.auth.installation_id,
                         Path(secrets[cfg.github.auth.private_key_path_env]).read_bytes(), time.time)

    def gh_get(path, *, app=False, query=None):
        return client.request('GET', path, query=query,
            headers={'Authorization': 'Bearer ' + auth._jwt() if app else auth(),
                     'X-GitHub-Api-Version': API_VERSION}, accept='application/vnd.github+json').json()

    try:
        app = gh_get('/app', app=True)
        require(str(app.get('id')) == cfg.github.auth.app_id == '5515659'
                and app.get('slug', '') + '[bot]' == cfg.github.bot_login
                and app.get('permissions') == PERMS, 'github_app_mismatch')
        installation = gh_get('/app/installations/176298402', app=True)
        require(installation.get('id') == cfg.github.auth.installation_id == 176298402
                and installation.get('app_id') == 5515659
                and installation.get('account', {}).get('login') == 'rengalaxies'
                and installation.get('repository_selection') == 'selected'
                and installation.get('permissions') == PERMS
                and not installation.get('suspended_at'), 'github_installation_mismatch')
        repos = gh_get('/installation/repositories', query={'per_page': 100})
        require(repos.get('total_count') == 2 and {r['full_name'] for r in repos['repositories']}
                == {r.name for r in cfg.github.repositories}
                and all(r['private'] for r in repos['repositories']), 'github_repository_scope_mismatch')
        bot = gh_get('/users/' + cfg.github.bot_login)
        require(bot.get('id') == 349497413 and bot.get('type') == 'Bot', 'github_bot_mismatch')
        for repo in cfg.github.repositories:
            branch = gh_get('/repos/' + repo.name + '/branches/' + repo.branch)
            require(bool(branch.get('commit', {}).get('sha')), 'github_branch_unavailable')
            prs = gh_get('/repos/' + repo.name + '/pulls', query={'state': 'open', 'per_page': 100})
            require(not prs, 'open_pr_exists:' + repo.name)
    finally:
        if auth._token:
            client.request('DELETE', '/installation/token', headers={
                'Authorization': auth(), 'X-GitHub-Api-Version': API_VERSION})
    print(json.dumps({'ok': True, 'level': 'REAL_API_READ_ONLY', 'jira_owner_identity_matches': True,
                      'app_installation_repositories_match': True, 'open_prs': 0,
                      'issues': [{'id': i['id'], 'key': i['key'], 'updated': i['fields']['updated']}
                                 for i in issues], 'jira_comment_sha256': comments}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'ok': False, 'code': getattr(exc, 'code', type(exc).__name__),
                          'http_status': getattr(exc, 'status', None)}))
        raise SystemExit(1)
