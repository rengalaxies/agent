"""agent-service box: the single installer and maintenance tool of a Linux VM installation.

    box plan     [--config box.yaml]   check the configuration, secrets and host; show what install will change
    box install  [--config box.yaml]   validate → release → configure → mirrors → probes → graph → start → smoke → report
    box update   [--config box.yaml]   install of a newer release: the old service stops and its state and configuration
                                       are backed up before any code of the new release opens them; automatic
                                       rollback if a later phase fails
    box status                         release and core the running process loaded; liveness / process / scenario
    box doctor                         status plus live credential and source checks with what to do
    box backup [--label L] | backups | restore NAME
    box rollback [--to RELEASE]        previous release; restores the matching backup when the state schema differs
    box sync-mirrors                   fetch Git mirrors (the systemd timer runs it)

Every phase is idempotent: a second install changes nothing that is already
right, and an install interrupted at any point is finished by running it again.
Commands and plans come from this trusted code, never from model output.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

from . import config as box_config
from . import release as rel
from . import state as box_state
from . import recovery
from .layout import SERVICE_USER, Layout, is_root, venv_python
from .messages import explain
from .supervisor import box_command, choose

# "backup" runs only when the install replaces another active release, before anything of the new one runs.
PHASES = ("validate", "release", "backup", "configure", "mirrors", "probes", "graph", "start", "smoke", "report")
EXIT_READY, EXIT_FAILED, EXIT_NOT_READY = 0, 1, 2


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Failed(Exception):
    """A phase that cannot continue; ``problems`` are safe, human-readable lines."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class Box:
    def __init__(self, layout: Layout, release_dir: Path, supervisor: str | None, out=print):
        self.layout = layout
        self.release = Path(release_dir).resolve()
        self.manifest, self.manifest_sha = rel.load_manifest(self.release)
        self.bindings = layout.bindings(self.manifest["name"])
        self.supervisor = choose(layout, supervisor)
        self.supervisor.manager = self.release
        self.out = out

    # -- journal and lock ------------------------------------------------

    def journal(self) -> dict:
        try:
            return json.loads(self.layout.journal.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self, journal: dict):
        self.layout.box.mkdir(parents=True, exist_ok=True, mode=0o700)
        box_config.write_json(self.layout.journal, journal)

    @contextmanager
    def lock(self):
        from agent_graph.portable import lock_nonblocking, open_lock_file

        self.layout.box.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = open_lock_file(self.layout.box / "lock")
        deadline = time.time() + 60  # e.g. the daily backup timer holds it for a few seconds
        while True:
            try:
                lock_nonblocking(fd)
                break
            except BlockingIOError:
                if time.time() > deadline:
                    os.close(fd)
                    raise Failed(["Другая операция box уже выполняется на этой машине. Дождитесь её завершения."])                         from None
                time.sleep(1)
        try:
            recovered = box_state.recover(self.layout)  # a restore killed half way: the old databases go back
            if recovered:
                self.out(f"Незавершённое восстановление из {recovered['backup']} разобрано: {recovered['outcome']}.")
            yield
        finally:
            os.close(fd)

    # -- helpers ---------------------------------------------------------

    def secrets(self) -> dict:
        try:
            return box_config.read_secrets(self.layout.secrets)
        except FileNotFoundError:
            return {}

    def fix_sidecars(self):
        """SQLite -wal/-shm files that a root read created must belong to the service user, or it cannot write."""
        if not (self.layout.system and is_root()):
            return
        for directory in (self.layout.state / "service", self.layout.state / "core"):
            if directory.is_dir():
                for path in directory.iterdir():
                    if path.name.endswith(("-wal", "-shm", "-journal")) and path.stat().st_uid == 0:
                        shutil.chown(path, SERVICE_USER, SERVICE_USER)

    def chown(self, path: Path, mode: int | None = None, *, group_only=False):
        if mode is not None and os.name != "nt":
            os.chmod(path, mode)
        if self.layout.system and is_root():
            shutil.chown(path, None if group_only else SERVICE_USER, SERVICE_USER)

    def task(self, name: str, *args: str, release: Path | None = None, timeout=900) -> dict:
        """Run tasks.py as the service user with the secrets in its environment; parse its JSON."""
        release = release or self.release
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG")}
        env.update(self.secrets())
        env.update(PYTHONDONTWRITEBYTECODE="1", HOME=str(self.layout.run / "home"), TMPDIR=str(self.layout.state / "tmp"))
        if os.name == "nt":
            env["TEMP"] = env["TMP"] = str(self.layout.state / "tmp")
        kwargs = {}
        if self.layout.system and is_root():
            kwargs = dict(user=SERVICE_USER, group=SERVICE_USER, extra_groups=[], umask=0o077)
        command = [str(venv_python(release / "venv")), "-I", "-B",
                   str(release / "app/tools/agent_service/box/tasks.py"), name, *args]
        out = subprocess.run(command, env=env, cwd=str(self.layout.state), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, timeout=timeout, **kwargs)
        try:
            return json.loads(out.stdout.decode("ascii").strip().splitlines()[-1])
        except (ValueError, IndexError, UnicodeError):
            return {"ok": False, "error": {"code": "task_crashed", "task": name, "exit": out.returncode}}

    def fault(self, phase: str, when: str, cfg: box_config.BoxConfig | None):
        """Test hook: AGENT_SERVICE_BOX_KILL_AT=<phase>[:start] kills the installer there (testing.fault_hooks)."""
        spec = os.environ.get("AGENT_SERVICE_BOX_KILL_AT")
        if not spec or not cfg or not cfg.testing.fault_hooks:
            return
        target, _, at = spec.partition(":")
        if target == phase and (at or "done") == when:
            self.out(f"[test] installer killed at {phase}:{when}")
            sys.stdout.flush()
            if os.name == "nt":
                os._exit(137)
            os.kill(os.getpid(), signal.SIGKILL)

    # -- validate / plan -------------------------------------------------

    def validate(self, config_path: Path) -> tuple[box_config.BoxConfig, list[str], list[str]]:
        """(config, problems, plan). No changes to the machine."""
        problems, plan = [], []
        try:
            cfg = box_config.load(config_path)
        except box_config.ConfigProblem as exc:
            raise Failed([f"box.yaml: {p}" for p in exc.problems]) from None
        if self.layout.system and not shutil.which("systemctl"):
            problems.append("systemd не найден: коробка рассчитана на Linux-ВМ с systemd.")
        git = shutil.which("git")
        if not git:
            problems.append("git не установлен (apt install git).")
        else:
            version = subprocess.run(["git", "version"], stdout=subprocess.PIPE, text=True).stdout.split()[-1]
            parts = tuple(int(x) for x in version.split(".")[:2] if x.isdigit())
            if parts < (2, 31):
                problems.append(f"git {version} слишком старый, нужен 2.31 или новее.")
        secrets_path = self.layout.secrets
        if not secrets_path.is_file():
            problems.append(f"Нет файла секретов {secrets_path}. Создайте его (права 600) со строками: "
                            + ", ".join(f"{n}=..." for n in cfg.secret_names() if n != box_config.STATUS_TOKEN_ENV))
            values = {}
        else:
            try:
                values = box_config.read_secrets(secrets_path)
            except box_config.ConfigProblem as exc:
                problems += exc.problems
                values = {}
            missing = [n for n in cfg.secret_names() if n != box_config.STATUS_TOKEN_ENV and not values.get(n)]
            for name in missing:
                problems.append(f"В {secrets_path} не задан {name} ({cfg.secret_names()[name]}).")
            if cfg.github.auth.kind == "app" and values.get(cfg.github.auth.private_key_path_env):
                key = Path(values[cfg.github.auth.private_key_path_env])
                if not key.is_file():
                    problems.append(f"{cfg.github.auth.private_key_path_env} указывает на несуществующий файл.")
        for label, path in (("ownership_file", cfg.ownership_file), ("constitution_file", cfg.constitution_file),
                            ("model.qualification.report_path",
                             cfg.model.qualification.report_path if cfg.model and cfg.model.qualification else None)):
            if path is not None and not Path(path).is_file():
                problems.append(f"box.yaml: {label} указывает на несуществующий файл {path}.")
        parent = self.layout.state if self.layout.state.exists() else self.layout.prefix
        free = shutil.disk_usage(parent).free
        if free < 1 << 30:
            problems.append(f"Свободно {free >> 20} МиБ, нужно не меньше 1024 МиБ под состояние и зеркала.")
        loaded = self.loaded()
        if not (loaded and self.supervisor.active()) and not _port_free(cfg.listen.host, cfg.listen.port):
            problems.append(f"Порт {cfg.listen.host}:{cfg.listen.port} занят другим процессом.")
        journal = self.journal()
        active = journal.get("active", {}).get("name")
        name = self.manifest["name"]
        plan.append(f"релиз {name} (commit {self.manifest['code']['commit'][:12]}) "
                    + ("уже активен" if active == name else f"заменит {active}" if active else "будет установлен"))
        if active and active != name:
            plan.append("до запуска кода нового релиза: остановка сервиса и копия состояния и конфигурации (pre-update)")
        if self.layout.system:
            plan.append(f"пользователь {SERVICE_USER}: " + ("есть" if _user_exists() else "будет создан"))
        plan.append(f"конфигурация: {config_path} → {self.layout.config}; сгенерированные service.json, policy.json "
                    f"этого релиза в {self.bindings}")
        mirrors = [r.graph_id for r in cfg.github.repositories]
        existing = [m for m in mirrors if (self.layout.mirrors / f"{m}.git").exists()]
        plan.append(f"Git-зеркала: обновить {len(existing)}, клонировать {len(mirrors) - len(existing)}")
        plan.append(f"проверки источников: GitHub ({len(mirrors)} репозиториев)" + (", Jira" if cfg.jira else ""))
        plan.append("начальный граф по веткам по умолчанию; запуск сервиса " + self.supervisor.name
                    + f" на {cfg.listen.host}:{cfg.listen.port}; offline smoke установленного релиза")
        plan.append(f"публикация: {cfg.publication}; модель: "
                    + ("выключена" if not cfg.model else f"{cfg.model.model} ({cfg.model.configuration_id})"))
        return cfg, problems, plan

    # -- install phases --------------------------------------------------

    def configure(self, cfg: box_config.BoxConfig, config_path: Path) -> dict:
        L = self.layout
        changed = []
        if L.system and is_root() and not _user_exists():
            subprocess.run(["useradd", "--system", "--user-group", "--home-dir", str(L.state), "--no-create-home",
                            "--shell", "/usr/sbin/nologin", SERVICE_USER], check=True)
            changed.append("user")
        L.etc.mkdir(parents=True, exist_ok=True)
        for d in (L.generated, self.bindings):
            d.mkdir(parents=True, exist_ok=True)
            self.chown(d, 0o750, group_only=True)
        for d, mode in ((L.state, 0o750), (L.state / "service", 0o700), (L.state / "core", 0o700),
                        (L.mirrors, 0o700), (L.run, 0o700), (L.run / "home", 0o700), (L.state / "tmp", 0o700),
                        (L.state / "dry-run", 0o700)):
            d.mkdir(parents=True, exist_ok=True)
            self.chown(d, mode)
        L.backups.mkdir(parents=True, exist_ok=True, mode=0o700)
        if Path(config_path).resolve() != L.config.resolve():
            if box_config.write_bytes(L.config, Path(config_path).read_bytes(), 0o644):
                changed.append("box.yaml")
        values = self.secrets()
        if not values.get(box_config.STATUS_TOKEN_ENV):
            import secrets as tokens

            with open(L.secrets, "a", encoding="utf-8") as f:
                f.write(f"\n{box_config.STATUS_TOKEN_ENV}={tokens.token_urlsafe(32)}\n")
            changed.append("status token")
        if os.name != "nt":
            os.chmod(L.secrets, 0o600)
            if L.system and is_root():
                shutil.chown(L.secrets, "root", "root")
        if cfg.github.auth.kind == "app":
            key = Path(values.get(cfg.github.auth.private_key_path_env, ""))
            if key.is_file():
                self.chown(key, 0o640, group_only=True)
        constitution = cfg.constitution_file or self.release / "app" / self.manifest["contracts"]["constitution"]["path"]
        # Written by this release's code into its own directory: the bindings of the active release stay as they
        # are until the supervisor switches to this release, and a rollback switches back to them unchanged.
        service = cfg.service(state=L.state, policy_path=self.bindings / "policy.json",
                              constitution=Path(constitution), release_id=self.manifest["release_id"])
        if box_config.write_json(self.bindings / "service.json", service):
            changed.append("service.json")
        self.chown(self.bindings / "service.json", 0o640, group_only=True)
        return {"changed": changed}

    def mirrors(self, cfg: box_config.BoxConfig) -> dict:
        L = self.layout
        result = self.task("mirrors", "--box-config", str(L.config), "--mirrors", str(L.mirrors))
        previous = {}
        active = self.journal().get("active", {}).get("name")
        for source in [self.bindings] + ([L.bindings(active)] if active else []):
            try:
                previous = {r["id"]: r["revision"]
                            for r in json.loads((source / "policy.json").read_text(encoding="utf-8"))["repositories"]}
                break
            except (OSError, ValueError, KeyError):
                pass
        tips = {}
        for r in result.get("repositories", []):
            tips[r["id"]] = r.get("tip") or previous.get(r["id"]) or "0" * 40
        for r in cfg.github.repositories:
            tips.setdefault(r.graph_id, previous.get(r.graph_id, "0" * 40))
        constitution = cfg.constitution_file or self.release / "app" / self.manifest["contracts"]["constitution"]["path"]
        changed = box_config.write_json(self.bindings / "policy.json",
                                        cfg.policy(mirrors=L.mirrors, tips=tips, constitution=Path(constitution)))
        self.chown(self.bindings / "policy.json", 0o640, group_only=True)
        result["policy_changed"] = changed
        return result

    def config_digest(self, name: str) -> str:
        parts = [(self.layout.bindings(name) / n).read_bytes() for n in ("service.json",)]
        parts.append(self.layout.secrets.read_bytes() if self.layout.secrets.is_file() else b"")
        return rel.sha256_bytes(b"\0".join(parts))

    def loaded(self) -> dict | None:
        try:
            return json.loads((self.layout.run / "loaded.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def activate(self, cfg: box_config.BoxConfig, release: Path, manifest: dict) -> dict:
        """Point the supervisor at ``release`` and make sure exactly one process of it runs."""
        L = self.layout
        recovery.check_start(L.state, manifest, rel.load_manifest(release)[1])
        units_changed = self.supervisor.configure(release, cfg.listen.host, cfg.listen.port,
                                                  sync_seconds=cfg.freshness.mirror_sync_seconds,
                                                  daily_backup=cfg.storage.daily_backup)
        journal = self.journal()
        digest = self.config_digest(manifest["name"])
        loaded = self.loaded()
        pid = self.supervisor.pid()
        running_right = (pid is not None and loaded is not None and pid in (loaded.get("pid"), loaded.get("launcher_pid"))
                         and loaded.get("release") == manifest["name"] and journal.get("config_digest") == digest)
        action = "kept"
        self.fix_sidecars()
        if not running_right or units_changed:
            (L.run / "loaded.json").unlink(missing_ok=True)
            if pid is not None:
                self.supervisor.restart()
                action = "restarted"
            else:
                self.supervisor.start()
                action = "started"
        history = journal.get("history", [])
        if journal.get("active", {}).get("name") != manifest["name"]:
            if journal.get("active"):
                history.append({**journal["active"], "deactivated_at": now()})
            journal["active"] = {"name": manifest["name"], "release_id": manifest["release_id"],
                                 "commit": manifest["code"]["commit"],
                                 "manifest_sha256": rel.sha256_bytes((release / "manifest.json").read_bytes()),
                                 "activated_at": now()}
        journal["history"] = history[-20:]
        journal["config_digest"] = digest
        journal["supervisor"] = self.supervisor.name
        journal["listen"] = {"host": cfg.listen.host, "port": cfg.listen.port}
        self.save(journal)
        # Keep the new manager after a downgrade; the old archive's CLI is not patched.
        self.write_wrapper(self.release)
        ready = self.wait_ready(cfg, manifest, timeout=120)
        return {"action": action, "units_changed": units_changed, **ready}

    def write_wrapper(self, release: Path):
        if os.name == "nt":
            return
        command = " ".join(box_command(self.layout, release))
        prefix = "" if self.layout.system else f" --prefix {self.layout.prefix}"
        script = f"#!/bin/sh\n# agent-service box of the active release\nexec {command}{prefix} \"$@\"\n"
        box_config.write_bytes(self.layout.wrapper, script.encode(), 0o755)

    def http(self, cfg_listen: dict, path: str, token: str | None = None) -> tuple[int, dict | None]:
        host = cfg_listen["host"] if cfg_listen["host"] not in ("0.0.0.0", "::") else "127.0.0.1"
        req = urllib.request.Request(f"http://{host}:{cfg_listen['port']}{path}",
                                     headers={"Authorization": f"Bearer {token}"} if token else {})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            exc.close()
            return exc.code, None
        except (urllib.error.URLError, OSError, ValueError):
            return 0, None

    def process_level(self, listen: dict, manifest: dict | None = None) -> dict:
        """Liveness and process readiness, measured now."""
        manifest = manifest or self.active_manifest()
        status, body = self.http(listen, "/healthz")
        live = status == 200 and bool(body and body.get("live"))
        loaded = self.loaded()
        pid = self.supervisor.pid()
        problems = []
        if not live:
            problems.append("service_not_live")
        if loaded is None:
            problems.append("loaded_identity_missing")
        else:
            if pid is None or pid not in (loaded.get("pid"), loaded.get("launcher_pid")):
                problems.append("loaded_identity_from_other_process")
            if manifest and loaded.get("release") != manifest["name"]:
                problems.append("running_release_differs_from_active")
            if manifest and loaded.get("core") != manifest["contracts"]["core"]:
                problems.append("running_core_differs_from_manifest")
            if manifest:
                problems += self.binding_problems(loaded, manifest)
        code, queue = self.http(listen, "/status", self.secrets().get(box_config.STATUS_TOKEN_ENV))
        if code != 200:
            problems.append("status_endpoint_unavailable" if code != 401 else "status_token_rejected")
        return {"live": live, "process_ready": live and not problems, "problems": problems, "pid": pid,
                "loaded": loaded, "queue": queue if code == 200 else None}

    def binding_problems(self, loaded: dict, manifest: dict) -> list[str]:
        """The configuration, code_version and constitution the process loaded must be those of its release."""
        problems = []
        expected = (self.layout.bindings(manifest["name"]) / "service.json").resolve()
        if not loaded.get("config") or Path(loaded["config"]).resolve() != expected:
            problems.append("running_config_of_other_release")
        if loaded.get("code_version") != manifest["release_id"]:
            problems.append("running_code_version_differs_from_release")
        if loaded.get("constitution") != self.expected_constitution(manifest):
            problems.append("running_constitution_differs_from_release")
        return problems

    def expected_constitution(self, manifest: dict) -> str | None:
        """The release's own constitution, or the owner's constitution_file from box.yaml."""
        try:
            own = box_config.load(self.layout.config).constitution_file
        except box_config.ConfigProblem:
            own = None
        if own is None:
            return manifest["contracts"]["constitution"]["version_id"]
        from agent_graph.constitution import load

        try:
            return load(own)[1]
        except Exception:
            return None

    def wait_ready(self, cfg: box_config.BoxConfig, manifest: dict, timeout: float) -> dict:
        listen = {"host": cfg.listen.host, "port": cfg.listen.port}
        deadline = time.time() + timeout
        while True:
            level = self.process_level(listen, manifest)
            if level["process_ready"] or time.time() > deadline:
                return level
            time.sleep(1)

    def active_release(self) -> Path:
        """The release whose code and bindings serve now (this one before the first install)."""
        name = self.journal().get("active", {}).get("name")
        return self.layout.release(name) if name and self.layout.release(name).is_dir() else self.release

    def active_manifest(self) -> dict | None:
        name = self.journal().get("active", {}).get("name")
        if not name:
            return None
        try:
            return rel.load_manifest(self.layout.release(name))[0]
        except (OSError, rel.ReleaseError):
            return None

    # -- the install flow ------------------------------------------------

    def install(self, config_path: Path, *, update: bool) -> int:
        L = self.layout
        journal = self.journal()
        run = {"id": uuid.uuid4().hex[:12], "release": self.manifest["name"], "started_at": now(), "phases": [],
               "command": "update" if update else "install"}
        unfinished = journal.get("run")
        if unfinished and unfinished.get("state") == "IN_PROGRESS":
            run["resumed_after"] = {"id": unfinished["id"], "last_phase": (unfinished["phases"] or [{}])[-1]}
        journal["run"] = {**run, "state": "IN_PROGRESS"}
        self.save(journal)
        started = time.monotonic()
        cfg = None
        outcome = {}

        def phase(name, fn):
            self.fault(name, "start", cfg)
            t = time.monotonic()
            self.out(f"[{name}] ...")
            try:
                detail = fn() or {}
                state = detail.pop("_state", "DONE")
            except (Failed, rel.ReleaseError, box_state.BackupError) as exc:
                run["phases"].append({"phase": name, "state": "FAILED", "seconds": round(time.monotonic() - t, 2)})
                if isinstance(exc, Failed):
                    raise
                raise Failed([exc.code]) from None
            entry = {"phase": name, "state": state, "seconds": round(time.monotonic() - t, 2), "detail": detail}
            run["phases"].append(entry)
            j = self.journal()
            j["run"] = {**run, "state": "IN_PROGRESS"}
            self.save(j)
            self.out(f"[{name}] {state} ({entry['seconds']} s)")
            self.fault(name, "done", cfg)
            return detail

        try:
            if recovery.pending(L.state):
                raise Failed(["recovery_unfinished: сначала повторите ту же команду rollback/restore; "
                              "новое обновление не запускается."])
            def do_validate():
                nonlocal cfg
                cfg, problems, plan = self.validate(config_path)
                for line in plan:
                    self.out(f"  план: {line}")
                if problems:
                    raise Failed(problems)
                return {"plan": plan}

            phase("validate", do_validate)
            phase("release", lambda: {"name": self.manifest["name"], "release_id": self.manifest["release_id"],
                                      "commit": self.manifest["code"]["commit"],
                                      "manifest_sha256": rel.verify_tree(self.release)[1]})
            previous = self.journal().get("active")
            if previous and previous["name"] != self.manifest["name"]:
                # The old service stops and its state, box.yaml and bindings are copied before any code of this
                # release opens the state (graph, start) or writes configuration (configure).
                phase("backup", lambda: self.pre_update_backup(previous))
            # Record the writer before graph/tasks opens SQLite, including interrupted upgrades.
            recovery.identify(L.state, self.manifest, self.manifest_sha,
                              reconcile=bool(previous and previous["name"] != self.manifest["name"]))
            phase("configure", lambda: self.configure(cfg, config_path))
            self.chown(L.state / recovery.IDENTITY, 0o600)

            def do_mirrors():
                r = self.mirrors(cfg)
                return {**r, "_state": "DONE" if r.get("ok") else "DEGRADED"}

            phase("mirrors", do_mirrors)

            def do_probes():
                r = self.task("probes", "--config", str(self.bindings / "service.json"))
                return {**r, "_state": "DONE" if r.get("ok") else "DEGRADED"}

            phase("probes", do_probes)

            def do_graph():
                r = self.task("graph", "--config", str(self.bindings / "service.json"))
                return {**r, "_state": "DONE" if r.get("ok") else "DEGRADED"}

            phase("graph", do_graph)

            def do_start():
                r = self.activate(cfg, self.release, self.manifest)
                if not r["process_ready"]:
                    raise Failed(["Сервис не перешёл в состояние готовности процесса: " + ", ".join(r["problems"])])
                if self.update_state().get("state") == "IN_PROGRESS":
                    j = self.journal()
                    j["update"]["state"] = "DONE"
                    j["rollback_point"] = {"release": j["update"]["from"], "backup": j["update"]["backup"]}
                    self.save(j)
                return {k: r[k] for k in ("action", "units_changed", "pid", "problems")}

            phase("start", do_start)

            def do_smoke():
                r = self.task("smoke", "--tmp", str(L.state / "tmp"), timeout=600)
                failed = [c["check"] for c in r.get("checks", []) if not c["ok"]]
                return {"ok": r.get("ok", False), "seconds": r.get("seconds"), "failed_checks": failed,
                        "_state": "DONE" if r.get("ok") else "DEGRADED"}

            phase("smoke", do_smoke)

            def do_report():
                nonlocal outcome
                outcome = self.readiness(listen={"host": cfg.listen.host, "port": cfg.listen.port}, run=run)
                return {"scenario": outcome["scenario"]["status"]}

            phase("report", do_report)
        except Failed as exc:
            problems = list(exc.problems)
            upd = self.update_state()
            rolled_back = upd.get("state") == "IN_PROGRESS" and upd.get("to") == self.manifest["name"]
            if rolled_back:  # an update that stopped the old service never leaves the machine without it
                try:
                    outcome_ = self.auto_rollback(cfg or self.current_config(), upd["from"])
                except Failed as again:
                    outcome_ = "не удался: " + "; ".join(again.problems)
                problems.append(f"Автоматический откат на {upd['from']}: {outcome_}")
            run.update(state="FAILED", problems=problems, finished_at=now(),
                       machine_seconds=round(time.monotonic() - started, 1))
            self.finish(run)
            self.out("Установка не завершена:")
            for p in problems:
                self.out(f"  - {p}")
            self.out("Исправьте и запустите ту же команду ещё раз" + (": обновление начнётся заново с новой копией."
                                                                     if rolled_back else
                                                                     ": сделанные шаги не повторяются."))
            return EXIT_FAILED
        run.update(state="DONE", finished_at=now(), machine_seconds=round(time.monotonic() - started, 1),
                   readiness=outcome)
        report = self.finish(run)
        self.print_readiness(outcome)
        self.out(f"Машинное время установки: {run['machine_seconds']} с. Отчёт: {report}")
        return EXIT_READY if outcome["scenario"]["status"] == "READY" else EXIT_NOT_READY

    def finish(self, run: dict) -> Path:
        j = self.journal()
        j["run"] = run
        j.setdefault("runs", []).append({k: run.get(k) for k in ("id", "command", "release", "state", "started_at",
                                                                 "finished_at", "machine_seconds")})
        j["runs"] = j["runs"][-50:]
        self.save(j)
        self.layout.reports.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.layout.reports / f"{run['started_at'].replace(':', '')}-{run['command']}-{run['id']}.json"
        box_config.write_json(path, run)
        return path

    # -- update / rollback ------------------------------------------------

    def update_state(self) -> dict:
        return self.journal().get("update", {})

    def pre_update_backup(self, previous: dict) -> dict:
        upd = self.update_state()
        if upd.get("state") == "IN_PROGRESS" and upd.get("to") == self.manifest["name"] and upd.get("backup"):
            box_state.verify(self.layout, upd["backup"])
            return {"backup": upd["backup"], "reused": True}  # an interrupted update keeps its first backup
        old, old_sha = rel.verify_tree(self.layout.release(previous["name"]))
        recovery.semantics(old, old_sha)  # unknown old contracts are not guessed from schema
        self.supervisor.stop()
        try:
            identity = recovery.read_identity(self.layout.state)
            if identity is None:
                recovery.adopt_legacy(self.layout.state, old, old_sha)
            elif identity["semantics"] != recovery.semantics(old, old_sha):
                raise box_state.BackupError("active_state_semantics_mismatch")
            meta = box_state.create(self.layout, label="pre-update", release=recovery.record(old, old_sha))
        except (OSError, box_state.BackupError, rel.ReleaseError) as exc:
            # Restart only the previously configured process; no new state writer ran.
            self.supervisor.start()
            raise Failed([f"Копия перед обновлением не создана ({getattr(exc, 'code', None) or type(exc).__name__}"
                          f"{': ' + exc.strerror if getattr(exc, 'strerror', None) else ''}). Обновление не начато, "
                          f"работает {previous['name']}."]) from None
        j = self.journal()
        j["update"] = {"from": previous["name"], "to": self.manifest["name"], "backup": meta["name"],
                       "state": "IN_PROGRESS", "started_at": now()}
        self.save(j)
        return {"backup": meta["name"], "schemas": meta["schemas"], "counts": meta["counts"]}

    def current_config(self) -> box_config.BoxConfig:
        try:
            return box_config.load(self.layout.config)
        except box_config.ConfigProblem as exc:
            raise Failed([f"box.yaml: {p}" for p in exc.problems]) from None

    def auto_rollback(self, cfg, name: str) -> str:
        try:
            r = self.rollback(cfg, name)
        except Failed as exc:
            return "не удался: " + "; ".join(exc.problems)
        return r["mode"] + ("" if r["process_ready"] else ", но процесс не готов: " + ", ".join(r["problems"]))

    def rollback(self, cfg: box_config.BoxConfig, target_name: str | None, *, backup_name: str | None = None) -> dict:
        L = self.layout
        journal = self.journal()
        active = journal.get("active", {}).get("name")
        if target_name is None:
            older = [h["name"] for h in reversed(journal.get("history", [])) if h["name"] != active]
            if not older:
                raise Failed(["Нет предыдущего релиза для отката."])
            target_name = older[0]
        target = L.release(target_name)
        try:
            manifest, manifest_sha = rel.verify_tree(target)
            target_semantics = recovery.semantics(manifest, manifest_sha)
        except (OSError, rel.ReleaseError) as exc:
            raise Failed([f"Релиз {target_name} не найден или повреждён ({getattr(exc, 'code', exc)})."]) from None
        if not (L.bindings(target_name) / "service.json").is_file():
            raise Failed([f"Нет конфигурации, которую релиз {target_name} сгенерировал для себя "
                          f"({L.bindings(target_name)}). Установите его заново: box install."])
        disk = box_state.schemas(L.state)
        ok, why = box_state.compatible(manifest["contracts"]["state"], disk)
        identity = recovery.read_identity(L.state)
        semantic_ok = identity is not None and identity["semantics"] == target_semantics
        pending = recovery.pending(L.state)
        if pending and pending["target"] != recovery.record(manifest, manifest_sha):
            raise Failed(["recovery_unfinished: повторите rollback к " + pending["target"]["name"]])
        result = {"from": active, "to": target_name, "schemas_on_disk": disk}
        if ok and semantic_ok and not pending and backup_name is None:
            self.supervisor.stop()
            result["mode"] = "release_only"  # state stays: no event or comment after the update is lost
        else:
            candidates = [m for m in box_state.listing(L)
                          if recovery.backup_matches(m, manifest, manifest_sha)
                          and box_state.compatible(manifest["contracts"]["state"], m["schemas"])[0]]
            point = (journal.get("rollback_point") or {}).get("backup")
            # Prefer the backup the update itself took when it left the target release.
            candidates.sort(key=lambda m: (m["name"] == point, m["name"]))
            if not candidates:
                raise Failed([f"matching_backup_missing: состояние/schema/semantics не подтверждены для {target_name} "
                              f"({'; '.join(why)}). Запуск целевого релиза запрещён."])
            backup = pending["backup"] if pending else backup_name or candidates[-1]["name"]
            try:
                meta = box_state.verify(L, backup)
                recovery.verify_backup(L, meta, manifest, manifest_sha)
                self.supervisor.stop()
                safety = ({"name": pending["safety_backup"]} if pending else
                          box_state.create(L, label="pre-rollback", release=journal.get("active")))
                pending = {"target": recovery.record(manifest, manifest_sha), "backup": backup,
                           "safety_backup": safety["name"], "phase": "RESTORING"}
                recovery.hold(L.state, pending)
                meta = box_state.restore(L, backup, chown=lambda p: self.chown(p, 0o600),
                                         fault=lambda point: self.fault("restore", point, cfg))
                recovery.restore_config(L, meta, manifest)
                for name in ("service.json", "policy.json"):
                    self.chown(L.bindings(target_name) / name, 0o640, group_only=True)
            except (OSError, box_state.BackupError) as exc:
                raise Failed([f"Восстановление копии {backup} не удалось ({getattr(exc, 'code', None) or exc}). "
                              "Запуск удерживается. Повторите ту же команду; safety backup сохранён."]) from None
            result.update(mode="restored_backup", backup=backup, backup_created_at=meta["created_at"],
                          safety_backup=safety["name"],
                          counts=meta["counts"],
                          note="Локальная история после backup остаётся в safety backup; автоматического слияния нет. "
                               "Текущее состояние внешних ресурсов возвращается сверкой, комментарии — по маркерам.")
        recovery.identify(L.state, manifest, manifest_sha, reconcile=True)
        self.chown(L.state / recovery.IDENTITY, 0o600)
        if pending:
            recovery.hold(L.state, {**pending, "phase": "READY_TO_START"})
        self.fault("rollback", "before-start", cfg)
        cfg = self.current_config()
        level = self.activate(cfg, target, manifest)
        if not level["process_ready"]:
            self.supervisor.stop()
            raise Failed(["recovery_start_failed: публикация удерживается; повторите rollback. "
                          + ", ".join(level["problems"])])
        (L.state / recovery.TRANSITION).unlink(missing_ok=True)
        j = self.journal()
        j.pop("rollback_point", None)
        if j.get("update", {}).get("state") == "IN_PROGRESS":
            j["update"]["state"] = "ROLLED_BACK"
        self.save(j)
        result["process_ready"] = level["process_ready"]
        result["problems"] = level["problems"]
        return result

    # -- readiness, status, doctor ----------------------------------------

    def readiness(self, listen: dict, run: dict | None = None, probes: dict | None = None) -> dict:
        process = self.process_level(listen)
        active = self.active_release()
        view = self.task("readiness", "--config", str(self.layout.bindings(active.name) / "service.json"),
                         release=active, timeout=300)
        reasons = []
        sources = view.get("sources", [])
        if "graph_error" in view:
            reasons.append(f"graph:{view['graph_error'].get('code')}")
        elif not view.get("graph", {}).get("relationships") or not any(
                s.get("source_kind") == "git" for s in sources):
            reasons.append("graph_empty")
        for s in sources:
            if s["freshness"]["status"] != "CURRENT":
                reasons.append(f"source_{s['freshness']['status'].lower()}:{s['source_id']}")
        notices = (process.get("queue") or view.get("queue") or {}).get("notices", [])
        for n in notices:
            reasons.append(f"notice:{n['kind']}:{n.get('detail') or n.get('subject') or ''}")
        model = view.get("model", {})
        if model and not model.get("ok") and model.get("reason_code") != "model_not_configured":
            reasons.append(f"model:{model.get('reason_code')}")
        for p in (run or {}).get("phases", []):
            if p["state"] == "DEGRADED":
                reasons.append(f"install_phase_degraded:{p['phase']}")
        if probes and not probes.get("ok"):
            for c in probes.get("checks", []):
                if not c["ok"]:
                    reasons.append(f"probe:{c['source']}:{c.get('code')}")
        scenario = "READY" if process["process_ready"] and not reasons else "NOT_READY"
        manifest = self.active_manifest() or {}
        return {
            "checked_at": now(),
            "release": {"name": manifest.get("name"), "release_id": manifest.get("release_id"),
                        "commit": (manifest.get("code") or {}).get("commit"),
                        "core_digest": ((manifest.get("contracts") or {}).get("core") or {}).get("core_digest")},
            "supervisor": {"name": self.supervisor.name, "production": self.supervisor.production},
            "liveness": {"status": "LIVE" if process["live"] else "DOWN"},
            "process": {"status": "READY" if process["process_ready"] else "NOT_READY",
                        "problems": process["problems"], "loaded": process["loaded"]},
            "scenario": {"status": scenario, "reasons": reasons,
                         "graph": view.get("graph"), "sources": [{k: s.get(k) for k in ("source_kind", "source_id",
                                                                                         "status", "last_success_at")}
                                                                 | {"freshness": s["freshness"]["status"]}
                                                                 for s in sources],
                         "model": model, "queue": {k: v for k, v in (process.get("queue") or view.get("queue")
                                                                       or {}).items() if k != "notices"}},
        }

    def print_readiness(self, r: dict):
        rel_ = r["release"]
        self.out(f"Релиз: {rel_['name']} (commit {str(rel_['commit'])[:12]}, ядро {str(rel_['core_digest'])[:12]})")
        loaded = r["process"].get("loaded") or {}
        if loaded:
            self.out(f"Запущенный процесс {loaded.get('pid')}: {loaded.get('release')}, ядро "
                     f"{loaded.get('core', {}).get('core_digest', '')[:12]}, конституция {loaded.get('constitution')}")
        if not r["supervisor"]["production"]:
            self.out("Супервизор: process (только для разработки, не для эксплуатации)")
        self.out(f"Живость: {r['liveness']['status']}; процесс: {r['process']['status']}; "
                 f"сценарий: {r['scenario']['status']}")
        for reason in r["process"]["problems"] + r["scenario"]["reasons"]:
            self.out(f"  - {explain(reason)}")

    def doctor(self, cfg: box_config.BoxConfig) -> tuple[int, dict]:
        problems = []
        try:
            _, vproblems, _ = self.validate(self.layout.config)
            problems += [p for p in vproblems if "занят" not in p]
        except Failed as exc:
            problems += exc.problems
        active = self.active_release()
        probes = self.task("probes", "--config", str(self.layout.bindings(active.name) / "service.json"),
                           release=active)
        listen = self.journal().get("listen") or {"host": cfg.listen.host, "port": cfg.listen.port}
        r = self.readiness(listen, probes=probes)
        backups = box_state.listing(self.layout)
        r["backups"] = {"count": len(backups), "latest": backups[-1]["created_at"] if backups else None}
        runs = self.journal().get("runs") or [{}]
        installed_hours = _age_hours(runs[0]["started_at"].replace("Z", "+00:00")) if runs[0].get("started_at") else 0
        last = backups[-1]["created_at"] if backups else None
        if cfg.storage.daily_backup and installed_hours > 36 and (not last or _age_hours(last) > 36):
            problems.append("Последней резервной копии больше 36 часов (или её нет): проверьте таймер "
                            "agent-service-backup.timer или выполните box backup.")
        r["configuration_problems"] = problems
        self.print_readiness(r)
        for p in problems:
            self.out(f"  - {p}")
        code = EXIT_READY if r["scenario"]["status"] == "READY" and not problems else EXIT_FAILED
        return code, r


def _user_exists() -> bool:
    if os.name == "nt":
        return True
    import pwd

    try:
        pwd.getpwnam(SERVICE_USER)
        return True
    except KeyError:
        return False


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if os.name != "nt":
            # The service binds with SO_REUSEADDR too: TIME_WAIT left by a stopped service is not "taken".
            # (On Windows the option would let the probe bind over a live listener.)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host if host not in ("0.0.0.0",) else "0.0.0.0", port))
            return True
        except OSError:
            return False


def _age_hours(iso: str) -> float:
    then = datetime.datetime.fromisoformat(iso)
    return (datetime.datetime.now(datetime.timezone.utc) - then).total_seconds() / 3600


def main(argv=None, *, release_dir: Path) -> int:
    def options(p, default):
        p.add_argument("--prefix", default=default(os.environ.get("AGENT_SERVICE_BOX_PREFIX")))
        p.add_argument("--supervisor", choices=["systemd", "process"], default=default(None))
        p.add_argument("--json", action="store_true", default=default(False), help="machine-readable output")

    parser = argparse.ArgumentParser(prog="box", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    options(parser, lambda value: value)
    common = argparse.ArgumentParser(add_help=False)  # the same options are accepted after the command
    options(common, lambda value: argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    def command(name):
        return sub.add_parser(name, parents=[common])

    for name in ("plan", "install", "update"):
        command(name).add_argument("--config", type=Path)
    command("status")
    command("doctor")
    command("backup").add_argument("--label", default="manual")
    command("backups")
    command("restore").add_argument("name")
    command("rollback").add_argument("--to")
    command("sync-mirrors")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # a non-UTF-8 console must not abort an install half way
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace", **({} if stream.isatty() else {"encoding": "utf-8"}))
    layout = Layout.at(args.prefix)
    quiet = args.json
    box = Box(layout, release_dir, args.supervisor, out=(lambda *a: None) if quiet else print)

    def emit(value):
        if quiet:
            sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")

    def current_config() -> box_config.BoxConfig:
        try:
            return box_config.load(layout.config)
        except box_config.ConfigProblem as exc:
            raise Failed([f"box.yaml: {p}" for p in exc.problems]) from None

    try:
        if args.command == "sync-mirrors":
            cfg = current_config()
            if layout.system and is_root():
                result = box.task("mirrors", "--box-config", str(layout.config), "--mirrors", str(layout.mirrors))
            else:
                from .mirrors import sync

                result = {"repositories": sync(cfg, layout.mirrors, dict(os.environ))}
                result["ok"] = all(x["status"] == "OK" for x in result["repositories"])
            emit(result)
            for x in result.get("repositories", []):
                box.out(f"{x['repository']}: {x['status']} {x.get('code', x.get('action', ''))}")
            return 0 if result.get("ok") else EXIT_FAILED
        with box.lock():
            if args.command == "plan":
                cfg, problems, plan = box.validate(args.config or layout.config)
                emit({"plan": plan, "problems": problems})
                for line in plan:
                    box.out(f"план: {line}")
                for p in problems:
                    box.out(f"проблема: {p}")
                return EXIT_FAILED if problems else 0
            if args.command in ("install", "update"):
                config_path = args.config or layout.config
                active = box.journal().get("active")
                if args.command == "update" and not active:
                    raise Failed(["Установки ещё нет: используйте box install."])
                code = box.install(config_path, update=args.command == "update")
                emit(box.journal().get("run"))
                return code
            if args.command == "status":
                cfg = current_config()
                listen = box.journal().get("listen") or {"host": cfg.listen.host, "port": cfg.listen.port}
                r = box.readiness(listen)
                emit(r)
                box.print_readiness(r)
                return EXIT_READY if r["scenario"]["status"] == "READY" else EXIT_NOT_READY
            if args.command == "doctor":
                code, r = box.doctor(current_config())
                emit(r)
                return code
            if args.command == "backup":
                cfg = current_config()
                meta = box_state.create(layout, label=args.label, release=box.journal().get("active"))
                box.fix_sidecars()
                protect = {(box.journal().get("rollback_point") or {}).get("backup")}
                removed = box_state.prune(layout, cfg.storage.keep_backups, protect)
                emit({**meta, "pruned": removed})
                box.out(f"Резервная копия {meta['name']}: {meta['counts']}")
                return 0
            if args.command == "backups":
                items = box_state.listing(layout)
                emit(items)
                for m in items:
                    box.out(f"{m['name']}  релиз {(m.get('release') or {}).get('name')}  схемы {m['schemas']}  "
                            f"{m['counts']}")
                return 0
            if args.command == "restore":
                cfg = current_config()
                manifest = box.active_manifest()
                if manifest is None:
                    raise Failed(["active_release_unknown"])
                result = box.rollback(cfg, manifest["name"], backup_name=args.name)
                result["restored"] = result["backup"]
                emit(result)
                box.out(f"Восстановлено из {result['backup']} (safety backup: {result['safety_backup']}).")
                return 0 if result["process_ready"] else EXIT_FAILED
            if args.command == "rollback":
                result = box.rollback(current_config(), args.to)
                emit(result)
                box.out(f"Откат {result['from']} → {result['to']}: {result['mode']}")
                if result.get("note"):
                    box.out(result["note"])
                return 0 if result["process_ready"] else EXIT_FAILED
    except Failed as exc:
        emit({"status": "FAILED", "problems": exc.problems})
        for p in exc.problems:
            print(f"ошибка: {p}", file=sys.stderr)
        return EXIT_FAILED
    except (box_state.BackupError, rel.ReleaseError) as exc:
        emit({"status": "FAILED", "code": exc.code})
        print(f"ошибка: {explain(exc.code)}", file=sys.stderr)
        return EXIT_FAILED
    return 0
