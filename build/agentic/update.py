"""`mitos update` — core pull → overlay pull → deploy, reported as one `schema: 1` object.

The unattended counterpart of `mitos sync pull`, built for a caller that reads data rather
than prose (MitosAgent's updater). Invariants:
  - never force, prune, adopt, or push — `force`/`prune` are literals at the deploy call;
  - the first terminal condition wins, and every outcome carries every schema key;
  - a dirty checkout skips its pull, never stashes or resets it. A *scheduled* run with a
    dirty core does nothing at all (a timer must not deploy half-finished edits);
  - after the core pull moves HEAD the rest runs in a fresh interpreter, because the compiler
    modules already imported here are the pre-pull ones. A changed `build/requirements.txt`
    stops the run: the venv must be reinstalled by the owner first.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

from . import commands, loader
from .sync import SyncError, git_sync

SCHEMA = 1
_REQUIREMENTS = "build/requirements.txt"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


def _reexec(argv: list[str], cwd: Path) -> tuple[int, str]:
    """Run the child with stderr passed through (its deploy prose), stdout captured (its JSON)."""
    res = subprocess.run(argv, cwd=str(cwd), stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
    return res.returncode, res.stdout.decode("utf-8", errors="replace")


def _blank(machine: str, scheduled: bool) -> dict:
    return {"schema": SCHEMA, "ok": False, "machine": machine, "scheduled": scheduled,
            "started": _now(), "finished": None, "skipped": None, "error": None,
            "core": None, "overlay": None, "deploy": None}


def _finish(result: dict) -> dict:
    d = result["deploy"]
    result["ok"] = result["error"] is None and bool(
        result["skipped"] or (d is not None and d["rc"] == 0 and not d["blocked"]))
    result["finished"] = _now()
    return result


def _head(git, repo: Path) -> str | None:
    res = git(repo, "rev-parse", "HEAD")
    return res.stdout.strip() if res.returncode == 0 else None


def _dirty(git, repo: Path, *, untracked: bool) -> bool:
    args = ["status", "--porcelain"] + ([] if untracked else ["--untracked-files=no"])
    res = git(repo, *args)
    if res.returncode != 0:
        raise SyncError(f"`git status` failed in {repo.as_posix()}: {res.stderr.strip()}")
    return bool(res.stdout.strip())


def _deploy_block(outcome: commands.DeployOutcome) -> dict:
    return dataclasses.asdict(outcome)


def run_update(repo_root: Path, machine: str, *, scheduled: bool, skip_core_pull: bool,
               dry_run: bool, git=_git, reexec=_reexec, load=loader.load) -> dict:
    repo_root = Path(repo_root)
    result = _blank(machine, scheduled)
    try:
        return _run(repo_root, machine, result, scheduled=scheduled,
                    skip_core_pull=skip_core_pull, dry_run=dry_run, git=git, reexec=reexec,
                    load=load)
    except SyncError as e:
        result["error"] = str(e)
        return _finish(result)


def _run(repo_root, machine, result, *, scheduled, skip_core_pull, dry_run, git, reexec,
         load) -> dict:
    # 1. core checkout state. Tracked edits only: an untracked scratch file is not a half-edit.
    core_dirty = _dirty(git, repo_root, untracked=False)
    branch = git(repo_root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or None
    before = _head(git, repo_root)
    core = result["core"] = {"branch": branch, "before": before, "after": before,
                             "pulled": False, "skipped_reason": None,
                             "requirements_changed": False}
    if core_dirty and scheduled:
        result["skipped"] = "core dirty (scheduled)"
        return _finish(result)

    # 2. core pull — fast-forward only
    if core_dirty:
        core["skipped_reason"] = "dirty"
    elif skip_core_pull:
        core["skipped_reason"] = "re-exec"
    elif dry_run:
        core["skipped_reason"] = "dry-run"
    elif git(repo_root, "rev-parse", "--abbrev-ref", "@{u}").returncode != 0:
        core["skipped_reason"] = "no upstream"
    else:
        res = git(repo_root, "pull", "--ff-only")
        if res.returncode != 0:
            text = (res.stderr or res.stdout).lower()
            if "fast-forward" in text or "diverg" in text:
                core["skipped_reason"] = "not fast-forward"
            else:
                result["error"] = f"core pull failed: {(res.stderr or res.stdout).strip()}"
                return _finish(result)
        else:
            core["after"] = _head(git, repo_root)
            core["pulled"] = core["after"] != before

    # 3. HEAD moved: stop on a dependency change, else continue in a fresh interpreter
    if core["pulled"]:
        changed = git(repo_root, "diff", "--name-only", before, core["after"]).stdout.split()
        if _REQUIREMENTS in changed:
            core["requirements_changed"] = True
            result["error"] = (f"{_REQUIREMENTS} changed — reinstall the venv, then re-run")
            return _finish(result)
        argv = [sys.executable, str(repo_root / "build" / "mitos.py"), "update",
                "--machine", machine, "--skip-core-pull", "--json"]
        if scheduled:
            argv.append("--scheduled")
        try:
            _rc, out = reexec(argv, repo_root)
            lines = [ln for ln in out.splitlines() if ln.strip()]
            child = json.loads(lines[-1]) if lines else None
        except (OSError, ValueError) as e:
            child, out = None, repr(e)
        if not isinstance(child, dict):
            result["error"] = f"re-exec failed: no JSON from the child ({out.strip()[:200]!r})"
            return _finish(result)
        child["core"] = core
        child["started"] = result["started"]
        return _finish(child)

    # 4. machine + sync config, from the registry as it is on disk now
    try:
        reg = load(repo_root)
    except loader.RegistryError as e:
        result["error"] = f"registry invalid: {e}"
        return _finish(result)
    profile = reg.machines.get(machine)
    if profile is None:
        result["error"] = f"unknown machine {machine!r}"
        return _finish(result)
    cfg = profile.get("sync") or {}
    if not (cfg.get("git") or {}).get("hub"):
        result["error"] = f"machine {machine!r} has no sync.git.hub configured"
        return _finish(result)

    # 5. overlay
    overlay = repo_root / "registry" / "local"
    gitdir = overlay / ".git"
    if not gitdir.exists():
        result["error"] = f"{overlay.as_posix()} is not a git repo — run `mitos sync clone` first"
        return _finish(result)
    if (gitdir / "rebase-merge").exists() or (gitdir / "rebase-apply").exists():
        result["error"] = ("an unresolved rebase is left in registry/local/ — finish it "
                           "(`git rebase --continue`) or abort it (`git rebase --abort`)")
        return _finish(result)
    obefore = _head(git, overlay)
    ov = result["overlay"] = {"before": obefore, "after": obefore, "pulled": False,
                              "skipped_reason": None, "conflict": False}
    holder: dict = {}

    def deploy(m: str) -> int:
        try:
            fresh = load(repo_root)            # the just-pulled overlay, never the snapshot
        except loader.RegistryError as err:
            holder["registry_error"] = f"registry invalid after pull: {err}"
            return 1
        holder["outcome"] = commands.run_deploy(fresh, m, dry_run, False, prune=False)
        return holder["outcome"].rc

    if _dirty(git, overlay, untracked=True):
        ov["skipped_reason"] = "dirty"
        deploy(machine)
    elif dry_run:
        ov["skipped_reason"] = "dry-run"
        deploy(machine)
    else:
        try:
            git_sync(repo_root, machine, cfg, action="pull", deploy=deploy)
            ov["pulled"] = True
        except SyncError as e:
            if "outcome" not in holder and "registry_error" not in holder:
                ov["conflict"] = (gitdir / "rebase-merge").exists() or \
                    (gitdir / "rebase-apply").exists()
                result["error"] = str(e)
            else:
                ov["pulled"] = True
        ov["after"] = _head(git, overlay)

    # 6. deploy
    if "registry_error" in holder:
        result["deploy"] = {"rc": 1, "dry_run": dry_run, "counts": {}, "written": [],
                            "blocked": [], "captured": [], "orphans": [],
                            "error": holder["registry_error"]}
    elif "outcome" in holder:
        out = holder["outcome"]
        result["deploy"] = _deploy_block(out)
        if out.error and "deploy in progress" in out.error:
            result["error"] = "busy: " + out.error.removeprefix("error: ")
    return _finish(result)
