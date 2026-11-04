"""Additive Bitbucket Cloud read foundation; not a registered service connector.

No writes, credential discovery, queue/state mutation or GitHub behavior changes.
Repository UUIDs pin PR identities; next links may only address the same listing.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import re
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from ..envelope import digest
from ..http import ClientError, HttpClient, NotFound, segment


def _invalid():
    return ClientError('bitbucket_response_invalid')


def _uuid(value) -> str:
    try:
        if not isinstance(value, str):
            raise ValueError
        return str(UUID(value))
    except ValueError:
        raise _invalid() from None


def _text(value, *, empty=False) -> str:
    if not isinstance(value, str) or (not empty and not value) or any(c in value for c in '\r\n\x00'):
        raise _invalid()
    _utf8(value)
    return value


def _utf8(value):
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise _invalid() from None


def _sha(value) -> str:
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{40}', value):
        raise _invalid()
    return value


class ApiTokenAuth:
    """REST Basic auth. Git authentication is a separate future boundary."""
    def __init__(self, email: str, token: str):
        if (not isinstance(email, str) or not isinstance(token, str) or '@' not in email or not token
                or ':' in email or any(c in email + token for c in '\r\n\x00')):
            raise ValueError('invalid_bitbucket_credentials')
        self._header = 'Basic ' + base64.b64encode(f'{email}:{token}'.encode()).decode()

    def __call__(self) -> str:
        return self._header


@dataclass(frozen=True)
class RepositoryInfo:
    workspace: str
    slug: str
    workspace_uuid: str
    uuid: str
    default_branch: str | None
    is_private: bool


@dataclass(frozen=True)
class PullRequestInfo:
    repository: RepositoryInfo
    number: int
    title: str
    description: str
    state: str
    draft: bool
    source_repository_uuid: str
    source_branch: str
    destination_branch: str
    head_sha: str
    base_sha: str

    @property
    def resource_id(self) -> str:
        return f'bitbucket:{self.repository.workspace_uuid}/{self.repository.uuid}#{self.number}'

    @property
    def version(self) -> str:
        return 'bitbucket:' + digest(dict(
            identity=self.resource_id, title=self.title, description=self.description,
            state=self.state, draft=self.draft, source_repository_uuid=self.source_repository_uuid,
            source_branch=self.source_branch, destination_branch=self.destination_branch,
            head_sha=self.head_sha, base_sha=self.base_sha))[:32]


class BitbucketReadClient:
    def __init__(self, client: HttpClient, auth: ApiTokenAuth, *, workspace: str,
                 workspace_uuid: str, repositories):
        parts = urlsplit(client.base_url)
        production = client.base_url == 'https://api.bitbucket.org/2.0'
        local = parts.scheme == 'http' and parts.hostname in {'127.0.0.1', 'localhost', '::1'} and parts.path == '/2.0'
        if not (production or local):
            raise ValueError('invalid_bitbucket_api_origin')
        if not self._slug(workspace) or isinstance(repositories, str):
            raise ValueError('invalid_bitbucket_repository_scope')
        self.repositories = frozenset(repositories)
        if not self.repositories or any(not self._slug(r) for r in self.repositories):
            raise ValueError('invalid_bitbucket_repository_scope')
        try:
            self.workspace_uuid = str(UUID(workspace_uuid))
        except (ValueError, AttributeError, TypeError):
            raise ValueError('invalid_bitbucket_workspace_uuid') from None
        self.client, self.auth, self.workspace = client, auth, workspace
        self._resolved = {}

    @staticmethod
    def _slug(value):
        return isinstance(value, str) and re.fullmatch('[a-z0-9][a-z0-9._-]{0,99}', value) is not None

    def _path(self, slug):
        if slug not in self.repositories:
            raise ValueError('bitbucket_repository_not_allowed')
        return f'/repositories/{segment(self.workspace)}/{segment(slug)}'

    def _repo_path(self, repo):
        if (not isinstance(repo, RepositoryInfo) or repo.workspace != self.workspace
                or repo.workspace_uuid != self.workspace_uuid):
            raise ValueError('bitbucket_repository_not_allowed')
        self._path(repo.slug)  # preserve the configured repository allowlist
        if self._resolved.get(repo.slug) != repo.uuid:
            raise ValueError('bitbucket_repository_not_allowed')
        return f'/repositories/{segment(self.workspace)}/{segment("{" + _uuid(repo.uuid) + "}")}'

    def _get(self, path, query=None):
        response = self.client.request('GET', path, query=query,
                                       headers={'Authorization': self.auth()})
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (ValueError, UnicodeError):
            raise _invalid() from None

    def repository(self, slug: str) -> RepositoryInfo:
        data = self._get(self._path(slug))
        try:
            ws = data['workspace']
            if (data['slug'] != slug or data['full_name'] != f'{self.workspace}/{slug}'
                    or ws['slug'] != self.workspace or _uuid(ws['uuid']) != self.workspace_uuid
                    or type(data['is_private']) is not bool):
                raise _invalid()
            branch = data.get('mainbranch')
            repo = RepositoryInfo(self.workspace, slug, self.workspace_uuid, _uuid(data['uuid']),
                                  None if branch is None else _text(branch['name']), data['is_private'])
            if slug in self._resolved and self._resolved[slug] != repo.uuid:
                raise ClientError('bitbucket_repository_identity_changed')
            self._resolved[slug] = repo.uuid
            return repo
        except (KeyError, TypeError):
            raise _invalid() from None

    def branch(self, repo: RepositoryInfo, branch: str | None = None) -> str:
        path = self._repo_path(repo)
        name = branch if branch is not None else repo.default_branch
        if name is None:
            raise ClientError('bitbucket_empty_repository')
        _text(name)
        data = self._get(path + '/refs/branches/' + segment(name))
        try:
            if data['name'] != name:
                raise _invalid()
            return _sha(data['target']['hash'])
        except (KeyError, TypeError):
            raise _invalid() from None

    @staticmethod
    def _number(value):
        if type(value) is not int or not 1 <= value < 2**63:
            raise _invalid()
        return value

    def _commit_sha(self, repo, value, repository_uuid):
        if isinstance(value, str) and re.fullmatch('[a-f0-9]{40}', value):
            return value
        if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{12,39}', value):
            raise _invalid()
        if repository_uuid != repo.uuid:
            raise ClientError('bitbucket_compact_fork_sha_unsupported')
        try:
            data = self._get(self._repo_path(repo) + '/commit/' + segment(value))
        except NotFound:
            raise ClientError('bitbucket_commit_unavailable') from None
        try:
            full = _sha(data['hash'])
            if not full.startswith(value):
                raise _invalid()
            return full
        except (KeyError, TypeError):
            raise _invalid() from None

    def _pr(self, repo, data, *, number=None):
        try:
            n = self._number(data['id'])
            dest, source = data['destination'], data['source']
            if (number is not None and n != number or _uuid(dest['repository']['uuid']) != repo.uuid
                    or dest['repository']['full_name'] != f'{self.workspace}/{repo.slug}'
                    or data['state'] not in {'OPEN', 'MERGED', 'DECLINED'}
                    or type(data.get('draft', False)) is not bool):
                raise _invalid()
            title = _text(data['title'])
            description = data.get('description')
            if description is None:
                description = ''
            if not isinstance(description, str):
                raise _invalid()
            _utf8(description)
            source_uuid = _uuid(source['repository']['uuid'])
            head_sha = self._commit_sha(repo, source['commit']['hash'], source_uuid)
            base_sha = self._commit_sha(repo, dest['commit']['hash'], repo.uuid)
            return PullRequestInfo(repo, n, title, description, data['state'], data.get('draft', False),
                source_uuid, _text(source['branch']['name']),
                _text(dest['branch']['name']), head_sha, base_sha)
        except (KeyError, TypeError):
            raise _invalid() from None

    def pull_request(self, repo: RepositoryInfo, number: int) -> PullRequestInfo:
        path = self._repo_path(repo)
        self._number(number)
        return self._pr(repo, self._get(path + '/pullrequests/' + str(number)), number=number)

    def _next_query(self, url, path):
        base = urlsplit(self.client.base_url)
        try:
            if not isinstance(url, str) or not url:
                raise ValueError
            nxt = urlsplit(url)
            if (nxt.scheme != base.scheme or nxt.netloc != base.netloc or nxt.username is not None
                    or nxt.password is not None or nxt.path != base.path + path or nxt.fragment):
                raise ValueError
            if re.search(r'%(?![0-9a-fA-F]{2})', nxt.query):
                raise ValueError
            pairs = parse_qsl(nxt.query, keep_blank_values=True, strict_parsing=True, errors='strict')
            query = dict(pairs)
            if len(query) != len(pairs) or 'state' in query and query['state'] != 'OPEN':
                raise ValueError
            return query  # opaque provider query: do not invent page/cursor values
        except (ValueError, UnicodeError):
            raise ClientError('bitbucket_pagination_invalid') from None

    def open_pull_requests(self, repo: RepositoryInfo) -> tuple[PullRequestInfo, ...]:
        path = self._repo_path(repo) + '/pullrequests'
        query = {'state': 'OPEN', 'pagelen': '50'}
        seen, result = set(), {}
        for _ in range(20):
            cursor = tuple(sorted(query.items()))
            if cursor in seen:
                raise ClientError('bitbucket_listing_incomplete')
            seen.add(cursor)
            page = self._get(path, query)
            if not isinstance(page.get('values'), list):
                raise _invalid()
            for item in page['values']:
                pr = self._pr(repo, item)
                if pr.state != 'OPEN':
                    raise _invalid()
                if pr.number in result and result[pr.number].version != pr.version:
                    raise ClientError('bitbucket_listing_changed')
                result[pr.number] = pr
            if 'next' not in page:
                return tuple(result.values())
            query = self._next_query(page['next'], path)
        raise ClientError('bitbucket_listing_incomplete')
