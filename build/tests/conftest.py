"""Shared fixtures and helpers for the mitos compiler test suite.

pytest auto-imports this file, making all helpers available to every test_*.py file.
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "build"))

from agentic import loader, planner, render  # noqa: E402
from agentic import commands
from agentic.commands import classify_output  # noqa: E402

# Globally mock _git_clone/_git_pull for all tests to prevent real network calls and clone
# operations. Individual tests can still override these by monkeypatching commands._git_clone
# / commands._git_pull.
def _test_safe_git_clone(repo: str, dest: Path, branch: str = "") -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    (dest / ".git").mkdir(parents=True, exist_ok=True)
    (dest / ".git" / "config").write_text("[core]\n\trepositoryformatversion = 0\n", encoding="utf-8")
    return 0, ""

def _test_safe_git_pull(dest: Path, branch: str = "") -> tuple[str, str]:
    # Existing checkouts are left untouched in tests — report a clean no-op skip so the
    # non-destructive contract holds without touching a real git tree.
    return "skipped", "test stub — checkout left untouched"

# Preserve the real implementations so unit tests can exercise them directly (driving the
# lower-level `commands._git` with a stub) even though the deploy path uses the safe stubs.
commands._real_git_clone = commands._git_clone
commands._real_git_pull = commands._git_pull
commands._git_clone = _test_safe_git_clone
commands._git_pull = _test_safe_git_pull

reg = loader.load(REPO_ROOT, ignore_local=True)


class _MonkeyPatch:
    """Minimal stand-in for pytest's `monkeypatch` fixture, for the stdlib runner.

    The runner (`test_compiler.py`) supplies one of these to any test that declares a
    `monkeypatch` parameter, so a test written against pytest's fixture runs identically
    under both. Only the operations the suite actually uses are implemented — anything
    else should be added here rather than worked around in a test."""

    def __init__(self) -> None:
        self._undo: list = []

    def setattr(self, target, name, value):
        old = getattr(target, name)
        self._undo.append(lambda: setattr(target, name, old))
        setattr(target, name, value)

    def delattr(self, target, name):
        old = getattr(target, name)
        self._undo.append(lambda: setattr(target, name, old))
        delattr(target, name)

    def setitem(self, mapping, key, value):
        missing = key not in mapping
        old = mapping.get(key)
        self._undo.append(
            (lambda: mapping.pop(key, None)) if missing
            else (lambda: mapping.__setitem__(key, old)))
        mapping[key] = value

    def delitem(self, mapping, key):
        old = mapping[key]
        self._undo.append(lambda: mapping.__setitem__(key, old))
        del mapping[key]

    def setenv(self, name, value):
        import os
        self.setitem(os.environ, name, str(value))

    def delenv(self, name, raising: bool = True):
        import os
        if name in os.environ:
            self.delitem(os.environ, name)
        elif raising:
            raise KeyError(name)

    def chdir(self, path):
        import os
        old = os.getcwd()
        self._undo.append(lambda: os.chdir(old))
        os.chdir(str(path))

    def syspath_prepend(self, path):
        old = list(sys.path)
        self._undo.append(lambda: sys.path.__setitem__(slice(None), old))
        sys.path.insert(0, str(path))

    def undo(self) -> None:
        for fn in reversed(self._undo):
            fn()
        self._undo.clear()


class _NonInteractiveStdin:
    """A stand-in for `sys.stdin` that is not a terminal and cannot be read — the same
    contract pytest's own capture gives a test by default.

    It exists because interactive code paths branch on `sys.stdin.isatty()`
    (`mitos._pick_folder` no-ops when stdin isn't a terminal) or read it outright
    (`mitos._ask`). Left to the ambient stdin, such a test passes in CI and under captured
    pytest, then fails the moment anyone runs it from a real terminal — the outcome depends
    on the shell, not the code. Reads raise rather than returning "" so a test that reaches
    a prompt it did not intend fails loudly instead of silently taking the blank-input
    branch."""

    def isatty(self) -> bool:
        return False

    def _unreadable(self, *_a, **_kw):
        raise OSError("stdin is not readable in tests — a prompt was reached unexpectedly")

    read = readline = readlines = _unreadable

    def __iter__(self):
        return iter(())

    def fileno(self) -> int:
        raise OSError("no fileno for the test stdin stand-in")

    def close(self) -> None:
        pass


@contextlib.contextmanager
def noninteractive_stdin():
    """Run a block with `sys.stdin` guaranteed non-interactive and unreadable.

    Used two ways: the stdlib runner wraps the WHOLE suite in it so it matches pytest's
    default capture (see test_compiler.main), and a test driving an interactive entrypoint
    uses it directly so it states the interactivity it expects instead of inheriting the
    shell's — which keeps it correct under `pytest -s` too."""
    original = sys.stdin
    sys.stdin = _NonInteractiveStdin()
    try:
        yield
    finally:
        sys.stdin = original


def make_fixture(name: str):
    """Build the stdlib-runner stand-in for a pytest fixture, or raise if unsupported.

    Returns `(value, teardown)`. Keep the supported set here in sync with what the suite
    declares — an unknown fixture name fails loudly (a test that silently received `None`
    is how the CI/pytest divergence went unnoticed before)."""
    import tempfile
    if name == "monkeypatch":
        mp = _MonkeyPatch()
        return mp, mp.undo
    if name == "tmp_path":
        d = Path(tempfile.mkdtemp(prefix="ae-tmp-path-"))
        return d, lambda: None          # temp dirs are left for post-mortem, as elsewhere
    raise LookupError(
        f"unsupported fixture {name!r} in the stdlib test runner — add it to "
        f"conftest.make_fixture (build/tests/conftest.py)")

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
        "claude-code", "antigravity", "agents-md", "claude-app"]
    # pin the canonical drive layout too — projects_root is per-PC config (drive letters
    # vary by machine); path-resolution tests assert against this fixed value
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    return r

def _connected_rig(machine: str, store: str = "gws", base=None):
    """A registry copy whose `machine` declares `store` as a wired connection.

    The shipped use-case templates (`machines/example-*.yaml`) deliberately declare NO
    `document_store:` — a brand-new box must not receive MCP wiring or a
    `requires_server:` skill for a server nobody set up (planner._gws /
    _selected_skills). Tests that assert on connection-bound output therefore have to
    state that precondition, the way `_full_windows_rig` states the target set."""
    import copy
    r = copy.deepcopy(base if base is not None else reg)
    r.machines[machine]["document_store"] = store
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
        "name": "rig", "os": _local_os(), "targets": ["mitos-agent", "agents-md"],
        # rig is the fully-wired rig: it hosts gws AND declares the connection, so
        # connection-gated output (mcp.json, the `requires_server: gws` skills) is
        # planned here. The shipped machines/example-*.yaml deliberately do not.
        "document_store": "gws",
        "paths": {"assistant_root": f"{home}/MitosAgent",   # single install root
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
            "source": {"machine": "rig", "tool": "mitos-agent"}, "base_hash": "",
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

