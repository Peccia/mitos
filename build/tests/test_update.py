"""`mitos update` unit tests — git, the deploy, and the re-exec are all stand-ins here.

The real-git behaviour (dirty trees, rebases, conflicts) lives in test_update_git.py.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from conftest import REPO_ROOT

GOLDEN = REPO_ROOT / "build" / "tests" / "fixtures" / "update_outcome"
SCENARIOS = ("clean", "blocked", "captured", "conflict", "error", "skipped")


class FakeGit:
    """Answers the git calls run_update makes; records every argv it saw."""

    def __init__(self, *, core_dirty=False, overlay_dirty=False, upstream=True,
                 pull_moves=False, pull_rc=0, pull_err="", changed=("build/agentic/x.py",)):
        self.core_dirty, self.overlay_dirty = core_dirty, overlay_dirty
        self.upstream, self.pull_moves, self.pull_rc, self.pull_err = (
            upstream, pull_moves, pull_rc, pull_err)
        self.changed = changed
        self.head = "a" * 40
        self.calls: list[tuple] = []

    def __call__(self, repo, *args):
        self.calls.append((Path(repo).name, *args))
        out, rc, err = "", 0, ""
        overlay = Path(repo).name == "local"
        if args[:2] == ("status", "--porcelain"):
            out = " M x\n" if (self.overlay_dirty if overlay else self.core_dirty) else ""
        elif args == ("rev-parse", "--abbrev-ref", "HEAD"):
            out = "v0.1.7\n"
        elif args == ("rev-parse", "--abbrev-ref", "@{u}"):
            rc = 0 if self.upstream else 128
        elif args == ("rev-parse", "HEAD"):
            out = ("c" * 40 if overlay else self.head) + "\n"
        elif args == ("pull", "--ff-only"):
            rc, err = self.pull_rc, self.pull_err
            if rc == 0 and self.pull_moves:
                self.head = "b" * 40
        elif args[:2] == ("diff", "--name-only"):
            out = "\n".join(self.changed) + "\n"
        return subprocess.CompletedProcess(args, rc, out, err)


def _repo(tmp_path) -> Path:
    (tmp_path / "registry" / "local" / ".git").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _reg(hub=True):
    sync = {"git": {"hub": "file:///hub.git"}} if hub else {}
    return SimpleNamespace(machines={"m": {"name": "m", "sync": sync}})


def _outcome(**kw):
    from agentic.commands import DeployOutcome
    base = dict(rc=0, dry_run=False, counts={"ok": 3}, written=[], blocked=[], captured=[],
                orphans=[])
    base.update(kw)
    return DeployOutcome(**base)


def _patch_deploy(monkeypatch, outcome, spy=None):
    """Stand in for run_deploy and for git_sync (which pulls, then calls the deploy)."""
    from agentic import commands, update
    from agentic.sync import SyncError

    def fake_run_deploy(reg, machine, dry_run, force, **kw):
        if spy is not None:
            spy.append({"dry_run": dry_run, "force": force, **kw})
        return outcome

    def fake_git_sync(repo_root, machine, cfg, *, action, deploy):
        assert action == "pull"
        rc = deploy(machine)
        if rc != 0:
            raise SyncError(f"deploy --machine {machine} failed (rc {rc})")
        return []

    monkeypatch.setattr(commands, "run_deploy", fake_run_deploy)
    monkeypatch.setattr(update, "git_sync", fake_git_sync)


def _run(tmp_path, git, *, scheduled=False, skip_core_pull=False, dry_run=False, load=None,
         reexec=None):
    from agentic.update import run_update
    return run_update(_repo(tmp_path), "m", scheduled=scheduled, skip_core_pull=skip_core_pull,
                      dry_run=dry_run, git=git, load=load or (lambda root: _reg()),
                      reexec=reexec or (lambda argv, cwd: (_ for _ in ()).throw(
                          AssertionError("unexpected re-exec"))))


def _keys(obj):
    """The recursive key shape of an outcome: a dict maps key -> shape, anything else -> type."""
    if isinstance(obj, dict):
        return {k: _keys(v) for k, v in obj.items()}
    return None if obj is None else type(obj).__name__


def _scenario(name, tmp_path, monkeypatch) -> dict:
    root = tmp_path.as_posix()
    if name == "clean":
        _patch_deploy(monkeypatch, _outcome(written=[f"{root}/agent/skills/x/SKILL.md"]))
        return _run(tmp_path, FakeGit())
    if name == "blocked":
        _patch_deploy(monkeypatch, _outcome(rc=1, blocked=[f"{root}/agent/SOUL.md"]))
        return _run(tmp_path, FakeGit())
    if name == "captured":
        _patch_deploy(monkeypatch, _outcome(captured=["registry/local/inbox/abc"],
                                            written=[f"{root}/agent/SOUL.md"]))
        return _run(tmp_path, FakeGit(overlay_dirty=True))
    if name == "conflict":
        from agentic import update
        from agentic.sync import SyncError

        def conflicted(repo_root, machine, cfg, *, action, deploy):
            (Path(repo_root) / "registry/local/.git/rebase-merge").mkdir()
            raise SyncError("git pull --rebase hit a conflict")
        monkeypatch.setattr(update, "git_sync", conflicted)
        return _run(tmp_path, FakeGit())
    if name == "error":
        return _run(tmp_path, FakeGit(), load=lambda root: _reg(hub=False))
    if name == "skipped":
        return _run(tmp_path, FakeGit(core_dirty=True), scheduled=True)
    raise KeyError(name)


def _normalized(result: dict, tmp_path) -> dict:
    text = json.dumps(result).replace(tmp_path.as_posix(), "<ROOT>")
    return json.loads(text)


# ── pipeline order and terminal conditions ───────────────────────────────────

def test_clean_run_pulls_core_then_overlay_then_deploys(tmp_path, monkeypatch):
    spy: list = []
    _patch_deploy(monkeypatch, _outcome(written=["x"]), spy)
    git = FakeGit()
    result = _run(tmp_path, git)
    assert result["ok"] is True and result["error"] is None and result["schema"] == 1
    assert ("pull", "--ff-only") in [c[1:3] for c in git.calls]
    assert result["overlay"]["pulled"] is True
    assert result["deploy"]["written"] == ["x"]
    assert spy == [{"dry_run": False, "force": False, "prune": False}]


def test_force_and_prune_are_never_passed_true(tmp_path, monkeypatch):
    spy: list = []
    _patch_deploy(monkeypatch, _outcome(), spy)
    _run(tmp_path, FakeGit())
    _run(tmp_path, FakeGit(overlay_dirty=True))
    _run(tmp_path, FakeGit(), dry_run=True)
    assert spy and all(c["force"] is False and c.get("prune", False) is False for c in spy)


def test_scheduled_run_with_dirty_core_does_nothing(tmp_path, monkeypatch):
    spy: list = []
    _patch_deploy(monkeypatch, _outcome(), spy)
    git = FakeGit(core_dirty=True)
    result = _run(tmp_path, git, scheduled=True)
    assert result["ok"] is True and result["skipped"] == "core dirty (scheduled)"
    assert result["overlay"] is None and result["deploy"] is None and not spy
    assert not any(c[1] == "pull" for c in git.calls)


def test_manual_run_with_dirty_core_skips_pull_and_still_deploys(tmp_path, monkeypatch):
    spy: list = []
    _patch_deploy(monkeypatch, _outcome(), spy)
    git = FakeGit(core_dirty=True)
    result = _run(tmp_path, git)
    assert result["core"]["skipped_reason"] == "dirty" and result["ok"] is True
    assert not any(c[1:3] == ("pull", "--ff-only") for c in git.calls)
    assert len(spy) == 1


def test_no_upstream_and_not_fast_forward_skip_the_core_pull(tmp_path, monkeypatch):
    _patch_deploy(monkeypatch, _outcome())
    assert _run(tmp_path, FakeGit(upstream=False))["core"]["skipped_reason"] == "no upstream"
    ff = FakeGit(pull_rc=128, pull_err="fatal: Not possible to fast-forward, aborting.")
    result = _run(tmp_path, ff)
    assert result["core"]["skipped_reason"] == "not fast-forward" and result["ok"] is True


def test_core_pull_network_failure_stops_before_deploy(tmp_path, monkeypatch):
    spy: list = []
    _patch_deploy(monkeypatch, _outcome(), spy)
    result = _run(tmp_path, FakeGit(pull_rc=1, pull_err="ssh: connect timed out"))
    assert result["ok"] is False and "core pull failed" in result["error"] and not spy


def test_moved_head_reexecs_with_skip_core_pull_and_merges_core(tmp_path, monkeypatch):
    spy: list = []
    _patch_deploy(monkeypatch, _outcome(), spy)
    seen = {}
    child = {"schema": 1, "ok": True, "machine": "m", "scheduled": True, "started": "child",
             "finished": None, "skipped": None, "error": None,
             "core": {"skipped_reason": "re-exec"}, "overlay": {"pulled": True},
             "deploy": {"rc": 0, "blocked": []}}

    def reexec(argv, cwd):
        seen["argv"] = argv
        return 0, "noise on stdout?\n" + json.dumps(child) + "\n"
    result = _run(tmp_path, FakeGit(pull_moves=True), scheduled=True, reexec=reexec)
    assert seen["argv"][2:] == ["update", "--machine", "m", "--skip-core-pull", "--json",
                                "--scheduled"]
    assert result["core"]["pulled"] is True and result["core"]["after"] == "b" * 40
    assert result["ok"] is True and not spy          # the parent never deployed


def test_reexec_without_json_is_an_error(tmp_path, monkeypatch):
    _patch_deploy(monkeypatch, _outcome())
    result = _run(tmp_path, FakeGit(pull_moves=True), reexec=lambda argv, cwd: (1, ""))
    assert result["ok"] is False and result["error"].startswith("re-exec failed")


def test_requirements_change_stops_before_deploy(tmp_path, monkeypatch):
    spy: list = []
    _patch_deploy(monkeypatch, _outcome(), spy)
    git = FakeGit(pull_moves=True, changed=("build/requirements.txt",))
    result = _run(tmp_path, git)
    assert result["ok"] is False and result["core"]["requirements_changed"] is True
    assert "reinstall the venv" in result["error"] and not spy


def test_blocked_deploy_is_reported_after_the_sync_error(tmp_path, monkeypatch):
    _patch_deploy(monkeypatch, _outcome(rc=1, blocked=["/a/SOUL.md"]))
    result = _run(tmp_path, FakeGit())
    assert result["ok"] is False and result["error"] is None
    assert result["deploy"]["blocked"] == ["/a/SOUL.md"]


def test_busy_lock_is_a_top_level_error(tmp_path, monkeypatch):
    _patch_deploy(monkeypatch, _outcome(rc=1, error="error: deploy in progress (pid 9 since t)"))
    result = _run(tmp_path, FakeGit())
    assert result["ok"] is False and result["error"].startswith("busy: deploy in progress")


def test_registry_invalid_after_pull_is_a_deploy_error(tmp_path, monkeypatch):
    from agentic import loader
    _patch_deploy(monkeypatch, _outcome())
    calls = []

    def load(root):
        calls.append(root)
        if len(calls) > 1:
            raise loader.RegistryError("skills/x/SKILL.md: bad frontmatter")
        return _reg()
    result = _run(tmp_path, FakeGit(), load=load)
    assert result["ok"] is False and "bad frontmatter" in result["deploy"]["error"]


def test_unknown_machine_and_missing_hub(tmp_path):
    result = _run(tmp_path, FakeGit(), load=lambda root: SimpleNamespace(machines={}))
    assert result["error"] == "unknown machine 'm'"
    result = _run(tmp_path, FakeGit(), load=lambda root: _reg(hub=False))
    assert "no sync.git.hub" in result["error"]


def test_dry_run_pulls_nothing(tmp_path, monkeypatch):
    spy: list = []
    _patch_deploy(monkeypatch, _outcome(dry_run=True), spy)
    git = FakeGit()
    result = _run(tmp_path, git, dry_run=True)
    assert not any(c[1] == "pull" for c in git.calls)
    assert result["overlay"]["skipped_reason"] == "dry-run" and spy[0]["dry_run"] is True


# ── schema contract ──────────────────────────────────────────────────────────

def test_every_path_fills_every_top_level_key(tmp_path, monkeypatch):
    keys = {"schema", "ok", "machine", "scheduled", "started", "finished", "skipped", "error",
            "core", "overlay", "deploy"}
    for name in SCENARIOS:
        sub = tmp_path / name
        sub.mkdir()
        result = _scenario(name, sub, monkeypatch)
        assert set(result) == keys, name
        assert result["schema"] == 1 and result["finished"]
        monkeypatch.undo()


def test_golden_outcomes_match_schema(tmp_path, monkeypatch):
    for name in SCENARIOS:
        sub = tmp_path / name
        sub.mkdir()
        result = _normalized(_scenario(name, sub, monkeypatch), sub)
        monkeypatch.undo()
        golden = json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))
        assert _keys(result) == _keys(golden), name
        assert "ae-" not in json.dumps(golden), f"{name}.json leaks a temp path"


def test_cli_json_is_exactly_one_line_even_with_non_ascii_paths(monkeypatch):
    import contextlib

    import mitos
    from agentic import update
    payload = {"schema": 1, "ok": True, "deploy": {"written": ["D:/Projects/Café/SKILL.md"]}}

    def fake(repo_root, machine, **kw):
        print("deploy prose that must not reach stdout")
        return payload
    monkeypatch.setattr(update, "run_update", fake)
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "__stdout__", out)
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()) as stray:
        rc = mitos.main(["update", "--machine", "m", "--json"])
    text = out.getvalue()
    assert rc == 0 and text.count("\n") == 1 and text.isascii()
    assert json.loads(text)["deploy"]["written"] == ["D:/Projects/Café/SKILL.md"]
    assert "deploy prose" in err.getvalue() and stray.getvalue() == ""


def test_cli_exit_codes(monkeypatch):
    import contextlib

    import mitos
    from agentic import update
    for result, want in (({"ok": False, "error": "unknown machine 'x'"}, 2),
                         ({"ok": False, "error": "boom"}, 1)):
        monkeypatch.setattr(update, "run_update", lambda *a, _r=result, **k: {
            "schema": 1, "skipped": None, "core": None, "overlay": None, "deploy": None, **_r})
        monkeypatch.setattr(sys, "__stdout__", io.StringIO())
        with contextlib.redirect_stderr(io.StringIO()):
            assert mitos.main(["update", "--machine", "x", "--json"]) == want
        monkeypatch.undo()


def write_goldens() -> None:
    """Regenerate fixtures/update_outcome/*.json (run by hand after a schema change)."""
    import tempfile

    from conftest import _MonkeyPatch
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for name in SCENARIOS:
        tmp = Path(tempfile.mkdtemp(prefix="ae-golden-"))
        mp = _MonkeyPatch()
        try:
            result = _normalized(_scenario(name, tmp, mp), tmp)
        finally:
            mp.undo()
        result["started"] = result["finished"] = "2026-09-16T10:00:00Z"
        (GOLDEN / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n",
                                            encoding="utf-8", newline="\n")


if __name__ == "__main__":
    write_goldens()
