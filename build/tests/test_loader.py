"""Loader, overlay, machine, project, and init tests."""
from __future__ import annotations

import sys
from pathlib import Path

from conftest import (
    REPO_ROOT, reg, loader, planner, render, classify_output,
    _inbox, _temp_registry, _doc, _write_graph,
    _plant_candidate, _skill_meta, _full_windows_rig, _connected_rig, _sandbox_deploy,
    _git_available, _run_git, _make_overlay_hub, _clone_overlay, _seed_overlay,
)

def test_registry_validates():
    assert reg.skills and reg.partials and reg.projects
    assert "gws" in reg.servers["servers"]

def test_core_registry_integrity():
    """Guard against man-in-the-middle tampering and unauthorized repo cloning.

    The public-track core must ship with no production endpoints, no sync hubs,
    and no external server URLs. All real addresses belong in registry/local/
    (gitignored). This prevents a compromised or cloned registry from silently
    routing agent traffic or overlay syncs to an attacker-controlled server.

    Agents are instructed (via the builder context Invariants) never to write
    directly into registry/. This test verifies those guard rules are present
    and that the structural guardrails in the core remain intact.
    """
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp(prefix="ae-integrity-"))
    for d in ("registry", "connections", "targets", "machines"):
        ignore = shutil.ignore_patterns("local") if d == "registry" else None
        shutil.copytree(REPO_ROOT / d, tmp / d, ignore=ignore)
    core_reg = loader.load(tmp)

    # 1. All MCP server URLs must be localhost — no production/LAN addresses in core.
    #    Real endpoints belong in registry/local/connections/servers.yaml.
    for name, server in (core_reg.servers.get("servers") or {}).items():
        url = server.get("url", "")
        if url:
            assert "localhost" in url, (
                f"server {name!r}: core must not ship production URLs; got {url!r} — "
                f"put real addresses in registry/local/connections/servers.yaml")
        for machine_name, override_url in (server.get("urls") or {}).items():
            assert "localhost" in override_url, (
                f"server {name!r} machine-url for {machine_name!r}: "
                f"got {override_url!r} — LAN overrides belong in registry/local/")

    # 2. gws.hosted_on must be empty in core — no machine hardcoded to host a server.
    assert core_reg.servers["servers"]["gws"]["hosted_on"] == [], (
        "gws.hosted_on must be empty in the core registry; "
        "set it in your machine profile under registry/local/")

    # 3. No machine may have a sync hub in the public core.
    #    sync.git.hub routes private overlay data to an external repo — if set in the
    #    core and committed, any clone of this repo could receive your private context.
    for name, machine in core_reg.machines.items():
        hub = ((machine.get("sync") or {}).get("git") or {}).get("hub", "")
        assert not hub, (
            f"machine {name!r}: sync.git.hub found in public-track core — "
            f"move it to registry/local/machines/ to prevent overlay data leaking "
            f"to unauthorized repos")

    # 4. The partial that compiles into this repo's own AGENTS.md must carry the
    #    write-guard Invariants. That artifact is what an agent working IN this repo
    #    reads, so its absence would let an impostor AGENTS.md instruct agents without
    #    the repo-write prohibition and inbox-only proposal rule.
    #    Bound to selfdoc.SOURCE rather than a hardcoded path so the guard follows the
    #    artifact's source wherever it moves (it was context.builder until the project
    #    node and the repo artifact were split onto separate partials).
    from agentic import selfdoc
    repo_ctx_key = selfdoc.SOURCE.relative_to(selfdoc.REPO_ROOT / "registry").as_posix()
    assert repo_ctx_key in core_reg.partials, (
        f"selfdoc source partial {repo_ctx_key!r} missing from the core registry — "
        f"this repo's AGENTS.md cannot be compiled and write-guard Invariants are absent")
    builder_body = core_reg.partials[repo_ctx_key].body
    assert "Invariants" in builder_body, (
        "the repo's builder context is missing the Invariants section — possible tampering; "
        "agents would operate without structural guardrails")
    assert "Never write into" in builder_body, (
        "the repo's builder context is missing the registry write-guard rule — possible "
        "tampering; agents and humans could bypass the inbox and modify the registry directly")

    # The mitos project node must still resolve its own prose partial — separate file,
    # separate job (orientation + document map), but a missing one means no node at all.
    builder_rel = (core_reg.projects.get("mitos") or {}).get("context", {}).get("builder", "")
    assert builder_rel, "mitos project missing context.builder — project node cannot be generated"
    assert builder_rel.removeprefix("registry/") in core_reg.partials, (
        f"mitos context.builder partial {builder_rel!r} missing from registry")

def test_inbox_dir_resolves_under_overlay_not_repo_root():
    # inbox_dir points into registry/local/ (syncs with mitos-local overlay), not at
    # the repo root — private state must never land in the public-track repo.
    from agentic.loader import inbox_dir
    treg, tmp = _temp_registry()
    assert inbox_dir(treg) == treg.root / "registry" / "local" / "inbox"
    assert inbox_dir(treg, tmp / "sandbox") == tmp / "sandbox" / "registry" / "local" / "inbox"
    assert inbox_dir(treg) == _inbox(treg.root)

def test_env_planned_only_for_hosting_machines():
    # the neutral public core hosts gws nowhere (hosted_on is empty) — a user sets which
    # machine runs it in their overlay. With no host, no env output is planned anywhere.
    # Use a clean temp copy without local overlay or _temp_registry()'s hosted_on patch.
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp(prefix="ae-env-"))
    for d in ("registry", "connections", "targets", "machines"):
        ignore = shutil.ignore_patterns("local") if d == "registry" else None
        shutil.copytree(REPO_ROOT / d, tmp / d, ignore=ignore)
    core_reg = loader.load(tmp)
    assert core_reg.servers["servers"]["gws"]["hosted_on"] == []
    for machine in ("example-windows", "example-linux"):
        assert not [o for o in planner.plan_machine(core_reg, machine) if o.kind == "env"]

def test_materialize_env_merges_overlay():
    from dataclasses import replace as _replace

    from agentic.commands import _materialize_env
    tmpl = (REPO_ROOT / "connections/env/gws.env.example").read_text(encoding="utf-8")
    base = planner.Output(target="env", kind="env", deploy_path="~/x/.env",
                          dist_rel="env/x.env", content=tmpl, drift_policy="protect",
                          lane="connections")
    # no overlay configured → template passes through
    assert "WORKSPACE_MCP_PORT=8000" in _materialize_env(reg, base).content
    # overlay (in gitignored .local/) wins over template values
    tmp_overlay = REPO_ROOT / ".local" / "test-tmp-overlay.env"
    tmp_overlay.parent.mkdir(exist_ok=True)  # .local/ is gitignored — absent on fresh checkouts
    tmp_overlay.write_text("WORKSPACE_MCP_PORT=9999\n", encoding="utf-8")
    try:
        merged = _materialize_env(
            reg, _replace(base, env_local=".local/test-tmp-overlay.env")).content
        assert "WORKSPACE_MCP_PORT=9999" in merged
        assert "WORKSPACE_MCP_PORT=8000" not in merged
    finally:
        tmp_overlay.unlink()

def test_local_path_resolution():
    from agentic.loader import RegistryError, resolve_local_path
    win = {"paths": {"projects_root": "C:/Projects"}}
    # relative dir resolves against the machine's projects_root (per-PC drive letters)
    assert resolve_local_path("example-windows", win, "example-project") == \
        "C:/Projects/example-project"
    # absolute forms pass through untouched: drive-letter, ~, /
    assert resolve_local_path("example-windows", win, "C:/Elsewhere/x") == "C:/Elsewhere/x"
    assert resolve_local_path("example-linux", {}, "~/Projects/x") == "~/Projects/x"
    assert resolve_local_path("example-linux", {}, "/srv/x") == "/srv/x"
    # relative without a projects_root fails loudly at validation time
    try:
        resolve_local_path("bare-box", {}, "some-project")
        raise AssertionError("expected RegistryError")
    except RegistryError:
        pass

def test_resolved_project_paths_unchanged():
    # the manifests' relative entries must land exactly where the absolute ones did;
    # uses only example-project (core registry, no overlay dependency)
    outs = planner.plan_machine(_full_windows_rig(), "example-windows")
    assert any(o.deploy_path == "C:/Projects/example-project/CLAUDE.md" for o in outs)

