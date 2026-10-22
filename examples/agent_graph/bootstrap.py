"""Create a disposable corpus and operator policy for the JSON CLI."""
import argparse
import json
from pathlib import Path
from fixture import create_fixture


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--directory", required=True)
    args = p.parse_args()
    directory = Path(args.directory).absolute()
    policy = create_fixture(directory)
    path = directory / "operator-policy.json"
    path.write_text(policy.model_dump_json(indent=2) + "\n")
    print(json.dumps(dict(policy=str(path), state=str(directory / "state"))))
