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
    # example-linux ships with no document_store — declare it, since MCP wiring is gated
    # on the machine actually having the connection (planner._gws)
    linux = planner.plan_machine(_connected_rig("example-linux", base=treg), "example-linux")
    # Mitos Agent writes a whole-file mcp.json (kind="json"), not a yaml_merge block.
    mcp_json = next(o for o in linux if o.deploy_path.endswith("mcp.json"))
    assert "http://localhost:8000/mcp" in mcp_json.content

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

def test_machine_role_exclusivity_assistant_vs_coding():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.machines["example-linux"]["targets"] = ["mitos-agent", "agents-md", "claude-code"]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError due to hermes + coding target on one machine")
    except RegistryError as e:
        assert "cannot share a machine with coding harness target(s)" in str(e)
        assert "claude-code" in str(e)

def test_mitos_agent_requires_agents_md():
    """The harness traverses the agents-md operating tree, so mitos-agent without agents-md
    on the same machine is refused — it would install SOUL/skills/mcp with no tree to read."""
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.machines["example-linux"]["targets"] = ["mitos-agent"]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError: mitos-agent needs agents-md")
    except RegistryError as e:
        assert "requires 'agents-md'" in str(e)

def test_machine_role_agents_md_alone_is_not_a_coding_harness():
    """agents-md is the context format, not a harness — it may coexist with hermes
    (the agentic machine-mount combo) with no exclusivity violation."""
    import copy
    from agentic.loader import _validate
    rig = copy.deepcopy(reg)
    rig.machines["example-linux"]["targets"] = ["mitos-agent", "agents-md"]
    _validate(rig)  # must not raise

def test_agents_md_without_assistant_target_never_leaks_org_routing():
    """The actual bug this exists to prevent: `agents-md` alone (no `hermes` target) is a
    valid, common shape — example-windows.yaml ships exactly this (claude-code +
    antigravity + claude-app + agents-md) — but org skills declare `targets: [mitos-agent]`
    only, so they never deploy there. Both org-rendering surfaces (the agentic-graph
    reference mount via agentic_context_root, and the org-domain table on the
    agents-md/assistant tree) must therefore omit orgs entirely on such a machine, even
    though example-project's 'Launch Prep' effort IS tagged orgDomain: marketing.
    A real hermes machine (example-linux) must still carry both."""
    rig = _full_windows_rig()  # agents-md, no hermes — mirrors example-windows.yaml exactly
    outs = planner.plan_machine(rig, "example-windows")
    graph_tree = [o for o in outs if o.target == "agentic-graph"]
    assert graph_tree, "agentic_context_root must still materialize the reference mount"
    for o in graph_tree:
        assert "org-marketing" not in o.content
        assert "runs under the `marketing` org" not in o.content

    hermes_outs = planner.plan_machine(reg, "example-linux")
    projects_agents = next(o for o in hermes_outs
                           if o.deploy_path.endswith("Projects/AGENTS.md"))
    assert "org-marketing" in projects_agents.content        # org-domain table present
    example_agents = next(o for o in hermes_outs
                          if o.deploy_path.endswith("Projects/Example Project/AGENTS.md"))
    assert "runs under the `marketing` org" in example_agents.content

def test_coverage_line_renders_without_an_assistant_target():
    """The never-gated decision, asserted at the PLANNER level rather than the renderer.

    `_effort_coverage_line` takes no `org_routing` argument, so graph-level tests can only
    show that the renderer never gates it. This asserts the property that actually matters:
    on a real `claude-code + agents-md` machine with NO mitos-agent target — the shape
    example-windows.yaml ships — the coverage line still reaches the deployed tree while the
    org routing line beside it stays suppressed. The two lines sit under the same heading and
    are one edit away from being gated together; that edit is what this test exists to catch.

    Coverage names no skill to load, so it is descriptive metadata a coding harness benefits
    from reading. Org routing issues an instruction ("load the `org-marketing` skill") that is
    false on a machine where that skill was never deployed."""
    from dataclasses import replace
    rig = _full_windows_rig()          # agents-md + claude-code, no mitos-agent
    pg = rig.graphs["example-project"]
    pg.efforts = [replace(e, requirements_coverage=("performance", "security"))
                  if e.id == "launch-prep" else e for e in pg.efforts]

    outs = planner.plan_machine(rig, "example-windows")
    # The RENDERED line, not the phrase: the builder context (registry/context/projects/mitos.md)
    # documents this feature in prose and would otherwise match.
    line = "_Requirements coverage: performance, security._"      # canonical order preserved
    rendered = [o for o in outs if line in o.content]
    assert rendered, "the coverage line must survive on a machine with no assistant target"
    for o in rendered:
        assert "runs under the `marketing` org" not in o.content   # ...while org routing stays gated


