"""Operator-only Docker guard. Never import or expose this module from the web app."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

from agent_graph_demo.contracts import DemoError, now
from agent_graph_demo.locks import locked
from agent_graph_demo.snapshots import atomic_json
from tools.agent_graph_demo.state_access import APP_UID, APP_GID

DOCKER = ["docker", "--host=unix:///var/run/docker.sock"]


class RuntimeGuard:
    def __init__(self, state_root, runtime_root, image, product_sha):
        self.state_root, self.root = Path(state_root), Path(runtime_root)
        self.registry = self.root / "active.json"
        self.image, self.product_sha = image, product_sha
        if not re.fullmatch(r"(?:[a-zA-Z0-9./:_-]+@)?sha256:[a-f0-9]{64}", image):
            raise DemoError("immutable_image_required")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o750)
        if os.geteuid() == 0:
            self.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.state_root.stat().st_uid != APP_UID:
                raise DemoError("state_root_must_belong_to_app_uid")
            os.chown(self.root, 0, APP_GID)
            self.root.chmod(0o750)
            lock = self.state_root / "workload.lock"
            try:
                fd = os.open(
                    lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
                )
            except FileExistsError:
                if lock.is_symlink() or lock.stat().st_uid != APP_UID:
                    raise DemoError("workload_lock_owner_mismatch")
            else:
                try:
                    os.fchown(fd, APP_UID, APP_GID)
                finally:
                    os.close(fd)
        # Do not inherit a Docker endpoint selector pointing to a different host.
        self.env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in {
                "DOCKER_HOST",
                "DOCKER_CONTEXT",
                "DOCKER_TLS",
                "DOCKER_TLS_VERIFY",
                "DOCKER_CERT_PATH",
            }
        }

    def docker(self, *args, timeout=45):
        r = subprocess.run(
            [*DOCKER, *args], env=self.env, capture_output=True, timeout=timeout
        )
        if r.returncode:
            raise DemoError("docker_operation_failed")
        if len(r.stdout) > 2_000_000:
            raise DemoError("docker_output_limit")
        return r.stdout.decode()

    @contextmanager
    def exclusive(self):
        with locked(self.state_root / "workload.lock"):
            with locked(self.root / "guard.lock"):
                yield

    def read(self):
        if not self.registry.exists():
            # Initialization still inventories Docker below; never assume absence of old projects.
            return dict(
                generation=0,
                state="UNKNOWN",
                session_id=None,
                project_name=None,
                manifest_sha256=None,
                observed_at=now(),
                reason="needs_reconciliation",
            )
        return json.loads(self.registry.read_text())

    def write(self, value, state, **extra):
        r = {
            **value,
            **extra,
            "state": state,
            "generation": value["generation"] + 1,
            "observed_at": now(),
        }
        atomic_json(self.registry, r)
        self.registry.chmod(0o640)
        if os.geteuid() == 0:
            os.chown(self.registry, 0, APP_GID)
        return r

    def project(self, sid):
        return "agent-graph-demo-sbx-" + str(uuid.UUID(sid))

    def plan(self, record):
        sid = str(uuid.UUID(record["session_id"]))
        sha = record["manifest_sha256"]
        if not re.fullmatch("[a-f0-9]{64}", sha) or record[
            "project_name"
        ] != self.project(sid):
            raise DemoError("runtime_registry_invalid")
        return self.root / "plans" / sid / sha / "compose.json"

    def inventory(self):
        # Enumerate all containers, then exact project-name allowlist. No regex-only deletion.
        ids = self.docker("ps", "-aq").split()
        if not ids:
            return []
        all_containers = json.loads(self.docker("inspect", *ids))
        own = []
        for c in all_containers:
            project = (
                c["Config"].get("Labels", {}).get("com.docker.compose.project", "")
            )
            if project.startswith("agent-graph-demo-sbx-"):
                try:
                    sid = str(uuid.UUID(project.removeprefix("agent-graph-demo-sbx-")))
                except ValueError:
                    continue
                if project == self.project(sid):
                    own.append(c)
        return own

    @staticmethod
    def active(containers):
        return [c for c in containers if c["State"]["Running"]]

    def compare(self, record):
        own = self.inventory()
        if any(
            c["Config"]["Labels"].get("com.docker.compose.project")
            != record.get("project_name")
            for c in own
        ):
            raise DemoError("unexpected_sandbox_requires_reconciliation")
        for c in self.active(own):
            labels = c["Config"]["Labels"]
            if (
                labels.get("agent-graph-demo.manifest") != record["manifest_sha256"]
                or labels.get("agent-graph-demo.session") != record["session_id"]
            ):
                raise DemoError("runtime_manifest_mismatch")
        return own

    def down(self, record):
        if record.get("session_id"):
            plan = self.plan(record)
            if not plan.is_file():
                raise DemoError("pinned_runtime_plan_missing")
            self.docker(
                "compose",
                "-p",
                record["project_name"],
                "-f",
                str(plan),
                "down",
                "--remove-orphans",
            )
        if self.inventory():
            raise DemoError("sandbox_stop_unconfirmed")

    def stop(self, sid, expected_generation):
        with self.exclusive():
            r = self.read()
            if r["generation"] != expected_generation:
                raise DemoError("runtime_generation_conflict")
            if r.get("session_id") not in (None, sid):
                raise DemoError("runtime_owned_by_other_session")
            if r["state"] in ("UNKNOWN", "STARTING"):
                raise DemoError("runtime_reconciliation_required")
            try:
                self.compare(r)
                self.down(r)
                return self.write(r, "STOPPED")
            except Exception:
                self.write(r, "UNKNOWN", reason="stop_failed")
                raise

    def reconcile(self, expected_generation):
        # Explicit operator action: down only the one pinned project in the registry.
        # Unexpected/foreign sandbox names are reported; never inferred and deleted.
        with self.exclusive():
            r = self.read()
            if r["generation"] != expected_generation:
                raise DemoError("runtime_generation_conflict")
            try:
                self.compare(r)
                self.down(r)
                return self.write(r, "STOPPED", reason=None)
            except Exception:
                self.write(r, "UNKNOWN", reason="manual_reconciliation_required")
                raise

    def refresh(self, expected_generation):
        with self.exclusive():
            r = self.read()
            if r["generation"] != expected_generation:
                raise DemoError("runtime_generation_conflict")
            if r["state"] not in ("RUNNING", "STOPPED"):
                raise DemoError("runtime_reconciliation_required")
            try:
                own = self.compare(r)
                if r["state"] == "RUNNING":
                    active = self.active(own)
                    services = {
                        c["Config"]["Labels"].get("com.docker.compose.service")
                        for c in active
                    }
                    if services != {"orders", "status"} or len(active) != 2:
                        raise DemoError("runtime_services_missing")
                    if any(c["Image"] != self.image_id() for c in active):
                        raise DemoError("runtime_image_mismatch")
                elif own:
                    raise DemoError("stopped_registry_has_containers")
                return self.write(r, r["state"])
            except Exception:
                self.write(r, "UNKNOWN", reason="runtime_observation_failed")
                raise

    def image_id(self):
        value = json.loads(self.docker("image", "inspect", self.image))[0]
        if (
            value["Config"].get("Labels", {}).get("agent-graph-demo.product")
            != self.product_sha
        ):
            raise DemoError("runtime_product_image_mismatch")
        return value["Id"]

    def activate_locked(self, sid, manifest, corpus, dataset_path, expected_generation):
        """Caller holds exclusive() through collection and receipt publication."""
        r = self.read()
        if r["generation"] != expected_generation:
            raise DemoError("runtime_generation_conflict")
        if r["state"] not in ("RUNNING", "STOPPED"):
            raise DemoError("runtime_reconciliation_required")
        self.image_id()
        try:
            own = self.compare(r)
            same = (
                r.get("session_id") == sid
                and r.get("manifest_sha256") == manifest["manifest_sha256"]
            )
            if same and r["state"] == "RUNNING":
                active = self.active(own)
                if (
                    len(active) != 2
                    or {
                        c["Config"]["Labels"].get("com.docker.compose.service")
                        for c in active
                    }
                    != {"orders", "status"}
                    or any(c["Image"] != self.image_id() for c in active)
                ):
                    raise DemoError("runtime_services_missing")
                return r
            self.down(r)
            r = self.write(r, "STOPPED")
            target = dict(
                session_id=sid,
                project_name=self.project(sid),
                manifest_sha256=manifest["manifest_sha256"],
            )
            plan_record = {**r, **target}
            plan = self.plan(plan_record)
            plan.parent.mkdir(parents=True, exist_ok=True)
            labels = {
                "agent-graph-demo.session": sid,
                "agent-graph-demo.manifest": manifest["manifest_sha256"],
            }
            base = dict(
                image=self.image,
                user="10001:10001",
                read_only=True,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                pids_limit=64,
                cpus=0.5,
                tmpfs=["/tmp:size=16m"],
                restart="no",
                labels=labels,
                logging={
                    "driver": "json-file",
                    "options": {"max-size": "5m", "max-file": "2"},
                },
                volumes=[
                    str(corpus) + ":/corpus:ro",
                    str(dataset_path) + ":/dataset.json:ro",
                ],
                environment={
                    "PYTHONPATH": "/corpus:/app:/app/src",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "DEMO_DATASET": "/dataset.json",
                    "NO_PROXY": "orders,status,127.0.0.1,localhost",
                    "no_proxy": "orders,status,127.0.0.1,localhost",
                },
            )
            services = {
                name: {
                    **base,
                    "mem_limit": "192m" if name == "orders" else "128m",
                    "command": [
                        "python",
                        "-m",
                        "uvicorn",
                        f"{name}.app:app",
                        "--host",
                        "0.0.0.0",
                        "--port",
                        "8000",
                    ],
                }
                for name in ("orders", "status")
            }
            for name in ("reporting", "billing", "health", "export"):
                services[name] = {
                    **base,
                    "mem_limit": "128m",
                    "profiles": ["check"],
                    "command": [
                        "python",
                        "/app/tools/agent_graph_demo/consumer.py",
                        name,
                    ],
                }
            atomic_json(
                plan,
                {"services": services, "networks": {"default": {"internal": True}}},
            )
            # Persist the new pinned plan before STARTING. Crash is not auto-resumed.
            r = self.write(r, "STARTING", **target)
            self.docker(
                "compose",
                "-p",
                r["project_name"],
                "-f",
                str(plan),
                "up",
                "-d",
                "orders",
                "status",
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    # Health consumer exercises a real request to the separate Status service.
                    self.consumer(r, "health", timeout=7)
                    self.consumer(r, "billing", timeout=7)
                    return self.write(
                        r, "RUNNING", product_sha=self.product_sha, image=self.image
                    )
                except DemoError:
                    time.sleep(0.3)
            raise DemoError("runtime_readiness_timeout")
        except Exception:
            self.write(r, "UNKNOWN", reason="activation_failed")
            raise

    def consumer(self, r, consumer, timeout=20):
        if consumer not in ("reporting", "billing", "health", "export"):
            raise DemoError("consumer_forbidden")
        out = self.docker(
            "compose",
            "-p",
            r["project_name"],
            "-f",
            str(self.plan(r)),
            "run",
            "--rm",
            "--no-deps",
            "-T",
            consumer,
            timeout=timeout,
        )
        try:
            result = json.loads(out)
        except ValueError:
            raise DemoError("consumer_invalid_output") from None
        if result.get("status") == "ERROR":
            raise DemoError("consumer_execution_failed")
        return result
