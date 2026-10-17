"""Trusted isolated failure fixture, never exposed as a model or deployment tool."""
import json
import os
from pathlib import Path
import sys
from lab.app import service
from lab.runtime.core import Stop, tree_digest, json_exact
from lab.runtime.dispatch import _perform_transition, reconcile_unknown

JOURNAL=Path('/evidence/journal')
ARTIFACT=tree_digest(Path('lab/sql'))


def counter():
    with service.db() as db:db.execute('UPDATE ci_transition_calls SET n=n+1')


def main(mode):
    if mode=='prepare':
        service.initialize()
        expected=json.loads(Path('lab/evaluator/commit-gap-expectations.json').read_text())
        for order, rub in expected['input_rubles'].items():
            service.create_order(order,str(rub))
            if order!='gap-pending':service.publish();service.consume()
        service.publish()
        with service.db() as db:
            db.execute('''CREATE TABLE ci_transition_calls(n integer NOT NULL);
                INSERT INTO ci_transition_calls VALUES(0);
                CREATE TABLE ci_backfill_updates(order_id text NOT NULL);
                CREATE FUNCTION ci_track_update() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN INSERT INTO ci_backfill_updates VALUES(NEW.order_id); RETURN NEW; END $$;
                CREATE TRIGGER ci_backfill AFTER UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION ci_track_update();
                GRANT SELECT ON ci_transition_calls,ci_backfill_updates TO lab_verifier;''')
        return {'state':'PREPARED','pending_order':'gap-pending'}
    if mode=='fault':
        # No grant is issued. This private fixture exercises the same post-authorization
        # effect/journal boundary as dispatcher.execute, on disposable CI resources only.
        return _perform_transition(Path('.'),JOURNAL,'S1',ARTIFACT,'ci-frozen-S1-context',counter,
                                   after_commit=lambda:os._exit(81))
    if mode=='recover':
        result=reconcile_unknown(JOURNAL,ARTIFACT)
        try:
            _perform_transition(Path('.'),JOURNAL,'S1',ARTIFACT,'ci-frozen-S1-context',counter)
        except Stop as exc:
            result['retry']={'state':'DENIED_BEFORE_EFFECT','reason':str(exc)}
        else:raise AssertionError('blind retry accepted')
        return result
    if mode=='drain':
        first=service.consume();second=service.consume();publication=service.publish()
        connection=service.rabbit()
        try:
            ready=connection.channel().queue_declare(queue='billing',passive=True).method.message_count
        finally:connection.close()
        return {'first':first,'second':second,'publish':publication,'queue_ready':ready}
    if mode=='readonly':
        result=service.snapshot()
        with service.db('source',readonly=True) as db:
            result['instrumentation']={'transition_invocations':db.execute('SELECT n FROM ci_transition_calls').fetchone()['n'],
                'backfill_updates':db.execute('SELECT order_id FROM ci_backfill_updates ORDER BY order_id').fetchall()}
        return result
    raise ValueError('unsupported fixture mode')

if __name__=='__main__':print(json.dumps(main(sys.argv[1]),default=json_exact,sort_keys=True))
