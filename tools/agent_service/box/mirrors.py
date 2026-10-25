"""Local Git mirrors the core reads pinned commits from.

The core never fetches (agent_graph.git_sources); the service resolves
branch tips and PR heads through the GitHub API and then reads those commits
from these mirrors. The box keeps them current: once at install and then
from a systemd timer every ``freshness.mirror_sync_seconds``.

Credentials reach git only through the environment (GIT_CONFIG_COUNT), never
the command line or a stored config, and only for the configured web host.
Errors become reason codes; git's own output is not printed.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
import shutil
import subprocess
import time

from .config import BoxConfig

GIT_TIMEOUT = 600


def _reason(stderr: str) -> str:
    text = stderr.lower()
    if "dubious ownership" in text:
        return "git_repository_owner_mismatch"
    if any(s in text for s in ("authentication failed", "could not read username", "invalid username",
                               "returned error: 401", "returned error: 403")):
        return "git_credentials_rejected"
    if "not found" in text or "does not appear to be a git repository" in text or "does not exist" in text:
        return "git_repository_not_found_or_no_access"
    if any(s in text for s in ("could not resolve host", "timed out", "failed to connect", "network is unreachable",
                               "connection refused")):
        return "git_host_unreachable"
    return "git_fetch_failed"


def github_token(config: BoxConfig, env: dict) -> str:
    auth = config.github.auth
    if auth.kind == "token":
        return env[auth.token_env]
    from agent_service.connectors.github import GitHubAppAuth
    from agent_service.http import HttpClient

    key = Path(env[auth.private_key_path_env]).read_bytes()
    client = HttpClient(config.github.api_base, allow_loopback_http=config.testing.allow_loopback_http)
    return GitHubAppAuth(client, auth.app_id, auth.installation_id, key, time.time)()


def git_env(home: Path, *, header: tuple[str, str] | None, allow_local: bool) -> dict:
    home.mkdir(parents=True, exist_ok=True)
    (home / "gitconfig").touch()
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG")}
    env.update(HOME=str(home), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(home / "gitconfig"),
               GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="", SSH_ASKPASS="", LC_ALL="C")
    pairs = [("credential.helper", ""), ("core.hooksPath", os.devnull), ("protocol.file.allow",
                                                                         "always" if allow_local else "never")]
    if allow_local:
        pairs.append(("safe.directory", "*"))  # test stand repositories belong to another local user
    if header:
        pairs.append(header)
    env["GIT_CONFIG_COUNT"] = str(len(pairs))
    for i, (key, value) in enumerate(pairs):
        env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = key, value
    return env


def _git(env, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          stdin=subprocess.DEVNULL, timeout=GIT_TIMEOUT, text=True)


def tip(env, mirror: Path, branch: str) -> str | None:
    out = _git(env, "--git-dir", str(mirror), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}")
    return out.stdout.strip() if out.returncode == 0 else None


def sync(config: BoxConfig, mirrors: Path, env_secrets: dict) -> list[dict]:
    """Clone missing mirrors, fetch existing ones. One result per repository; never raises for a repository."""
    from agent_graph.portable import lock_nonblocking, open_lock_file

    mirrors.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = open_lock_file(mirrors / ".sync.lock")
    deadline = time.time() + GIT_TIMEOUT
    while True:
        try:
            lock_nonblocking(lock)
            break
        except BlockingIOError:
            if time.time() > deadline:
                os.close(lock)
                return [{"repository": r.name, "id": r.graph_id, "status": "FAILED", "code": "sync_already_running"}
                        for r in config.github.repositories]
            time.sleep(1)
    try:
        header = None
        token_problem = None
        if any(config.clone_url(r).startswith("https://") for r in config.github.repositories):
            try:
                token = github_token(config, env_secrets)
                basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
                header = (f"http.{config.github.web_base.rstrip('/')}/.extraHeader", f"Authorization: Basic {basic}")
            except KeyError:
                token_problem = "github_secret_missing"
            except Exception as exc:  # connector errors carry a safe code
                token_problem = getattr(exc, "code", "github_token_unavailable")
        env = git_env(mirrors.parent / "run" / "git-home", header=header,
                      allow_local=config.testing.allow_local_sources)
        results = []
        for repo in config.github.repositories:
            url = config.clone_url(repo)
            target = mirrors / f"{repo.graph_id}.git"
            entry = {"repository": repo.name, "id": repo.graph_id}
            if token_problem and url.startswith("https://"):
                results.append({**entry, "status": "FAILED", "code": token_problem,
                                "tip": tip(env, target, repo.branch) if target.exists() else None})
                continue
            if target.exists():
                out = _git(env, "--git-dir", str(target), "fetch", "--prune", "--quiet", "origin")
                action = "fetched"
            else:
                tmp = mirrors / f".clone-{repo.graph_id}-{os.getpid()}"
                shutil.rmtree(tmp, ignore_errors=True)
                out = _git(env, "clone", "--mirror", "--quiet", "--", url, str(tmp))
                if out.returncode == 0:
                    tmp.rename(target)
                else:
                    shutil.rmtree(tmp, ignore_errors=True)
                action = "cloned"
            if out.returncode != 0:
                results.append({**entry, "status": "FAILED", "code": _reason(out.stderr),
                                "tip": tip(env, target, repo.branch) if target.exists() else None})
                continue
            head = tip(env, target, repo.branch)
            if head is None:
                results.append({**entry, "status": "FAILED", "code": "git_branch_not_found", "tip": None})
                continue
            results.append({**entry, "status": "OK", "action": action, "tip": head})
        return results
    finally:
        os.close(lock)
