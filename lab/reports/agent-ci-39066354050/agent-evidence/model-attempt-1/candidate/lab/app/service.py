"""Real lab services. All writes are restricted to a dedicated Compose project.

No exactly-once transport claim: outbox may send twice, ledger effect is idempotent.
S6 legacy retirement is deliberately not implemented.
"""
import json
import os
import uuid
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

import pika
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

MAX_MINOR = 9223372036854775807
LOCK = 83017422
SQL = Path(__file__).resolve().parents[1] / 'sql'


class LabError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def db(kind='source', readonly=False):
    key = kind.upper() + ('_READ_DSN' if readonly else '_DSN')
    return psycopg.connect(os.environ[key], row_factory=dict_row)


def money(value, currency='RUB'):
    if currency != 'RUB':
        raise LabError('CURRENCY', 'Only RUB is authorized')
    if value is None or isinstance(value, (bool, float)):
        raise LabError('AMOUNT', 'Use an exact integer or decimal string')
    try:
        rub = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise LabError('AMOUNT', 'Invalid exact decimal') from None
    if not rub.is_finite() or rub < 0:
        raise LabError('AMOUNT', 'Nonnegative finite amount required')
    if rub > Decimal(MAX_MINOR) / 100 or len(rub.as_tuple().digits) > 256:
        raise LabError('AMOUNT', 'Amount outside exact supported range')
    with localcontext() as context:
        context.prec = 300
        minor = rub * 100
    if minor != minor.to_integral_value() or minor > MAX_MINOR:
        raise LabError('AMOUNT', 'Not representable as BIGINT minor units')
    if minor % 100:
        raise LabError('COMPATIBILITY', 'Active integer-ruble v1 cannot represent fractional rubles; S6 requires separate authorization')
    return int(minor)


def rabbit():
    parameters = pika.URLParameters(os.environ['RABBITMQ_URL'])
    parameters.heartbeat = 30
    parameters.blocked_connection_timeout = 30
    parameters.socket_timeout = 10
    parameters.connection_attempts = 15
    parameters.retry_delay = 2
    return pika.BlockingConnection(parameters)


def topology(channel, version=1, rare=False):
    channel.exchange_declare(exchange='orders.events', exchange_type='direct', durable=True)
    channel.queue_declare(queue='billing', durable=True)
    channel.queue_bind(queue='billing', exchange='orders.events', routing_key=f'order.created.v{version}')
    if rare:
        channel.queue_declare(queue='rare-audit', durable=True)
        channel.queue_bind(queue='rare-audit', exchange='orders.events', routing_key='order.created.v1')


def initialize():
    """Schema initialization only. Bootstrap creates isolated roles/databases separately."""
    for kind in ('source', 'billing'):
        with db(kind) as connection:
            connection.execute((SQL / f'{kind}.sql').read_text())
    connection = rabbit()
    try:
        with db() as source:
            state = source.execute('SELECT * FROM lab_state').fetchone()
        topology(connection.channel(), state['event_version'])
    finally:
        connection.close()
    return {'status': 'READY', 'state': state['current_state']}


