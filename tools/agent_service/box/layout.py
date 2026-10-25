"""Where an installation lives. Standard library only (the bootstrap uses it).

Release files and durable state are kept apart:

    /opt/agent-service/releases/<name>/   immutable verified releases, each with its own venv
    /etc/agent-service/box.yaml           the owner's single configuration file
    /etc/agent-service/secrets.env        secret values (root, 0600), read by systemd
    /etc/agent-service/generated/<name>/  service.json, policy.json of each release (derived, never hand-edited)
    /var/lib/agent-service/               service state: queue, graph, Git mirrors (service user)
    /var/lib/agent-service-box/           installer journal, reports, lock (root)
    /var/backups/agent-service/           verified state backups (root)

``prefix`` moves the whole tree for tests and for the development supervisor.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys

SERVICE_USER = "agent-service"
UNIT = "agent-service.service"
SYNC_UNIT = "agent-service-sync"
BACKUP_UNIT = "agent-service-backup"


@dataclass(frozen=True)
class Layout:
    prefix: Path

    @classmethod
    def at(cls, prefix: str | os.PathLike | None) -> "Layout":
        return cls(Path(prefix or "/").resolve())

    def _p(self, *parts: str) -> Path:
        return self.prefix.joinpath(*parts)

    @property
    def system(self) -> bool:
        return self.prefix == Path("/").resolve()

    @property
    def opt(self) -> Path:
        return self._p("opt", "agent-service")

    @property
    def releases(self) -> Path:
        return self.opt / "releases"

    @property
    def etc(self) -> Path:
        return self._p("etc", "agent-service")

    @property
    def config(self) -> Path:
        return self.etc / "box.yaml"

    @property
    def secrets(self) -> Path:
        return self.etc / "secrets.env"

    @property
    def generated(self) -> Path:
        return self.etc / "generated"

    @property
    def state(self) -> Path:
        return self._p("var", "lib", "agent-service")

    @property
    def mirrors(self) -> Path:
        return self.state / "mirrors"

    @property
    def run(self) -> Path:
        return self.state / "run"

    @property
    def box(self) -> Path:
        return self._p("var", "lib", "agent-service-box")

    @property
    def journal(self) -> Path:
        return self.box / "box.json"

    @property
    def reports(self) -> Path:
        return self.box / "reports"

    @property
    def backups(self) -> Path:
        return self._p("var", "backups", "agent-service")

    @property
    def units(self) -> Path:
        return self._p("etc", "systemd", "system")

    @property
    def wrapper(self) -> Path:
        return self._p("usr", "local", "sbin", "agent-service-box")

    def release(self, name: str) -> Path:
        return self.releases / name

    def bindings(self, name: str) -> Path:
        """Configuration a release generated for itself: its code, constitution and release identity together."""
        return self.generated / name


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def running_in(release: Path) -> bool:
    try:
        return Path(sys.prefix).resolve() == (release / "venv").resolve()
    except OSError:
        return False