def test_per_machine_server_url():
    # the neutral core ships gws at localhost with no per-machine overrides (urls: {}).
    # Use a temp registry (no registry/local/) so a user's LAN overlay doesn't bleed in.
    treg, _ = _temp_registry()
    assert treg.servers["servers"]["gws"]["urls"] == {}
    win = planner.plan_machine(treg, "example-windows")
    mcp_cfg = next(o for o in win if o.deploy_path.endswith("mcp_config.json"))
    assert "http://localhost:8000/mcp" in mcp_cfg.content
    # rig has document_store="gws" and targets ["mitos-agent", "context-tree"]
    rig_plan = planner.plan_machine(treg, "rig")
    mcp_json = next(o for o in rig_plan if o.deploy_path.endswith("mcp.json"))
    assert "http://localhost:8000/mcp" in mcp_json.content

def test_retired_user_keys_warn_naming_the_line():
    """user.yaml keys 'mitos_agent' and 'default_deliverables' were retired in M6.
    If present, loader emits a warning naming the file and the line number to delete.
    Unknown keys still raise RegistryError."""
    from agentic.loader import RegistryError
    _treg, tmp = _temp_registry()
    user_file = tmp / "registry" / "user.yaml"
    user_file.write_text("given_name: User\nmitos_agent: true\ndefault_deliverables:\n  - tests\n", encoding="utf-8")
    loaded = loader.load(tmp)
    assert any("mitos_agent" in w and "line 2" in w for w in loaded.warnings)
    assert any("default_deliverables" in w and "line 3" in w for w in loaded.warnings)

    # An unknown non-retired key raises RegistryError
    user_file.write_text("given_name: User\nbogus_key: val\n", encoding="utf-8")
    try:
        loader.load(tmp)
        raise AssertionError("expected RegistryError for unknown key")
    except RegistryError as e:
        assert "bogus_key" in str(e)


def test_path_validation_control_characters():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects\x07"
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError due to control character")
    except RegistryError as e:
        assert "contains invalid/garbled characters" in str(e)


def test_path_validation_workspace_overlap():
    import copy
    from agentic.loader import _validate, RegistryError
    # uses example-project (core registry, overlay-independent) to trigger the overlap guard
    rig = copy.deepcopy(reg)
    rig.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    rig.machines["example-windows"]["paths"]["agentic_context_root"] = "C:/Projects/example-project"
    rig.projects["example-project"]["local_path"]["example-windows"] = "example-project"
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError due to workspace path overlap")
    except RegistryError as e:
        assert "must not overlap with project 'example-project' workspace path" in str(e)



def test_context_tree_valid():
    import copy
    from agentic.loader import _validate
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["context_tree"] = "MitosAgent"
    _validate(rig)  # must not raise

def test_context_tree_rejects_path_separators():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["context_tree"] = "sub/dir"
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for path-like context_tree")
    except RegistryError as e:
        assert "must be a single directory name" in str(e)

def test_context_tree_rejects_empty():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["context_tree"] = "   "
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for empty context_tree")
    except RegistryError as e:
        assert "must be a non-empty string" in str(e)

def test_context_tree_collides_with_repo_checkout_dir():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = "git@github.com:example/MitosAgent.git"
    rig.projects["example-project"]["context_tree"] = "MitosAgent"
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for context_tree/repo checkout collision")
    except RegistryError as e:
        assert "collides with the checkout dir of repo" in str(e)

def test_renamed_keys_fail_naming_the_new_key():
    """TEST-14: Renamed keys/targets fail validation naming the new key explicitly."""
    import copy
    from agentic.loader import _validate, RegistryError

    # 1. assistant_root in machine paths -> 'context_root'
    rig1 = copy.deepcopy(reg)
    rig1.machines["example-linux"]["paths"]["assistant_root"] = "~/MitosAgent"
    try:
        _validate(rig1)
        raise AssertionError("expected RegistryError for assistant_root")
    except RegistryError as e:
        assert "assistant_root" in str(e) and "context_root" in str(e)

    # 2. agentic_tree in project -> 'context_tree'
    rig2 = copy.deepcopy(reg)
    rig2.projects["example-project"]["agentic_tree"] = "MitosAgent"
    try:
        _validate(rig2)
        raise AssertionError("expected RegistryError for agentic_tree")
    except RegistryError as e:
        assert "agentic_tree" in str(e) and "context_tree" in str(e)

    # 3. agents-md in machine targets -> 'context-tree'
    rig3 = copy.deepcopy(reg)
    rig3.machines["example-linux"]["targets"] = ["mitos-agent", "agents-md"]
    try:
        _validate(rig3)
        raise AssertionError("expected RegistryError for agents-md machine target")
    except RegistryError as e:
        assert "agents-md" in str(e) and "context-tree" in str(e)

    # 4. agents-md in partial audience -> 'context-tree'
    rig4 = copy.deepcopy(reg)
    p = next(iter(rig4.partials.values()))
    p.audience.append("agents-md")
    try:
        _validate(rig4)
        raise AssertionError("expected RegistryError for agents-md in audience")
    except RegistryError as e:
        assert "agents-md" in str(e) and "context-tree" in str(e)

def test_repo_branches_validates_against_checkout_basenames():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = "git@github.com:example/thing.git"
    # a branch keyed by a basename that isn't one of the project's repos → loud error
    rig.projects["example-project"]["repo_branches"] = {"nope": "main"}
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for unknown repo_branches key")
    except RegistryError as e:
        assert "does not match any 'repo' checkout basename" in str(e)
    # a valid basename + a non-empty branch validates cleanly
    rig.projects["example-project"]["repo_branches"] = {"thing": "develop"}
    _validate(rig)
    # an empty branch value is rejected
    rig.projects["example-project"]["repo_branches"] = {"thing": ""}
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for empty branch")
    except RegistryError as e:
        assert "must be a non-empty string" in str(e)

def test_repo_branches_threads_into_clonespec():
    import copy
    from agentic.planner import plan_clones
    rig = copy.deepcopy(reg)
    rig.projects["mitos"]["repo_branches"] = {"mitos": "release/0.1.4"}
    spec = next(c for c in plan_clones(rig, "example-linux") if c.slug == "mitos")
    assert spec.branch == "release/0.1.4"
    # a project without a repo_branches entry carries an empty branch (its default)
    rig.projects["mitos"].pop("repo_branches")
    spec = next(c for c in plan_clones(rig, "example-linux") if c.slug == "mitos")
    assert spec.branch == ""

def test_repo_ssh_keys_validates_against_checkout_basenames():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = "git@github.com:example/thing.git"
    # a key keyed by a basename that isn't one of the project's repos → loud error
    rig.projects["example-project"]["repo_ssh_keys"] = {"nope": "id_github_thing"}
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for unknown repo_ssh_keys key")
    except RegistryError as e:
        assert "does not match any 'repo' checkout basename" in str(e)
    # a valid basename + a non-empty key name validates cleanly
    rig.projects["example-project"]["repo_ssh_keys"] = {"thing": "id_github_thing"}
    _validate(rig)
    # an empty key value is rejected
    rig.projects["example-project"]["repo_ssh_keys"] = {"thing": ""}
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for empty ssh key")
    except RegistryError as e:
        assert "must be a non-empty string" in str(e)

def test_repo_ssh_keys_threads_into_clonespec():
    import copy
    from agentic.planner import plan_clones
    rig = copy.deepcopy(reg)
    rig.projects["mitos"]["repo_ssh_keys"] = {"mitos": "id_github_mitos"}
    spec = next(c for c in plan_clones(rig, "example-linux") if c.slug == "mitos")
    assert spec.ssh_key == "id_github_mitos"
    # a project without a repo_ssh_keys entry carries an empty key (ambient default identity)
    rig.projects["mitos"].pop("repo_ssh_keys")
    spec = next(c for c in plan_clones(rig, "example-linux") if c.slug == "mitos")
    assert spec.ssh_key == ""

