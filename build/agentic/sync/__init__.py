"""Git-backed overlay sync (Mitos).

Sync is **git-only**: the private overlay (`registry/local/`) is its own git repo, reconciled
with its hub (any git URL — self-hosted or a private GitHub repo) by `git_sync`:
pull --rebase → deploy → push, stop-on-conflict. `git_init`/`git_clone` set the repo up on the
first and subsequent machines; `git_status` reports where it stands against the hub.

Like the connectors, this lives **beside** the compiler and is never imported by the
deterministic verbs (compile / deploy / diff / adopt / harvest).
"""
from .base import SyncError
from .git import git_clone, git_init, git_status, git_sync

__all__ = ["SyncError", "git_sync", "git_init", "git_clone", "git_status"]
