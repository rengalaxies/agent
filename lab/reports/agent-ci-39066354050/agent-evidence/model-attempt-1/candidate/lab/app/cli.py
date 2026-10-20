import argparse
import json
import sys
from . import service


def main():
    parser = argparse.ArgumentParser(description='Isolated money-contract laboratory')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('init','bootstrap','analytics','snapshot'):
        sub.add_parser(name)
    create = sub.add_parser('create-order')
    create.add_argument('--order-id', required=True)
    create.add_argument('--amount-rub', required=True)
    create.add_argument('--currency', default='RUB')
    create.add_argument('--fault', choices=['after_order_commit'])
    create.add_argument('--naive', action='store_true', help='Deliberately corrupt fixture; isolated test database only')
    for name, point in [('publish','after_publish_confirm'),('consume','after_billing_commit')]:
        command = sub.add_parser(name)
        command.add_argument('--fault', choices=[point])
        command.add_argument('--limit', type=int, default=1000)
    transition = sub.add_parser('transition')
    transition.add_argument('--target', required=True, choices=['S1','S2','S3','S4','S5'])
    args = vars(parser.parse_args())
    command = args.pop('command').replace('-', '_')
    try:
        if command == 'bootstrap':
            from .bootstrap import bootstrap
            result = bootstrap()
        else:
            result = getattr(service, 'initialize' if command == 'init' else command)(**args)
        print(json.dumps(result, default=str, sort_keys=True))
    except service.LabError as error:
        print(json.dumps({'status':'BLOCKED', 'code':error.code, 'message':str(error)}))
        return 2
    except Exception as error:
        # Connection strings and server exception details may include secrets.
        print(json.dumps({'status':'ERROR','type':type(error).__name__}))
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
