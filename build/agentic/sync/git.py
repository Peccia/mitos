"""Git overlay sync — reconcile registry/local/ with its hub. Sync is git-only.

The overlay (`registry/local/`) is its own git repo whose remote is your hub — any git URL: a
self-hosted server, a bare repo on a box/NAS, or a private GitHub repo. `mitos sync` reconciles
it: **pull --rebase → deploy → push**, stopping *loudly* on conflict (never auto-resolving,
never forcing).

The setup verbs make the repo on the first machine (`git_init`) and onboard the rest
(`git_clone`); both install the post-merge auto-deploy hook and record this machine's name.
`git_status` reports where the overlay stands against the hub.
"""
from __future__ import annotations

import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .base import SyncError


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        res = subprocess.run(["git", "-C", str(repo), *args],
                             capture_output=True, text=True)
    except FileNotFoundError as e:
        raise SyncError("git not found on PATH — install git to use the git sync backend") from e
    if check and res.returncode != 0:
        raise SyncError(f"`git {' '.join(args)}` failed (rc {res.returncode}): "
                        f"{(res.stderr or res.stdout).strip()}")
    return res


def _cfg(cfg: dict) -> tuple[str, str, str, str | None]:
    git = cfg.get("git") or {}
    hub = git.get("hub")
    if not hub:
        raise SyncError("git backend needs sync.git.hub (the overlay repo's remote URL)")
    return hub, git.get("remote") or "origin", git.get("branch") or "main", git.get("ssh_key")


def _resolve_key_path(ssh_key) -> Path:
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


def _ssh_command(ssh_key) -> str | None:
    """The `core.sshCommand` value that pins git to a user-chosen private key (resolved to an
    absolute path). `IdentitiesOnly` keeps ssh from offering every agent key — which also means a
    wrong `-i` path fails hard rather than silently, so the path must be right."""
    if not ssh_key:
        return None
    key = _resolve_key_path(ssh_key).as_posix()
    return f'ssh -i "{key}" -o IdentitiesOnly=yes'


def _check_key(ssh_key) -> None:
    """Fail early with a clear message when a named key file is missing — far better than ssh's
    downstream 'Permission denied (publickey)' (rc 128) after IdentitiesOnly blocks the fallback."""
    if not ssh_key:
        return
    key = _resolve_key_path(ssh_key)
    if not key.exists():
        raise SyncError(
            f"ssh key not found at {key.as_posix()} (from {ssh_key!r}). Pass the path to your "
            f"private key — a bare name is looked up in ~/.ssh, or give an absolute path.")


def _apply_ssh_key(overlay: Path, ssh_key) -> str | None:
    """Persist the chosen key as the overlay repo's `core.sshCommand`, so *every* git operation on
    it — sync, the post-merge pull, a bare cron `git pull` — authenticates with that key. Clearing
    it when `ssh_key` is unset keeps the profile the single source of truth."""
    cmd = _ssh_command(ssh_key)
    if cmd is None:
        _git(overlay, "config", "--unset", "core.sshCommand", check=False)
        return None
    _git(overlay, "config", "core.sshCommand", cmd)
    key = _resolve_key_path(ssh_key)
    note = f"ssh key: {key.as_posix()} (core.sshCommand)"
    if not key.exists():
        note += "  [warning: no file there — ssh will fail to authenticate]"
    return note


def _normalize(url: str) -> str:
    """Loosely normalize a git URL for comparison — tolerate \\ vs /, trailing .git/slash, case."""
    u = url.strip().replace("\\", "/").rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    return u.lower()


def _verify_hub(overlay: Path, remote: str, hub: str) -> None:
    res = _git(overlay, "remote", "get-url", remote, check=False)
    if res.returncode != 0:
        raise SyncError(f"overlay repo has no remote {remote!r} — run `mitos sync init` to set "
                        f"the hub first")
    actual = res.stdout.strip()
    if _normalize(actual) != _normalize(hub):
        raise SyncError(f"refusing to sync: overlay remote {remote!r} is {actual!r}, not the "
                        f"configured hub {hub!r}. (Guards against pushing your private overlay "
                        f"to the wrong remote.)")


