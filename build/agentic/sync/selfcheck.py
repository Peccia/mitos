"""Compiler self-check: compare local build/ against the official upstream branch.

Reads git metadata only — never writes, never executes fetched code. The check is
intentionally non-fatal: a behind notice is informational. The caller decides whether to
print it or suppress it (compiler_sync: false in the machine profile turns it off).
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _pick_remote(repo_root: Path) -> str | None:
    """The remote that tracks the OFFICIAL repo. A contributor clones their fork (origin)
    and adds `upstream` for the official repo, so prefer `upstream` when it exists; a plain
    user clones official directly, so `origin` is official for them. None = no remotes."""
    res = _git(repo_root, "remote")
    if res.returncode != 0:
        return None
    remotes = res.stdout.split()
    if "upstream" in remotes:
        return "upstream"
    if "origin" in remotes:
        return "origin"
    return None


def check_compiler(repo_root: Path, remote: str | None = None,
                   branch: str = "main") -> str | None:
    """Return a human-readable notice when the local build/ is behind the official branch,
    or None when up-to-date, unreachable, or not in a git repo.

    `remote` defaults to auto-detection: `upstream` (a contributor's official remote) if
    present, else `origin` (a plain user's official remote). Does a `git fetch` (network,
    may be slow; the caller suppresses via the compiler_sync flag). All errors are swallowed
    — a broken remote must never block the primary command."""
    try:
        # must be inside a git repo
        top = _git(repo_root, "rev-parse", "--show-toplevel")
        if top.returncode != 0:
            return None

        if remote is None:
            remote = _pick_remote(repo_root)
            if remote is None:
                return None  # no remotes configured — nothing to compare against

        fetch = _git(repo_root, "fetch", remote, branch)
        if fetch.returncode != 0:
            return None  # no network, private repo without creds, etc. — silent

        ref = f"{remote}/{branch}"
        # count commits where build/ changed on upstream but not locally
        log = _git(repo_root, "log", "--oneline", f"HEAD..{ref}", "--", "build/")
        if log.returncode != 0 or not log.stdout.strip():
            return None

        n = len(log.stdout.strip().splitlines())
        return (
            f"notice: the compiler (build/) is {n} commit(s) behind {remote}/{branch}.\n"
            f"  To update:  git pull {remote} {branch}\n"
            f"  To skip this check: set compiler_sync: false in your machine profile's sync: block."
        )
    except (FileNotFoundError, OSError):
        return None  # git not on PATH — skip silently