def test_agentic_tree_valid():
    import copy
    from agentic.loader import _validate
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["agentic_tree"] = "MitosAgent"
    _validate(rig)  # must not raise

def test_agentic_tree_rejects_path_separators():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["agentic_tree"] = "sub/dir"
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for path-like agentic_tree")
    except RegistryError as e:
        assert "must be a single directory name" in str(e)

def test_agentic_tree_rejects_empty():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["agentic_tree"] = "   "
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for empty agentic_tree")
    except RegistryError as e:
        assert "must be a non-empty string" in str(e)

def test_agentic_tree_collides_with_repo_checkout_dir():
    import copy
    from agentic.loader import _validate, RegistryError
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["repo"] = "git@github.com:example/MitosAgent.git"
    rig.projects["example-project"]["agentic_tree"] = "MitosAgent"
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for agentic_tree/repo checkout collision")
    except RegistryError as e:
        assert "collides with the checkout dir of repo" in str(e)

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
    # init now seeds only session-protocol + who-i-am + README (domain skills ship in core)
    assert "local/identity/session-protocol.md" in written
    assert "local/context/collaboration.md" not in written
    assert "local/context/org-roles.md" not in written
    # the captured name + form of address land in the overlay identity, which overrides the
    # neutral core who-i-am.md for every tool — skills stay neutral and read the name here
    who = (tmp / "registry/local/identity/who-i-am.md").read_text(encoding="utf-8")
    assert "Jane Doe" in who and 'Address me as "Ms. Doe"' in who
    reg2 = loader.load(tmp)
    org = reg2.partials["identity/session-protocol.md"]
    assert org.rel == "local/identity/session-protocol.md" and "Creative Director" in org.body
    outputs = planner.plan_machine(reg2, "rig")
    soul = next(o for o in outputs if o.deploy_path.endswith("SOUL.md"))
    assert "Creative Director" in soul.content              # overlay org reached SOUL.md
    # a template seed REPLACES the core session-protocol (last-layer-wins), so it must carry
    # the Session Protocol itself — a seed without it would mask the core protocol and
    # break session alignment (new-session, concrete project root, skills mechanics)
    assert "new-session" in soul.content
    assert "MitosAgent" in soul.content, "{{project_root}} must expand in a seeded SOUL"
    assert "{{project_root}}" not in soul.content
    assert "{{skills_root}}" not in soul.content
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

def test_scaffold_machine_use_cases_gate_orgs_and_agents_md():
    """scaffold_machine writes a registry/local/machines/<name>.yaml whose `targets:` list
    matches the chosen use case, and — since org skills target hermes only and the
    org-domain table/routing lines render exclusively on the agents-md/hermes tree — only
    the 'mitos-agent' use case's plan carries orgs or an agents-md tree. 'workstation' and
    'coding' must never deploy either, matching what a claude-code/antigravity-only user
    expects (the bug this wizard exists to prevent)."""
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
        agents_md_tree = [o for o in outputs if o.target == "agents-md"]
        if use_case == "mitos-agent":
            assert any("org-software" in p for p in skill_paths)
            assert agents_md_tree
        else:
            assert not any("org-" in p for p in skill_paths)
            assert not agents_md_tree