def create_order(order_id, amount_rub, currency='RUB', fault=None, naive=False):
    minor = money(amount_rub, currency)
    if not isinstance(order_id, str) or not order_id or len(order_id) > 200:
        raise LabError('ORDER_ID', 'Nonempty order_id up to 200 characters required')
    with db() as source:
        source.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        state = source.execute('SELECT * FROM lab_state WHERE singleton').fetchone()
        if naive and state['current_state'] != 'S0':
            raise LabError('FIXTURE_SCOPE', 'Naive corruption fixture is only supported in isolated S0')
        if state['paused']:
            raise LabError('PAUSED', 'Ingress is stopped at the migration watermark')
        old = source.execute('SELECT * FROM orders WHERE order_id=%s', (order_id,)).fetchone()
        if old:
            if old['amount_rub'] * 100 != minor or old['currency'] != currency:
                raise LabError('IDEMPOTENCY_CONFLICT', 'Same order ID with different money')
            return {'order_id': order_id, 'created': False, 'amount_minor': minor}
        if state['current_state'] == 'S0':
            source.execute('INSERT INTO orders(order_id,amount_rub,currency) VALUES(%s,%s,%s)', (order_id, minor if naive else minor // 100, currency))
        else:
            source.execute('INSERT INTO orders(order_id,amount_rub,amount_minor,currency) VALUES(%s,%s,%s,%s)', (order_id, minor // 100, minor, currency))
        version = state['event_version']
        event = {'event_id': str(uuid.uuid4()), 'order_id': order_id, 'contract_version': version, 'currency': currency}
        event['amount' if version == 1 else 'amount_minor'] = minor if naive or version == 2 else minor // 100
        source.execute('INSERT INTO outbox(event_id,order_id,routing_key,payload) VALUES(%s,%s,%s,%s)', (event['event_id'], order_id, f'order.created.v{version}', Jsonb(event)))
    if fault == 'after_order_commit':
        raise LabError('INJECTED_AFTER_ORDER_COMMIT', 'Order and outbox committed; publisher has not run')
    return {'order_id': order_id, 'created': True, 'amount_minor': minor, 'event_id': event['event_id']}


def publish(fault=None, limit=1000):
    published = 0
    connection = rabbit()
    try:
        channel = connection.channel()
        channel.confirm_delivery()
        for _ in range(limit):
            with db() as source:
                row = source.execute('SELECT * FROM outbox WHERE published_at IS NULL ORDER BY seq FOR UPDATE SKIP LOCKED LIMIT 1').fetchone()
                if not row:
                    break
                channel.basic_publish(exchange='orders.events', routing_key=row['routing_key'], body=json.dumps(row['payload']).encode(), mandatory=True, properties=pika.BasicProperties(content_type='application/json', delivery_mode=2, message_id=str(row['event_id'])))
                if fault == 'after_publish_confirm':
                    raise LabError('INJECTED_AFTER_CONFIRM', 'Broker confirmed; outbox mark rolled back, retry can duplicate')
                source.execute('UPDATE outbox SET published_at=now(),attempts=attempts+1 WHERE seq=%s', (row['seq'],))
                published += 1
    finally:
        if connection.is_open:
            connection.close()
    return {'published': published}


def event_minor(event, version):
    if version not in (1, 2):
        raise LabError('MIXED_VERSION', 'Unknown Billing version')
    if not isinstance(event, dict) or type(event.get('contract_version')) is not int or event.get('currency') != 'RUB' or event.get('contract_version') not in (1, 2):
        raise LabError('CONTRACT', 'Unknown contract or currency')
    if version == 1 and event['contract_version'] != 1:
        raise LabError('MIXED_VERSION', 'Billing v1 cannot accept v2')
    field = 'amount' if event['contract_version'] == 1 else 'amount_minor'
    expected = {'event_id','order_id','contract_version','currency',field}
    if set(event) != expected or type(event.get(field)) is not int:
        raise LabError('CONTRACT', 'Exact event fields and integer amount required')
    try:
        uuid.UUID(event['event_id'])
    except (ValueError, TypeError, AttributeError):
        raise LabError('CONTRACT', 'Invalid event ID') from None
    if not isinstance(event['order_id'], str) or not event['order_id']:
        raise LabError('CONTRACT', 'Invalid order ID')
    minor = event[field] * (100 if field == 'amount' else 1)
    if minor < 0 or minor > MAX_MINOR or minor % 100:
        raise LabError('CONTRACT', 'Money outside active compatibility contract')
    return minor


def consume(fault=None, limit=1000, version=None):
    if version is None:
        with db('source', readonly=bool(os.environ.get('SOURCE_READ_DSN'))) as source:
            version = source.execute('SELECT billing_version FROM lab_state').fetchone()['billing_version']
    connection = rabbit()
    handled = 0
    duplicate = 0
    try:
        channel = connection.channel()
        channel.basic_qos(prefetch_count=1)
        for _ in range(limit):
            method, properties, body = channel.basic_get(queue='billing', auto_ack=False)
            if method is None:
                break
            # Invalid messages remain unacked and return to queue on disconnect: visible safe stop.
            event = json.loads(body)
            minor = event_minor(event, version)
            with db('billing') as billing:
                billing.execute('INSERT INTO ledger(order_id,amount_minor,currency) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (event['order_id'], minor, event['currency']))
                row = billing.execute('SELECT * FROM ledger WHERE order_id=%s FOR UPDATE', (event['order_id'],)).fetchone()
                if row['amount_minor'] != minor or row['currency'] != event['currency']:
                    raise LabError('IDEMPOTENCY_CONFLICT', 'A duplicate order carries different money')
                existing = billing.execute('SELECT order_id FROM processed_events WHERE event_id=%s', (event['event_id'],)).fetchone()
                if existing and existing['order_id'] != event['order_id']:
                    raise LabError('IDEMPOTENCY_CONFLICT', 'Event ID reused across orders')
                inserted = billing.execute('INSERT INTO processed_events(event_id,order_id) VALUES(%s,%s) ON CONFLICT DO NOTHING RETURNING event_id', (event['event_id'], event['order_id'])).fetchone()
                confirmed = billing.execute('SELECT order_id FROM processed_events WHERE event_id=%s', (event['event_id'],)).fetchone()
                if confirmed['order_id'] != event['order_id']:
                    raise LabError('IDEMPOTENCY_CONFLICT', 'Concurrent event ID reuse across orders')
                duplicate += int(inserted is None)
            if fault == 'after_billing_commit':
                raise LabError('INJECTED_AFTER_BILLING_COMMIT', 'Ledger committed; ack omitted; restart redelivers')
            channel.basic_ack(method.delivery_tag)
            handled += 1
    finally:
        if connection.is_open:
            connection.close()
    return {'handled': handled, 'duplicate_events': duplicate}


def analytics():
    with db('source', readonly=bool(os.environ.get('SOURCE_READ_DSN'))) as source:
        version = source.execute('SELECT analytics_version FROM lab_state').fetchone()['analytics_version']
        query = 'SELECT count(*) AS orders, coalesce(sum(amount_rub::numeric * 100),0) AS amount_minor FROM analytics.orders_v1' if version == 1 else 'SELECT count(*) AS orders,coalesce(sum(amount_minor::numeric),0) AS amount_minor FROM analytics.orders_v2'
        result = source.execute(query).fetchone()
    return {**result, 'amount_minor': str(result['amount_minor']), 'version': version}


def snapshot():
    result = {}
    for kind, tables in [('source', ['lab_state', 'orders', 'outbox', 'transition_log']), ('billing', ['ledger', 'processed_events'])]:
        with db(kind, readonly=bool(os.environ.get(kind.upper()+'_READ_DSN'))) as connection:
            result[kind] = {table: connection.execute(f'SELECT * FROM {table}').fetchall() for table in tables}
    return result


def transition(target):
    if target not in ['S1', 'S2', 'S3', 'S4', 'S5']:
        raise LabError('SCOPE', 'Only S1 through S5 authorized by this implementation')
    with db() as source:
        source.execute('SELECT pg_advisory_lock(%s)', (LOCK,))
        source.commit()
        try:
            state = source.execute('SELECT * FROM lab_state WHERE singleton').fetchone()
            source.commit()
            if source.execute('SELECT 1 FROM transition_log WHERE target=%s', (target,)).fetchone():
                return {'state': state['current_state'], 'replayed': True}
            if int(target[1:]) != int(state['current_state'][1:]) + 1:
                raise LabError('TRANSITION_ORDER', f"Cannot move {state['current_state']} to {target}")
            if target == 'S1':
                source.execute(Path(os.environ.get('LAB_EXPAND_SQL', str(SQL/'expand.sql'))).read_text())
                if source.execute('SELECT count(*) n FROM orders WHERE amount_minor IS DISTINCT FROM amount_rub*100').fetchone()['n']:
                    raise LabError('BACKFILL', 'Candidate changes normalized business amount')
            elif target == 'S2':
                source.execute('UPDATE lab_state SET billing_version=2')
            elif target == 'S3':
                source.execute('CREATE OR REPLACE VIEW analytics.orders_v2 AS SELECT order_id,amount_minor,currency FROM orders')
                source.execute('GRANT SELECT ON analytics.orders_v2 TO lab_verifier')
                source.execute('UPDATE lab_state SET analytics_version=2')
            elif target == 'S4':
                # Persist pause before non-transactional broker work; restart observes it.
                source.execute('UPDATE lab_state SET paused=true, watermark=(SELECT coalesce(max(seq),0) FROM orders)')
                source.commit()
                while publish()['published']:
                    pass
                while consume()['handled']:
                    pass
                connection = rabbit()
                try:
                    channel = connection.channel()
                    stats = channel.queue_declare(queue='billing', durable=True, passive=True)
                    if stats.method.message_count:
                        raise LabError('DRAIN', 'v1 queue not empty')
                    topology(channel, 2)
                    # A mandatory probe exercises new binding without creating an order.
                    probe = str(uuid.uuid4())
                    channel.confirm_delivery()
                    channel.basic_publish(exchange='orders.events', routing_key='order.created.v2', body=json.dumps({'probe': probe}), mandatory=True, properties=pika.BasicProperties(delivery_mode=2))
                    method, _, body = channel.basic_get(queue='billing', auto_ack=False)
                    if method is None or json.loads(body) != {'probe': probe}:
                        raise LabError('ROUTING_PROBE', 'New route did not deliver expected probe')
                    channel.basic_ack(method.delivery_tag)
                    channel.queue_unbind(queue='billing', exchange='orders.events', routing_key='order.created.v1')
                finally:
                    if connection.is_open:
                        connection.close()
                source.execute('UPDATE lab_state SET event_version=2,paused=false')
            elif target == 'S5':
                source.execute('UPDATE lab_state SET paused=true,watermark=(SELECT coalesce(max(seq),0) FROM orders)')
                source.commit()
                while publish()['published']:
                    pass
                while consume()['handled']:
                    pass
                expected = source.execute('SELECT order_id,amount_minor,currency FROM orders ORDER BY order_id').fetchall()
                with db('billing', readonly=bool(os.environ.get('BILLING_READ_DSN'))) as billing:
                    actual = billing.execute('SELECT order_id,amount_minor,currency FROM ledger ORDER BY order_id').fetchall()
                if expected != actual:
                    raise LabError('RECONCILIATION', 'Missing, extra or incorrect Billing records')
                if sum(row['amount_minor'] for row in expected) != int(analytics()['amount_minor']):
                    raise LabError('ANALYTICS', 'Analytical total mismatch')
                source.execute('UPDATE lab_state SET paused=false')
            source.execute('UPDATE lab_state SET current_state=%s,updated_at=now()', (target,))
            source.execute('INSERT INTO transition_log(target,detail) VALUES(%s,%s)', (target, Jsonb({'previous': state['current_state'], 'legacy_retired': False})))
            source.commit()
            return {'state': target, 'replayed': False}
        except Exception:
            source.rollback()
            raise
        finally:
            source.execute('SELECT pg_advisory_unlock(%s)', (LOCK,))
            source.commit()
