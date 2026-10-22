"""Container-only fixed consumer launcher; imports trusted verified runtime source."""

import importlib
import json
import sys


def main():
    name = sys.argv[1]
    if name not in ("reporting", "billing", "health", "export"):
        return 2
    try:
        value = importlib.import_module(name + ".client").run()
        print(json.dumps({"result": value}, allow_nan=False))
        return 0
    except Exception:
        print(json.dumps({"status": "ERROR", "code": "consumer_execution_failed"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
