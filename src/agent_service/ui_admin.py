"""Local OS-operator account lifecycle. Passwords are never CLI arguments."""
import argparse
import getpass
import sqlite3
from types import SimpleNamespace

from agent_graph.contracts import Policy
from .config import ServiceConfig, _document
from .ui_auth import AuthStore, UISettings
from .ui_scope import scope_for_config, validate_private_locations


def main(argv=None):
    parser=argparse.ArgumentParser(prog='agent_service.ui_admin')
    parser.add_argument('--config',required=True)
    parser.add_argument('--ui-config',required=True)
    parser.add_argument('--username',required=True)
    parser.add_argument('--role',choices=['reviewer','operator'])
    parser.add_argument('action',choices=['create-user','set-password','set-role','disable-user','enable-user','revoke-sessions','approve-scope'])
    args=parser.parse_args(argv)
    try:
        if args.action in ('create-user','set-role') and args.role is None:raise ValueError('role_required')
        config=ServiceConfig.load(args.config);settings=UISettings.load(args.ui_config)
        scope=scope_for_config(config)
        policy=Policy.model_validate(_document(config.core.policy_path))
        validate_private_locations(settings,SimpleNamespace(analyzer=SimpleNamespace(policy=policy),
            store=SimpleNamespace(path=config.state_path)),args.ui_config)
        auth=AuthStore(settings.database,create=args.action=='create-user')
        if args.action in ('create-user','set-password'):
            password=getpass.getpass('Новый пароль: ')
            if password!=getpass.getpass('Повтори пароль: '):raise ValueError('password_mismatch')
            if args.action=='create-user':auth.create_user(args.username,password,args.role,scope.identity)
            else:auth.change_user(args.username,password=password)
        elif args.action=='set-role':auth.change_user(args.username,role=args.role)
        elif args.action=='approve-scope':auth.change_user(args.username,scope=scope.identity)
        elif args.action in ('disable-user','enable-user'):
            auth.change_user(args.username,disabled=args.action=='disable-user')
        else:auth.revoke_user(args.username)
    except (ValueError,TypeError,KeyError,OSError,sqlite3.Error):
        print('ui_operation_failed: проверь конфигурацию, права на файлы, параметры пользователя и совпадение паролей.')
        return 1
    print('ui_operation_complete: изменение сохранено; прежние сессии пользователя отозваны, если они существовали.')
    return 0


if __name__=='__main__':raise SystemExit(main())
