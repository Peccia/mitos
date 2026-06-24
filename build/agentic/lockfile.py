"""`.deploy-lock.json` — per-machine record of what was deployed and its hashes.

Drift detection is a three-way comparison:
  - fresh render hash  vs  lock.source_hash   -> registry changed since deploy (pending)
  - live file hash     vs  lock.deployed_hash -> file edited in place since deploy (drift)
This mirrors optimistic-concurrency: the lock is the ETag the deploy checks against.
"""
from __future__ import annotations

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
