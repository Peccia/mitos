"""Shared fixtures and helpers for the mitos compiler test suite.

pytest auto-imports this file, making all helpers available to every test_*.py file.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "build"))

from agentic import loader, planner, render  # noqa: E402
from agentic import commands
from agentic.commands import classify_output  # noqa: E402

# Globally mock _git_clone for all tests to prevent real network calls and clone operations.
# Individual tests can still override this temporarily by monkeypatching commands._git_clone.
def _test_safe_git_clone(repo: str, dest: Path) -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    (dest / ".git").mkdir(parents=True, exist_ok=True)
    (dest / ".git" / "config").write_text("[core]\n\trepositoryformatversion = 0\n", encoding="utf-8")
    return 0, ""

commands._git_clone = _test_safe_git_clone

reg = loader.load(REPO_ROOT, ignore_local=True)

def _inbox(root: Path) -> Path:
    """Mirror of loader.inbox_dir for tests — inbox lives inside the overlay, not at repo root."""
    return root / "registry" / "local" / "inbox"

def _full_windows_rig():
    """A registry copy whose example-windows carries the canonical full target set —
    tests assert against this rig so a live machine config can be trimmed (an
    intentional, frequent experiment) without breaking the suite."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = [
        "claude-code", "gemini", "agents-md", "claude-ai"]
    # pin the canonical drive layout too — projects_root is per-PC config (drive letters
    # vary by machine); path-resolution tests assert against this fixed value
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    return r

def _sandbox_deploy(machine: str) -> Path:
    """Deploy a machine into a fresh temp root; return the root."""
    import tempfile

    from agentic.commands import cmd_deploy
    root = Path(tempfile.mkdtemp(prefix="ae-sandbox-"))
    rc = cmd_deploy(reg, machine, dry_run=False, force=False, root=root)
    assert rc == 0, f"sandbox deploy failed (rc={rc})"
    return root

def _temp_registry():
    import shutil
    import tempfile

    import yaml as _y

    from agentic.commands import _local_os
    tmp = Path(tempfile.mkdtemp(prefix="ae-reg-"))
    for d in ("registry", "connections", "targets", "machines"):
        # exclude registry/local/ — it's gitignored private user data and must not leak
        # into test temp registries (its presence breaks tests that create local/ dirs)
        ignore = shutil.ignore_patterns("local") if d == "registry" else None
        shutil.copytree(REPO_ROOT / d, tmp / d, ignore=ignore)
    home = (tmp / "home").as_posix()
    # rig hosts gws too, so an env output is planned (exemption tests need one)
    conn = tmp / "connections" / "servers.yaml"
    conn.write_text(conn.read_text(encoding="utf-8").replace(
        "hosted_on: []", "hosted_on: [rig]"), encoding="utf-8")
    profile = {
        "name": "rig", "os": _local_os(), "targets": ["hermes", "agents-md"],
        "paths": {"hermes_home": f"{home}/.hermes",
                  "hermes_config": f"{home}/.hermes/config.yaml",
                  "assistant_root": f"{home}/MitosAgent",
                  "gws_env": f"{home}/gws/.env"},
    }
    (tmp / "machines" / "rig.yaml").write_text(_y.safe_dump(profile), encoding="utf-8")
    return loader.load(tmp), tmp

def _plant_candidate(tmp, cid, meta, payload_name, payload_text):
    import yaml as _y
    folder = _inbox(tmp) / cid
    folder.mkdir(parents=True)
    (folder / "meta.yaml").write_text(_y.safe_dump(meta), encoding="utf-8")
    (folder / payload_name).write_text(payload_text, encoding="utf-8", newline="\n")
    return folder

def _skill_meta(rp="skills/gws/SKILL.md"):
    return {"registry_path": rp, "kind": "drift",
            "source": {"machine": "rig", "tool": "hermes"}, "base_hash": "",
            "deploy_path": "", "sources": [rp], "captured_at": "2026-06-12T00:00:00Z",
            "note": "test candidate"}

def _write_graph(text: str) -> Path:
    import tempfile
    p = Path(tempfile.mktemp(suffix=".jsonld"))
    p.write_text(text, encoding="utf-8")
    return p

def _doc(drive_id, name, desc, modified):
    from agentic import graph
    return graph.Document(drive_id, name, desc, modified)

def _git_available() -> bool:
    import shutil
    return shutil.which("git") is not None

def _run_git(cwd, *args):
    import subprocess
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True)

def _make_overlay_hub(tmp):
    """A bare hub seeded with one commit on `main`; returns the hub path."""
    hub = tmp / "hub.git"
    _run_git(tmp, "init", "--bare", str(hub))
    _run_git(hub, "symbolic-ref", "HEAD", "refs/heads/main")
    seed = tmp / "seed"
    _run_git(tmp, "clone", str(hub), str(seed))
    _run_git(seed, "config", "user.email", "t@example.com")
    _run_git(seed, "config", "user.name", "t")
    (seed / "identity").mkdir()
    (seed / "identity" / "who.md").write_text("v0\n", encoding="utf-8")
    _run_git(seed, "add", "-A")
    _run_git(seed, "commit", "-m", "init")
    _run_git(seed, "branch", "-M", "main")
    _run_git(seed, "push", "-u", "origin", "main")
    return hub

def _clone_overlay(tmp, hub, name):
    """A repo_root whose registry/local is a clone of `hub`; returns (repo_root, overlay)."""
    root = tmp / name
    (root / "registry").mkdir(parents=True)
    overlay = root / "registry" / "local"
    _run_git(tmp, "clone", str(hub), str(overlay))
    _run_git(overlay, "config", "user.email", f"{name}@example.com")
    _run_git(overlay, "config", "user.name", name)
    return root, overlay

def _seed_overlay(root):
    """A repo_root with a non-empty registry/local/ (not yet a git repo); returns the overlay."""
    overlay = root / "registry" / "local"
    (overlay / "identity").mkdir(parents=True)
    (overlay / "identity" / "who.md").write_text("v0\n", encoding="utf-8")
    return overlay

def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0

