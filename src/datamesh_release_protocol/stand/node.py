"""Independent domain HTTP process with a local SQLite metadata/event store."""
import argparse
import json
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from threading import RLock

from ..knowledge import KnowledgeRecord,canonical,digest
from .protocol import WorkItem,make_vote,sign,revision
from .policy import project


class DomainNode:
    def __init__(self,config):
        self.config=config;self.domain=config['domain_id'];self.lock=RLock()
        self.db=sqlite3.connect(config['database'],check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS records (record_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS requests (event_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, response TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS journal (seq INTEGER PRIMARY KEY, kind TEXT, payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS configuration (id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL)')
        seed_hash=digest({'domain':self.domain,'records':config['records'],'public_keys':config['public_keys'],'routes':config['routes']})
        seed=self.db.execute('SELECT fingerprint FROM configuration WHERE id=1').fetchone()
        if seed and seed[0]!=seed_hash:raise ValueError('configuration identity differs from persisted seed')
        for raw in config['records']:
            r=KnowledgeRecord.model_validate(raw)
            if config['routes'][r.owner_domain]!=self.domain:raise ValueError('foreign record in domain configuration')
            payload=canonical(r.model_dump(mode='json'));prior=self.db.execute('SELECT payload FROM records WHERE record_id=?',(r.record_id,)).fetchone()
            if not seed and prior and prior[0]!=payload:raise ValueError('configuration differs from persisted domain state')
            self.db.execute('INSERT OR IGNORE INTO records VALUES (?,?)',(r.record_id,payload))
        self.db.execute('INSERT OR IGNORE INTO configuration VALUES (1,?)',(seed_hash,))
        self.db.commit()

    def records_for(self,snapshot):
        all_records=[KnowledgeRecord.model_validate_json(row[0]) for row in self.db.execute('SELECT payload FROM records')]
        ids={r.record_id for r in snapshot.records}
        return [r for r in all_records if r.record_id in ids or r.data.get('product_id')==snapshot.product_id or
                (r.kind=='obligation' and r.data['requirement']['product_id']==snapshot.product_id)]

    def check(self,raw,kind):
        work=WorkItem.model_validate(raw);work.snapshot.verify()
        identity=kind+':'+work.event_id;fingerprint=digest(work.model_dump(mode='json'))
        with self.lock:
            row=self.db.execute('SELECT fingerprint,response FROM requests WHERE event_id=?',(identity,)).fetchone()
            if row:
                if row[0]!=fingerprint:raise ValueError('event_id reused with conflicting payload')
                return json.loads(row[1])
            vote=make_vote(work,self.domain,self.config['routes'],self.records_for(work.snapshot),kind)
            # event_id binds the final, complete response body.
            vote.event_id=digest(vote.model_dump(mode='json',exclude={'event_id'}))
            response=sign(vote,self.config['private_key']).model_dump(mode='json')
            self.db.execute('INSERT INTO requests VALUES (?,?,?)',(identity,fingerprint,canonical(response)))
            self.db.execute('INSERT INTO journal(kind,payload) VALUES (?,?)',(kind,canonical(response)))
            self.db.commit()
            return response

    def update_record(self,raw):
        r=KnowledgeRecord.model_validate(raw)
        if self.config['routes'][r.owner_domain]!=self.domain:raise PermissionError('foreign domain record')
        with self.lock:
            row=self.db.execute('SELECT payload FROM records WHERE record_id=?',(r.record_id,)).fetchone()
            if not row:raise ValueError('record must already exist')
            prior=KnowledgeRecord.model_validate_json(row[0])
            if r.version!=prior.version+1 or r.valid_from<=prior.valid_from:raise ValueError('invalid domain revision')
            self.db.execute('UPDATE records SET payload=? WHERE record_id=?',(canonical(r.model_dump(mode='json')),r.record_id))
            self.db.execute('INSERT INTO journal(kind,payload) VALUES (?,?)',('METADATA_UPDATE',canonical(r.model_dump(mode='json'))));self.db.commit()
            return {'record_id':r.record_id,'version':r.version}


def serve(config):
    node=DomainNode(config)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,value):
            data=canonical(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.path=='/health':self.reply(200,{'domain_id':node.domain,'status':'ready'});return
            self.reply(404,{'error':'not found'})
        def do_POST(self):
            token=self.headers.get('Authorization','').removeprefix('Bearer ')
            if not secrets.compare_digest(token,config['token']):self.reply(401,{'error':'authenticated peer required'});return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<=0 or length>4*1024*1024:raise ValueError('invalid request size')
                body=json.loads(self.rfile.read(length))
                if self.path=='/check':result=node.check(body,'VERDICT')
                elif self.path=='/fence':result=node.check(body,'FENCE')
                elif self.path=='/metadata':
                    if not secrets.compare_digest(self.headers.get('X-Admin-Token',''),config['admin_token']):raise PermissionError('domain administrator required')
                    result=node.update_record(body)
                elif self.path=='/finalize':
                    work=WorkItem.model_validate(body['work'])
                    result=project(work.snapshot,work.run_id,work.migrations,body['messages'],config['public_keys'],config['routes'],body['deadline_expired'])
                else:self.reply(404,{'error':'not found'});return
                self.reply(200,result)
            except PermissionError as e:self.reply(403,{'error':str(e)})
            except (ValueError,KeyError) as e:self.reply(409,{'error':str(e)})
            except Exception:self.reply(500,{'error':'domain processing failed'})
    server=ThreadingHTTPServer((config.get('host','127.0.0.1'),config['port']),Handler)
    import os
    print(canonical({'domain_id':node.domain,'pid':os.getpid(),'url':'http://'+config.get('host','127.0.0.1')+':'+str(server.server_address[1])}),flush=True)
    try:server.serve_forever(poll_interval=0.05)
    finally:server.server_close();node.db.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args();serve(json.loads(a.config.read_text()))

if __name__=='__main__':main()