def test_git_clone_pins_core_ssh_command_for_the_chosen_key():
    """`_git_clone` passes `-c core.sshCommand=...` on the clone itself (so the network call
    authenticates with the right key) and persists it on the checkout afterwards (so later
    pulls, including a bare cron `git pull`, keep using it without mitos re-stating it)."""
    import tempfile
    from agentic import commands
    git_clone = commands._real_git_clone
    calls: list[list[str]] = []

    def fake_git(args, cwd=None, timeout=600):
        calls.append(args)
        return 0, "", ""

    tmp = Path(tempfile.mkdtemp(prefix="ae-sshkey-"))
    dest = tmp / "y"
    # a real file so the ssh-key-exists preflight check passes and the clone actually proceeds
    key_file = tmp / "id_github_y"
    key_file.write_text("fake key", encoding="utf-8")
    orig = commands._git
    try:
        commands._git = fake_git
        rc, err = git_clone("git@github.com:x/y.git", dest, ssh_key=str(key_file))
        assert rc == 0 and err == ""
        clone_call = calls[0]
        assert clone_call[0] == "-c" and "core.sshCommand=" in clone_call[1]
        assert key_file.as_posix() in clone_call[1]
        assert "clone" in clone_call
        # persisted onto the checkout for future pulls
        config_call = calls[-1]
        assert config_call[:2] == ["config", "core.sshCommand"]
    finally:
        commands._git = orig

def test_git_clone_reports_missing_key_file_without_touching_the_network():
    """A `repo_ssh_keys:` entry naming a file this machine doesn't have fails fast with a
    named path — never git's cryptic 'Permission denied (publickey)' / '...and the repository
    exists.' after a real network round-trip."""
    import tempfile
    from agentic import commands
    git_clone = commands._real_git_clone
    calls: list[list[str]] = []

    def fake_git(args, cwd=None, timeout=600):
        calls.append(args)
        return 0, "", ""

    dest = Path(tempfile.mkdtemp(prefix="ae-sshkey-")) / "y"
    orig = commands._git
    try:
        commands._git = fake_git
        rc, err = git_clone("git@github.com:x/y.git", dest,
                            ssh_key="definitely-not-a-real-key-9d3f1a")
        assert rc != 0
        assert "ssh key not found" in err and ".ssh" in err
        assert calls == []   # no git invocation at all — failed before touching the network
    finally:
        commands._git = orig

def test_git_pull_reconciles_ssh_key_before_fetching():
    """`_git_pull` reconciles the checkout's `core.sshCommand` with `repo_ssh_keys:` before any
    fetch, so a key changed (or removed) in the manifest takes effect on the very next deploy."""
    import tempfile
    from agentic import commands
    git_pull = commands._real_git_pull
    calls: list[list[str]] = []

    def fake_git(args, cwd=None, timeout=600):
        calls.append(args)
        if args[:1] == ["status"]:
            return 0, "", ""
        if args[:1] == ["symbolic-ref"]:
            return 0, "main", ""
        if args[:1] == ["rev-parse"]:
            return 0, "origin/main", ""
        return 0, "", ""

    # a real file so the ssh-key-exists check passes and the pull actually proceeds
    key_file = Path(tempfile.mkdtemp(prefix="ae-sshkey-")) / "id_github_mitos"
    key_file.write_text("fake key", encoding="utf-8")
    orig = commands._git
    try:
        commands._git = fake_git
        outcome, detail = git_pull(Path("x"), "main", str(key_file))
        assert outcome == "pulled"
        assert calls[0][:2] == ["config", "core.sshCommand"]
        assert key_file.as_posix() in calls[0][2]
        # no key configured → the checkout's core.sshCommand is cleared, not left stale
        commands._git = fake_git
        calls.clear()
        git_pull(Path("x"), "main", "")
        assert calls[0] == ["config", "--unset", "core.sshCommand"]
    finally:
        commands._git = orig

def test_git_pull_is_fast_forward_only_and_nondestructive():
    """_git_pull refuses to touch a dirty or diverged checkout — it only ever fast-forwards
    a clean, tracking branch. Driven by a stubbed `_git` so no real repo is needed."""
    from agentic import commands
    git_pull = commands._real_git_pull   # the real impl (conftest stubs the module attr)
    calls: list[list[str]] = []

    def make_git(status="", branch="main", upstream_ok=True, ff_ok=True):
        def _git(args, cwd=None, timeout=600):
            calls.append(args)
            if args[:1] == ["status"]:
                return 0, status, ""
            if args[:1] == ["symbolic-ref"]:
                return (0, branch, "") if branch else (1, "", "detached")
            if args[:1] == ["rev-parse"]:
                return (0, "origin/main", "") if upstream_ok else (1, "", "no upstream")
            if args[:1] == ["fetch"]:
                return 0, "", ""
            if args[:1] == ["merge"]:
                return (0, "", "") if ff_ok else (1, "", "not ff")
            return 0, "", ""
        return _git

    orig = commands._git
    try:
        commands._git = make_git(status=" M file.py")     # dirty tree
        assert git_pull(Path("x"))[0] == "skipped"
        commands._git = make_git(branch="")               # detached HEAD
        assert git_pull(Path("x"))[0] == "skipped"
        commands._git = make_git(branch="feature")        # wrong branch vs manifest
        assert git_pull(Path("x"), "main")[0] == "skipped"
        commands._git = make_git(upstream_ok=False)       # no upstream
        assert git_pull(Path("x"))[0] == "skipped"
        commands._git = make_git(ff_ok=False)             # diverged — cannot ff
        assert git_pull(Path("x"))[0] == "skipped"
        commands._git = make_git()                        # clean, tracking, ff-able
        outcome, detail = git_pull(Path("x"), "main")
        assert outcome == "pulled" and detail == "main"
        # a fast-forward run never issues a destructive verb
        flat = [a for c in calls for a in c]
        assert "reset" not in flat and "checkout" not in flat and "stash" not in flat
    finally:
        commands._git = orig

def test_planner_output_path_collision():
    import copy
    from agentic import planner
    from agentic.loader import RegistryError, Skill
    rig = copy.deepcopy(reg)
    # inject a second skill targeting antigravity to force a collision
    rig.skills["mock-skill"] = Skill(name="mock-skill", rel="skills/mock-skill/SKILL.md", frontmatter={"targets": ["antigravity"]}, body="")
    rig.machines["example-windows"]["paths"]["antigravity_skills"] = "C:/AntigravityPrompts"
    rig.targets["antigravity"]["skills"]["subdir"] = "AGENTS.md"
    try:
        planner.plan_machine(rig, "example-windows")
        raise AssertionError("expected RegistryError due to duplicate output path")
    except RegistryError as e:
        assert "output path collision on" in str(e)
        assert "Target 'antigravity'" in str(e)

def test_filter_prior_by_machine_paths():
    from agentic.commands import _filter_prior_by_machine_paths
    import copy
    rig = copy.deepcopy(reg)

    # Configure path keys
    rig.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    rig.machines["example-windows"]["paths"]["antigravity_config"] = "~/.gemini/config"

    prior = {
        "C:/Projects/mitos/CLAUDE.md": {"deployed_hash": "h1"},
        "~/.gemini/config/mcp_config.json": {"deployed_hash": "h2"},
        "D:/Projects/mitos/CLAUDE.md": {"deployed_hash": "h3"},  # stale drive
        "/etc/somewhere/else": {"deployed_hash": "h4"}                       # stale absolute path
    }

    filtered = _filter_prior_by_machine_paths(rig, "example-windows", prior)

    assert "C:/Projects/mitos/CLAUDE.md" in filtered
    assert "~/.gemini/config/mcp_config.json" in filtered
    assert "D:/Projects/mitos/CLAUDE.md" not in filtered
    assert "/etc/somewhere/else" not in filtered

