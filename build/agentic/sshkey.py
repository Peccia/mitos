"""Shared SSH private-key resolution for git operations against a chosen identity — used by
both the registry/local/ overlay sync (`sync/git.py`) and project repo auto-clone
(`commands.py`, via `repo_ssh_keys:`) so the path-resolution logic exists exactly once.
"""
from __future__ import annotations

from pathlib import Path


def resolve_key_path(ssh_key) -> Path:
    """Turn a user-supplied key into an **absolute** path. git runs `core.sshCommand` with its own
    working directory (the clone's parent), so a relative `-i` arg resolves against the wrong place
    and ssh silently can't find the key. A bare filename (no separator) means the conventional
    `~/.ssh/<name>`; anything with a path is expanded and made absolute against the invocation cwd."""
    raw = str(ssh_key).strip()
    key = Path(raw).expanduser()
    if key.is_absolute():
        return key
    if raw == Path(raw).name:                 # bare filename → standard ~/.ssh location
        return Path.home() / ".ssh" / raw
    return (Path.cwd() / key).resolve()        # relative path → absolute against where we were run


def ssh_command(ssh_key) -> str | None:
    """The `core.sshCommand` value that pins git to a user-chosen private key (resolved to an
    absolute path). `IdentitiesOnly` keeps ssh from offering every agent key — which also means a
    wrong `-i` path fails hard rather than silently, so the path must be right."""
    if not ssh_key:
        return None
    key = resolve_key_path(ssh_key).as_posix()
    return f'ssh -i "{key}" -o IdentitiesOnly=yes'
