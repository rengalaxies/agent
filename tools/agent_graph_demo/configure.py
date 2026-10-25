"""Create local operator config using an interactive password; never print its value."""

import argparse
import getpass
import hashlib
from pathlib import Path

from agent_graph_demo.contracts import DemoSettings
from agent_graph_demo.graph_cli import GraphCLI
from agent_graph_demo.snapshots import atomic_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, required=True)
    # Optional: by default the demo runs the core shipped with it (GraphCLI checks core_identity).
    p.add_argument("--core-root", type=Path)
    p.add_argument("--product-sha", required=True)
    args = p.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (directory / "auth.json").exists() or (directory / "web.json").exists():
        p.error("config already exists; update explicitly as operator")
    GraphCLI(args.core_root)  # None = the bundled core
    password = getpass.getpass("Пароль оператора (не сохраняется в открытом виде): ")
    if len(password) < 16:
        p.error("use at least 16 characters")
    atomic_json(
        directory / "auth.json",
        {
            "users": [
                {
                    "subject": "operator",
                    "role": "operator",
                    "password_sha256": hashlib.sha256(password.encode()).hexdigest(),
                    "allowed_session_ids": [],
                }
            ]
        },
    )
    (directory / "auth.json").chmod(0o600)
    settings = DemoSettings(
        state_root=directory / "state",
        core_root=args.core_root.resolve() if args.core_root else None,
        auth_config_path=directory / "auth.json",
        runtime_registry_path=directory / "runtime/active.json",
        product_sha=args.product_sha,
    )
    atomic_json(directory / "web.json", settings.model_dump(mode="json"))
    print("Config created. Username: operator. No runtime has been started.")


if __name__ == "__main__":
    main()