def test_scaffold_machine_never_clobbers_existing_profile():
    from agentic import init as initmod
    treg, tmp = _temp_registry()
    written = initmod.scaffold_machine(tmp, name="box", os_name="linux",
                                       use_case="workstation")
    assert written == "local/machines/box.yaml"
    original = (tmp / "registry/local/machines/box.yaml").read_text(encoding="utf-8")
    again = initmod.scaffold_machine(tmp, name="box", os_name="linux", use_case="mitos-agent")
    assert again is None
    assert (tmp / "registry/local/machines/box.yaml").read_text(encoding="utf-8") == original
    forced = initmod.scaffold_machine(tmp, name="box", os_name="linux",
                                      use_case="mitos-agent", overwrite=True)
    assert forced == "local/machines/box.yaml"
    assert "mitos-agent" in (tmp / "registry/local/machines/box.yaml").read_text(encoding="utf-8")

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
            assert "agents-md" not in reg2.machines["box"]["targets"]

def test_scaffold_machine_rejects_illegal_target_sets():
    from agentic import init as initmod
    bad = (
        {"targets": ["mitos-agent", "claude-code"]},   # machine-role exclusivity (loader._validate)
        {"targets": []},                          # nothing to deploy
        {"targets": ["no-such-tool"]},
        {},                                       # neither use_case nor targets
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
    # hermes pulls agents-md in with it — the tree is the point of that target
    assert initmod.resolve_targets(targets=["mitos-agent"]) == ["mitos-agent", "agents-md"]

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
                       if o.target == "agents-md"]
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
        "name: home-server\nos: linux\ntargets: [mitos-agent, agents-md]\n"
        'paths:\n  assistant_root: "~/MitosAgent"\n',
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

    written = initmod.scaffold_overlay(tmp, given_name="Jane", org_template="marketing-firm",
                                       backend="mock")
    # the user's files are untouched and were NOT re-written
    assert (overlay / "identity" / "who-i-am.md").read_text(encoding="utf-8") == \
        "MY CUSTOM IDENTITY\n"
    assert "local/identity/who-i-am.md" not in written
    assert (overlay / "skills" / "mine" / "SKILL.md").read_text(encoding="utf-8") == "mine\n"
    # but genuinely missing pieces are still seeded
    assert "local/identity/session-protocol.md" in written
    # domain org skills now ship in core — init no longer seeds skills/org/SKILL.md
    assert (overlay / "skills" / "org" / "SKILL.md").exists() is False
    # overwrite=True forces a clean re-scaffold when asked
    written2 = initmod.scaffold_overlay(tmp, given_name="Jane", org_template="marketing-firm",
                                        backend="mock", overwrite=True)
    assert "local/identity/who-i-am.md" in written2
    assert "Jane" in (overlay / "identity" / "who-i-am.md").read_text(encoding="utf-8")

def test_init_org_template_optional():
    # scaffold_overlay with org_template=None (the default) skips seeding session-protocol.md —
    # the core session protocol is used as-is; who-i-am.md and README are still seeded
    from agentic import init as initmod
    _treg, tmp = _temp_registry()
    written = initmod.scaffold_overlay(tmp, given_name="Sam", email="sam@example.com")
    assert "local/identity/who-i-am.md" in written
    assert "local/README.md" in written
    assert "local/identity/session-protocol.md" not in written

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


# ── V3.3: org_domain-driven domain discovery (loader.known_org_domains) ─────────
def test_known_org_domains_discovers_new_domain_from_skill_frontmatter():
    import copy

    from agentic.loader import Skill, _validate, known_org_domains
    rig = copy.deepcopy(reg)
    rig.skills["org-finance"] = Skill(
        name="org-finance", rel="local/skills/org-finance/SKILL.md",
        frontmatter={"name": "org-finance", "targets": ["mitos-agent"], "org_domain": "finance"},
        body="# Instructions\n")
    assert known_org_domains(rig) == {"software", "design", "marketing", "finance"}

    # an effort tagged with the + ORG-scaffolded domain is immediately valid
    from dataclasses import replace as _replace
    pg = rig.graphs["example-project"]
    pg.efforts = [_replace(e, org_domain="finance") for e in pg.efforts]
    _validate(rig)  # must not raise

def test_effort_org_domain_not_declared_by_any_skill_is_rejected():
    import copy
    from dataclasses import replace as _replace

    from agentic.loader import RegistryError, _validate
    rig = copy.deepcopy(reg)
    pg = rig.graphs["example-project"]
    assert pg.efforts, "example graph must carry a tagged effort for this test"
    pg.efforts = [_replace(e, org_domain="not-a-real-domain") for e in pg.efforts]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for unknown effort org domain")
    except RegistryError as e:
        assert "not-a-real-domain" in str(e)

