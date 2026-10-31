"""Who keeps the service process running.

``systemd`` is the production path on the Linux VM: one unit per
installation, restart on failure, the service user, a read-only system and
secrets from an EnvironmentFile that only root can read.

``process`` exists for development machines and tests without systemd
(including Windows): one detached process tracked by a PID file. It has no
restart-on-failure and no timers; ``box status`` names it as not for
production.
"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import time

from .config import write_bytes
from .layout import BACKUP_UNIT, SERVICE_USER, SYNC_UNIT, UNIT, Layout, venv_python

HARDENING = """NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
UMask=0077"""


def service_command(layout: Layout, release: Path, host: str, port: int, manager: Path | None = None) -> list[str]:
    if manager:
        return [str(venv_python(manager / "venv")), "-I", "-B", str(manager / "app/tools/agent_service/box/guard.py"),
                "--target", str(release), "--config", str(layout.bindings(release.name) / "service.json"),
                "--run", str(layout.run), "--host", host, "--port", str(port)]
    return [str(venv_python(release / "venv")), "-I", "-B", str(release / "app/tools/agent_service/box/launch.py"),
            "--config", str(layout.bindings(release.name) / "service.json"), "--run", str(layout.run),
            "--host", host, "--port", str(port)]


def box_command(layout: Layout, release: Path, *args: str) -> list[str]:
    return [str(venv_python(release / "venv")), "-I", "-B", str(release / "box"), *args]


class Systemd:
    name = "systemd"
    production = True

    def __init__(self, layout: Layout):
        self.layout = layout

    @staticmethod
    def available() -> bool:
        return Path("/run/systemd/system").is_dir()

    def _ctl(self, *args, check=True) -> str:
        out = subprocess.run(["systemctl", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             timeout=300)
        if check and out.returncode:
            raise RuntimeError(f"systemctl {' '.join(args)} failed: {out.stderr.strip()[:200]}")
        return out.stdout.strip()

    def units(self, release: Path, host: str, port: int, *, sync_seconds: int, daily_backup: bool) -> dict[str, str]:
        L = self.layout
        command = " ".join(service_command(L, release, host, port, getattr(self, "manager", None)))
        units = {UNIT: f"""[Unit]
Description=agent-service ({release.name})
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User={SERVICE_USER}
Group={SERVICE_USER}
EnvironmentFile={L.secrets}
Environment=PYTHONDONTWRITEBYTECODE=1
WorkingDirectory={L.state}
ExecStart={command}
Restart=on-failure
RestartSec=5
TimeoutStopSec=45
ReadWritePaths={L.state}
{HARDENING}

[Install]
WantedBy=multi-user.target
""",
                 f"{SYNC_UNIT}.service": f"""[Unit]
Description=agent-service Git mirror sync
After=network-online.target

[Service]
Type=oneshot
User={SERVICE_USER}
Group={SERVICE_USER}
EnvironmentFile={L.secrets}
WorkingDirectory={L.state}
ExecStart={" ".join(box_command(L, release, "sync-mirrors"))}
TimeoutStartSec=900
ReadWritePaths={L.state}
{HARDENING}
""",
                 f"{SYNC_UNIT}.timer": f"""[Unit]
Description=agent-service Git mirror sync every {sync_seconds}s

[Timer]
OnBootSec=60
OnUnitInactiveSec={sync_seconds}
AccuracySec=5

[Install]
WantedBy=timers.target
"""}
        if daily_backup:
            units[f"{BACKUP_UNIT}.service"] = f"""[Unit]
Description=agent-service daily state backup

[Service]
Type=oneshot
ExecStart={" ".join(box_command(L, release, "backup", "--label", "daily"))}
"""
            units[f"{BACKUP_UNIT}.timer"] = """[Unit]
Description=agent-service daily state backup

[Timer]
OnCalendar=daily
RandomizedDelaySec=1800
Persistent=true

[Install]
WantedBy=timers.target
"""
        return units

    def configure(self, release: Path, host: str, port: int, *, sync_seconds: int, daily_backup: bool) -> bool:
        units = self.units(release, host, port, sync_seconds=sync_seconds, daily_backup=daily_backup)
        changed = False
        for name, text in units.items():
            changed |= write_bytes(self.layout.units / name, text.encode(), 0o644)
        if not daily_backup and (self.layout.units / f"{BACKUP_UNIT}.timer").exists():
            self._ctl("disable", "--now", f"{BACKUP_UNIT}.timer", check=False)
            for suffix in (".timer", ".service"):
                (self.layout.units / f"{BACKUP_UNIT}{suffix}").unlink()
            changed = True
        if changed:
            self._ctl("daemon-reload")
        timers = [f"{SYNC_UNIT}.timer"] + ([f"{BACKUP_UNIT}.timer"] if daily_backup else [])
        self._ctl("enable", UNIT, *timers)
        self._ctl("start", *timers)
        return changed

    def start(self):
        self._ctl("start", UNIT)

    def restart(self):
        self._ctl("restart", UNIT)

    def stop(self):
        self._ctl("stop", UNIT, check=False)

    def pid(self) -> int | None:
        value = self._ctl("show", "-p", "MainPID", "--value", UNIT, check=False)
        return int(value) if value.isdigit() and int(value) > 0 else None

    def active(self) -> bool:
        return self._ctl("is-active", UNIT, check=False) == "active"

    def run_sync(self):
        self._ctl("start", f"{SYNC_UNIT}.service")


class Process:
    name = "process"
    production = False

    def __init__(self, layout: Layout):
        self.layout = layout
        self.pidfile = layout.run / "service.pid"
        self.spec = layout.box / "process.cmd"

    def configure(self, release: Path, host: str, port: int, *, sync_seconds: int, daily_backup: bool) -> bool:
        command = "\0".join(service_command(self.layout, release, host, port, getattr(self, "manager", None)))
        return write_bytes(self.spec, command.encode(), 0o600)

    def _env(self) -> dict:
        from .config import read_secrets

        env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG", "HOME",
                                                             "USERPROFILE")}
        env.update(read_secrets(self.layout.secrets))
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    def start(self):
        if self.active():
            return
        command = self.spec.read_bytes().decode().split("\0")
        self.layout.run.mkdir(parents=True, exist_ok=True)
        log = open(self.layout.run / "service.log", "ab")
        kwargs = dict(stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=self._env(),
                      cwd=str(self.layout.state), close_fds=True)
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(command, **kwargs)
        log.close()
        write_bytes(self.pidfile, str(proc.pid).encode(), 0o600)

    def stop(self):
        pid = self.pid()
        if pid is None:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        deadline = time.time() + 30
        while _alive(pid) and time.time() < deadline:
            time.sleep(0.2)
        if _alive(pid) and os.name != "nt":
            os.kill(pid, signal.SIGKILL)
        self.pidfile.unlink(missing_ok=True)

    def restart(self):
        self.stop()
        self.start()

    def pid(self) -> int | None:
        try:
            pid = int(self.pidfile.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return pid if _alive(pid) else None

    def active(self) -> bool:
        return self.pid() is not None



def _alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # a zombie child of this process is not running
        done, _ = os.waitpid(pid, os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True


def choose(layout: Layout, requested: str | None):
    if requested == "process" or (requested is None and not (layout.system and Systemd.available())):
        return Process(layout)
    if not Systemd.available():
        raise SystemExit("systemd не найден: на этой машине доступен только --supervisor process (не для эксплуатации).")
    return Systemd(layout)