def _assert_clean(overlay: Path) -> None:
    dirty = _git(overlay, "status", "--porcelain").stdout.strip()
    if dirty:
        raise SyncError("registry/local/ has uncommitted changes — commit (or stash) them "
                        "before syncing, so what you share is intentional:\n" + dirty)


def git_sync(repo_root, machine: str, cfg: dict, *, action: str = "all",
             dry_run: bool = False, deploy=None) -> list[str]:
    """Reconcile the overlay repo with its hub. `deploy` is a callable(machine)->int run
    between pull and push (the down-direction); pass None to skip it (tests)."""
    overlay = Path(repo_root) / "registry" / "local"
    hub, remote, branch, ssh_key = _cfg(cfg)
    if not (overlay / ".git").exists():
        raise SyncError(f"{overlay.as_posix()} is not a git repo yet — run `mitos sync init` "
                        f"or `mitos sync clone` first")
    _verify_hub(overlay, remote, hub)
    _apply_ssh_key(overlay, ssh_key)   # reconcile the repo's key with the profile before any fetch
    gitdir = overlay / ".git"
    if (gitdir / "rebase-merge").exists() or (gitdir / "rebase-apply").exists():
        raise SyncError("a previous sync left an unresolved rebase in registry/local/ — finish "
                        "it (`git rebase --continue`) or abort it (`git rebase --abort`), then "
                        "re-run. Never force.")
    lines: list[str] = []

    if dry_run:
        _git(overlay, "fetch", remote, branch)
        behind = _git(overlay, "rev-list", "--count", f"HEAD..{remote}/{branch}",
                      check=False).stdout.strip() or "0"
        ahead = _git(overlay, "rev-list", "--count", f"{remote}/{branch}..HEAD",
                     check=False).stdout.strip() or "0"
        lines.append(f"dry-run: {behind} commit(s) to pull, {ahead} to push "
                     f"({remote}/{branch}) — nothing changed")
        return lines

    _assert_clean(overlay)

    if action in ("pull", "all"):
        lines.append(_pull(overlay, remote, branch))
        lines += _deploy(deploy, machine)
    elif action == "refresh":
        lines += _deploy(deploy, machine)

    if action in ("push", "all"):
        lines.append(_push(overlay, remote, branch))
    return lines


def _deploy(deploy, machine: str) -> list[str]:
    if deploy is None:
        return []
    rc = deploy(machine)
    if rc != 0:
        raise SyncError(f"deploy --machine {machine} failed (rc {rc}) — overlay synced but not "
                        f"applied to the harnesses; fix and re-run")
    return [f"deploy: applied overlay to {machine}"]


def _pull(overlay: Path, remote: str, branch: str) -> str:
    res = _git(overlay, "pull", "--rebase", remote, branch, check=False)
    if res.returncode != 0:
        raise SyncError("git pull --rebase hit a conflict (or failed) in registry/local/. "
                        "Resolve it by hand (edit + `git rebase --continue`, or `git rebase "
                        "--abort`), then re-run `mitos sync`. Never force.\n"
                        + (res.stderr or res.stdout).strip())
    return f"pull: rebased onto {remote}/{branch}"


def _push(overlay: Path, remote: str, branch: str) -> str:
    res = _git(overlay, "push", remote, branch, check=False)
    if res.returncode != 0:
        raise SyncError("git push was rejected (a peer likely pushed first). Re-run `mitos "
                        "sync` to pull their changes, then it will push. Never force-push.\n"
                        + (res.stderr or res.stdout).strip())
    return f"push: published to {remote}/{branch}"


# ── setup: make the overlay a repo (init) / onboard a new machine (clone) ──────────────────

_HOOK = """#!/bin/sh
# Mitos auto-deploy — re-materialize this machine's harnesses after a pull brings new overlay
# content. Installed by `mitos sync init|clone`; re-run either verb to regenerate after a move.
MITOS_PY="{py}"
MITOS_ROOT="{root}"
[ -f "$MITOS_ROOT/build/compile.py" ] || exit 0
changed=$(git diff-tree -r --name-only ORIG_HEAD HEAD 2>/dev/null)
[ -z "$changed" ] && exit 0
exec "$MITOS_PY" "$MITOS_ROOT/build/compile.py" deploy --machine "$(git config mitos.machine)"
"""


