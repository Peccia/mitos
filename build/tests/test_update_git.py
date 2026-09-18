"""`mitos update` against real git: a core repo, an overlay cloned from a local bare hub, and a
sandbox assistant_root — the dirty/rebase/conflict states a fake git cannot model honestly."""
from __future__ import annotations

from pathlib import Path

import yaml

from conftest import (
    _clone_overlay, _git_available, _make_overlay_hub, _run_git, _temp_registry,
)

_SKILL = """---
name: {name}
description: "Update test skill {name}."
version: 1.0.0
targets: [mitos-agent]
category: productivity
---

# {name}

{body}
"""


def _rig(tmp_path):
    """(repo_root, overlay, hub, peer): a git core repo whose `rig` machine syncs to `hub`."""
    hub = _make_overlay_hub(tmp_path)
    _treg, root = _temp_registry()
    profile_path = root / "machines" / "rig.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["sync"] = {"git": {"hub": str(hub), "branch": "main"}}
    profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")
    (root / ".gitignore").write_text("registry/local/\n.deploy-lock.json*\nhome/\ndist/\n",
                                     encoding="utf-8")
    _run_git(root, "init", "-b", "main")
    _run_git(root, "config", "user.email", "core@example.com")
    _run_git(root, "config", "user.name", "core")
    _run_git(root, "add", "-A")
    _run_git(root, "commit", "-m", "core")
    overlay = root / "registry" / "local"
    _run_git(tmp_path, "clone", str(hub), str(overlay))
    _run_git(overlay, "config", "user.email", "rig@example.com")
    _run_git(overlay, "config", "user.name", "rig")
    _peer_root, peer = _clone_overlay(tmp_path, hub, "peer")
    return root, overlay, hub, peer


def _push_skill(peer: Path, name: str, body: str) -> None:
    d = peer / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(_SKILL.format(name=name, body=body), encoding="utf-8",
                                newline="\n")
    _run_git(peer, "add", "-A")
    _run_git(peer, "commit", "-m", f"skill {name}")
    _run_git(peer, "push", "origin", "main")


def _update(root: Path, **kw) -> dict:
    from agentic.update import run_update
    return run_update(root, "rig", scheduled=kw.pop("scheduled", False),
                      skip_core_pull=False, dry_run=False)


def test_hub_advance_is_pulled_and_the_new_skill_deployed(tmp_path):
    if not _git_available():
        return
    root, overlay, _hub, peer = _rig(tmp_path)
    _push_skill(peer, "update-probe", "first text")
    result = _update(root)
    assert result["ok"] is True, result
    assert result["core"]["skipped_reason"] == "no upstream"
    assert result["overlay"]["pulled"] is True
    assert result["overlay"]["before"] != result["overlay"]["after"]
    assert any(p.endswith("update-probe/SKILL.md") for p in result["deploy"]["written"])
    assert (root / "home/MitosAgent/skills/productivity/update-probe/SKILL.md").exists()


def test_dirty_overlay_skips_the_pull_and_still_deploys(tmp_path):
    if not _git_available():
        return
    root, overlay, _hub, peer = _rig(tmp_path)
    assert _update(root)["ok"] is True
    (overlay / "inbox" / "cand-1").mkdir(parents=True)
    (overlay / "inbox" / "cand-1" / "meta.yaml").write_text("kind: report\n", encoding="utf-8")
    _push_skill(peer, "later-skill", "not pulled yet")
    result = _update(root)
    assert result["overlay"]["skipped_reason"] == "dirty"
    assert result["overlay"]["pulled"] is False
    assert result["deploy"] is not None and result["deploy"]["rc"] == 0
    assert not (root / "home/MitosAgent/skills/productivity/later-skill").exists()


def test_leftover_rebase_stops_before_deploy(tmp_path):
    if not _git_available():
        return
    root, overlay, _hub, _peer = _rig(tmp_path)
    (overlay / ".git" / "rebase-merge").mkdir()
    result = _update(root)
    assert result["ok"] is False and "rebase" in result["error"]
    assert result["deploy"] is None
    assert not (root / "home/MitosAgent/SOUL.md").exists()


def test_pull_conflict_reports_and_leaves_the_rebase_for_the_owner(tmp_path):
    if not _git_available():
        return
    root, overlay, _hub, peer = _rig(tmp_path)
    (peer / "identity" / "who.md").write_text("peer\n", encoding="utf-8")
    _run_git(peer, "commit", "-am", "peer edit")
    _run_git(peer, "push", "origin", "main")
    (overlay / "identity" / "who.md").write_text("local\n", encoding="utf-8")
    _run_git(overlay, "commit", "-am", "local edit")
    result = _update(root)
    assert result["ok"] is False and result["overlay"]["conflict"] is True
    assert result["deploy"] is None
    git = overlay / ".git"
    assert (git / "rebase-merge").exists() or (git / "rebase-apply").exists()


def test_dirty_core_manual_deploys_scheduled_does_nothing(tmp_path):
    if not _git_available():
        return
    root, _overlay, _hub, _peer = _rig(tmp_path)
    servers = root / "connections" / "servers.yaml"
    servers.write_text(servers.read_text(encoding="utf-8") + "\n# local edit\n",
                       encoding="utf-8")
    scheduled = _update(root, scheduled=True)
    assert scheduled["ok"] is True and scheduled["skipped"] == "core dirty (scheduled)"
    assert scheduled["deploy"] is None and not (root / "home/MitosAgent/SOUL.md").exists()
    manual = _update(root)
    assert manual["core"]["skipped_reason"] == "dirty"
    assert manual["deploy"]["rc"] == 0 and (root / "home/MitosAgent/SOUL.md").exists()


def test_blocked_protected_drift_is_reported_not_forced(tmp_path):
    if not _git_available():
        return
    root, _overlay, _hub, _peer = _rig(tmp_path)
    assert _update(root)["ok"] is True
    soul = root / "home/MitosAgent/SOUL.md"
    soul.write_text(soul.read_text(encoding="utf-8") + "\nrogue\n", encoding="utf-8")
    result = _update(root)
    assert result["ok"] is False and result["error"] is None
    assert [p for p in result["deploy"]["blocked"] if p.endswith("SOUL.md")]
    assert "rogue" in soul.read_text(encoding="utf-8")
