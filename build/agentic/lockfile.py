"""`.deploy-lock.json` — per-machine record of what was deployed and its hashes.

Drift detection is a three-way comparison:
  - fresh render hash  vs  lock.source_hash   -> registry changed since deploy (pending)
  - live file hash     vs  lock.deployed_hash -> file edited in place since deploy (drift)
This mirrors optimistic-concurrency: the lock is the ETag the deploy checks against.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path

from .io import dump_json, load_json

LOCK_NAME = ".deploy-lock.json"


def path(repo_root: Path) -> Path:
    return repo_root / LOCK_NAME


def load(repo_root: Path) -> dict:
    data = load_json(path(repo_root))
    data.setdefault("machines", {})
    return data


def save(repo_root: Path, data: dict) -> None:
    dump_json(path(repo_root), data)


def machine_files(data: dict, machine: str) -> dict:
    return data.get("machines", {}).get(machine, {}).get("files", {})


def record(data: dict, machine: str, deployed_at: str, files: dict) -> None:
    data.setdefault("machines", {})[machine] = {
        "deployed_at": deployed_at,
        "files": files,
    }


class LockBusy(Exception):
    """Another process holds the deploy lock for this repo."""


def _describe(lock: Path) -> str:
    try:
        info = json.loads(lock.read_text(encoding="utf-8"))
        return f"deploy in progress (pid {info.get('pid')} since {info.get('started')})"
    except (OSError, ValueError):
        return "deploy in progress (lock holder unknown)"


@contextmanager
def deploy_lock(lock_base: Path, *, wait: float = 10.0, stale_after: float = 900.0):
    """Cross-process mutex for one repo's .deploy-lock.json, which every machine's section
    shares. O_CREAT|O_EXCL on <lock_base>/.deploy-lock.json.lock holding {pid, host, started}.
    Stale = mtime older than stale_after (15 min, above the agent's 10-min timeout); a stale
    lock is unlinked once and acquisition retried. Age only — no pid probe (os.kill on
    Windows terminates the process)."""
    lock = Path(lock_base) / (LOCK_NAME + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + wait
    broke_stale = False
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                continue                      # released between open and stat — retry now
            if age > stale_after and not broke_stale:
                broke_stale = True
                try:
                    lock.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise LockBusy(_describe(lock)) from None
            time.sleep(0.2)
    try:
        started = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        os.write(fd, json.dumps({"pid": os.getpid(), "host": socket.gethostname(),
                                 "started": started}).encode("utf-8"))
    finally:
        os.close(fd)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
