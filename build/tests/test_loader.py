"""Loader, overlay, machine, project, and init tests."""
from __future__ import annotations

import sys
from pathlib import Path

from conftest import (
    REPO_ROOT, reg, loader, planner, render, classify_output,
    _inbox, _temp_registry, _doc, _write_graph,
    _plant_candidate, _skill_meta, _full_windows_rig, _sandbox_deploy,
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

    # 4. Mitos builder context must exist and contain the write-guard Invariants.
    #    Their absence would let an impostor AGENTS.md instruct agents without the
    #    repo-write prohibition and inbox-only proposal rule.
    builder_rel = (core_reg.projects.get("mitos") or {}).get("context", {}).get("builder", "")
    assert builder_rel, "mitos project missing context.builder — builder AGENTS.md cannot be generated"
    # Manifests store paths as "registry/<rel>"; partials are keyed without the prefix
    partial_key = builder_rel.removeprefix("registry/")
    assert partial_key in core_reg.partials, (
        f"mitos context.builder partial {builder_rel!r} missing from registry — "
        f"builder AGENTS.md cannot be compiled and write-guard Invariants are absent")
    builder_body = core_reg.partials[partial_key].body
    assert "Invariants" in builder_body, (
        "mitos builder context is missing the Invariants section — possible tampering; "
        "agents would operate without structural guardrails")
    assert "Never write into" in builder_body, (
        "mitos builder context is missing the registry write-guard rule — possible tampering; "
        "agents and humans could bypass the inbox and modify the registry directly")

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
    # the manifests' relative entries must land exactly where the absolute ones did
    outs = planner.plan_machine(_full_windows_rig(), "example-windows")
    assert any(o.deploy_path == "C:/Projects/example-project/CLAUDE.md" for o in outs)
    assert any(o.deploy_path == "C:/Projects/mitos/AGENTS.md" for o in outs)

def test_per_machine_server_url():
    # the neutral core ships gws at localhost with no per-machine overrides (urls: {}).
    # Use a temp registry (no registry/local/) so a user's LAN overlay doesn't bleed in.
    treg, _ = _temp_registry()
    assert treg.servers["servers"]["gws"]["urls"] == {}
    win = planner.plan_machine(treg, "example-windows")
    mcp_cfg = next(o for o in win if o.deploy_path.endswith("mcp_config.json"))
    assert "http://localhost:8000/mcp" in mcp_cfg.content
    linux = planner.plan_machine(treg, "example-linux")
    hermes_block = next(o for o in linux if o.kind == "yaml_merge")
    assert "http://localhost:8000/mcp" in hermes_block.content

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
    rig = copy.deepcopy(reg)
    rig.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    rig.machines["example-windows"]["paths"]["agentic_context_root"] = "C:/Projects/mitos"
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError due to workspace path overlap")
    except RegistryError as e:
        assert "must not overlap with project 'mitos' workspace path" in str(e)

def test_planner_output_path_collision():
    import copy
    from agentic import planner
    from agentic.loader import RegistryError
    rig = copy.deepcopy(reg)
    rig.machines["example-windows"]["paths"]["antigravity_skills"] = "C:/GeminiPrompts"
    rig.targets["gemini"]["skills"]["subdir"] = "AGENTS.md"
    try:
        planner.plan_machine(rig, "example-windows")
        raise AssertionError("expected RegistryError due to duplicate output path")
    except RegistryError as e:
        assert "output path collision on" in str(e)
        assert "Target 'gemini'" in str(e)

def test_filter_prior_by_machine_paths():
    from agentic.commands import _filter_prior_by_machine_paths
    import copy
    rig = copy.deepcopy(reg)

    # Configure path keys
    rig.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    rig.machines["example-windows"]["paths"]["gemini_config"] = "~/.gemini/config"

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
        "---\naudience: [hermes]\n---\nOVERLAY comms rules\n", encoding="utf-8")
    (local / "skills" / "extra").mkdir(parents=True)              # add a new local skill
    (local / "skills" / "extra" / "SKILL.md").write_text(
        "---\nname: extra\ndescription: d\ntargets: [hermes]\ncategory: productivity\n---\n"
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

def test_init_scaffolds_overlay_and_org_template_reaches_soul():
    # mitos init scaffolds the overlay; the chosen org template REPLACES the default core
    # org by landing in the overlay and overriding the core — and flows into SOUL.md
    from agentic import init as initmod
    treg, tmp = _temp_registry()
    assert set(initmod.org_templates(tmp)) == {"marketing-firm", "software-firm", "design-firm"}
    written = initmod.scaffold_overlay(tmp, given_name="Jane", family_name="Doe",
                                       address="Ms. Doe", email="jane@example.com",
                                       location="NYC", org_template="design-firm",
                                       backend="mock")
    # init now seeds only org-hierarchy + who-i-am + README (domain skills ship in core)
    assert "local/identity/org-hierarchy.md" in written
    assert "local/context/collaboration.md" not in written
    assert "local/context/org-roles.md" not in written
    # the captured name + form of address land in the overlay identity, which overrides the
    # neutral core who-i-am.md for every tool — skills stay neutral and read the name here
    who = (tmp / "registry/local/identity/who-i-am.md").read_text(encoding="utf-8")
    assert "Jane Doe" in who and 'Address me as "Ms. Doe"' in who
    reg2 = loader.load(tmp)
    org = reg2.partials["identity/org-hierarchy.md"]
    assert org.rel == "local/identity/org-hierarchy.md" and "Creative Director" in org.body
    outputs = planner.plan_machine(reg2, "rig")
    soul = next(o for o in outputs if o.deploy_path.endswith("SOUL.md"))
    assert "Creative Director" in soul.content              # overlay org reached SOUL.md
    # domain org skills ship in core and are available on all hermes machines
    assert "org-software" in reg2.skills
    assert "org-design" in reg2.skills
    assert "org-marketing" in reg2.skills
    # Assistant/AGENTS.md replaces Collaboration/AGENTS.md
    assistant = next((o for o in outputs
                      if o.deploy_path.endswith("Assistant/AGENTS.md")), None)
    assert assistant is not None, "Assistant/AGENTS.md must be planned for agents-md"
    assert not any(o.deploy_path.endswith("Collaboration/AGENTS.md") for o in outputs)
    # Projects/AGENTS.md is still planned (roster of all projects)
    projects_agents = next((o for o in outputs
                            if o.deploy_path.endswith("Projects/AGENTS.md")), None)
    assert projects_agents is not None
    # an unknown template is refused without writing
    try:
        initmod.scaffold_overlay(tmp, given_name="x", email="y", org_template="no-such")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

def test_example_project_suppressed_when_overlay_projects_exist():
    """An `example: true` sample steps aside once overlay projects exist — across BOTH
    enumeration trees (agents-md assistant tree + agentic-graph roster). Real reg carries
    overlay projects (apdict, apoc, personal-brand), so example-project must not deploy."""
    outs = planner.plan_machine(_full_windows_rig(), "example-windows")
    # agentic-graph roster: example-project absent, real overlay projects present
    graph_paths = [o.deploy_path for o in outs if o.target == "agentic-graph"]
    assert not any("example-project" in p for p in graph_paths), (
        "example-project graph appeared despite overlay projects being present")
    assert any("apdict" in p for p in graph_paths)
    # agents-md assistant tree: "Example Project" folder must not be emitted
    assistant_paths = [o.deploy_path for o in planner.plan_machine(_full_windows_rig(), "example-linux")
                       if o.target == "agents-md"]
    assert not any("Example Project" in p for p in assistant_paths), (
        "Example Project assistant-tree entry leaked despite overlay projects being present")
    # the suppression helper reports exactly the example slug
    assert planner._suppressed_examples(reg) == {"example-project"}

def test_example_project_rendered_on_fresh_clone():
    """With no overlay projects (_temp_registry excludes registry/local/), the example sample
    renders — the quick-start fallback must remain intact in both trees."""
    treg, tmp = _temp_registry()
    # no overlay projects → nothing suppressed
    assert treg.projects["example-project"].get("example") is True
    assert planner._suppressed_examples(treg) == set()
    # the assistant tree (rig target = agents-md) still emits the Example Project entry
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
        "name: home-server\nos: linux\ntargets: [hermes]\n"
        'paths:\n  hermes_home: "~/.hermes"\n  hermes_config: "~/.hermes/config.yaml"\n',
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
        "---\naudience: [hermes]\n---\nOVERLAY body line\n", encoding="utf-8")
    treg = loader.load(tmp)
    assert treg.partials["identity/comms-style.md"].rel == "local/identity/comms-style.md"

    meta = {"registry_path": "identity/comms-style.md", "kind": "drift",
            "source": {"machine": "rig", "tool": "hermes"}, "base_hash": "",
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

    written = initmod.scaffold_overlay(tmp, given_name="Jane", org_template="marketing-firm",
                                       backend="mock")
    # the user's files are untouched and were NOT re-written
    assert (overlay / "identity" / "who-i-am.md").read_text(encoding="utf-8") == \
        "MY CUSTOM IDENTITY\n"
    assert "local/identity/who-i-am.md" not in written
    assert (overlay / "skills" / "mine" / "SKILL.md").read_text(encoding="utf-8") == "mine\n"
    # but genuinely missing pieces are still seeded
    assert "local/identity/org-hierarchy.md" in written
    # domain org skills now ship in core — init no longer seeds skills/org/SKILL.md
    assert (overlay / "skills" / "org" / "SKILL.md").exists() is False
    # overwrite=True forces a clean re-scaffold when asked
    written2 = initmod.scaffold_overlay(tmp, given_name="Jane", org_template="marketing-firm",
                                        backend="mock", overwrite=True)
    assert "local/identity/who-i-am.md" in written2
    assert "Jane" in (overlay / "identity" / "who-i-am.md").read_text(encoding="utf-8")

def test_init_org_template_optional():
    # scaffold_overlay with org_template=None (the default) skips seeding org-hierarchy.md —
    # the core multi-org domain router is used as-is; who-i-am.md and README are still seeded
    from agentic import init as initmod
    _treg, tmp = _temp_registry()
    written = initmod.scaffold_overlay(tmp, given_name="Sam", email="sam@example.com")
    assert "local/identity/who-i-am.md" in written
    assert "local/README.md" in written
    assert "local/identity/org-hierarchy.md" not in written

def test_sync_config_capture_writes_a_valid_block_into_the_profile():
    import tempfile

    import yaml as _yaml
    from agentic.sync.config import ensure_profile_sync_block
    tmp = Path(tempfile.mkdtemp(prefix="ae-synccfg-"))
    md = tmp / "registry" / "local" / "machines"
    md.mkdir(parents=True)
    prof = md / "boxA.yaml"
    prof.write_text("name: boxA\nos: linux\ntargets: [agents-md]\n", encoding="utf-8")

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

# ── multi-repo clone planning ──────────────────────────────────────────────────────────────

def test_plan_clones_multi_repo_local_path_lane():
    import copy
    rig = copy.deepcopy(reg)
    # Use example-windows (no agents-md, no agentic_context_root) — local_path lane
    rig.machines["example-windows"]["targets"] = ["claude-code"]
    rig.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    rig.projects["example-project"]["repo"] = [
        "https://github.com/you/frontend.git",
        "https://github.com/you/backend.git",
    ]
    clones = planner.plan_clones(rig, "example-windows")
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
    rig.machines["example-windows"]["targets"] = ["claude-code"]
    rig.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    rig.projects["example-project"]["repo"] = "https://github.com/you/myapp.git"
    clones = planner.plan_clones(rig, "example-windows")
    ep_clones = [c for c in clones if c.slug == "example-project"]
    assert len(ep_clones) == 1
    assert "myapp" in ep_clones[0].dest