def _overlay(repo_root) -> Path:
    return Path(repo_root) / "registry" / "local"


def _ensure_identity(overlay: Path) -> None:
    """A commit needs an author. Real users have a global git identity; set a benign per-repo
    fallback only when none is configured (so init never dies on a fresh/CI box). Never override
    an existing identity."""
    if not _git(overlay, "config", "user.email", check=False).stdout.strip():
        _git(overlay, "config", "user.email", "mitos@localhost")
        _git(overlay, "config", "user.name", "Mitos")


def _install_post_merge_hook(overlay: Path, interpreter, repo_root) -> Path:
    hooks = overlay / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "post-merge"
    hook.write_text(_HOOK.format(py=Path(interpreter).as_posix(),
                                 root=Path(repo_root).as_posix()), encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return hook


def _local_hub_path(hub: str) -> Path | None:
    """Return a Path if `hub` is a reachable LOCAL filesystem location (one we can `git init
    --bare`), else None for any network remote (ssh/https/scp-style). Conservative on purpose:
    a misclassified remote just means we skip auto-create and the push reports a clear error."""
    if hub.startswith("file://"):
        rest = hub[len("file://"):]
        if re.match(r"^/[A-Za-z]:", rest):   # file:///C:/x → /C:/x → C:/x
            rest = rest[1:]
        return Path(rest)
    if "://" in hub:                          # ssh:// https:// git:// → remote
        return None
    if re.match(r"^[A-Za-z]:[\\/]", hub):     # C:\ or C:/ Windows drive → local
        return Path(hub)
    if ":" in hub:                            # host:path / git@host:path (scp-style) → remote
        return None
    return Path(hub)                          # /srv/git/x.git or ./x.git → local


def _maybe_create_bare(hub: str, branch: str) -> str | None:
    """If the hub is a local path whose bare repo doesn't exist yet, create it. Hosted providers
    (GitHub/GitLab) and ssh remotes are left alone — create those before init."""
    path = _local_hub_path(hub)
    if path is None or (path / "HEAD").exists() or (path / "refs").exists():
        return None
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "--bare")
    _git(path, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    return f"created bare hub at {path.as_posix()}"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def git_init(repo_root, machine: str, hub: str, *, remote: str = "origin",
             branch: str = "main", interpreter=None, ssh_key=None) -> list[str]:
    """Turn registry/local/ into a git repo on your first machine: create the bare hub if it's a
    reachable local path, commit the current overlay, install the auto-deploy hook, record this
    machine's name, pin the ssh key (if given), and push. For a hosted provider create the empty
    PRIVATE repo first."""
    overlay = _overlay(repo_root)
    if (overlay / ".git").exists():
        raise SyncError(f"{overlay.as_posix()} is already a git repo — use `mitos sync` to sync "
                        f"it, or `mitos sync status` to inspect it")
    _check_key(ssh_key)   # fail before making a repo we can't push
    overlay.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    note = _maybe_create_bare(hub, branch)
    if note:
        lines.append(note)
    _git(overlay, "init")
    _git(overlay, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    _ensure_identity(overlay)
    _git(overlay, "add", "-A")
    _git(overlay, "commit", "-m", "mitos overlay: initial commit", "--allow-empty")
    _git(overlay, "remote", "add", remote, hub)
    _git(overlay, "config", "mitos.machine", machine)
    keyline = _apply_ssh_key(overlay, ssh_key)   # pin the key BEFORE the push needs it
    hook = _install_post_merge_hook(overlay, interpreter or sys.executable, repo_root)
    lines.append(f"initialized overlay repo at {overlay.as_posix()} (machine {machine})")
    if keyline:
        lines.append(keyline)
    lines.append(f"installed auto-deploy hook: {hook.relative_to(Path(repo_root)).as_posix()}")
    res = _git(overlay, "push", "-u", remote, branch, check=False)
    if res.returncode != 0:
        raise SyncError(
            "first push to the hub failed. For a hosted provider (GitHub/GitLab) create the "
            "empty PRIVATE repo first, then re-run. For a self-hosted server make sure the bare "
            "repo exists and you can reach it (ssh key / credential helper).\n"
            + (res.stderr or res.stdout).strip())
    lines.append(f"pushed initial overlay to {remote}/{branch} ({hub})")
    lines.append("next: add a `sync: {git: {hub: ...}}` block to this machine's profile, then "
                 "`mitos sync` keeps it in step")
    return lines


def git_clone(repo_root, machine: str, hub: str, *, remote: str = "origin",
              branch: str = "main", interpreter=None, ssh_key=None) -> list[str]:
    """Onboard a new machine: clone the overlay from the hub into registry/local/, install the
    auto-deploy hook, record this machine's name, and pin the ssh key (if given). An existing
    overlay is moved aside first so nothing is clobbered — reconcile its machine-specific files
    into the clone afterwards."""
    overlay = _overlay(repo_root)
    if (overlay / ".git").exists():
        raise SyncError(f"{overlay.as_posix()} is already a git repo — use `mitos sync` to sync "
                        f"it, not clone over it")
    _check_key(ssh_key)   # fail before moving anything aside or hitting the network
    lines: list[str] = []
    if overlay.exists() and any(overlay.iterdir()):
        backup = overlay.parent / f"local.backup-{_stamp()}"
        overlay.rename(backup)
        lines.append(f"existing registry/local/ moved aside to {backup.name} — reconcile its "
                     f"machine-specific files (e.g. machines/{machine}.yaml) into the clone")
    overlay.parent.mkdir(parents=True, exist_ok=True)
    sshcmd = _ssh_command(ssh_key)
    pre = ["-c", f"core.sshCommand={sshcmd}"] if sshcmd else []   # the clone itself needs the key
    _git(overlay.parent, *pre, "clone", "--origin", remote, "--branch", branch, hub, overlay.name)
    _ensure_identity(overlay)
    _git(overlay, "config", "mitos.machine", machine)
    keyline = _apply_ssh_key(overlay, ssh_key)   # persist it for future pulls/pushes + the hook
    hook = _install_post_merge_hook(overlay, interpreter or sys.executable, repo_root)
    lines.append(f"cloned overlay from {hub} into {overlay.as_posix()} (machine {machine})")
    if keyline:
        lines.append(keyline)
    lines.append(f"installed auto-deploy hook: {hook.relative_to(Path(repo_root)).as_posix()}")
    lines.append(f"next: `mitos sync --machine {machine}` to deploy this machine's harnesses")
    return lines


def git_status(repo_root, cfg: dict, machine: str) -> list[str]:
    """Report where the overlay stands: recorded machine, hub, ahead/behind counts, dirty tree."""
    overlay = _overlay(repo_root)
    hub, remote, branch, ssh_key = _cfg(cfg)
    if not (overlay / ".git").exists():
        raise SyncError(f"{overlay.as_posix()} is not a git repo yet — run `mitos sync init` "
                        f"or `mitos sync clone` first")
    _verify_hub(overlay, remote, hub)
    keyline = _apply_ssh_key(overlay, ssh_key)
    recorded = _git(overlay, "config", "mitos.machine", check=False).stdout.strip()
    _git(overlay, "fetch", remote, branch, check=False)
    behind = _git(overlay, "rev-list", "--count", f"HEAD..{remote}/{branch}",
                  check=False).stdout.strip() or "0"
    ahead = _git(overlay, "rev-list", "--count", f"{remote}/{branch}..HEAD",
                 check=False).stdout.strip() or "0"
    dirty = _git(overlay, "status", "--porcelain").stdout.strip()
    lines = [f"overlay: {overlay.as_posix()} (machine {recorded or '—'}, hub {hub})"]
    if keyline:
        lines.append(keyline)
    lines.append(f"{behind} behind / {ahead} ahead of {remote}/{branch}")
    lines.append("working tree: " + (f"dirty\n{dirty}" if dirty else "clean"))
    return lines