def test_overlay_precedence_last_layer_wins():
    # registry/local/ overlays the core with a documented last-layer-wins contract
    treg, tmp = _temp_registry()
    local = tmp / "registry" / "local"
    (local / "identity").mkdir(parents=True)
    (local / "identity" / "comms-style.md").write_text(           # override same-key core
        "---\naudience: [mitos-agent]\n---\nOVERLAY comms rules\n", encoding="utf-8")
    (local / "skills" / "extra").mkdir(parents=True)              # add a new local skill
    (local / "skills" / "extra" / "SKILL.md").write_text(
        "---\nname: extra\ndescription: d\ntargets: [mitos-agent]\ncategory: productivity\n---\n"
        "body\n", encoding="utf-8")
    (local / "projects").mkdir(parents=True)                     # add a new local project
    (local / "projects" / "zeta.yaml").write_text(
        "slug: zeta\nname: Zeta\nstage: build\n", encoding="utf-8")
    reg2 = loader.load(tmp)
    # local replaced the same-key core partial; its rel points back into the overlay so an
    # adopt would route there, not into the core
    assert "OVERLAY comms rules" in reg2.partials["identity/comms-style.md"].body
    assert reg2.partials["identity/comms-style.md"].rel == "local/identity/comms-style.md"
    # new local key added; core-only keys remain untouched
    assert "extra" in reg2.skills and reg2.skills["extra"].rel == "local/skills/extra/SKILL.md"
    assert "gws" in reg2.skills                                   # core-only skill remains
    assert "zeta" in reg2.projects                               # new local project added
    assert reg2.partials["identity/who-i-am.md"].rel == "identity/who-i-am.md"  # untouched

def test_scaffold_machine_use_cases_gate_orgs_and_agents_md():
    """scaffold_machine writes a registry/local/machines/<name>.yaml whose `targets:` list
    matches the chosen use case."""
    from agentic import init as initmod

    for use_case, expected_targets in initmod.MACHINE_USE_CASES.items():
        treg, tmp = _temp_registry()
        written = initmod.scaffold_machine(tmp, name="box", os_name="windows",
                                           use_case=use_case)
        assert written == "local/machines/box.yaml"
        profile_path = tmp / "registry" / "local" / "machines" / "box.yaml"
        assert profile_path.exists()
        reg2 = loader.load(tmp)
        assert reg2.machines["box"]["targets"] == expected_targets
        outputs = planner.plan_machine(reg2, "box")
        skill_paths = [o.deploy_path for o in outputs if "SKILL.md" in o.deploy_path]
        assert not any("org-" in p for p in skill_paths)

def test_scaffold_machine_never_clobbers_existing_profile():
    from agentic import init as initmod
    treg, tmp = _temp_registry()
    written = initmod.scaffold_machine(tmp, name="box", os_name="linux",
                                       use_case="workstation")
    assert written == "local/machines/box.yaml"
    original = (tmp / "registry/local/machines/box.yaml").read_text(encoding="utf-8")
    again = initmod.scaffold_machine(tmp, name="box", os_name="linux", use_case="coding")
    assert again is None
    assert (tmp / "registry/local/machines/box.yaml").read_text(encoding="utf-8") == original
    forced = initmod.scaffold_machine(tmp, name="box", os_name="linux",
                                      use_case="coding", overwrite=True)
    assert forced == "local/machines/box.yaml"
    assert "antigravity" in (tmp / "registry/local/machines/box.yaml").read_text(encoding="utf-8")

def test_scaffold_machine_rejects_unknown_use_case():
    from agentic import init as initmod
    treg, tmp = _temp_registry()
    try:
        initmod.scaffold_machine(tmp, name="box", os_name="linux", use_case="no-such")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

def test_scaffold_machine_accepts_any_coding_harness_subset():
    """The presets are a wizard convenience, not the set of legal machines: ANY non-empty
    subset of the coding harnesses scaffolds a profile that loads, validates, and plans.
    The regression this guards is `mitos init` offering Claude Code as the only
    single-harness option — an Antigravity-only or Claude-Desktop-only box was always
    legal, nobody had just written down the preset."""
    import itertools

    from agentic import init as initmod

    harnesses = list(initmod.CODING_TARGETS)
    assert set(harnesses) == {"claude-code", "antigravity", "claude-app"}
    for size in range(1, len(harnesses) + 1):
        for combo in itertools.combinations(harnesses, size):
            treg, tmp = _temp_registry()
            written = initmod.scaffold_machine(tmp, name="box", os_name="windows",
                                               targets=list(combo))
            assert written == "local/machines/box.yaml"
            reg2 = loader.load(tmp)          # loader._validate runs inside load()
            assert set(reg2.machines["box"]["targets"]) == set(combo)
            planner.plan_machine(reg2, "box")
            # the paths block is the UNION of what those targets need — no more, no less
            expected = {k for t in combo for k in initmod._TARGET_PATH_KEYS[t]}
            assert set(reg2.machines["box"]["paths"]) == expected, combo
            # a coding-harness machine never carries the agentic tree or an org skill
            assert "context-tree" not in reg2.machines["box"]["targets"]

def test_scaffold_machine_rejects_illegal_target_sets():
    from agentic import init as initmod
    bad = (
        {"targets": ["agents-md"]},                    # renamed target
        {"targets": []},                               # nothing to deploy
        {"targets": ["no-such-tool"]},
        {},                                            # neither use_case nor targets
        {"use_case": "coding", "targets": ["claude-code"]},   # both
    )
    for kwargs in bad:
        treg, tmp = _temp_registry()
        try:
            initmod.scaffold_machine(tmp, name="box", os_name="linux", **kwargs)
            raise AssertionError(f"expected ValueError for {kwargs}")
        except ValueError:
            pass
        assert not (tmp / "registry/local/machines/box.yaml").exists(), \
            f"{kwargs}: refused, but still wrote a profile"

def test_scaffold_machine_document_store_is_asked_not_assumed():
    """`document_store:` is written only when the user names a store. Omitting it is the
    honest state for a box whose server isn't running — and it is the one signal every
    connection-bound output is gated on, so a wrong default silently deploys MCP wiring
    and `requires_server:` skills for a connection the user never had."""
    from agentic import init as initmod

    assert initmod.known_servers(REPO_ROOT) == ["gws"]   # the choices are read, not hardcoded

    treg, tmp = _temp_registry()
    initmod.scaffold_machine(tmp, name="box", os_name="windows", targets=["claude-code"])
    reg2 = loader.load(tmp)
    assert "document_store" not in reg2.machines["box"]
    assert not [o for o in planner.plan_machine(reg2, "box") if o.lane == "connections"]

    treg2, tmp2 = _temp_registry()
    initmod.scaffold_machine(tmp2, name="box", os_name="windows",
                             targets=["claude-code"], document_store="gws")
    reg3 = loader.load(tmp2)
    assert reg3.machines["box"]["document_store"] == "gws"

def test_example_project_suppressed_when_overlay_projects_exist():
    """An `example: true` sample steps aside once overlay projects exist — across BOTH
    enumeration trees (agents-md assistant tree + agentic-graph roster). Real reg carries
    overlay projects (apdict, apoc, personal-brand), so example-project must not deploy."""
    rig = _full_windows_rig()
    # Inject a local project and its graph to trigger example project suppression hermetically
    rig.projects["apdict"] = {"name": "Apdict", "slug": "apdict", "_is_local": True, "local_path": {"example-windows": "apdict"}}
    from agentic.graph import ProjectGraph
    rig.graphs["apdict"] = ProjectGraph(slug="apdict", name="Apdict", description="test description", documents=[], efforts=[], path=None)
    outs = planner.plan_machine(rig, "example-windows")
    # agentic-graph roster: example-project absent, real overlay projects present
    graph_paths = [o.deploy_path for o in outs if o.target == "agentic-graph"]
    assert not any("example-project" in p for p in graph_paths), (
        "example-project graph appeared despite overlay projects being present")
    assert any("apdict" in p for p in graph_paths)
    # agents-md assistant tree: "Example Project" folder must not be emitted
    assistant_paths = [o.deploy_path for o in planner.plan_machine(rig, "example-linux")
                       if o.target == "context-tree"]
    assert not any("Example Project" in p for p in assistant_paths), (
        "Example Project assistant-tree entry leaked despite overlay projects being present")
    # the suppression helper reports exactly the example slug
    assert planner._suppressed_examples(rig) == {"example-project"}

