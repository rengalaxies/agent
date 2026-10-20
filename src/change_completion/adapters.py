"""Bounded, deliberately incomplete adapters for the internal sql-window/1 lab.

These adapters are not a general SQL parser or an autonomous LLM provider.
Unknown syntax is a coverage gap, never evidence that all consumers were found.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import stat

MAX_FILES = 100
MAX_FILE_BYTES = 1_000_000
MAX_TOTAL_BYTES = 5_000_000
_TOKEN = re.compile(r"\s+|--[^\n]*(?:\n|$)|/\*.*?\*/|'(?:''|[^'])*'|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|<=|>=|<>|!=|[(),.;*+=<>/-]", re.S)


def read_repository_file(root: Path, relative_path: str) -> bytes:
    """Bounded no-follow read anchored to root; deployment owns root's parents.

    A descriptor is opened for every component, so swaps after opening cannot
    redirect the read. The caller's configured root and its ancestors must be
    trusted deployment paths, rather than paths supplied by repository content.
    """
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or any(part in {'..', '.'} for part in relative.parts) or '\\' in relative_path:
        raise ValueError('invalid_repository_path')
    if any(part.startswith('.') for part in relative.parts):
        raise ValueError('hidden_repository_path')
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        file_fd = os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('not_regular_file')
            if info.st_size > MAX_FILE_BYTES:
                raise ValueError('file_too_large')
            chunks, size = [], 0
            while size <= MAX_FILE_BYTES:
                chunk = os.read(file_fd, min(65536, MAX_FILE_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise ValueError('file_too_large')
            return b''.join(chunks)
        finally:
            os.close(file_fd)
    finally:
        os.close(directory)


def _tokens(sql: str) -> list[tuple[str, int, int]]:
    if len(sql.encode('utf-8')) > MAX_FILE_BYTES:
        raise ValueError('sql_too_large')
    result = []
    offset = 0
    while offset < len(sql):
        match = _TOKEN.match(sql, offset)
        if match is None:
            raise ValueError('unsupported_sql_token')
        value = match.group()
        if not value.isspace() and not value.startswith(('--', '/*')):
            result.append((value, match.start(), match.end()))
        offset = match.end()
    return result


def _select_tokens(sql: str) -> list[tuple[str, int, int]]:
    tokens = _tokens(sql)
    if not tokens or tokens[0][0].upper() not in {'SELECT', 'WITH'}:
        raise ValueError('select_only')
    words = [token[0].upper() for token in tokens]
    if any(word in {'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE', 'ATTACH', 'DETACH', 'PRAGMA', 'COPY', 'INTO', 'REPLACE'} for word in words):
        raise ValueError('select_only')
    if ';' in words[:-1]:
        raise ValueError('multiple_statements')
    depth = 0
    for word in words:
        depth += (word == '(') - (word == ')')
        if depth < 0:
            raise ValueError('unbalanced_parentheses')
    if depth:
        raise ValueError('unbalanced_parentheses')
    if not any(word == 'SELECT' for word in words):
        raise ValueError('select_required')
    return tokens


def prepare_window_patch(sql: str, *, old_window: int, new_window: int) -> dict:
    """Rewrite one literal in an unambiguous WHERE age_days predicate.

    The caller must independently authorize the requested semantic change.
    Comments and quoted string contents are never candidate predicates.
    """
    def stop(reason: str) -> dict:
        return {'status': 'unsupported', 'candidate': None, 'diff': '', 'reason_codes': [reason]}
    if any(type(value) is not int or not 0 < value <= 36500 for value in (old_window, new_window)):
        return stop('invalid_window')
    try:
        tokens = _select_tokens(sql)
    except ValueError as error:
        return stop(str(error))
    words = [token[0].upper() for token in tokens]
    # Keep this profile intentionally small: complex branching requires another adapter.
    if any(word in {'OR', 'CASE', 'UNION', 'INTERSECT', 'EXCEPT', 'NOT', 'BETWEEN'} for word in words):
        return stop('unsupported_predicate_structure')
    matches = []
    age_occurrences = 0
    for index, (value, _, _) in enumerate(tokens):
        if value.lower() != 'age_days':
            continue
        age_occurrences += 1
        if index + 2 >= len(tokens):
            continue
        before = words[:index]
        last_where = max((position for position, word in enumerate(before) if word == 'WHERE'), default=-1)
        last_select = max((position for position, word in enumerate(before) if word == 'SELECT'), default=-1)
        if last_where < last_select or last_where < 0:
            continue
        operator, number = tokens[index + 1][0], tokens[index + 2][0]
        preceding = words[index - 1] if index else ''
        # Only a direct predicate following WHERE/AND/(, optionally qualified.
        if preceding == '.' and index >= 3:
            preceding = words[index - 3]
        if preceding not in {'WHERE', 'AND', '('}:
            continue
        after = words[index + 3] if index + 3 < len(tokens) else ''
        if operator in {'<', '<='} and number.isdigit() and int(number) == old_window and after in {'', ';', ')', 'AND', 'GROUP', 'ORDER', 'LIMIT', 'HAVING'}:
            matches.append(tokens[index + 2])
    if len(matches) != 1 or age_occurrences != 1:
        return stop('ambiguous_or_missing_window_predicate')
    if old_window == new_window:
        return stop('no_change_requested')
    _, start, end = matches[0]
    candidate = sql[:start] + str(new_window) + sql[end:]
    diff = ''.join(difflib.unified_diff(sql.splitlines(keepends=True), candidate.splitlines(keepends=True), fromfile='original.sql', tofile='candidate.sql'))
    return {'status': 'prepared', 'candidate': candidate, 'diff': diff, 'reason_codes': []}


def _references(sql: str) -> tuple[list[str], list[str]]:
    tokens = _select_tokens(sql)
    words = [token[0] for token in tokens]
    refs, gaps = [], []
    ctes = {words[index] for index in range(len(words) - 2) if words[index + 1].upper() == 'AS' and words[index + 2] == '('}
    for index, word in enumerate(words):
        if word.upper() not in {'FROM', 'JOIN'}:
            continue
        cursor = index + 1
        if cursor >= len(words) or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', words[cursor]):
            gaps.append('unsupported_relation_expression')
            continue
        name = words[cursor]
        cursor += 1
        if cursor < len(words) and words[cursor] == '.':
            if cursor + 1 >= len(words) or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', words[cursor + 1]):
                gaps.append('unsupported_relation_expression')
                continue
            name += '.' + words[cursor + 1]
            cursor += 2
        if cursor < len(words) and words[cursor] == '(':
            gaps.append('unsupported_table_function')
        elif name not in ctes:
            refs.append(name)
    # Comma joins and dialect-specific constructs are outside this lab grammar.
    if ',' in words or any(word.upper() in {'LATERAL', 'UNNEST', 'PIVOT'} for word in words):
        gaps.append('dependency_coverage_incomplete')
    return sorted(set(refs)), sorted(set(gaps))


def discover_repository(root: Path) -> dict:
    """Read bounded SQL/JSON artifacts only; never follow symlinks.

    Dependency sources are SQL relation names, targets are repository paths.
    Every run declares static-only coverage: runtime consumers remain unknown.
    """
    root = Path(root)
    result = {'files': [], 'dependencies': [], 'gaps': ['static_snapshot_only_runtime_consumers_unknown']}
    if root.is_symlink() or not root.is_dir():
        result['gaps'].append('invalid_repository_root')
        return result
    total = 0
    seen = 0
    def walk(directory_fd: int, prefix: Path):
        nonlocal seen
        for name in sorted(os.listdir(directory_fd)):
            seen += 1
            if seen > 2000:
                result['gaps'].append('directory_entry_limit')
                return
            path = prefix / name
            if name.startswith('.') or any(secret in name.lower() for secret in ('secret', 'credential', 'token', 'password')):
                continue
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                result['gaps'].append('symlink_skipped:' + path.as_posix())
                continue
            if stat.S_ISDIR(info.st_mode):
                if len(path.parts) > 6:
                    result['gaps'].append('directory_depth_limit')
                else:
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    try:
                        yield from walk(child, path)
                    finally:
                        os.close(child)
            elif stat.S_ISREG(info.st_mode) and path.suffix.lower() in {'.sql', '.json'}:
                yield path
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        result['gaps'].append('snapshot_read_failed')
        return result
    try:
        for path in walk(root_fd, Path()):
            relative = path.as_posix()
            if len(result['files']) >= MAX_FILES:
                result['gaps'].append('snapshot_limit_reached')
                break
            try:
                data = read_repository_file(root, relative)
            except ValueError as error:
                result['gaps'].append(str(error) + ':' + relative)
                continue
            except OSError:
                result['gaps'].append('unsafe_or_unreadable_file:' + relative)
                continue
            if len(data) > MAX_FILE_BYTES:
                result['gaps'].append('file_too_large:' + relative)
                continue
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                result['gaps'].append('snapshot_limit_reached')
                break
            result['files'].append({'path': relative, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)})
            try:
                text = data.decode('utf-8')
                if path.suffix.lower() == '.json':
                    json.loads(text)
                else:
                    refs, gaps = _references(text)
                    result['dependencies'].extend({'source': source, 'target': relative, 'basis_path': relative} for source in refs)
                    result['gaps'].extend(gap + ':' + relative for gap in gaps)
            except (UnicodeError, ValueError) as error:
                result['gaps'].append('unsupported_artifact:' + relative + ':' + str(error))
    except OSError:
        result['gaps'].append('snapshot_read_failed')
    finally:
        os.close(root_fd)
    result['gaps'] = sorted(set(result['gaps']))
    return result