def test_effort_unknown_deliverable_is_rejected():
    """A deliverable outside graph.KNOWN_DELIVERABLES fails _validate loudly, naming the value and
    the valid set — the same loudness as the org-domain check directly above it."""
    import copy
    from dataclasses import replace as _replace

    from agentic.loader import RegistryError, _validate
    from agentic import graph
    rig = copy.deepcopy(reg)
    pg = rig.graphs["example-project"]
    assert pg.efforts, "example graph must carry an effort for this test"
    pg.efforts = [_replace(pg.efforts[0], deliverables=("documentation", "not-a-deliverable"))] \
        + list(pg.efforts[1:])
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for unknown deliverable")
    except RegistryError as e:
        assert "not-a-deliverable" in str(e)
        assert "documentation" in str(e)      # the valid set is named


def test_effort_valid_deliverables_pass_validation():
    import copy
    from dataclasses import replace as _replace

    from agentic.loader import _validate
    rig = copy.deepcopy(reg)
    pg = rig.graphs["example-project"]
    pg.efforts = [_replace(pg.efforts[0], deliverables=("documentation", "tests"))] \
        + list(pg.efforts[1:])
    _validate(rig)  # must not raise


def test_manifest_org_field_is_rejected():
    """org: on a project manifest is a category error now — org domains live on graph
    efforts, so a leftover field fails validation with a pointer to the new home."""
    import copy

    from agentic.loader import RegistryError, _validate
    rig = copy.deepcopy(reg)
    rig.projects["example-project"]["org"] = "software"
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for manifest org: field")
    except RegistryError as e:
        assert "no longer a manifest field" in str(e)


# ── skill extensions (extends_skill/extends_role) — R1/R2 ──────────────────────
def test_validate_skill_extension_no_pair_is_fine():
    from agentic.loader import validate_skill_extension
    assert validate_skill_extension(reg, "x", {}) is None
    assert validate_skill_extension(reg, "x", {"description": "d"}) is None

def test_validate_skill_extension_requires_both_fields_together():
    from agentic.loader import validate_skill_extension
    err = validate_skill_extension(reg, "x", {"extends_skill": "org-software"})
    assert err and "must be specified together" in err
    err = validate_skill_extension(reg, "x", {"extends_role": "CTO"})
    assert err and "must be specified together" in err

def test_validate_skill_extension_rejects_self_extension():
    from agentic.loader import validate_skill_extension
    err = validate_skill_extension(
        reg, "org-software", {"extends_skill": "org-software", "extends_role": "CTO"})
    assert err and "cannot extend itself" in err

def test_validate_skill_extension_rejects_unknown_parent():
    from agentic.loader import validate_skill_extension
    err = validate_skill_extension(
        reg, "x", {"extends_skill": "no-such-skill", "extends_role": "CTO"})
    assert err and "is not a known skill" in err

def test_validate_skill_extension_rejects_missing_anchor():
    import copy
    from agentic.loader import Skill, validate_skill_extension
    rig = copy.deepcopy(reg)
    rig.skills["no-anchor"] = Skill(name="no-anchor", rel="skills/no-anchor/SKILL.md",
                                    frontmatter={"targets": ["mitos-agent"]}, body="# Instructions\n")
    err = validate_skill_extension(
        rig, "x", {"extends_skill": "no-anchor", "extends_role": "CTO"})
    assert err and "has no" in err and "section to extend" in err

def test_validate_skill_extension_rejects_chained_extension():
    import copy
    from agentic.loader import Skill, validate_skill_extension
    rig = copy.deepcopy(reg)
    rig.skills["ext-a"] = Skill(
        name="ext-a", rel="local/skills/ext-a/SKILL.md",
        frontmatter={"targets": ["mitos-agent"], "extends_skill": "org-software",
                    "extends_role": "CTO"},
        body="body")
    err = validate_skill_extension(
        rig, "ext-b", {"extends_skill": "ext-a", "extends_role": "CTO"})
    assert err and "chained extensions are not supported" in err

def test_validate_skill_extension_accepts_valid_pair():
    from agentic.loader import validate_skill_extension
    assert validate_skill_extension(
        reg, "org-data-science", {"extends_skill": "org-software",
                                  "extends_role": "CTO"}) is None

