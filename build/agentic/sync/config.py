"""Capture a machine's sync config into its overlay profile — the YAML that `mitos sync` reads.

`mitos sync init`/`clone` configure the git *repo* (remote, core.sshCommand, mitos.machine), but
the day-to-day flow reads hub/branch/remote/ssh_key from `registry/local/machines/<name>.yaml`.
This module bridges the two: it writes that `sync:` block so the user never has to hand-edit it.

Safe by construction: it only *appends* a block when the profile has none yet (preserving the
file's existing content and comments via a text append, not a lossy YAML round-trip); when a
`sync:` block already exists, or the profile is missing, it reports rather than overwrites.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def sync_block_yaml(hub: str, *, remote: str = "origin", branch: str = "main",
                    ssh_key=None) -> str:
    """The `sync:` YAML block, with only the keys that differ from the defaults (besides hub and
    branch, which are always written so the configured branch is explicit)."""
    git = [f'    hub: "{hub}"']
    if remote and remote != "origin":
        git.append(f'    remote: "{remote}"')
    git.append(f'    branch: "{branch}"')
    if ssh_key:
        git.append(f'    ssh_key: "{ssh_key}"')
    return ("# How this machine reaches its overlay hub (written by `mitos sync init`).\n"
            "sync:\n  git:\n" + "\n".join(git) + "\n")


def ensure_profile_sync_block(repo_root, machine: str, hub: str, *, remote: str = "origin",
                              branch: str = "main", ssh_key=None) -> str:
    """Make `registry/local/machines/<machine>.yaml` carry the sync config. Returns a human
    message describing what happened. Never overwrites an existing `sync:` block."""
    profile = Path(repo_root) / "registry" / "local" / "machines" / f"{machine}.yaml"
    block = sync_block_yaml(hub, remote=remote, branch=branch, ssh_key=ssh_key)
    if not profile.exists():
        return (f"profile registry/local/machines/{machine}.yaml not found — create it (copy a "
                f"machines/example-*.yaml template and remove `example: true`), then add:\n\n"
                f"{block}")
    try:
        data = yaml.safe_load(profile.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        data = {}
    if isinstance(data, dict) and data.get("sync"):
        return (f"registry/local/machines/{machine}.yaml already has a sync block — leaving it "
                f"untouched. The config for this hub would be:\n\n{block}")
    text = profile.read_text(encoding="utf-8")
    sep = "" if text.endswith("\n") else "\n"
    profile.write_text(text + sep + "\n" + block, encoding="utf-8")
    return f"captured sync config into registry/local/machines/{machine}.yaml"
