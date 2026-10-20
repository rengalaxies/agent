"""Operator CLI for the single-node scoped registry; credentials come from env.

Example: python -m change_completion.control_cli --registry /private/control.db
--token-env CONTROL_TOKEN history --scope finance. Use --help for provisioning.
"""
import argparse
import json
import os
import sqlite3

from .control_plane import ControlPlane, run_worker_loop
from .run_cli import read_operator_file
from .verification import load_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', required=True)
    parser.add_argument('--token-env', default='CONTROL_TOKEN')
    commands = parser.add_subparsers(dest='command', required=True)
    init = commands.add_parser('init')
    init.add_argument('--actor', default='operator')
    recovery = commands.add_parser('recover-restored')
    recovery.add_argument('--actor', required=True)
    recovery.add_argument('--confirmed-authority', action='store_true')
    scope = commands.add_parser('scope')
    scope.add_argument('--id', required=True)
    scope.add_argument('--kind', required=True, choices=['organization', 'division', 'department'])
    scope.add_argument('--parent')
    identity = commands.add_parser('identity')
    identity.add_argument('--actor', required=True)
    identity.add_argument('--new-token-env', required=True)
    identity.add_argument('--expires-at', type=float, required=True, help='Unix UTC timestamp')
    grant = commands.add_parser('grant')
    grant.add_argument('--actor', required=True)
    grant.add_argument('--scope', required=True)
    grant.add_argument('--permissions', nargs='+', choices=['read', 'enqueue', 'work'], required=True)
    grant.add_argument('--expires-at', type=float, required=True)
    revoke = commands.add_parser('revoke')
    revoke.add_argument('--actor', required=True)
    register = commands.add_parser('register')
    register.add_argument('--scope', required=True)
    register.add_argument('--id', required=True)
    register.add_argument('--config', required=True, help='Operator-owned JSON with repository, transition, expectations, fixtures, trust, state, worker_actor')
    rebind = commands.add_parser('rebind-worker')
    rebind.add_argument('--binding', required=True)
    rebind.add_argument('--worker', required=True)
    rebind.add_argument('--confirmed-binding-review', action='store_true')
    enqueue = commands.add_parser('enqueue')
    enqueue.add_argument('--binding', required=True)
    enqueue.add_argument('--key', required=True)
    retry = commands.add_parser('retry')
    retry.add_argument('--task', required=True)
    retry.add_argument('--key', required=True)
    work = commands.add_parser('work-once')
    work.add_argument('--lease-seconds', type=int, default=120)
    loop = commands.add_parser('work-loop')
    loop.add_argument('--max-jobs', type=int, default=10)
    loop.add_argument('--max-seconds', type=float, default=60)
    loop.add_argument('--poll-seconds', type=float, default=1)
    history = commands.add_parser('history')
    history.add_argument('--scope', required=True)
    args = parser.parse_args(argv)
    try:
        plane = ControlPlane(args.registry)
        token = os.environ.get(args.token_env)
        result = None
        if args.command == 'init':
            plane.bootstrap(token, args.actor)
        elif args.command == 'recover-restored':
            plane.recover_restored(token, args.actor, confirmed_authority=args.confirmed_authority)
        elif args.command == 'scope':
            plane.add_scope(token, args.id, args.kind, args.parent)
        elif args.command == 'identity':
            plane.add_identity(token, os.environ.get(args.new_token_env), args.actor, args.expires_at)
        elif args.command == 'grant':
            plane.grant(token, args.actor, args.scope, args.permissions, args.expires_at)
        elif args.command == 'revoke':
            plane.revoke(token, args.actor)
        elif args.command == 'register':
            plane.register(token, args.scope, args.id, **load_json(read_operator_file(args.config)))
        elif args.command == 'rebind-worker':
            plane.rebind_worker(token, args.binding, args.worker, confirmed_binding_review=args.confirmed_binding_review)
        elif args.command == 'enqueue':
            result = plane.enqueue(token, args.binding, args.key)
        elif args.command == 'retry':
            result = plane.retry(token, args.task, args.key)
        elif args.command == 'work-once':
            result = plane.work_once(token, args.lease_seconds)
        elif args.command == 'work-loop':
            result = run_worker_loop(plane, token, max_jobs=args.max_jobs, max_seconds=args.max_seconds, poll_seconds=args.poll_seconds)
        else:
            result = plane.history(token, args.scope)
        print(json.dumps(result if result is not None else {'status': 'OK'}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, sqlite3.Error):
        print(json.dumps({'status': 'STOP', 'reason_codes': ['registry_input_or_authority_unavailable'], 'effects_authorized': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
