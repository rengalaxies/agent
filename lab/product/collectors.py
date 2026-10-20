"""Bounded read-only live catalogs, separately labelled static references.

RabbitMQ paths follow https://www.rabbitmq.com/docs/http-api-reference.
No messages are consumed and no management mutation endpoint is used.
"""
from __future__ import annotations
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone
import urllib.parse
import urllib.request
from lab.runtime.core import discover, digest, now, Stop


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise Stop('RabbitMQ redirect refused')


def _rows(connection, query):
    cursor = connection.execute(query)
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def postgres_snapshot(dsn):
    import psycopg
    with psycopg.connect(dsn, connect_timeout=10) as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        connection.execute("SET LOCAL statement_timeout = '10s'")
        roles = _rows(connection, 'SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user')
        if any(roles[0].values()):
            raise Stop('PostgreSQL collector requires unprivileged read role')
        schemas = _rows(connection, "SELECT nspname AS name FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema' ORDER BY 1")
        columns = _rows(connection, """SELECT n.nspname AS schema, c.relname AS object, c.relkind AS kind,
            a.attname AS column, pg_catalog.format_type(a.atttypid,a.atttypmod) AS type, a.attnotnull AS not_null
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_attribute a ON a.attrelid=c.oid
            WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema'
            AND c.relkind IN ('r','v','m','p') AND a.attnum>0 AND NOT a.attisdropped
            ORDER BY n.nspname,c.relname,a.attnum""")
        views = _rows(connection, """SELECT n.nspname AS schema,c.relname AS name,pg_get_viewdef(c.oid,true) AS definition
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind IN ('v','m')
            AND n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' ORDER BY 1,2""")
        dependencies = _rows(connection, """SELECT DISTINCT vn.nspname AS view_schema,v.relname AS view_name,
            tn.nspname AS target_schema,t.relname AS target_name
            FROM pg_rewrite r JOIN pg_class v ON v.oid=r.ev_class
            JOIN pg_namespace vn ON vn.oid=v.relnamespace JOIN pg_depend d ON d.objid=r.oid AND d.classid='pg_rewrite'::regclass
            JOIN pg_class t ON t.oid=d.refobjid AND d.refclassid='pg_class'::regclass
            JOIN pg_namespace tn ON tn.oid=t.relnamespace
            WHERE v.relkind IN ('v','m') AND v.oid<>t.oid AND vn.nspname NOT LIKE 'pg_%'
            AND vn.nspname<>'information_schema' ORDER BY 1,2,3,4""")
    return {'schemas': schemas, 'columns': columns, 'views': views, 'dependencies': dependencies,
            'method': 'pg_catalog read-only transaction', 'confirmation': 'LIVE_CATALOG_CONFIGURATION',
            'limitations': 'One source database only; catalog dependencies are not evidence of executed queries.'}


def rabbit_snapshot(base_url, username, password):
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'','/'}:
        raise Stop('RabbitMQ endpoint must be a bare HTTP(S) origin without credentials')
    auth = base64.b64encode((username + ':' + password).encode()).decode()
    opener = urllib.request.build_opener(NoRedirect())
    def get(path):
        request = urllib.request.Request(base_url.rstrip('/') + path, headers={'Authorization':'Basic '+auth,'Accept':'application/json'}, method='GET')
        with opener.open(request, timeout=10) as response:
            body = response.read(2_000_001)
        if len(body)>2_000_000:
            raise Stop('RabbitMQ catalog response exceeds bounded profile')
        return json.loads(body)
    who = get('/api/whoami')
    tags = who.get('tags', [])
    if isinstance(tags,str):
        tags = tags.split(',')
    if 'monitoring' not in tags or any(tag in tags for tag in ('administrator','policymaker')):
        raise Stop('RabbitMQ collector requires monitoring-only account')
    if who.get('name') != username:
        raise Stop('RabbitMQ authenticated identity differs')
    # Monitoring users cannot query permissions. A trusted CI control-plane observer
    # supplies a bounded, fresh attestation; this is not collector self-verification.
    attestation_path = os.environ.get('RABBIT_PERMISSION_ATTESTATION_FILE')
    if not attestation_path:
        raise Stop('RabbitMQ permission attestation missing')
    permissions = json.loads(Path(attestation_path).read_text())
    if permissions.get('username') != username or permissions.get('vhost') != '/' or any(
            permissions.get(kind) != '^$' for kind in ('configure','write','read')):
        raise Stop('RabbitMQ attestation requires empty configure/write/read permissions')
    observed_at = datetime.fromisoformat(permissions['collected_at']).timestamp()
    age = datetime.now(timezone.utc).timestamp() - observed_at
    if age < -30 or age > 900 or permissions.get('source') != 'trusted CI rabbitmqctl list_user_permissions':
        raise Stop('RabbitMQ permission attestation stale or unqualified')
    overview = get('/api/overview')
    if not permissions.get('broker_identity') or permissions['broker_identity'] != overview.get('node'):
        raise Stop('RabbitMQ permission attestation broker identity differs')
    fields = {'exchanges':('name','vhost','type','durable','auto_delete','internal','arguments'),
              'queues':('name','vhost','durable','auto_delete','exclusive','arguments'),
              'bindings':('source','vhost','destination','destination_type','routing_key','arguments')}
    result = {}
    for kind, keys in fields.items():
        rows = get('/api/'+kind+'/%2F?disable_stats=true')
        if not isinstance(rows,list):
            raise Stop('RabbitMQ catalog must be an unpaginated bounded list')
        result[kind] = sorted([{key:row[key] for key in keys if key in row} for row in rows], key=lambda x:json.dumps(x,sort_keys=True))
    return {**result, 'method':'RabbitMQ management HTTP GET; vhost /', 'confirmation':'LIVE_BROKER_CONFIGURATION',
            'permissions_verified': 'TRUSTED_CI_ATTESTATION',
            'permission_attestation': {key:permissions[key] for key in ('source','collected_at','broker_identity','vhost','configure','write','read')},
            'permission_attestation_digest':digest(permissions), 'limitations':'Bindings establish configuration, not observed message delivery; one vhost only.'}


