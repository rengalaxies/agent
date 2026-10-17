"""Private snapshot/restore of a quiesced installation. No overwrite restore."""
import argparse
from contextlib import ExitStack, contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3

MAX_FILE = 128 * 1024 * 1024

def _directory(path, *, new=False):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)): raise ValueError('symlink path')
    if new:
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
    if not path.is_dir(): raise ValueError('directory required')
    return path

@contextmanager
def _connect(path):
    c = sqlite3.connect(path, timeout=1)
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.rollback()
        c.close()

def snapshot(state, destination, *, quiesced=False):
    if quiesced is not True: raise ValueError('stop workers/server and confirm quiescence')
    state = _directory(state)
    destination = Path(destination).absolute()
    if destination.is_relative_to(state): raise ValueError('backup outside state required')
    files = sorted(state.glob('*.sqlite3'))
    if not 1 <= len(files) <= 16: raise ValueError('database count limit')
    for p in files:
        if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_FILE: raise ValueError('invalid database')
    with ExitStack() as stack:
        locks = [stack.enter_context(_connect(p)) for p in files]
        for c in locks: c.execute('BEGIN IMMEDIATE')
        for c in locks:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table, status in [('runs', 'RUNNING'), ('workflow_outbox', 'SENDING'), ('tasks', 'RUNNING')]:
                if table in tables and 'status' in {r[1] for r in c.execute('PRAGMA table_info('+table+')')}:
                    if c.execute('SELECT 1 FROM '+table+' WHERE status=? LIMIT 1', (status,)).fetchone():
                        raise ValueError('unreconciled in-flight state')
        target = _directory(destination, new=True)
        manifest = {'format': 'change-state/1', 'files': {}}
        try:
            for p in files:
                output = target / p.name
                with _connect(p) as source, _connect(output) as dest:
                    source.backup(dest)
                    if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise ValueError('integrity failure')
                os.chmod(output, 0o600)
                if output.stat().st_size > MAX_FILE: raise ValueError('snapshot output limit')
                manifest['files'][p.name] = sha256(output.read_bytes()).hexdigest()
            manifest_path = target/'manifest.json'
            manifest_path.write_text(json.dumps(manifest, sort_keys=True))
            os.chmod(manifest_path, 0o600)
        except BaseException:
            shutil.rmtree(target); raise
    return manifest

def restore(source, destination):
    source = _directory(source)
    raw = (source/'manifest.json')
    if raw.is_symlink() or raw.stat().st_size > 65536: raise ValueError('invalid manifest')
    manifest = json.loads(raw.read_bytes())
    if manifest.get('format') != 'change-state/1' or not 1 <= len(manifest.get('files', {})) <= 16: raise ValueError('invalid manifest')
    for name, digest in manifest['files'].items():
        if Path(name).name != name or not name.endswith('.sqlite3'): raise ValueError('unsafe filename')
        p = source/name
        if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_FILE: raise ValueError('invalid file')
        if sha256(p.read_bytes()).hexdigest() != digest: raise ValueError('digest mismatch')
    target = _directory(destination, new=True)
    try:
        for name in manifest['files']:
            output = target/name
            shutil.copyfile(source/name, output); os.chmod(output, 0o600)
            if sha256(output.read_bytes()).hexdigest() != manifest['files'][name]: raise ValueError('copied digest mismatch')
            with _connect(output) as c:
                if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise ValueError('integrity failure')
                tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if {'identities','memberships','tasks'} <= tables:
                    c.execute('UPDATE identities SET revoked=1')
                    c.execute('DELETE FROM memberships')
                    c.execute("UPDATE tasks SET status='UNKNOWN' WHERE status IN ('QUEUED','RUNNING')")
                    c.execute('CREATE TABLE IF NOT EXISTS restore_quarantine(singleton INTEGER PRIMARY KEY CHECK(singleton=1), acknowledged INTEGER NOT NULL DEFAULT 0)')
                    c.execute('INSERT OR REPLACE INTO restore_quarantine VALUES(1,0)')
                    c.commit()
                if {'workflows','workflow_outbox'} <= tables:
                    c.execute("UPDATE workflows SET status='STALE',reviews='{}',final_review=NULL")
                    c.execute("UPDATE workflow_outbox SET status='CANCELLED',reason='restored_requires_revalidation' WHERE status='PENDING'")
                    from datetime import datetime, timezone
                    for row in c.execute('SELECT run_id FROM workflows').fetchall():
                        c.execute('INSERT INTO workflow_history(run_id,timestamp,kind,payload) VALUES(?,?,?,?)',
                            (row[0], datetime.now(timezone.utc).isoformat(),'RESTORE_INVALIDATED','{}'))
                    c.commit()

    except BaseException:
        shutil.rmtree(target); raise
    return {'restored': sorted(manifest['files']), 'requires_operator_config_and_authority_revalidation': True}

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('operation', choices=['snapshot','restore'])
    p.add_argument('source'); p.add_argument('destination'); p.add_argument('--quiesced', action='store_true'); a=p.parse_args()
    result = snapshot(a.source,a.destination,quiesced=a.quiesced) if a.operation=='snapshot' else restore(a.source,a.destination)
    print(json.dumps(result))
if __name__=='__main__': main()
