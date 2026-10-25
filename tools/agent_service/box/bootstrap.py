#!/usr/bin/env python3
"""agent-service installer entry. The release ships this file as ``<release>/box``.

Run it with the host Python from an extracted release:

    sudo ./agent-service-<version>-g<sha>-<platform>/box install --config box.yaml

Standard library only. It verifies every file of this release against its
manifest, stages the release under /opt/agent-service/releases/<name> with
its own venv (hash-locked wheels unpacked, no pip, no network) and runs the
installer inside that venv. Inside the venv it only hands over to the CLI.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
BOX = Path("app") / "tools" / "agent_service" / "box"


def _module(name: str, root: Path):
    """Load a sibling stdlib-only module by path: a stray ``tools`` package on the host cannot shadow it."""
    path = root / BOX / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"agent_service_box_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _prefix(argv: list[str]) -> str | None:
    for i, arg in enumerate(argv):
        if arg == "--prefix" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--prefix="):
            return arg.split("=", 1)[1]
    return os.environ.get("AGENT_SERVICE_BOX_PREFIX")


def _host_python(version: str) -> str:
    if "%d.%d" % sys.version_info[:2] == version:
        return sys.executable
    found = shutil.which(f"python{version}")
    if not found:
        raise SystemExit(f"Нужен Python {version} (python{version} не найден). На Ubuntu 24.04 он установлен "
                         f"по умолчанию как python3.")
    return found


def _site_packages(python: Path) -> Path:
    out = subprocess.run([str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                         stdout=subprocess.PIPE, check=True, text=True)
    return Path(out.stdout.strip())


def _readonly(root: Path):
    if os.name == "nt":
        return
    for dirpath, dirnames, filenames in os.walk(root):
        os.chmod(dirpath, 0o755)
        for f in filenames:
            p = Path(dirpath) / f
            if not p.is_symlink():
                os.chmod(p, 0o755 if p.stat().st_mode & 0o111 else 0o644)


def stage(source: Path, releases: Path, release, layout) -> Path:
    """Copy a verified release into ``releases/<name>`` with its own venv. Idempotent."""
    manifest, manifest_sha = release.verify_tree(source)
    final = releases / manifest["name"]
    marker = final / ".staged.json"
    if marker.is_file():
        try:
            staged = json.loads(marker.read_text(encoding="utf-8"))
            release.verify_tree(final)
            if staged.get("manifest_sha256") == manifest_sha and layout.venv_python(final / "venv").is_file():
                return final
        except (ValueError, release.ReleaseError):
            pass
        broken = releases / f".broken-{manifest['name']}-{int(time.time())}"
        final.rename(broken)  # keep it for diagnosis; a verified copy replaces it
    releases.mkdir(parents=True, exist_ok=True)
    tmp = releases / f".staging-{manifest['name']}-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    for name in ("app", "wheels"):
        shutil.copytree(source / name, tmp / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(source / "manifest.json", tmp / "manifest.json")
    shutil.copy2(source / "box", tmp / "box")
    release.verify_tree(tmp)
    python = _host_python(manifest["python"])
    subprocess.run([python, "-m", "venv", "--without-pip", str(tmp / "venv")], check=True)
    venv_python = layout.venv_python(tmp / "venv")
    wheels = [tmp / "wheels" / w for w in sorted(manifest["dependencies"]["wheels"])]
    installed = release.install_wheels(wheels, _site_packages(venv_python))
    check = subprocess.run([str(venv_python), "-I", "-B", "-c",
                            "import pydantic, yaml, fastapi, uvicorn, cryptography; print('ok')"],
                           stdout=subprocess.PIPE, text=True)
    if check.returncode != 0 or check.stdout.strip() != "ok":
        raise SystemExit("Зависимости релиза не импортируются в его venv: релиз не подходит этой ОС/Python.")
    (tmp / ".staged.json").write_text(json.dumps({
        "manifest_sha256": manifest_sha, "release_id": manifest["release_id"], "wheels": installed,
        "python": subprocess.run([str(venv_python), "-I", "-c", "import sys; print(sys.version.split()[0])"],
                                 stdout=subprocess.PIPE, text=True).stdout.strip(),
        "staged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=2) + "\n")
    _readonly(tmp)
    tmp.rename(final)
    return final


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    layout = _module("layout", HERE)
    if layout.running_in(HERE):
        sys.path[:0] = [str(HERE / "app" / "src"), str(HERE / "app")]
        from tools.agent_service.box.cli import main as cli

        return cli(argv, release_dir=HERE)
    release = _module("release", HERE)
    if argv[:1] in (["-h"], ["--help"], []):
        print(__doc__)
        print("Команды: plan, install, update, status, doctor, backup, backups, restore, rollback, sync-mirrors")
        return 0
    where = layout.Layout.at(_prefix(argv))
    if where.system and not layout.is_root():
        raise SystemExit("Запустите от root (sudo): установка создаёт пользователя сервиса и unit systemd.")
    try:
        final = stage(HERE, where.releases, release, layout)
    except release.ReleaseError as exc:
        print(f"Релиз отклонён: {exc.code} {exc.detail}".strip(), file=sys.stderr)
        return 1
    python = layout.venv_python(final / "venv")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    return subprocess.run([str(python), "-I", "-B", str(final / "box"), *argv], env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