def test_example_project_rendered_on_fresh_clone():
    """With no overlay projects (_temp_registry excludes registry/local/), the example sample
    renders — the quick-start fallback must remain intact in both trees."""
    treg, tmp = _temp_registry()
    # no overlay projects → nothing suppressed
    assert treg.projects["example-project"].get("example") is True
    assert planner._suppressed_examples(treg) == set()
    # the assistant tree (rig target = context-tree) still emits the Example Project entry
    assistant_paths = [o.deploy_path for o in planner.plan_machine(treg, "rig")]
    assert any("Example Project" in p for p in assistant_paths)

def test_overlay_machines_and_connections_precedence():
    # the Mitos overlay also covers machine profiles and server connections (last-layer-wins),
    # so private hostnames/IPs and LAN server URLs stay out of the public core.
    import yaml as _y
    treg, tmp = _temp_registry()
    local = tmp / "registry" / "local"
    (local / "machines").mkdir(parents=True, exist_ok=True)
    # override an existing machine's paths, and add a brand-new private machine
    (local / "machines" / "example-windows.yaml").write_text(
        "name: example-windows\nos: windows\ntargets: [claude-code]\n"
        'paths:\n  projects_root: "D:/Private"\n', encoding="utf-8")
    (local / "machines" / "home-server.yaml").write_text(
        "name: home-server\nos: linux\ntargets: [mitos-agent, context-tree]\n"
        'paths:\n  context_root: "~/MitosAgent"\n',
        encoding="utf-8")
    # override the gws server URL with a private LAN address (synthetic, not real)
    (local / "connections").mkdir(parents=True, exist_ok=True)
    core_servers = _y.safe_load(
        (tmp / "connections" / "servers.yaml").read_text(encoding="utf-8"))
    core_servers["servers"]["gws"]["url"] = "http://10.0.0.1:8000/mcp"
    (local / "connections" / "servers.yaml").write_text(
        _y.safe_dump(core_servers), encoding="utf-8")

    reg2 = loader.load(tmp)
    assert reg2.machines["example-windows"]["paths"]["projects_root"] == "D:/Private"  # overridden
    assert "home-server" in reg2.machines                                              # added
    assert "example-linux" in reg2.machines                                            # core-only remains
    assert reg2.servers["servers"]["gws"]["url"] == "http://10.0.0.1:8000/mcp"        # overridden

def test_accept_routes_overlay_content_into_local_not_core():
    # updating your personal moat: a candidate for a partial that the overlay overrides
    # must route the accepted edit into registry/local/, leaving the public core untouched.
    from agentic import review
    treg, tmp = _temp_registry()
    overlay = tmp / "registry" / "local" / "identity"
    overlay.mkdir(parents=True, exist_ok=True)
    (overlay / "comms-style.md").write_text(
        "---\naudience: [mitos-agent]\n---\nOVERLAY body line\n", encoding="utf-8")
    treg = loader.load(tmp)
    assert treg.partials["identity/comms-style.md"].rel == "local/identity/comms-style.md"

    meta = {"registry_path": "identity/comms-style.md", "kind": "drift",
            "source": {"machine": "rig", "tool": "mitos-agent"}, "base_hash": "",
            "deploy_path": "", "sources": ["identity/comms-style.md"],
            "captured_at": "t", "note": "n"}
    _plant_candidate(tmp, "t1--rig--comms", meta, "comms-style.md",
                     "OVERLAY body line\n\n## Personal tweak\nmine\n")
    out = review.decide(treg, "t1--rig--comms", "accept", "")
    assert out["ok"] and out["changed"] == ["local/identity/comms-style.md"]   # overlay, not core
    assert "## Personal tweak" in (tmp / "registry/local/identity/comms-style.md").read_text(
        encoding="utf-8")
    assert "## Personal tweak" not in (tmp / "registry/identity/comms-style.md").read_text(
        encoding="utf-8")   # public core untouched

def test_compile_skips_example_templates_once_a_real_machine_exists():
    import copy

    from agentic.commands import cmd_compile
    tmp = Path(__import__("tempfile").mkdtemp(prefix="ae-compile-ex-"))
    # only example machines (a fresh clone) → all of them compile, so the quick-start works
    examples_only = copy.deepcopy(reg)
    examples_only.machines = {n: m for n, m in examples_only.machines.items()
                              if m.get("example")}
    assert cmd_compile(examples_only, tmp / "a") == 0
    assert (tmp / "a" / "example-windows" / "manifest.json").exists()
    # add one real machine → the examples step aside; only the real machine renders
    withreal = copy.deepcopy(examples_only)
    mybox = copy.deepcopy(reg.machines["example-linux"])
    mybox["name"] = "my-box"
    mybox.pop("example", None)
    withreal.machines["my-box"] = mybox
    assert cmd_compile(withreal, tmp / "b") == 0
    assert (tmp / "b" / "my-box" / "manifest.json").exists()        # real machine rendered
    assert not (tmp / "b" / "example-linux").exists()              # examples skipped
    assert not (tmp / "b" / "example-windows").exists()

def test_scaffold_overlay_preserves_existing_user_files():
    # init must finish AROUND a user's existing custom data, never clobber it
    from agentic import init as initmod
    _treg, tmp = _temp_registry()
    overlay = tmp / "registry" / "local"
    (overlay / "identity").mkdir(parents=True)
    (overlay / "identity" / "who-i-am.md").write_text("MY CUSTOM IDENTITY\n", encoding="utf-8")
    (overlay / "skills" / "mine").mkdir(parents=True)
    (overlay / "skills" / "mine" / "SKILL.md").write_text("mine\n", encoding="utf-8")

    written = initmod.scaffold_overlay(tmp, given_name="Jane", backend="mock")
    # the user's files are untouched and were NOT re-written
    assert (overlay / "identity" / "who-i-am.md").read_text(encoding="utf-8") == \
        "MY CUSTOM IDENTITY\n"
    assert "local/identity/who-i-am.md" not in written
    assert (overlay / "skills" / "mine" / "SKILL.md").read_text(encoding="utf-8") == "mine\n"
    # overwrite=True forces a clean re-scaffold when asked
    written2 = initmod.scaffold_overlay(tmp, given_name="Jane", backend="mock", overwrite=True)
    assert "local/identity/who-i-am.md" in written2
    assert "Jane" in (overlay / "identity" / "who-i-am.md").read_text(encoding="utf-8")


def test_sync_config_capture_writes_a_valid_block_into_the_profile():
    import tempfile

    import yaml as _yaml
    from agentic.sync.config import ensure_profile_sync_block
    tmp = Path(tempfile.mkdtemp(prefix="ae-synccfg-"))
    md = tmp / "registry" / "local" / "machines"
    md.mkdir(parents=True)
    prof = md / "boxA.yaml"
    prof.write_text("name: boxA\nos: linux\ntargets: [context-tree]\n", encoding="utf-8")

    msg = ensure_profile_sync_block(tmp, "boxA", "ssh://h/mitos-local.git",
                                    branch="trunk", ssh_key="~/.ssh/k")
    assert "captured" in msg
    data = _yaml.safe_load(prof.read_text(encoding="utf-8"))   # appended block is valid YAML
    assert data["name"] == "boxA"                              # existing content preserved
    assert data["sync"]["git"] == {"hub": "ssh://h/mitos-local.git",
                                    "branch": "trunk", "ssh_key": "~/.ssh/k"}

    # never overwrites an existing sync block
    msg2 = ensure_profile_sync_block(tmp, "boxA", "ssh://h/mitos-local.git")
    assert "already has a sync block" in msg2

    # missing profile → an instructive message containing the block, no crash
    msg3 = ensure_profile_sync_block(tmp, "ghost", "ssh://h/x.git")
    assert "not found" in msg3 and "sync:" in msg3


# ── repo field validation ──────────────────────────────────────────────────────────────────

def test_repo_validation_accepts_string():
    import copy
    from agentic.loader import _validate
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = "https://github.com/you/x.git"
    _validate(rig)  # must not raise

def test_repo_validation_accepts_list():
    import copy
    from agentic.loader import _validate
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = [
        "https://github.com/you/frontend.git",
        "https://github.com/you/backend.git",
    ]
    _validate(rig)  # must not raise

def test_repo_validation_accepts_empty_string_placeholder():
    import copy
    from agentic.loader import _validate
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = ""   # placeholder — treated as absent
    _validate(rig)  # must not raise

def test_repo_validation_rejects_whitespace_only_string():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = "   "
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "must not be empty" in str(e)