def test_registry_load_rejects_bad_extension_pair():
    import copy
    from agentic.loader import RegistryError, Skill, _validate
    rig = copy.deepcopy(reg)
    rig.skills["ext-bad"] = Skill(
        name="ext-bad", rel="local/skills/ext-bad/SKILL.md",
        frontmatter={"targets": ["mitos-agent"], "extends_skill": "no-such-skill",
                    "extends_role": "CTO"},
        body="body")
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "is not a known skill" in str(e)

def test_project_cannot_bind_extension_skill_to_claude_code():
    import copy
    from agentic.loader import RegistryError, Skill, _validate
    rig = copy.deepcopy(reg)
    rig.skills["ext-cc"] = Skill(
        name="ext-cc", rel="local/skills/ext-cc/SKILL.md",
        frontmatter={"targets": ["claude-code"], "extends_skill": "org-software",
                    "extends_role": "CTO"},
        body="body")
    rig.projects["example-project"]["skills"] = ["ext-cc"]
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "extends_skill" in str(e) and "bind its parent skill instead" in str(e)


# ── skill scope: global (default) | project ─────────────────────────────────────
def test_skill_scope_defaults_global():
    from agentic.loader import Skill
    s = Skill(name="x", rel="skills/x/SKILL.md", frontmatter={"targets": ["mitos-agent"]}, body="")
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

def test_validate_skill_scope_project_scope_ignores_hermes_and_claude_app_pairing():
    """A skill may target hermes/claude-app alongside a project-scope-capable target —
    neither has a project-scoped surface, so both just ignore `scope` (always ship
    globally) rather than being flagged incompatible."""
    from agentic.loader import validate_skill_scope
    assert validate_skill_scope(
        "x", {"targets": ["mitos-agent", "antigravity"], "scope": "project"}) is None
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
    rig.skills["hermes-only"] = Skill(
        name="hermes-only", rel="local/skills/hermes-only/SKILL.md",
        frontmatter={"targets": ["mitos-agent"]}, body="body")
    rig.projects["example-project"]["skills"] = ["hermes-only"]
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
    examples/scripts (Claude Code, Antigravity), references/templates (Hermes),
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
    paths = {o.deploy_path: o for o in outs if o.target == "agents-md"}
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

def test_known_org_domains_fallback_when_no_skill_declares_org_domain():
    """If no skill in the registry carries org_domain (a repo mid-migration, before any
    org-*/SKILL.md declares it), known_org_domains falls back to the legacy hardcoded
    set — so existing 'software'/'design'/'marketing' projects don't suddenly break."""
    import copy

    from agentic.loader import known_org_domains
    rig = copy.deepcopy(reg)
    for s in rig.skills.values():
        s.frontmatter.pop("org_domain", None)
    assert known_org_domains(rig) == {"software", "design", "marketing"}


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


def test_effort_unknown_coverage_is_rejected():
    """A coverage dimension outside graph.KNOWN_COVERAGE fails _validate loudly, naming the value
    and the valid set — the same loudness as the deliverable check directly above it."""
    import copy
    from dataclasses import replace as _replace

    from agentic.loader import RegistryError, _validate
    rig = copy.deepcopy(reg)
    pg = rig.graphs["example-project"]
    assert pg.efforts, "example graph must carry an effort for this test"
    pg.efforts = [_replace(pg.efforts[0],
                           requirements_coverage=("security", "not-a-dimension"))] \
        + list(pg.efforts[1:])
    try:
        _validate(rig)
        raise AssertionError("expected RegistryError for unknown coverage dimension")
    except RegistryError as e:
        assert "not-a-dimension" in str(e)
        assert "performance" in str(e)        # the valid set is named


def test_effort_valid_coverage_passes_validation():
    import copy
    from dataclasses import replace as _replace

    from agentic.loader import _validate
    from agentic import graph
    rig = copy.deepcopy(reg)
    pg = rig.graphs["example-project"]
    pg.efforts = [_replace(pg.efforts[0],
                           requirements_coverage=graph.KNOWN_COVERAGE[:2])] \
        + list(pg.efforts[1:])
    _validate(rig)          # must not raise
