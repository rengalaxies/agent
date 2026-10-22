"""Start the demo only from an operator-owned configuration outside analyzed roots."""

import argparse
import json
from pathlib import Path

import uvicorn

from .api import create_app
from .contracts import DemoSettings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    settings = DemoSettings.model_validate(json.loads(args.config.read_text()))
    uvicorn.run(
        create_app(settings), host="127.0.0.1", port=18081, workers=1, access_log=False
    )


if __name__ == "__main__":
    main()