def test_repo_validation_rejects_empty_list():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = []
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "list must not be empty" in str(e)

def test_repo_validation_rejects_non_string_element():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = ["https://github.com/you/x.git", 42]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "list[1] must be a non-empty string" in str(e)

def test_repo_validation_rejects_duplicate_url():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = [
        "https://github.com/you/x.git",
        "https://github.com/you/x.git",
    ]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "duplicate repo URL" in str(e)

def test_repo_validation_rejects_basename_collision():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    # different owners, same repo name → same checkout dirname
    rig.projects["example-project"]["repo"] = [
        "https://github.com/alice/myapp.git",
        "https://github.com/bob/myapp.git",
    ]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "collides" in str(e) and "myapp" in str(e)

def test_repo_validation_rejects_wrong_type():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = {"url": "https://github.com/you/x.git"}
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "string or a list of strings" in str(e)

# ── repo_notes field validation ──────────────────────────────────────────────────────────────

def test_repo_notes_validation_accepts_matching_basename():
    import copy
    from agentic.loader import _validate
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = "https://github.com/you/x.git"
    rig.projects["example-project"]["repo_notes"] = {"x": "the main checkout"}
    _validate(rig)  # must not raise

def test_repo_notes_validation_rejects_unknown_basename():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = "https://github.com/you/x.git"
    rig.projects["example-project"]["repo_notes"] = {"nope": "wrong key"}
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "does not match any" in str(e)

def test_repo_notes_validation_rejects_empty_description():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = "https://github.com/you/x.git"
    rig.projects["example-project"]["repo_notes"] = {"x": "   "}
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "must be a non-empty string" in str(e)

def test_repo_notes_validation_rejects_without_repo():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo_notes"] = {"x": "orphaned note"}
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "does not match any" in str(e)

def test_repo_notes_validation_rejects_non_dict():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = "https://github.com/you/x.git"
    rig.projects["example-project"]["repo_notes"] = ["x", "the main checkout"]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "must be a mapping" in str(e)

# ── multi-store document_store validation ───────────────────────────────────────────────────

def test_document_store_validation_accepts_string():
    import copy
    from agentic.loader import _validate
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["document_store"] = "gws"
    _validate(rig)  # must not raise

def test_document_store_validation_accepts_list():
    import copy
    from agentic.loader import _validate
    rig = copy.deepcopy(reg)
    rig.servers["servers"]["fake2"] = {"description": "Second store — for tests."}
    rig.projects["example-project"]["document_store"] = ["gws", "fake2"]
    _validate(rig)  # must not raise

def test_document_store_validation_rejects_empty_list():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["document_store"] = []
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "list must not be empty" in str(e)

def test_document_store_validation_rejects_duplicate():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["document_store"] = ["gws", "gws"]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "duplicate server name" in str(e)

def test_document_store_validation_rejects_unknown_server_in_list():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["document_store"] = ["gws", "not-a-server"]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "not-a-server" in str(e)

def test_document_store_validation_rejects_none_combined_with_real_store():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["document_store"] = ["gws", "none"]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "cannot be combined" in str(e)

def test_document_store_validation_rejects_wrong_type():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["document_store"] = {"server": "gws"}
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "string or a list of strings" in str(e)

def test_machine_document_store_validation_accepts_list():
    import copy
    from agentic.loader import _validate
    rig = copy.deepcopy(reg)
    rig.servers["servers"]["fake2"] = {"description": "Second store — for tests."}
    rig.machines["rig"] = {
        "name": "rig", "os": "windows", "targets": ["claude-code"],
        "document_store": ["gws", "fake2"],
    }
    _validate(rig)  # must not raise

def test_machine_document_store_validation_rejects_duplicate():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.machines["rig"] = {
        "name": "rig", "os": "windows", "targets": ["claude-code"],
        "document_store": ["gws", "gws"],
    }
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "duplicate server name" in str(e)

def test_document_stores_helper_normalizes_str_list_none():
    from agentic.loader import document_stores
    assert document_stores(None) == []
    assert document_stores("gws") == ["gws"]
    assert document_stores(["gws", "fake2"]) == ["gws", "fake2"]

# ── multi-repo clone planning ──────────────────────────────────────────────────────────────

def test_plan_clones_multi_repo():
    import copy
    rig = copy.deepcopy(reg)
    # Use example-linux (assistant_root lane)
    rig.projects["example-project"]["repo"] = [
        "https://github.com/you/frontend.git",
        "https://github.com/you/backend.git",
    ]
    clones = planner.plan_clones(rig, "example-linux")
    ep_clones = [c for c in clones if c.slug == "example-project"]
    assert len(ep_clones) == 2
    dests = {c.dest for c in ep_clones}
    assert any("frontend" in d for d in dests)
    assert any("backend" in d for d in dests)
    # each dest is unique (no collision)
    assert len(dests) == 2

def test_plan_clones_single_string_repo_still_works():
    import copy
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = "https://github.com/you/myapp.git"
    clones = planner.plan_clones(rig, "example-linux")
    ep_clones = [c for c in clones if c.slug == "example-project"]
    assert len(ep_clones) == 1
    assert "myapp" in ep_clones[0].dest


# ── skill scope: global (default) | project ─────────────────────────────────────
def test_skill_scope_defaults_global():
    from agentic.loader import Skill
    s = Skill(name="x", rel="skills/x/SKILL.md", frontmatter={"targets": ["claude-code"]}, body="")
    assert s.scope == "global"

def test_skill_scope_reads_frontmatter():
    from agentic.loader import Skill
    s = Skill(name="x", rel="skills/x/SKILL.md",
              frontmatter={"targets": ["antigravity"], "scope": "project"}, body="")
    assert s.scope == "project"

def test_validate_skill_scope_rejects_unknown_value():
    from agentic.loader import validate_skill_scope
    err = validate_skill_scope("x", {"targets": ["antigravity"], "scope": "workspace"})
    assert err and "invalid scope" in err

def test_validate_skill_scope_accepts_global_and_project_on_capable_targets():
    from agentic.loader import validate_skill_scope
    assert validate_skill_scope("x", {"targets": ["claude-code"]}) is None
    assert validate_skill_scope("x", {"targets": ["antigravity"], "scope": "project"}) is None
    assert validate_skill_scope(
        "x", {"targets": ["claude-code", "antigravity"], "scope": "project"}) is None

def test_validate_skill_scope_project_scope_ignores_claude_app_pairing():
    """A skill may target claude-app alongside a project-scope-capable target —
    claude-app has no project-scoped surface, so it just ignores `scope` (always ships
    globally) rather than being flagged incompatible."""
    from agentic.loader import validate_skill_scope
    assert validate_skill_scope(
        "x", {"targets": ["claude-app", "claude-code"], "scope": "project"}) is None
    assert validate_skill_scope("x", {"targets": ["claude-app"], "scope": "project"}) is None

def test_registry_load_rejects_bad_skill_scope():
    import copy
    from agentic.loader import RegistryError, Skill, _validate
    rig = copy.deepcopy(reg)
    rig.skills["bad-scope"] = Skill(
        name="bad-scope", rel="local/skills/bad-scope/SKILL.md",
        frontmatter={"targets": ["claude-code"], "scope": "workspace"}, body="body")
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "invalid scope" in str(e)

def test_project_can_bind_skill_that_only_targets_antigravity():
    """The project skills: binding check accepts any project-scope-capable target
    (claude-code OR antigravity), not just claude-code."""
    import copy
    from agentic.loader import Skill, _validate
    rig = copy.deepcopy(reg)
    rig.skills["antigravity-only"] = Skill(
        name="antigravity-only", rel="local/skills/antigravity-only/SKILL.md",
        frontmatter={"targets": ["antigravity"], "scope": "project"}, body="body")
    rig.projects["example-project"]["skills"] = ["antigravity-only"]
    _validate(rig)  # must not raise

def test_project_cannot_bind_skill_with_no_project_scope_capable_target():
    import copy
    from agentic.loader import RegistryError, Skill, _validate
    rig = copy.deepcopy(reg)
    rig.skills["app-only"] = Skill(
        name="app-only", rel="local/skills/app-only/SKILL.md",
        frontmatter={"targets": ["claude-app"]}, body="body")
    rig.projects["example-project"]["skills"] = ["app-only"]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "project-scoped skill surface" in str(e)


