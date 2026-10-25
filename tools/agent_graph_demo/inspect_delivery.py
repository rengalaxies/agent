"""Read-only image audit before authorized artifact export; no credentials or deploy."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile


def command(*args):
    return subprocess.check_output(args)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--image", required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    assert re.fullmatch(r"[a-f0-9]{40}", a.source_sha)
    image = json.loads(command("docker", "image", "inspect", a.image))[0]
    config = image["Config"]
    assert config["User"] == "10001:10001"
    assert config["Labels"]["agent-graph-demo.product"] == a.source_sha
    assert not config.get("Volumes")
    allowed_env = {"PATH", "LANG", "GPG_KEY", "PYTHON_VERSION", "PYTHON_SHA256",
                   "PYTHONPATH", "PYTHONDONTWRITEBYTECODE"}
    assert all(e.split("=", 1)[0] in allowed_env for e in config["Env"])
    paths = ["src/agent_graph", "src/agent_graph_demo", "examples/agent_graph_demo", "tools/agent_graph_demo",
             "constitutions/agent-service-v1.yaml", "infra/agent_graph_demo/requirements.lock"]
    files = command("git", "ls-tree", "-r", "--name-only", a.source_sha, "--", *paths).decode().splitlines()
    expected = {"app/" + f: hashlib.sha256(command("git", "show", a.source_sha + ":" + f)).hexdigest()
                for f in files}
    container = command("docker", "create", "--network", "none", a.image).decode().strip()
    try:
        with tarfile.open(fileobj=io.BytesIO(command("docker", "export", container))) as root:
            assert all(m.isfile() or m.isdir() for m in root
                       if m.name.removeprefix("./").startswith("app/")), "unexpected application link/device"
            actual = {m.name.removeprefix("./"): hashlib.sha256(root.extractfile(m).read()).hexdigest()
                      for m in root if m.isfile() and m.name.removeprefix("./").startswith("app/")}
            assert actual == expected, "application filesystem differs from allowlisted Git sources"
    finally:
        command("docker", "rm", container)
    forbidden = re.compile(r"(^|/)(?:\.git|\.ssh|\.env(?:\..*)?|auth\.json|web\.json|operator\.json|release\.env)(/|$)|\.sqlite3(?:-wal|-shm)?$")
    secret = re.compile(rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}")
    checked_layers = 0
    with tarfile.open(a.archive, "r:gz") as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        assert len(manifest) == 1
        assert hashlib.sha256(archive.extractfile(manifest[0]["Config"]).read()).hexdigest() == image["Id"].removeprefix("sha256:"), "archive does not contain inspected image"
        for layer in manifest[0]["Layers"]:
            with tarfile.open(fileobj=archive.extractfile(layer), mode="r|") as contents:
                for member in contents:
                    assert not forbidden.search(member.name), "credential/state filename in image layer"
                    if member.isfile() and member.size <= 2_000_000 and member.name.endswith((".py", ".json", ".txt", ".env", ".pem", ".key")):
                        assert not secret.search(contents.extractfile(member).read()), "credential pattern in image layer"
            checked_layers += 1
    a.output.write_text(json.dumps(dict(status="PASS", source_sha=a.source_sha, image_id=image["Id"],
        architecture=image["Architecture"], os=image["Os"], user=config["User"],
        environment_names=[e.split("=", 1)[0] for e in config["Env"]],
        app_files_sha256=actual, checked_layers=checked_layers,
        archive_sha256=hashlib.sha256(a.archive.read_bytes()).hexdigest(),
        checks=["exact allowlisted Git app files", "no extra application files", "no credential or state filenames in layers",
                "no credential patterns in bounded text files", "no runtime secret environment", "non-root default user"],
        limitations=["Static packaging audit, not a general vulnerability scan; trusted pinned Python base and hash-locked wheels"]), indent=2) + "\n")
    print("IMAGE_AUDIT_PASS " + image["Id"])


if __name__ == "__main__":
    main()
