import json
from pathlib import Path

import unittest
import tempfile

from change_completion.adapters import discover_repository, prepare_window_patch, read_repository_file


def test_patch_is_computed_from_supplied_windows():
    for old, new in ((30, 90), (14, 42), (365, 7)):
        sql = f'SELECT id FROM events WHERE age_days < {old}\n'
        result = prepare_window_patch(sql, old_window=old, new_window=new)
        assert result['status'] == 'prepared'
        assert result['candidate'] == f'SELECT id FROM events WHERE age_days < {new}\n'
        assert result['diff']


def test_comments_and_strings_are_not_patched():
    sql = "-- age_days < 30\nSELECT 'age_days < 30' AS note FROM events WHERE age_days <= 30"
    result = prepare_window_patch(sql, old_window=30, new_window=90)
    assert result['status'] == 'prepared'
    assert result['candidate'].count('age_days < 30') == 2
    assert result['candidate'].endswith('age_days <= 90')


def test_unsupported_and_ambiguous_predicates_stop():
    for sql in [
    'SELECT * FROM events WHERE age_days < 30 OR flag = 1',
    'SELECT * FROM events WHERE age_days < 30 AND age_days < 30',
    "SELECT 'age_days < 30' FROM events",
    'SELECT * FROM events WHERE age_days < 30 + 2',
    'SELECT * FROM events WHERE age_days < 30; DROP TABLE events',
    'DELETE FROM events WHERE age_days < 30',
    'SELECT * FROM events WHERE age_days < 30 /* unfinished',
    'SELECT * FROM events WHERE age_days < 30.5',
    'SELECT * FROM events WHERE age_days < 30e2',
    'SELECT age_days FROM events WHERE age_days < 30',
    'SELECT (age_days < 30) FROM events',
    'SELECT (age_days < 30) FROM events WHERE id = 1',
]:
        _assert_stopped(sql)


def _assert_stopped(sql):
    result = prepare_window_patch(sql, old_window=30, new_window=90)
    assert result['status'] == 'unsupported'
    assert result['candidate'] is None
    assert result['diff'] == ''


def test_no_pointless_rewrite_and_invalid_windows():
    sql = 'SELECT id FROM events WHERE age_days < 30'
    assert prepare_window_patch(sql, old_window=30, new_window=30)['reason_codes'] == ['no_change_requested']
    for invalid in (True, -1, 0, 1.5, '90', 36501):
        assert prepare_window_patch(sql, old_window=30, new_window=invalid)['status'] == 'unsupported'


def test_cte_and_qualified_predicate():
    sql = 'WITH base AS (SELECT id FROM events) SELECT id FROM base e WHERE e.age_days < 30;'
    assert prepare_window_patch(sql, old_window=30, new_window=90)['candidate'].endswith('e.age_days < 90;')


def test_snapshot_dependencies_and_content_hash(tmp_path):
    (tmp_path / 'report.sql').write_text('SELECT id FROM app.events JOIN users ON users.id = events.id WHERE age_days < 30')
    (tmp_path / 'contract.json').write_text(json.dumps({'version': 1}))
    result = discover_repository(tmp_path)
    assert len(result['files']) == 2
    assert all(len(item['sha256']) == 64 for item in result['files'])
    assert {item['source'] for item in result['dependencies']} == {'app.events', 'users'}
    assert all(item['target'] == 'report.sql' for item in result['dependencies'])
    assert 'static_snapshot_only_runtime_consumers_unknown' in result['gaps']


def test_symlinks_hidden_secrets_and_unsupported_sql(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + '-outside.sql')
    outside.write_text('SELECT id FROM secret_table')
    (tmp_path / 'escape.sql').symlink_to(outside)
    (tmp_path / '.env.json').write_text('{}')
    (tmp_path / 'credentials.json').write_text('{}')
    (tmp_path / 'broken.sql').write_text('SELECT * FROM generate_series(1, 3)')
    result = discover_repository(tmp_path)
    assert [item['path'] for item in result['files']] == ['broken.sql']
    assert not any(item['source'] == 'secret_table' for item in result['dependencies'])
    assert 'symlink_skipped:escape.sql' in result['gaps']
    assert any('unsupported_table_function' in gap for gap in result['gaps'])


def test_cte_is_not_external_relation(tmp_path):
    (tmp_path / 'view.sql').write_text('WITH base AS (SELECT id FROM events) SELECT id FROM base')
    assert [item['source'] for item in discover_repository(tmp_path)['dependencies']] == ['events']


def test_snapshot_bounds(tmp_path):
    import change_completion.adapters as module
    original = module.MAX_FILE_BYTES
    module.MAX_FILE_BYTES = 5
    (tmp_path / 'big.sql').write_text('SELECT id FROM events')
    assert discover_repository(tmp_path)['files'] == []
    assert 'file_too_large:big.sql' in discover_repository(tmp_path)['gaps']
    module.MAX_FILE_BYTES = original


def test_invalid_root(tmp_path):
    assert 'invalid_repository_root' in discover_repository(tmp_path / 'missing')['gaps']


def test_descriptor_read_rejects_escape_and_symlink_parent(tmp_path):
    (tmp_path / 'safe.sql').write_text('SELECT 1')
    assert read_repository_file(tmp_path, 'safe.sql') == b'SELECT 1'
    for invalid in ('../safe.sql', '/etc/passwd', '.hidden/file.sql'):
        try:
            read_repository_file(tmp_path, invalid)
        except ValueError:
            pass
        else:
            raise AssertionError('unsafe path accepted')
    (tmp_path / 'linked').symlink_to(tmp_path, target_is_directory=True)
    try:
        read_repository_file(tmp_path, 'linked/safe.sql')
    except OSError:
        pass
    else:
        raise AssertionError('symlink parent accepted')


def _wrap(function):
    def run(self):
        if function.__code__.co_argcount:
            with tempfile.TemporaryDirectory() as directory:
                function(Path(directory))
        else:
            function()
    return run


class AdapterTests(unittest.TestCase):
    pass


for _name, _function in list(globals().items()):
    if _name.startswith("test_") and callable(_function):
        setattr(AdapterTests, _name, _wrap(_function))
del _name, _function