# ── skill supporting files (examples/, scripts/) — R5/R6 ───────────────────────
def test_skill_resources_loaded_from_examples_and_scripts():
    treg, tmp = _temp_registry()
    skill_dir = tmp / "registry" / "skills" / "res-skill"
    (skill_dir / "examples").mkdir(parents=True)
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: res-skill\ndescription: d\ntargets: [mitos-agent]\ncategory: general\n---\n"
        "body\n", encoding="utf-8")
    (skill_dir / "examples" / "sample.md").write_text("expected output\n", encoding="utf-8")
    (skill_dir / "scripts" / "validate.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    reg2 = loader.load(tmp)
    skill = reg2.skills["res-skill"]
    assert set(skill.resources) == {"examples/sample.md", "scripts/validate.sh"}
    assert skill.resources["examples/sample.md"].text == "expected output\n"
    assert skill.resources["examples/sample.md"].rel == "skills/res-skill/examples/sample.md"
    assert skill.resources["scripts/validate.sh"].rel == "skills/res-skill/scripts/validate.sh"

def test_skill_resources_loaded_from_all_harness_convention_dirs():
    """_SKILL_RESOURCE_DIRS is the union of the harnesses' documented conventions:
    examples/scripts (Claude Code, Antigravity), references/templates (Mitos Agent),
    resources (Antigravity). A file under any of them loads; anything else is ignored."""
    treg, tmp = _temp_registry()
    skill_dir = tmp / "registry" / "skills" / "conv-skill"
    for sub in ("references", "templates", "resources", "unrelated"):
        (skill_dir / sub).mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: conv-skill\ndescription: d\ntargets: [mitos-agent]\ncategory: general\n---\n"
        "body\n", encoding="utf-8")
    (skill_dir / "references" / "api.md").write_text("api\n", encoding="utf-8")
    (skill_dir / "templates" / "config.yaml").write_text("k: v\n", encoding="utf-8")
    (skill_dir / "resources" / "notes.md").write_text("notes\n", encoding="utf-8")
    (skill_dir / "unrelated" / "junk.md").write_text("junk\n", encoding="utf-8")
    reg2 = loader.load(tmp)
    assert set(reg2.skills["conv-skill"].resources) == {
        "references/api.md", "templates/config.yaml", "resources/notes.md"}

def test_skill_resource_binary_file_rejected():
    from agentic.loader import RegistryError
    treg, tmp = _temp_registry()
    skill_dir = tmp / "registry" / "skills" / "bin-skill"
    (skill_dir / "examples").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: bin-skill\ndescription: d\ntargets: [mitos-agent]\ncategory: general\n---\n"
        "body\n", encoding="utf-8")
    (skill_dir / "examples" / "asset.bin").write_bytes(b"\xff\xfe\x00\x01binary")
    try:
        loader.load(tmp)
        raise AssertionError("expected RegistryError for binary resource")
    except RegistryError as e:
        assert "must be UTF-8 text" in str(e)


# ── dynamic agentic branches — R7 ───────────────────────────────────────────────
def test_dynamic_branch_discovered_and_deployed():
    from agentic.loader import Partial
    rig = _full_windows_rig()
    rig.partials["context/family/AGENTS.md"] = Partial(
        rel="context/family/AGENTS.md", audience=None,
        body="# Family\n\nFamily branch root.")
    rig.partials["context/family/notes.md"] = Partial(
        rel="context/family/notes.md", audience=None, body="Family notes.")
    outs = planner.plan_machine(rig, "example-linux")
    paths = {o.deploy_path: o for o in outs if o.target == "context-tree"}
    assert any(p.endswith("/family/AGENTS.md") for p in paths)
    assert any(p.endswith("/family/notes.md") for p in paths)
    root_out = next(o for p, o in paths.items() if p.endswith("/AGENTS.md")
                    and "/family/" not in p and "/Projects/" not in p and "/Assistant/" not in p)
    assert "family/" in root_out.content

def test_dynamic_branch_reserved_name_collision_rejected():
    from agentic.loader import Partial, RegistryError
    rig = _full_windows_rig()
    rig.partials["context/Projects/AGENTS.md"] = Partial(
        rel="context/Projects/AGENTS.md", audience=None, body="colliding branch.")
    try:
        planner.plan_machine(rig, "example-linux")
        raise AssertionError("expected RegistryError for reserved branch name")
    except RegistryError as e:
        assert "collides with a reserved top-level entry" in str(e)

def test_project_description_must_be_a_nonempty_string():
    """`description:` feeds the generated Project Roster — a non-string (or blank)
    value fails loudly at load, same posture as every other manifest field."""
    from agentic.loader import RegistryError
    treg, tmp = _temp_registry()
    py = tmp / "registry" / "projects" / "example-project.yaml"
    txt = py.read_text(encoding="utf-8")
    assert "description:" in txt, "example manifest should demonstrate description:"
    py.write_text(txt.replace(
        "description: one-line summary shown on the generated Project Roster (Projects/AGENTS.md)",
        "description: 42"), encoding="utf-8")
    try:
        loader.load(tmp)
        raise AssertionError("expected RegistryError for non-string description")
    except RegistryError as e:
        assert "'description' must be a non-empty string" in str(e)


def test_project_aliases_validation():
    """Project aliases must be a list of non-empty strings, free of ']' and '_'."""
    import copy
    from agentic.loader import RegistryError, _validate
    rig = copy.deepcopy(reg)
    slug = "example-project"

    # Non-list fails
    rig.projects[slug]["aliases"] = "not a list"
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for non-list aliases")
    except RegistryError as e:
        assert "'aliases' must be a list of strings" in str(e)

    # Non-string item fails
    rig.projects[slug]["aliases"] = [123]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for non-string alias")
    except RegistryError as e:
        assert "'aliases' must be a list of strings" in str(e)

    # Empty string alias fails
    rig.projects[slug]["aliases"] = [""]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for empty alias")
    except RegistryError as e:
        assert "alias in 'aliases' cannot be empty" in str(e)

    # Alias containing ']' fails
    rig.projects[slug]["aliases"] = ["bad]alias"]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for alias with ']'")
    except RegistryError as e:
        assert "contains invalid character" in str(e)

    # Alias containing '_' fails
    rig.projects[slug]["aliases"] = ["bad_alias"]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for alias with '_'")
    except RegistryError as e:
        assert "contains invalid character" in str(e)

    # Valid aliases list passes
    rig.projects[slug]["aliases"] = ["sensual predictions", "apdicts"]
    _validate(rig)


# ── Agent loading, curation, and validation ──────────────────────────────────
def test_agent_loads_and_validates():
    treg, tmp = _temp_registry()
    adir = tmp / "registry" / "agents"
    adir.mkdir(parents=True)
    agent_file = adir / "personal-crm.md"
    agent_file.write_text(
        "---\n"
        "name: personal-crm\n"
        "description: Manage personal contacts and CRM\n"
        "targets: [mitos-agent]\n"
        "goal: Keep relationships organized and up to date\n"
        "skills: [new-session]\n"
        "---\n"
        "# Instructions\n"
        "Help the owner manage personal contacts.\n",
        encoding="utf-8"
    )
    reg2 = loader.load(tmp)
    assert "personal-crm" in reg2.agents
    ag = reg2.agents["personal-crm"]
    assert ag.name == "personal-crm"
    assert ag.description == "Manage personal contacts and CRM"
    assert ag.targets == ["mitos-agent"]
    assert ag.goal == "Keep relationships organized and up to date"
    assert ag.skills == ["new-session"]
    assert "Help the owner manage personal contacts." in ag.body
    assert ag.source == agent_file


def test_agent_refuses_unknown_skill():
    treg, tmp = _temp_registry()
    adir = tmp / "registry" / "agents"
    adir.mkdir(parents=True)
    agent_file = adir / "bad-skill-agent.md"
    agent_file.write_text(
        "---\n"
        "name: bad-skill-agent\n"
        "description: desc\n"
        "targets: [mitos-agent]\n"
        "goal: goal\n"
        "skills: [unknown-skill]\n"
        "---\n"
        "body\n",
        encoding="utf-8"
    )
    try:
        loader.load(tmp)
        raise AssertionError("expected RegistryError for unknown skill in agent")
    except loader.RegistryError as e:
        assert "bad-skill-agent" in str(e)
        assert "unknown-skill" in str(e)