def repository_snapshot(root):
    discovered = discover(root)
    # Keep exact source hashes and references, not source file content or environment values.
    evidence = [{key:value for key,value in row.items() if key != 'content'} for row in discovered['evidence']]
    extra = []
    for row in discovered['evidence']:
        if row['source_type']!='py':
            continue
        try:
            module = ast.parse(row['content'])
        except SyntaxError:
            continue
        for node in ast.walk(module):
            if not isinstance(node,ast.Call):
                continue
            method = getattr(node.func,'attr','')
            if method not in {'basic_get','basic_consume','basic_publish','queue_bind'}:
                continue
            for kw in node.keywords:
                if kw.arg not in {'queue','exchange','routing_key'}:
                    continue
                if isinstance(kw.value,ast.Constant) and isinstance(kw.value.value,str):
                    extra.append({'source_ref':kw.value.value,'target_ref':row['object_ref'], 'relation_type':'BROKER_CODE_REFERENCE',
                        'method':method+'.'+kw.arg,'line':node.lineno,'confirmation':'STATIC_LITERAL_REFERENCE',
                        'evidence_ids':[row['evidence_id']], 'coverage_note':'Literal AST reference only; dynamic routing keys unresolved.'})
    return {'evidence':evidence,'dependencies':discovered['dependencies']+extra,'snapshot_digest':discovered['snapshot_digest'],
            'coverage_gaps':discovered['coverage_gaps']}


def basis_digest(postgres, rabbitmq, repository, owners):
    """Hash semantic material only. Repeated collection alone never invalidates work."""
    return digest({'postgres':{k:postgres[k] for k in ('schemas','columns','views','dependencies')},
        'rabbitmq':{k:rabbitmq[k] for k in ('exchanges','queues','bindings')},
        'repository':repository['snapshot_digest'],'owners':owners})


def collect():
    required = ('SOURCE_READ_DSN','RABBIT_READ_URL','RABBIT_READ_USER','RABBIT_READ_PASSWORD')
    if any(not os.environ.get(name) for name in required):
        raise Stop('Live collection BLOCKED: read-only source credentials missing')
    root = Path(os.environ.get('LAB_REPO_ROOT',Path(__file__).resolve().parents[2])).resolve()
    try:
        pg = postgres_snapshot(os.environ['SOURCE_READ_DSN'])
        broker = rabbit_snapshot(*(os.environ[name] for name in required[1:]))
        repo = repository_snapshot(root)
        owners = json.loads((root/'lab/catalog/owners.json').read_text())
        commit = subprocess.run(['git','rev-parse','HEAD'],cwd=root,check=True,capture_output=True,text=True,timeout=10).stdout.strip()
    except Exception as exc:
        # DSNs, authorization and management URLs must never enter persisted job errors.
        raise Stop('Live collection BLOCKED: '+type(exc).__name__) from None
    at = now()
    edges = []
    def edge(source,target,kind,method,confirmation,limitations,**extra):
        edges.append({'source':source,'target':target,'source_kind':kind,'method':method,'confirmation':confirmation,
            'limitations':limitations,'collected_at':at,**extra})
    for dep in pg['dependencies']:
        edge('postgres:'+dep['target_schema']+'.'+dep['target_name'], 'postgres:'+dep['view_schema']+'.'+dep['view_name'],
            'pg_catalog','pg_rewrite + pg_depend','LIVE_CATALOG_CONFIGURATION',pg['limitations'])
    for binding in broker['bindings']:
        edge('rabbitmq:exchange:'+binding['source'],'rabbitmq:'+binding['destination_type']+':'+binding['destination'],
            'rabbitmq_management','GET /api/bindings/%2F','LIVE_BROKER_CONFIGURATION',broker['limitations'],routing_key=binding['routing_key'])
    for dep in repo['dependencies']:
        edge(dep['source_ref'],dep['target_ref'],'repository',dep.get('method',dep['relation_type']),dep['confirmation'],dep['coverage_note'],
             evidence_ids=dep.get('evidence_ids',[]),line=dep.get('line'),owner=dep.get('owner','UNKNOWN'))
    for binding in owners.get('bindings',[]):
        edge(binding['object_ref'],'team:'+binding['team_id'],'owner_catalog','lab/catalog/owners.json','DECLARED_OWNER',
            'Declared ownership only; no live directory verification.',freshness=binding.get('confirmed_at','UNKNOWN'))
    return {'basis_digest':basis_digest(pg,broker,repo,owners),'collected_at':at,'mode':'LIVE RUN','postgres':pg,
        'rabbitmq':broker,'repository':repo,'owners':owners,'edges':edges,'source_commit':commit,
        'coverage_gaps':repo['coverage_gaps']+['No telemetry collected. No proof of graph completeness.',
            'Only source PostgreSQL database and RabbitMQ vhost / collected.','Declared owners are not authenticated live ownership.']}
