"""Controller-only initialization; never mount admin credentials in app/verifier."""
import os
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from .service import initialize, db


def bootstrap():
    admin = os.environ['ADMIN_DSN']
    users = [('lab_orders','ORDERS_PASSWORD'), ('lab_billing','BILLING_PASSWORD'), ('lab_verifier','VERIFIER_PASSWORD')]
    with psycopg.connect(admin, autocommit=True) as connection:
        for role, key in users:
            exists = connection.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone()
            if not exists:
                connection.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role), sql.Literal(os.environ[key])))
            # Never promote runtime roles to database administrators.
            connection.execute(sql.SQL('ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION').format(sql.Identifier(role)))
        for name, owner in [('lab_source','lab_orders'),('lab_billing','lab_billing')]:
            if not connection.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone():
                connection.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(owner)))
            connection.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(name)))
            connection.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}, lab_verifier').format(sql.Identifier(name), sql.Identifier(owner)))
    initialize()
    for kind, database in [('source','lab_source'),('billing','lab_billing')]:
        # PUBLIC CREATE removed explicitly for upgraded installations as well.
        with psycopg.connect(make_conninfo(admin, dbname=database)) as connection:
            connection.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        with db(kind) as connection:
            schemas = ['public','analytics'] if kind == 'source' else ['public']
            for schema in schemas:
                connection.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO lab_verifier').format(sql.Identifier(schema)))
                connection.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA {} TO lab_verifier').format(sql.Identifier(schema)))
                connection.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT ON TABLES TO lab_verifier').format(sql.Identifier(schema)))
    return {'status':'BOOTSTRAPPED'}