def test_agent_refuses_non_mitos_agent_skill():
    # Skill exists, but doesn't target mitos-agent
    treg, tmp = _temp_registry()
    sdir = tmp / "registry" / "skills" / "claude-only"
    sdir.mkdir(parents=True)
    (sdir / "SKILL.md").write_text(
        "---\n"
        "name: claude-only\n"
        "description: only for claude\n"
        "targets: [claude-code]\n"
        "---\n"
        "body\n",
        encoding="utf-8"
    )
    adir = tmp / "registry" / "agents"
    adir.mkdir(parents=True)
    agent_file = adir / "bad-target-agent.md"
    agent_file.write_text(
        "---\n"
        "name: bad-target-agent\n"
        "description: desc\n"
        "targets: [mitos-agent]\n"
        "goal: goal\n"
        "skills: [claude-only]\n"
        "---\n"
        "body\n",
        encoding="utf-8"
    )
    try:
        loader.load(tmp)
        raise AssertionError("expected RegistryError for agent skill not targeting mitos-agent")
    except loader.RegistryError as e:
        assert "bad-target-agent" in str(e)
        assert "claude-only" in str(e)


def test_agent_refuses_name_mismatch():
    treg, tmp = _temp_registry()
    adir = tmp / "registry" / "agents"
    adir.mkdir(parents=True)
    agent_file = adir / "agent-one.md"
    agent_file.write_text(
        "---\n"
        "name: agent-different\n"
        "description: desc\n"
        "targets: [mitos-agent]\n"
        "goal: goal\n"
        "skills: [gws]\n"
        "---\n"
        "body\n",
        encoding="utf-8"
    )
    try:
        loader.load(tmp)
        raise AssertionError("expected RegistryError for agent name mismatch")
    except loader.RegistryError as e:
        assert "agent-one" in str(e)
        assert "does not match filename stem" in str(e)


def test_agent_refuses_unknown_key():
    treg, tmp = _temp_registry()
    adir = tmp / "registry" / "agents"
    adir.mkdir(parents=True)
    agent_file = adir / "agent-bad-key.md"
    agent_file.write_text(
        "---\n"
        "name: agent-bad-key\n"
        "description: desc\n"
        "targets: [mitos-agent]\n"
        "goal: goal\n"
        "skills: [gws]\n"
        "extra_key: foo\n"
        "---\n"
        "body\n",
        encoding="utf-8"
    )
    try:
        loader.load(tmp)
        raise AssertionError("expected RegistryError for unknown frontmatter key in agent")
    except loader.RegistryError as e:
        assert "agent-bad-key" in str(e)
        assert "unknown frontmatter key(s)" in str(e)


def test_curation_accepts_twenty_agents():
    import copy
    from agentic.loader import Agent, _validate
    rig = copy.deepcopy(reg)
    rig.machines["example-linux"]["targets"] = ["claude-code"]
    # Populate rig with 20 agents
    for i in range(20):
        name = f"agent-{i:02d}"
        rig.agents[name] = Agent(
            name=name, description=f"Agent {i}", targets=["claude-code"], goal=f"Goal {i}",
            skills=["new-session"], body="body", source=Path(f"/fake/{name}.md")
        )
    _validate(rig)
    selected = loader.selected_agents(rig, rig.machines["example-linux"])
    assert len(selected) == 20


def test_loader_accepts_twenty_one_agents():
    import copy
    from agentic.loader import Agent, _validate
    rig = copy.deepcopy(reg)
    rig.machines["example-linux"]["targets"] = ["claude-code"]
    for i in range(21):
        name = f"agent-{i:02d}"
        rig.agents[name] = Agent(
            name=name, description=f"Agent {i}", targets=["claude-code"], goal=f"Goal {i}",
            skills=["new-session"], body="body", source=Path(f"/fake/{name}.md")
        )
    _validate(rig)
    selected = loader.selected_agents(rig, rig.machines["example-linux"])
    assert len(selected) == 21


def test_machine_agent_missing_curated_skill():
    import copy
    from agentic.loader import Agent, _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.machines["example-linux"]["targets"] = ["claude-code"]
    rig.agents["crm-agent"] = Agent(
        name="crm-agent", description="CRM", targets=["claude-code"], goal="Goal",
        skills=["new-session"], body="body", source=Path("/fake/crm-agent.md")
    )
    # Exclude new-session skill from claude-code target on a real (non-template) machine
    rig.machines["example-linux"]["example"] = False
    rig.machines["example-linux"]["skills"] = {"claude-code": {"exclude": ["new-session"]}}
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for missing curated skill")
    except RegistryError as e:
        msg = str(e)
        assert "crm-agent" in msg
        assert "new-session" in msg


def test_example_machine_skips_agent_skill_check():
    import copy
    from agentic.loader import Agent, _validate
    rig = copy.deepcopy(reg)
    rig.machines["example-linux"]["targets"] = ["claude-code"]
    rig.agents["crm-agent"] = Agent(
        name="crm-agent", description="CRM", targets=["claude-code"], goal="Goal",
        skills=["new-session"], body="body", source=Path("/fake/crm-agent.md")
    )
    assert rig.machines["example-linux"].get("example") is True
    rig.machines["example-linux"]["skills"] = {"claude-code": {"exclude": ["new-session"]}}
    _validate(rig)          # a template is never deployed, so it cannot strand the agent


def test_manifest_agents_key_still_rejected():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["agents"] = ["something"]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for project agents key")
    except RegistryError as e:
        assert "'agents' is not a manifest field — agents are registry resources in registry/agents/, curated per machine under `agents:`" in str(e)


# ── Milestone 2: unknown target skip & project_surface ─────────────────────────
def test_machine_with_unknown_target_is_skipped_with_warning():
    import pytest
    import yaml as _y
    from agentic import planner
    treg, tmp = _temp_registry()
    mach_file = tmp / "machines" / "unknown-mach.yaml"
    mach_cfg = {
        "name": "unknown-mach",
        "targets": ["nonexistent-target"],
        "paths": {"projects_root": "C:/Projects"},
    }
    mach_file.write_text(_y.safe_dump(mach_cfg), encoding="utf-8")
    loaded = loader.load(tmp)
    assert "unknown-mach" in loaded.skipped_machines
    assert any("machine unknown-mach: target 'nonexistent-target' is not defined — machine skipped." in w and "accept its seed in the inbox" in w for w in loaded.warnings)
    # plan_machine for the skipped machine is refused with RegistryError
    with pytest.raises(loader.RegistryError) as exc_info:
        planner.plan_machine(loaded, "unknown-mach")
    assert "machine unknown-mach: target 'nonexistent-target' is not defined — machine skipped" in str(exc_info.value)
    # other machines plan without error
    rig_planned = planner.plan_machine(loaded, "rig")
    assert rig_planned


def test_project_scope_follows_target_spec():
    import copy
    import pytest
    from agentic.loader import RegistryError, Skill, _validate
    r = copy.deepcopy(reg)
    # custom target with project_surface: true
    r.targets["custom-proj-capable"] = {"project_surface": True}
    r.skills["custom-skill"] = Skill(
        name="custom-skill", rel="local/skills/custom-skill/SKILL.md",
        frontmatter={"targets": ["custom-proj-capable"]}, body="body")
    r.projects["example-project"]["skills"] = ["custom-skill"]
    _validate(r)  # must not raise

    # custom target with project_surface: false
    r2 = copy.deepcopy(reg)
    r2.targets["custom-not-capable"] = {"project_surface": False}
    r2.skills["custom-skill2"] = Skill(
        name="custom-skill2", rel="local/skills/custom-skill2/SKILL.md",
        frontmatter={"targets": ["custom-not-capable"]}, body="body")
    r2.projects["example-project"]["skills"] = ["custom-skill2"]
    with pytest.raises(RegistryError) as exc_info:
        _validate(r2)
    assert "project-scoped skill surface" in str(exc_info.value)

