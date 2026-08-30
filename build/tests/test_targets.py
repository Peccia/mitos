"""Claude-code, Antigravity, Hermes, skill, prompt, and git-sync tests."""
from __future__ import annotations

import sys
from pathlib import Path

from conftest import (
    REPO_ROOT, reg, loader, planner, render, classify_output,
    _inbox, _temp_registry, _doc, _write_graph,
    _plant_candidate, _skill_meta, _full_windows_rig, _connected_rig, _sandbox_deploy,
    _git_available, _run_git, _make_overlay_hub, _clone_overlay, _seed_overlay,
)

def _lint(path, content):
    from agentic.planner import Output, lint_node_markdown
    return lint_node_markdown(Output(
        target="agents-md", kind="text", deploy_path=path, dist_rel="x",
        content=content, drift_policy="protect"))


def test_lint_node_markdown_accepts_conformant_node():
    body = ("# Sample Analytics\n\nA project.\n\n"
            "## Navigation\n- repos\n\n## Tools\n- gws\n\n## Skills\n- a skill\n\n"
            "## Google Workspace suite (`gws`)\n\n- paths\n\n### Launch\n- Doc\n")
    assert _lint("x/Projects/SampleAnalytics/AGENTS.md", body) == []


def test_lint_node_markdown_flags_double_h1():
    # the original regression: a generated block that opened a second H1
    body = "# Project\n\nprose.\n\n# Google Workspace suite (`gws`)\n\n- Doc\n"
    problems = _lint("x/Projects/P/AGENTS.md", body)
    assert any("exactly one H1" in p for p in problems)


def test_lint_node_markdown_flags_level_skip_and_reserved_misuse():
    skip = "# P\n\n### Deep\n"                        # H1 → H3, no H2
    assert any("skips" in p for p in _lint("x/AGENTS.md", skip))
    mislevel = "# P\n\n### Tools\n"                   # reserved name at wrong level
    assert any("must be H2" in p for p in _lint("x/AGENTS.md", mislevel))


def test_lint_node_markdown_flags_reserved_out_of_order():
    body = "# P\n\n## Skills\n- s\n\n## Navigation\n- n\n"  # Skills before Navigation
    assert any("out of order" in p for p in _lint("x/AGENTS.md", body))


def test_lint_node_markdown_skips_non_node_files():
    # SOUL.md (all-H2 system prompt) and CLAUDE.md stubs are not node files → not linted
    assert _lint("x/MitosAgent/SOUL.md", "## About Me\n\n## How to work\n") == []
    assert _lint("x/Projects/P/CLAUDE.md", "@AGENTS.md\n") == []
    assert _lint("x/SKILL.md", "# Instructions\n\n## Description\n") == []


def test_lint_node_markdown_ignores_headings_in_code_fences():
    body = "# P\n\nprose.\n\n```\n# not a heading\n## also not\n```\n\n## Tools\n- t\n"
    assert _lint("x/AGENTS.md", body) == []


def test_antigravity_grants_normalized():
    grants = render.antigravity_permission_grants(reg.servers["servers"]["gws"], "gws-mcp-local")
    allow = grants["userSettings"]["globalPermissionGrants"]["allow"]
    assert "mcp(gws-mcp-local/search_drive_files)" in allow
    # normalization dropped the extended-tier tools Antigravity used to grant
    assert not any("draft_gmail_message" in a for a in allow)
    assert len(allow) == 31

def test_mitos_agent_mcp_config_shape():
    # Whole-file mcp.json (not a merge block): one mcpServers entry per wired store, keyed
    # by server name, carrying url/transport/flat-tools. Keep the flat-tool-count assertion.
    tools = render.flat_tools(reg.servers["servers"]["gws"])
    assert len(tools) == 31
    assert tools[0] == "list_calendars"
    gws = dict(reg.servers["servers"]["gws"])
    cfg = render.mitos_agent_mcp_config({"gws": gws})
    assert set(cfg["mcpServers"]) == {"gws"}
    assert cfg["mcpServers"]["gws"]["tools"] == tools
    assert cfg["mcpServers"]["gws"]["url"] == gws["url"]
    # multi-store: one entry per store (the §5.4 resolve regression)
    cfg2 = render.mitos_agent_mcp_config({"gws": gws, "notion": {"url": "http://x", "tools": {}}})
    assert set(cfg2["mcpServers"]) == {"gws", "notion"}

def test_non_assistant_machine_coproduces_agents_md():
    """Claude-code machines without agents-md emit a co-located AGENTS.md (full graph
    context + prose) and a stub CLAUDE.md at each graph project's local_path.
    Hermes machines (with agents-md) are unaffected — the existing path applies."""
    import copy
    rig = copy.deepcopy(reg)
    if "apoc" not in rig.projects:
        rig.projects["apoc"] = {"name": "Apocalyptic Adventure", "slug": "apoc", "local_path": {}, "context": {}}
    from agentic.graph import ProjectGraph
    rig.graphs["apoc"] = ProjectGraph(slug="apoc", name="Apocalyptic Adventure", description="test description", documents=[], efforts=[], path=None)
    # configure example-windows as a pure workstation: remove agents-md and the
    # agentic_context_root (that's the separate Hermes tree, not needed here)
    rig.machines["example-windows"]["targets"] = ["claude-code"]
    rig.machines["example-windows"]["paths"].pop("agentic_context_root", None)
    # give apoc a local_path on example-windows so _local() resolves it
    rig.projects["apoc"]["local_path"]["example-windows"] = "apocalyptic_adventure"

    outs = planner.plan_machine(rig, "example-windows")
    by_path = {o.deploy_path: o for o in outs}

    agents_path = "C:/Projects/apocalyptic_adventure/AGENTS.md"
    claude_path = "C:/Projects/apocalyptic_adventure/CLAUDE.md"
    assert agents_path in by_path, "co-located AGENTS.md must be planned at local_path"
    assert claude_path in by_path, "stub CLAUDE.md must be planned at local_path"

    agents_out = by_path[agents_path]
    claude_out = by_path[claude_path]

    # AGENTS.md: full inline graph context (IDs visible) from claude-code target
    assert agents_out.target == "claude-code"
    assert "**ID:**" in agents_out.content or "_No documents mapped yet._" in agents_out.content
    # CLAUDE.md: thin stub, no section_bodies
    assert claude_out.content.strip() == "@AGENTS.md"
    assert not claude_out.section_bodies

    # Hermes machine: co-located AGENTS.md must NOT be emitted via claude-code target
    rig_hermes = copy.deepcopy(reg)
    if "apoc" not in rig_hermes.projects:
        rig_hermes.projects["apoc"] = {"name": "Apocalyptic Adventure", "slug": "apoc", "local_path": {}, "context": {}}
    from agentic.graph import ProjectGraph
    rig_hermes.graphs["apoc"] = ProjectGraph(slug="apoc", name="Apocalyptic Adventure", description="test description", documents=[], efforts=[], path=None)
    rig_hermes.machines["example-windows"]["targets"] = ["claude-code", "agents-md"]
    rig_hermes.projects["apoc"]["local_path"]["example-windows"] = "apocalyptic_adventure"
    hermes_paths = [o.deploy_path for o in planner.plan_machine(rig_hermes, "example-windows")
                    if o.target == "claude-code"]
    assert not any("apocalyptic_adventure/AGENTS.md" in p for p in hermes_paths), \
        "Hermes machine must not emit co-located AGENTS.md via claude-code target"

def test_stub_claude_md_inlines_builder_when_agents_md_absent():
    """A stub_import project (mitos) on a claude-code-only machine must never emit a
    dangling CLAUDE.md → @AGENTS.md when no AGENTS.md is generated. The planner inlines
    the project's builder context into a self-contained CLAUDE.md instead, so AGENTS and
    CLAUDE never split. With agents-md present the stub is valid and stays a stub."""
    import copy

    # claude-code-only machine: agents-md (which generates AGENTS.md) is NOT a target.
    rig = copy.deepcopy(reg)
    rig.machines["example-windows"]["targets"] = ["claude-code"]
    rig.machines["example-windows"]["paths"].pop("agentic_context_root", None)
    # give mitos a local_path on example-windows so _local() resolves it (the live overlay
    # binds mitos only to the user's real machines, so the test pins its own)
    rig.projects["mitos"]["local_path"]["example-windows"] = "Mitos"
    claude_path = "C:/Projects/Mitos/CLAUDE.md"

    by_path = {o.deploy_path: o for o in planner.plan_machine(rig, "example-windows")}
    assert claude_path in by_path, "mitos CLAUDE.md must be planned on a claude-code-only machine"
    out = by_path[claude_path]
    assert out.content.strip() != "@AGENTS.md", \
        "must not dangle a stub @AGENTS.md when no AGENTS.md is generated"
    assert "agentic SDLC loop" in out.content, "self-contained CLAUDE.md inlines the builder prose"
    assert out.section_bodies, "an inlined multi-source CLAUDE.md records its per-section base"

    # Counterpart — with agents-md present, the AGENTS.md co-deploys, so the stub is valid.
    rig2 = copy.deepcopy(reg)
    rig2.machines["example-windows"]["targets"] = ["claude-code", "agents-md"]
    rig2.projects["mitos"]["local_path"]["example-windows"] = "Mitos"
    by_path2 = {o.deploy_path: o for o in planner.plan_machine(rig2, "example-windows")}
    assert by_path2[claude_path].content.strip() == "@AGENTS.md", \
        "with agents-md present, mitos CLAUDE.md stays a thin stub"
    assert "C:/Projects/Mitos/AGENTS.md" in by_path2, \
        "agents-md must co-deploy the AGENTS.md that the stub imports"


def test_project_node_does_not_repeat_repo_builder_context():
    """The mitos project node and this repo's own AGENTS.md are two documents with two
    jobs, and must not carry the same prose.

    They were one partial until the node — deployed to the project FOLDER that holds the
    checkout — repeated all 57KB of builder prose the repo artifact already carries, so a
    session started inside the repo loaded both. The node answers "which checkout, and what
    is this project for"; selfdoc.SOURCE answers "how do I change code in here". Pinning
    the negative: the node must never regrow the deep sections."""
    from agentic import selfdoc
    node_key = "context/projects/mitos.md"
    repo_key = selfdoc.SOURCE.relative_to(selfdoc.REPO_ROOT / "registry").as_posix()
    assert node_key in reg.partials and repo_key in reg.partials
    assert node_key != repo_key, "the node and the repo artifact must not share a partial"

    node_body = reg.partials[node_key].body
    repo_body = reg.partials[repo_key].body
    # The deep builder sections belong to the repo artifact alone.
    for section in ("## Invariants", "## To change X, edit Y", "## Verifying changes"):
        assert section in repo_body, f"{repo_key} lost its {section!r} section"
        assert section not in node_body, (
            f"{node_key} regrew {section!r} — the project node must not repeat the repo's "
            f"builder context; both load when a session starts inside the checkout")
    assert len(node_body) < len(repo_body) / 4, (
        "the project node has grown toward repo-artifact size again — it is orientation "
        "plus the generated document map, not a builder manual")


def test_builder_context_project_agents_md_includes_graph_docs():
    """A `context.builder` project (e.g. Mitos self-hosting) with a knowledge graph must
    get the same lightweight titles-index + companion AGENTS_DETAILS.md that every other
    project in the Hermes tree gets (the context.assistant / ctx_key branch) — the
    connection/document-store heading and document titles in AGENTS.md, full per-document
    detail (raw IDs) in AGENTS_DETAILS.md — not just persona/prose."""
    import copy
    from agentic import graph as graphmod
    rig = copy.deepcopy(reg)
    rig.machines["example-windows"]["targets"] = ["claude-code", "agents-md"]
    rig.projects["mitos"]["local_path"]["example-windows"] = "Mitos"
    rig.projects["mitos"]["document_store"] = "gws"
    rig.graphs["mitos"] = graphmod.ProjectGraph(
        slug="mitos", name="Mitos", description="test description",
        documents=[_doc("MITOS_DOC_1", "Design Review", "a design review", "2026-06-27")],
        efforts=[], path=None)

    outs = planner.plan_machine(rig, "example-windows")
    by_path = {o.deploy_path: o for o in outs}
    agents_path = "C:/Projects/Mitos/AGENTS.md"
    details_path = "C:/Projects/Mitos/AGENTS_DETAILS.md"
    assert agents_path in by_path
    assert details_path in by_path, "AGENTS_DETAILS.md must be emitted alongside, like other projects"
    out = by_path[agents_path]
    det = by_path[details_path]
    assert out.target == "agents-md" and det.target == "agents-md"
    assert det.drift_policy == "generated"

    # persona/builder prose survives, plus the connection heading + doc title (index only)
    assert "agentic SDLC loop" in out.content
    assert "Google Workspace suite" in out.content
    assert "Design Review" in out.content
    assert "`MITOS_DOC_1`" not in out.content, "raw ID belongs in details, not the index"

    # full detail (raw ID) lives in the companion file, under the same connection heading
    assert "Google Workspace suite" in det.content
    assert "`MITOS_DOC_1`" in det.content

    # section-aware drift tracking: prose sections stay separate from the generated tail
    assert out.section_bodies
    assert any(render.is_generated_source(s) for s, _ in out.section_bodies)

def test_multi_store_project_renders_one_connection_section_per_store():
    """A project bound to two stores (document_store: a list) gets one `## <Name>
    (`key`)` section per store in its generated AGENTS.md, each holding only that
    store's documents — the render primitive already produces one section per call;
    multi-store just calls it once per store (planner._project_doc_block)."""
    import copy
    from agentic import graph as graphmod
    rig = copy.deepcopy(reg)
    rig.machines["example-windows"]["targets"] = ["claude-code", "agents-md"]
    rig.projects["mitos"]["local_path"]["example-windows"] = "Mitos"
    rig.servers["servers"]["fake2"] = {"description": "Fake Store — a second test store."}
    rig.projects["mitos"]["document_store"] = ["gws", "fake2"]
    rig.graphs["mitos"] = graphmod.ProjectGraph(
        slug="mitos", name="Mitos", description="test description",
        documents=[
            graphmod.Document("GWS_DOC", "Gws Design", "a gws doc", "2026-06-27", store="gws"),
            graphmod.Document("FAKE_DOC", "Fake Plan", "a fake2 doc", "2026-06-27",
                              store="fake2"),
        ], efforts=[], path=None)

    outs = planner.plan_machine(rig, "example-windows")
    by_path = {o.deploy_path: o for o in outs}
    out = by_path["C:/Projects/Mitos/AGENTS.md"]
    det = by_path["C:/Projects/Mitos/AGENTS_DETAILS.md"]

    # AGENTS.md nests under the project's prose H1, so BOTH store sections render as H2.
    assert out.content.count("## Google Workspace suite") == 1
    assert out.content.count("## Fake Store") == 1
    # AGENTS_DETAILS.md is standalone: the FIRST store's heading is the file's own H1
    # identity (invariant #12 — exactly one H1), the second nests as a sibling H2.
    assert det.content.count("# Google Workspace suite") == 1
    assert "## Google Workspace suite" not in det.content
    assert det.content.count("## Fake Store") == 1
    for content in (out.content, det.content):
        assert "Gws Design" in content
        assert "Fake Plan" in content
    # each doc's raw ID lives only in the details file, under its OWN store's section —
    # not leaked into the other store's section
    gws_section, fake_section = det.content.split("## Fake Store", 1)
    assert "`GWS_DOC`" in gws_section and "`FAKE_DOC`" not in gws_section
    assert "`FAKE_DOC`" in fake_section and "`GWS_DOC`" not in fake_section

def test_multi_store_machine_connections_block_emits_one_section_per_store():
    """A machine bound to two stores gets one connection section per store on the
    operating root (render.connections_block), same as a project."""
    import copy
    rig = copy.deepcopy(reg)
    rig.servers["servers"]["fake2"] = {"description": "Fake Store — a second test store."}
    block = render.connections_block(
        rig.servers["servers"],
        {"document_store": ["gws", "fake2"]},
        {})
    assert block.count("## Google Workspace suite") == 1
    assert block.count("## Fake Store") == 1

def test_project_agents_md_drops_identity_on_assistant_machines():
    """On a machine that also deploys hermes, SOUL.md already carries the identity
    partials on every request — the project-root AGENTS.md (project_agents) must not
    repeat them. An agents-md machine WITHOUT hermes has no SOUL.md, so it keeps the
    full persona header (the persona has to live somewhere)."""
    import copy

    def _rig(targets):
        rig = copy.deepcopy(reg)
        rig.machines["example-windows"]["targets"] = targets
        # the mitos-agent install root — a distinct dir from this machine's existing
        # agentic_context_root (C:/MitosAgent) so the operating tree and the reference
        # graph mount don't collide; irrelevant to the identity-drop assertion itself
        rig.machines["example-windows"]["paths"]["assistant_root"] = "C:/AssistantHome"
        rig.projects["mitos"]["local_path"]["example-windows"] = "Mitos"
        return rig

    agents_path = "C:/Projects/Mitos/AGENTS.md"

    # hermes co-deployed → identity dropped, builder prose kept
    outs = planner.plan_machine(_rig(["claude-code", "agents-md", "mitos-agent"]),
                                "example-windows")
    out = next(o for o in outs if o.deploy_path == agents_path and o.target == "agents-md")
    assert "About Me" not in out.content, "identity must not duplicate SOUL.md"
    assert not any(s.startswith("identity/") for s in out.sources)
    assert "agentic SDLC loop" in out.content

    # no hermes → full persona header stays
    outs2 = planner.plan_machine(_rig(["claude-code", "agents-md"]), "example-windows")
    out2 = next(o for o in outs2 if o.deploy_path == agents_path and o.target == "agents-md")
    assert "About Me" in out2.content
    assert any(s.startswith("identity/") for s in out2.sources)

def test_agentic_tree_project_mount_emits_full_tree():
    """A workstation project with agentic_tree: gets the full operating tree (the same
    Navigation/Workflows/Skills/roster shape a Hermes machine gets at its assistant_root)
    at <local_path>/<subdir>/ — protect policy, edits reconcile back to the registry."""
    import copy
    rig = copy.deepcopy(reg)
    rig.machines["example-windows"]["targets"] = ["claude-code", "agents-md"]
    rig.machines["example-windows"]["paths"].pop("assistant_root", None)
    proj = rig.projects["example-project"]
    proj.pop("example", None)  # don't let the shipped-sample guard suppress it
    proj["agentic_tree"] = "MitosAgent"
    proj["local_path"]["example-windows"] = "example-project"

    outs = planner.plan_machine(rig, "example-windows")
    mount_root = "C:/Projects/example-project/MitosAgent"
    by_path = {o.deploy_path: o for o in outs}

    root_agents = by_path.get(f"{mount_root}/AGENTS.md")
    assert root_agents is not None, "project mount must emit its own root AGENTS.md"
    assert root_agents.target == "agents-md"
    assert root_agents.drift_policy == "protect"

    projects_agents = by_path.get(f"{mount_root}/Projects/AGENTS.md")
    assert projects_agents is not None
    assert "example-project" in projects_agents.content, "roster must list the mounting project"

    per_project = by_path.get(f"{mount_root}/Projects/Example Project/AGENTS.md")
    assert per_project is not None, "the ctx_key dynamic entry must also render at the mount root"

def test_agentic_tree_cross_reference_note_on_claude_code_graph_lane():
    """A workstation project with BOTH a knowledge graph and agentic_tree: gets a
    generated cross-reference note in its normal doc-index AGENTS.md pointing at the
    separate operating-tree mount — two AGENTS.md-shaped files legitimately coexist, so
    the split is named rather than left for a reader to guess at."""
    import copy
    from agentic import graph as graphmod
    rig = copy.deepcopy(reg)
    rig.machines["example-windows"]["targets"] = ["claude-code"]
    proj = rig.projects["example-project"]
    proj.pop("example", None)
    proj["agentic_tree"] = "MitosAgent"
    proj["local_path"]["example-windows"] = "example-project"
    rig.graphs["example-project"] = graphmod.ProjectGraph(
        slug="example-project", name="Example Project", description="",
        documents=[_doc("EX_DOC_1", "Notes", "notes", "2026-06-27")],
        efforts=[], path=None)

    outs = planner.plan_machine(rig, "example-windows")
    by_path = {o.deploy_path: o for o in outs}
    out = by_path.get("C:/Projects/example-project/AGENTS.md")
    assert out is not None
    assert "Operating Tree" in out.content
    assert "MitosAgent/AGENTS.md" in out.content

def test_agentic_tree_cross_reference_note_on_project_agents_lane():
    """The Hermes-style project_agents lane (context.builder projects) gets the same
    cross-reference note when agentic_tree: is set — consistent with the claude-code
    graph lane above."""
    import copy
    from agentic import graph as graphmod
    rig = copy.deepcopy(reg)
    rig.machines["example-windows"]["targets"] = ["claude-code", "agents-md"]
    rig.projects["mitos"]["local_path"]["example-windows"] = "Mitos"
    rig.projects["mitos"]["document_store"] = "gws"
    rig.projects["mitos"]["agentic_tree"] = "MitosAgent"
    rig.graphs["mitos"] = graphmod.ProjectGraph(
        slug="mitos", name="Mitos", description="test description",
        documents=[_doc("MITOS_DOC_1", "Design Review", "a design review", "2026-06-27")],
        efforts=[], path=None)

    outs = planner.plan_machine(rig, "example-windows")
    by_path = {o.deploy_path: o for o in outs}
    out = by_path["C:/Projects/Mitos/AGENTS.md"]
    assert "Operating Tree" in out.content
    assert "MitosAgent/AGENTS.md" in out.content

def test_agentic_tree_no_effect_on_agentic_machine():
    """agentic_tree is a workstation-only concept — an agentic (hermes) machine already
    hosts the tree at its assistant_root, so a project's agentic_tree must not produce a
    second, redundant mount there."""
    import copy
    rig = copy.deepcopy(reg)
    rig.machines["example-windows"]["targets"] = ["mitos-agent", "agents-md"]
    rig.machines["example-windows"]["paths"]["assistant_root"] = "C:/MitosAgent"
    proj = rig.projects["example-project"]
    proj.pop("example", None)
    proj["agentic_tree"] = "MitosAgent"
    proj["local_path"]["example-windows"] = "example-project"

    outs = planner.plan_machine(rig, "example-windows")
    mount_root = "C:/Projects/example-project/MitosAgent"
    paths = {o.deploy_path for o in outs}
    assert f"{mount_root}/AGENTS.md" not in paths, \
        "agentic_tree must be a no-op on an agentic machine"

def test_workstation_produces_no_clones_and_context_root_produces_clones():
    """Workstations (claude-code without agents-md) never auto-clone or pull checkouts.
    agentic_context_root machines produce clones in the reference tree."""
    import copy
    rig = copy.deepcopy(reg)
    if "apoc" not in rig.projects:
        rig.projects["apoc"] = {"name": "Apocalyptic Adventure", "slug": "apoc", "local_path": {}, "context": {}}
    rig.machines["example-windows"]["targets"] = ["claude-code"]
    rig.machines["example-windows"]["paths"].pop("agentic_context_root", None)
    rig.projects["apoc"]["local_path"]["example-windows"] = "apocalyptic_adventure"
    rig.projects["apoc"]["repo"] = "git@github.com:Peccia/apoc.git"

    clones = planner.plan_clones(rig, "example-windows")
    assert clones == [], "workstations must never auto-clone into local_path"

    # agentic_context_root lane fires when agentic_context_root + agents-md are present
    rig2 = copy.deepcopy(reg)
    if "apoc" not in rig2.projects:
        rig2.projects["apoc"] = {"name": "Apocalyptic Adventure", "slug": "apoc", "local_path": {}, "context": {}}
    rig2.machines["example-windows"]["targets"] = ["claude-code", "agents-md"]
    rig2.machines["example-windows"]["paths"]["agentic_context_root"] = "C:/MitosAgent"
    rig2.projects["apoc"]["local_path"]["example-windows"] = "apocalyptic_adventure"
    rig2.projects["apoc"]["repo"] = "git@github.com:Peccia/apoc.git"
    clones2 = planner.plan_clones(rig2, "example-windows")
    dests = {c.dest for c in clones2 if c.slug == "apoc"}
    assert any("MitosAgent" in d for d in dests), "agentic_context_root lane must fire"
    assert not any("apocalyptic_adventure" in d for d in dests), "local_path lane must not fire"

def test_claude_app_target_stages_uploadable_zip():
    import copy
    import json as _json
    import tempfile
    import zipfile

    from agentic.commands import classify_output, cmd_deploy
    from agentic.io import safe_rel
    # This test is about the ZIP FORMAT, not about how many skills opt into claude-app —
    # selecting gws by name rather than asserting a count keeps it from breaking (and being
    # rubber-stamped into a new number) every time a skill is added.
    # example-windows sets claude_skills_staging but NOT claude_desktop_config, so every
    # claude-app output here is a skill zip (the Desktop-MCP half is opt-in by path key).
    reg2 = copy.deepcopy(reg)
    outs = [o for o in planner.plan_machine(reg2, "example-windows")
            if o.target == "claude-app"]
    assert all(o.kind == "zip" for o in outs), [o.kind for o in outs]
    o = next(o for o in outs if o.deploy_path.endswith("gws.zip"))
    assert (o.kind, o.lane, o.drift_policy) == ("zip", "content", "protect")
    assert o.deploy_path.endswith("ClaudeSkills/gws.zip")

    root = Path(tempfile.mkdtemp(prefix="ae-claudeai-"))
    assert cmd_deploy(reg2, "example-windows", dry_run=False, force=False, root=root) == 0
    dest = root / safe_rel(o.deploy_path)
    with zipfile.ZipFile(dest) as zf:                # official format: folder/SKILL.md
        assert zf.namelist() == ["gws/SKILL.md"]
        text = zf.read("gws/SKILL.md").decode("utf-8")
        assert text.startswith("---\nname: gws\n")   # Agent Skills frontmatter
        assert "description:" in text.split("---")[1]
    # idempotent: an unedited skill classifies unchanged on the next run
    lock = _json.loads((root / ".deploy-lock.json").read_text(encoding="utf-8"))
    st = classify_output(reg2, "example-windows", o, lock, root=root)
    assert st.state == "unchanged", st.state
    # a registry edit flips the staged zip to pending — the re-upload reminder
    o2 = type(o)(**{**o.__dict__, "content": o.content + "\nedited\n"})
    assert classify_output(reg2, "example-windows", o2, lock, root=root).state == "pending"

def test_skill_selection_layers():
    # Curation (pull layer) now lives on the machine profile, not the target spec —
    # a personal choice belongs on the (overlayable) machine, never on core targets/*.yaml.
    from agentic.planner import _selected_skills
    base = {"include_target": "mitos-agent"}
    # `gws` declares requires_server: gws, so every layer below is exercised on a machine
    # that actually has the connection wired (see test_requires_server_gates_skill).
    wired = {"document_store": "gws"}
    all_hermes = {s.name for s in _selected_skills(reg, base, wired)}
    assert "gws" in all_hermes and "idea-revision" not in all_hermes  # push layer
    only = _selected_skills(reg, base, {**wired, "skills": {"mitos-agent": {"include": ["new-session", "gws"]}}})
    assert {s.name for s in only} == {"new-session", "gws"}                  # pull: include
    rest = _selected_skills(reg, base, {**wired, "skills": {"mitos-agent": {"exclude": ["gws"]}}})
    assert {s.name for s in rest} == all_hermes - {"gws"}             # pull: exclude
    # include cannot smuggle a skill the frontmatter doesn't target
    assert not _selected_skills(
        reg, {"include_target": "claude-code"},
        {**wired, "skills": {"claude-code": {"include": ["graph-bootstrap"]}}})

def test_requires_server_gates_skill():
    """A skill declaring `requires_server:` reaches only a machine that declares that
    server in its `document_store:`. The regression this guards: a brand-new
    coding-harness box (no workspace wired) used to receive the `gws` SKILL.md — a page
    of instructions for MCP tools it cannot call — as the ONLY thing deploy gave it."""
    from agentic.planner import _selected_skills
    for tgt in ("mitos-agent", "claude-code", "claude-app", "antigravity"):
        spec = {"include_target": tgt}
        if tgt not in reg.skills["gws"].targets:
            continue
        assert "gws" not in {s.name for s in _selected_skills(reg, spec, {})}
        assert "gws" not in {s.name for s in _selected_skills(reg, spec, {"document_store": "none"})}
        assert "gws" in {s.name for s in _selected_skills(reg, spec, {"document_store": "gws"})}
        # a multi-store machine counts as wired when gws is anywhere in the list
        assert "gws" in {s.name for s in
                         _selected_skills(reg, spec, {"document_store": ["gws"]})}
    # curation cannot smuggle it back in: the connection gate is not a preference
    assert "gws" not in {s.name for s in _selected_skills(
        reg, {"include_target": "mitos-agent"}, {"skills": {"mitos-agent": {"include": ["gws"]}}})}

def test_fresh_coding_machine_deploys_no_workspace_content():
    """End-to-end guard for the fresh-user path: a machine built from init's
    coding-harness use cases must not receive a workspace skill or MCP wiring for a
    connection it never declared, and its CLAUDE.md must not name a hermes-only skill."""
    import copy

    from agentic.init import MACHINE_USE_CASES
    for use_case in ("workstation", "coding"):
        rig = copy.deepcopy(reg)
        m = rig.machines["example-windows"]
        m["targets"] = list(MACHINE_USE_CASES[use_case])
        m.pop("document_store", None)
        outs = planner.plan_machine(rig, "example-windows")
        assert not [o for o in outs if "/gws/" in o.deploy_path or o.deploy_path.endswith("gws.zip")], \
            f"{use_case}: workspace skill deployed without a declared connection"
        assert not [o for o in outs if o.lane == "connections"], \
            f"{use_case}: MCP wiring planned without a declared connection"
        # the identity header must not carry the agentic tree's operating rules — they
        # name `new-session` (a hermes-only skill) and an AGENTS.md tree that a
        # coding-harness box does not have. A builder-context MENTION of the skill name
        # is fine; the imperative bullet is what must be gone.
        for o in outs:
            if o.deploy_path.endswith("CLAUDE.md"):
                assert "execution of the skill: `new-session`" not in o.content, \
                    f"{use_case}: CLAUDE.md instructs a skill only hermes deploys"
                assert "Always read `AGENTS.md` within" not in o.content, \
                    f"{use_case}: CLAUDE.md routes through an agentic tree that isn't here"

def test_coding_harness_context_carries_no_assistant_persona():
    """A project's CLAUDE.md on a coding-harness box must not cast the agent as the
    owner's *personal assistant*, must not inline the owner's email/location (that file is
    normally committed to the repo), and must not claim a document store the machine never
    declared. `identity/who-i-am.md` is [mitos-agent, agents-md]; `who-i-am-coding.md` is the
    [claude-code] counterpart, and audience picks exactly one."""
    import copy

    from agentic.init import MACHINE_USE_CASES
    user = reg.user or {}
    for use_case in ("workstation", "coding"):
        rig = copy.deepcopy(reg)
        m = rig.machines["example-windows"]
        m["targets"] = list(MACHINE_USE_CASES[use_case])
        m.pop("document_store", None)
        # a user's OWN project: no knowledge graph, repo context only — the branch that
        # inlines the identity partials rather than emitting a stub or an AGENTS.md
        rig.projects["myapp"] = {
            "name": "MyApp", "slug": "myapp", "stage": "build",
            "local_path": {"example-windows": "myapp"},
            "context": {"repo": "registry/context/projects/example-project-repo.md"},
        }
        claude_mds = [o for o in planner.plan_machine(rig, "example-windows")
                      if o.deploy_path.endswith("myapp/CLAUDE.md")]
        assert claude_mds, f"{use_case}: expected a CLAUDE.md for a repo-context project"
        for o in claude_mds:
            assert "personal assistant" not in o.content, \
                f"{use_case}: coding harness cast as the assistant persona"
            assert "document store" not in o.content, \
                f"{use_case}: claims a document store this machine never declared"
            for field in ("email", "location"):
                value = (user.get(field) or "").strip()
                if value:
                    assert value not in o.content, \
                        f"{use_case}: leaks the owner's {field} into a committed CLAUDE.md"
            # the coding counterpart IS present — this is a swap, not a deletion
            assert "coding agent" in o.content, f"{use_case}: no identity header at all"

def test_deployed_workspace_skill_names_no_assistant_machinery():
    """The `gws` skill is the one core skill a coding-harness box can receive. Its BODY
    must not reference machinery only the agentic harness has — `SOUL.md`, Hermes, or
    Hermes's `config.yaml` — since those name files that box does not have. (The gate in
    test_requires_server_gates_skill stops it deploying UNWIRED; this covers the wired
    case.)"""
    import copy

    rig = _connected_rig("example-windows")           # document_store: gws → skill deploys
    rig = copy.deepcopy(rig)
    outs = [o for o in planner.plan_machine(rig, "example-windows")
            if "gws" in o.deploy_path and o.target != "mitos-agent"]
    assert outs, "expected the gws skill on a wired coding-harness machine"
    for o in outs:
        body = "\n".join(o.zip_members.values()) if o.zip_members else o.content
        for term in ("SOUL", "Hermes", "config.yaml"):
            assert term not in body, \
                f"{o.deploy_path}: names hermes-only machinery '{term}'"

def test_target_side_skill_curation_rejected():
    """include:/exclude: under a targets/*.yaml skills: block is core, shared by every
    user, and not overlayable — curation belongs on the machine profile instead."""
    import copy

    from agentic.loader import RegistryError, _validate
    for bad_skills in ({"include": ["gws"]}, {"exclude": ["gws"]}):
        reg2 = copy.deepcopy(reg)
        reg2.targets["mitos-agent"]["skills"].update(bad_skills)
        try:
            _validate(reg2)
            raise AssertionError(f"expected RegistryError for {bad_skills}")
        except RegistryError as e:
            assert "not allowed in targets" in str(e)

def test_machine_side_skill_curation_validation():
    import copy

    from agentic.loader import RegistryError, _validate
    bad_cases = (
        {"mitos-agent": {"include": ["no-such-skill"]}},
        {"mitos-agent": {"include": ["gws"], "exclude": ["gws"]}},
        {"not-a-target": {"include": ["gws"]}},
    )
    for bad in bad_cases:
        reg2 = copy.deepcopy(reg)
        reg2.machines["example-linux"]["skills"] = bad
        try:
            _validate(reg2)
            raise AssertionError(f"expected RegistryError for {bad}")
        except RegistryError:
            pass
    # a valid machine-side curation block passes
    reg2 = copy.deepcopy(reg)
    reg2.machines["example-linux"]["skills"] = {"mitos-agent": {"include": ["gws"]}}
    _validate(reg2)

def test_machine_side_curation_of_a_manual_target_rejected():
    """A manual target stages a menu the operator picks from at upload time, so the planner
    ignores curation there. Rejected loudly rather than silently ignored — the same posture
    the target-side rejection takes, and for the same reason: a list that quietly does nothing
    is worse than one that fails."""
    import copy

    from agentic.loader import RegistryError, _validate
    reg2 = copy.deepcopy(reg)
    reg2.machines["example-windows"]["skills"] = {"claude-app": {"exclude": ["gws"]}}
    try:
        _validate(reg2)
        raise AssertionError("expected RegistryError for curation on a manual target")
    except RegistryError as e:
        assert "cannot be curated" in str(e) and "upload" in str(e)

def test_deselect_then_prune():
    from agentic.commands import cmd_deploy
    from agentic.io import safe_rel
    reg2 = _connected_rig("example-linux")   # gws needs its connection to deploy at all
    root = Path(__import__("tempfile").mkdtemp(prefix="ae-prune-"))
    assert cmd_deploy(reg2, "example-linux", dry_run=False, force=False, root=root) == 0
    gws_path = next(o.deploy_path for o in planner.plan_machine(reg2, "example-linux")
                    if "skills" in o.deploy_path and o.deploy_path.endswith("gws/SKILL.md"))
    dest = root / safe_rel(gws_path)
    assert dest.exists()

    # deselect via machine-side exclude: deploy reports an orphan but keeps the file
    reg2.machines["example-linux"]["skills"] = {"mitos-agent": {"exclude": ["gws"]}}
    assert cmd_deploy(reg2, "example-linux", dry_run=False, force=False, root=root) == 0
    assert dest.exists(), "without --prune the deployed copy must remain"
    import json as _json
    files = _json.loads((root / ".deploy-lock.json").read_text(encoding="utf-8")
                        )["machines"]["example-linux"]["files"]
    assert gws_path in files, "orphan lock entry must be kept for a later --prune"

    # drift the orphan, then prune: captured to inbox, deleted, lock entry dropped
    dest.write_text(dest.read_text(encoding="utf-8") + "\nlate tool edit\n",
                    encoding="utf-8", newline="\n")
    assert cmd_deploy(reg2, "example-linux", dry_run=False, force=False, root=root,
                      prune=True) == 0
    assert not dest.exists()
    captured = [d for d in (_inbox(root)).iterdir()
                if d.is_dir() and (d / "SKILL.md").exists()
                and "late tool edit" in (d / "SKILL.md").read_text(encoding="utf-8")]
    assert captured, "drifted orphan must be captured before deletion"
    files = _json.loads((root / ".deploy-lock.json").read_text(encoding="utf-8")
                        )["machines"]["example-linux"]["files"]
    assert gws_path not in files

def test_parse_fragment_rejects_wrong_project_and_bad_shape():
    from agentic import graph
    SC = '{"@vocab":"https://schema.org/"}'
    # a document belonging to a different project than the candidate's slug
    wrong = ('{"@context":%s,"@graph":[{"@id":"http://peccia.net/document/D1",'
             '"@type":"DigitalDocument","identifier":"D1","name":"x","description":"y",'
             '"dateModified":"2026-01-01",'
             '"isPartOf":{"@id":"http://peccia.net/project/OTHER"}}]}' % SC)
    try:
        graph.parse_fragment(wrong, "example-project")
        raise AssertionError("expected GraphError for cross-project fragment")
    except graph.GraphError:
        pass
    # a clean doc-only fragment for the right project parses to one Document
    good = ('{"@context":%s,"@graph":[{"@id":"http://peccia.net/document/D2",'
            '"@type":"DigitalDocument","identifier":"D2","name":"Spec","description":"d",'
            '"dateModified":"2026-02-02",'
            '"isPartOf":{"@id":"http://peccia.net/project/example-project"}}]}' % SC)
    name, desc, docs, efforts = graph.parse_fragment(good, "example-project")
    assert name is None and [d.drive_id for d in docs] == ["D2"]

def test_per_project_binding_deploys_skills():
    """Per-project skill binding: a manifest-bound scope:project skill deploys to that
    project's checkout; a skill not in the manifest does not. Uses an isolated rig so
    the test is independent of overlay local_path config."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["claude-code"]
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    r.skills["proj-skill"] = loader.Skill(
        name="proj-skill", rel="local/skills/proj-skill/SKILL.md",
        frontmatter={"targets": ["claude-code"], "scope": "project"}, body="proj body")
    # give example-project a local_path so _local() resolves it (core registry has this)
    r.projects["example-project"]["local_path"]["example-windows"] = "example-project"
    r.projects["example-project"]["skills"] = ["proj-skill"]
    outs = planner.plan_machine(r, "example-windows")
    paths = [o.deploy_path for o in outs]
    # bound skill deployed to this project
    assert any(p.endswith("example-project/.claude/skills/proj-skill/SKILL.md") for p in paths)
    # new-session skill not bound → not deployed
    assert not any(p.endswith("example-project/.claude/skills/new-session/SKILL.md") for p in paths)

def test_binding_validation_rejects_unknown_and_incompatible():
    import copy

    from agentic.loader import RegistryError, _validate
    for mutate in (
        lambda p: p.update(skills=["no-such-skill"]),
        lambda p: p.update(skills=["graph-bootstrap"]),  # exists but not claude-code-compatible
        lambda p: p.update(skills="plan"),           # not a list
    ):
        r = copy.deepcopy(reg)
        mutate(r.projects["example-project"])
        try:
            _validate(r)
            raise AssertionError("expected RegistryError")
        except RegistryError:
            pass

def test_agents_manifest_field_rejected_loudly():
    """The agents lane was retired (0.1.3 batch 1) — any manifest `agents:` key, even
    an empty list, is a loud RegistryError, mirroring the retired `org:` field."""
    import copy

    from agentic.loader import RegistryError, _validate
    r = copy.deepcopy(reg)
    r.projects["example-project"]["agents"] = []
    try:
        _validate(r)
        raise AssertionError("expected RegistryError")
    except RegistryError as e:
        assert "agents" in str(e)

def test_repo_basename_forms():
    from agentic.planner import _repo_basename
    assert _repo_basename("git@github.com:Peccia/mitos.git") == \
        "mitos"
    assert _repo_basename("https://github.com/Peccia/foo.git") == "foo"
    assert _repo_basename("https://example.com/bar/") == "bar"

_EX_PARTIAL = "context/projects/example-project.md"


def _rig_with_repos(prose_body: str | None = None):
    """example-windows with example-project carrying two repos (one described), and
    optionally a replacement prose body for its context partial."""
    import copy
    from dataclasses import replace as _replace
    rig = _full_windows_rig()
    rig.projects["example-project"] = copy.deepcopy(rig.projects["example-project"])
    rig.projects["example-project"]["repo"] = [
        "https://github.com/you/frontend.git", "https://github.com/you/backend.git"]
    rig.projects["example-project"]["repo_notes"] = {"frontend": "client UI"}
    if prose_body is not None:
        rig.partials = dict(rig.partials)
        rig.partials[_EX_PARTIAL] = _replace(rig.partials[_EX_PARTIAL], body=prose_body)
    return rig


def _example_node(rig):
    from agentic import planner
    return next(o for o in planner.plan_machine(rig, "example-windows")
                if o.target == "agentic-graph"
                and o.deploy_path.endswith("Projects/example-project/AGENTS.md"))


def test_project_node_renders_repo_roster_inside_navigation():
    """A project node's cloned checkouts render as the GENERATED `## Navigation` roster —
    the single source for the repo list — ahead of the generated document block, with no
    `## Workspace Layout` section and no clone URLs. This fixture's prose carries no `##`
    of its own, so the roster supplies the heading."""
    from agentic import render
    node = _example_node(_rig_with_repos())
    assert "## Workspace Layout" not in node.content
    assert "## Navigation" in node.content
    assert "- `frontend/` — client UI" in node.content
    assert "- `backend/`" in node.content          # no note → bare checkout dir
    assert "github.com/you/frontend.git" not in node.content   # URL is deploy machinery
    # Navigation leads the generated document block (reserved-section order, invariant #12)
    assert node.content.index("## Navigation") < node.content.index(
        "Knowledge-graph documents for this project")
    assert render.GENERATED_NAV in [s for s, _ in node.section_bodies]


def test_project_node_roster_attaches_under_authored_navigation():
    """When the prose already opens `## Navigation` (the apdict shape), the roster attaches
    beneath the author's routing text instead of emitting a second heading — which splits
    the partial into TWO regions around the generated one. The carve must keep both, or
    adopt would silently drop the half above the roster."""
    from agentic import render
    prose = ("# Example Project\n\nintro line\n\n"
             "## Navigation\n\nrouting prose here\n\n"
             "## Tools\n\n- the browser\n")
    node = _example_node(_rig_with_repos(prose))
    assert node.content.count("## Navigation") == 1      # no duplicate heading
    # roster lands under the authored routing prose, above the next reserved section
    nav = node.content.index("routing prose here")
    assert nav < node.content.index("- `frontend/` — client UI") < node.content.index("## Tools")

    kinds = [s for s, _ in node.section_bodies]
    assert kinds.count(_EX_PARTIAL) == 2, \
        "prose is split around the generated roster, so it contributes two regions"
    carved = render.split_live_sections(node.section_bodies, node.content)
    assert carved is not None
    # the partial's regions rejoin to exactly its authored prose — nothing generated leaks
    # into what adopt would write back
    rejoined = render.rejoin_regions(carved, _EX_PARTIAL)
    assert "frontend/" not in rejoined
    assert "routing prose here" in rejoined and "- the browser" in rejoined

def test_project_node_without_repos_has_no_navigation_roster():
    """A project with no repos degrades to exactly the shape it had before the roster
    existed — no bare `## Navigation` heading, no empty region in the lockfile."""
    from agentic import planner, render
    rig = _full_windows_rig()   # example-project ships repo: "" (absent)
    outs = planner.plan_machine(rig, "example-windows")
    node = next(o for o in outs if o.target == "agentic-graph"
                and o.deploy_path.endswith("Projects/example-project/AGENTS.md"))
    assert "## Navigation" not in node.content
    assert render.GENERATED_NAV not in [s for s, _ in node.section_bodies]
    assert [s for s, _ in node.section_bodies].count(
        "context/projects/example-project.md") == 1

def test_plan_clones_lands_in_the_right_tree_per_machine():
    from agentic.planner import plan_clones
    # mitos-agent machine: clones land beside the OPERATING tree's project node, keyed by the
    # project NAME (_emit_tree uses the name), so the harness resolves a checkout structurally.
    linux = plan_clones(reg, "example-linux")
    lslugs = [c.slug for c in linux]
    assert "mitos" in lslugs                                # non-empty repo → included
    assert "example-project" not in lslugs                 # repo "" → excluded
    lc = next(c for c in linux if c.slug == "mitos")
    assert lc.dest.endswith("MitosAgent/Projects/Mitos/mitos")   # project NAME "Mitos"
    assert lc.repo == "git@github.com:Peccia/mitos.git"
    # claude-code + agents-md machine: clones land in the reference tree, keyed by the SLUG.
    win = plan_clones(reg, "example-windows")
    wc = next(c for c in win if c.slug == "mitos")
    assert wc.dest.endswith("MitosAgent/Projects/mitos/mitos")   # project SLUG "mitos"
    # workstation machine (claude-code only / no agents-md): workstation checkouts are
    # never auto-cloned or pulled.
    workstation = plan_clones(reg, "example-workstation")
    assert workstation == [], "workstations must never auto-clone or pull checkouts"

def test_clone_is_idempotent_and_nondestructive():
    from agentic import commands
    from agentic.commands import cmd_deploy
    from agentic.io import safe_rel
    from agentic.planner import plan_clones
    calls: list = []

    def fake_clone(repo, dest, branch="", ssh_key=""):
        calls.append(repo)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / ".git").write_text("fake", encoding="utf-8")
        return 0, ""

    mitos_clone = next(c for c in plan_clones(reg, "example-windows")
                       if c.slug == "mitos")
    dest_rel = safe_rel(mitos_clone.dest)
    root = Path(__import__("tempfile").mkdtemp(prefix="ae-clone-"))
    orig = commands._git_clone
    commands._git_clone = fake_clone
    try:
        assert cmd_deploy(reg, "example-windows", dry_run=False, force=False, root=root) == 0
        first_calls = list(calls)
        assert "git@github.com:Peccia/mitos.git" in first_calls  # mitos cloned on first deploy
        assert (root / dest_rel / ".git").exists()
        # a sentinel proves the existing checkout is never touched on redeploy
        (root / dest_rel / "local-work.txt").write_text("mine", encoding="utf-8")
        assert cmd_deploy(reg, "example-windows", dry_run=False, force=False, root=root) == 0
        assert calls == first_calls  # NOT re-cloned (idempotent)
        assert (root / dest_rel / "local-work.txt").read_text(encoding="utf-8") == "mine"
    finally:
        commands._git_clone = orig

def test_clone_failure_is_reported_not_fatal():
    from agentic import commands
    from agentic.commands import cmd_deploy
    from agentic.io import safe_rel
    from agentic.planner import plan_clones

    def failing_clone(repo, dest, branch="", ssh_key=""):
        return 1, "fatal: could not read Username (auth)"

    dest_rel = safe_rel(plan_clones(reg, "example-windows")[0].dest)
    root = Path(__import__("tempfile").mkdtemp(prefix="ae-clonefail-"))
    orig = commands._git_clone
    commands._git_clone = failing_clone
    try:
        # deploy still succeeds (rc 0) — a clone failure is reported, never fatal
        assert cmd_deploy(reg, "example-windows", dry_run=False, force=False, root=root) == 0
        assert not (root / dest_rel).exists()
    finally:
        commands._git_clone = orig

def test_project_agents_md_includes_graph_index_and_emits_details():
    """Per-project AGENTS.md in assistant_root = prose context + graph titles-index;
    AGENTS_DETAILS.md is emitted alongside it. Projects without a graph get prose only."""
    from agentic import graph as graphmod
    treg, tmp = _temp_registry()
    outputs = planner.plan_machine(treg, "rig")

    # example-project has both context.assistant (prose) and a graph
    proj_agents = [o for o in outputs if "Example Project" in o.deploy_path
                   and o.deploy_path.endswith("AGENTS.md")]
    assert len(proj_agents) == 1, "expected exactly one per-project AGENTS.md"
    pa = proj_agents[0]
    # must contain prose (the assistant context partial has project description content)
    assert len(pa.content) > 200
    # must contain the graph titles-index connection section (H2, under the prose H1)
    assert "## Example Project — Documents" in pa.content
    # titles-only index (no Drive URL or raw ID in index)
    assert "https://drive.google.com/open?id=" not in pa.content
    assert "`EXAMPLE_DRIVE_ID" not in pa.content

    # AGENTS_DETAILS.md must be emitted alongside
    details = [o for o in outputs if "Example Project" in o.deploy_path
               and o.deploy_path.endswith(graphmod.DETAILS_FILENAME)]
    assert len(details) == 1, "AGENTS_DETAILS.md must be emitted for projects with a graph"
    det = details[0]
    assert "EXAMPLE_DRIVE_ID_1" in det.content   # raw ID in details (condensed, inline)
    assert "https://drive.google.com/open?id=" not in det.content  # no URL — resolved by ID
    assert det.drift_policy == "generated"

def test_domain_org_skills_deploy_and_effort_domain_line_in_project_agents_md():
    """Three core org skills target hermes; per-project AGENTS.md carries the org line of
    a tagged EFFORT (the example graph's launch-prep effort is tagged marketing) — never a
    project-level Domain line; a leftover manifest org: field is rejected loudly."""
    from agentic import loader as loadermod
    # 1. Core skills exist and target hermes
    for skill_name in ("org-software", "org-design", "org-marketing"):
        assert skill_name in reg.skills, f"{skill_name} must be a core registry skill"
        assert "mitos-agent" in reg.skills[skill_name].targets

    # 2. The tagged effort's org line appears in per-project AGENTS.md; the retired
    # project-level Domain line never does
    treg, tmp = _temp_registry()
    outputs = planner.plan_machine(treg, "rig")
    proj_agents = next((o for o in outputs
                        if "Example Project" in o.deploy_path
                        and o.deploy_path.endswith("AGENTS.md")), None)
    assert proj_agents is not None
    assert "runs under the `marketing` org" in proj_agents.content
    assert "org-marketing" in proj_agents.content
    assert "**Domain:**" not in proj_agents.content

    # 3. a manifest org: field is a category error now — rejected loudly
    import tempfile, shutil
    bad_tmp = Path(tempfile.mkdtemp(prefix="ae-orgval-"))
    for d in ("registry", "connections", "targets", "machines"):
        shutil.copytree(REPO_ROOT / d, bad_tmp / d,
                        ignore=shutil.ignore_patterns("local") if d == "registry" else None)
    (bad_tmp / "registry" / "projects").mkdir(exist_ok=True)
    (bad_tmp / "registry" / "projects" / "bad.yaml").write_text(
        "name: Bad\nslug: bad\nstage: build\norg: software\n", encoding="utf-8")
    try:
        loadermod.load(bad_tmp)
        raise AssertionError("expected RegistryError for manifest org: field")
    except loadermod.RegistryError as e:
        assert "no longer a manifest field" in str(e)
    finally:
        shutil.rmtree(bad_tmp, ignore_errors=True)

def test_assistant_replaces_collaboration_in_agents_md():
    """Assistant/AGENTS.md is planned; Collaboration/AGENTS.md is gone. SOUL.md stays
    LEAN (the less-is-more lesson): the session protocol only — org routing and the
    domain table live in the deployed tree (Projects/AGENTS.md), never the system
    prompt."""
    treg, tmp = _temp_registry()
    outputs = planner.plan_machine(treg, "rig")
    paths = [o.deploy_path for o in outputs]
    assert any("Assistant/AGENTS.md" in p for p in paths), "Assistant/AGENTS.md must be planned"
    assert not any("Collaboration/AGENTS.md" in p for p in paths), \
        "Collaboration/AGENTS.md must not appear (renamed to Assistant/)"

    # SOUL carries the session protocol, not the org detail
    soul = next(o for o in outputs if o.deploy_path.endswith("SOUL.md"))
    assert "new session" in soul.content
    assert "org-software" not in soul.content, "org detail must not bloat the lean SOUL"

    # the per-task org routing + generated domain table live in Projects/AGENTS.md
    proj_index = next(o for o in outputs if o.deploy_path.endswith("/Projects/AGENTS.md"))
    for skill in ("org-software", "org-design", "org-marketing"):
        assert skill in proj_index.content

def test_assistant_root_agents_md_is_the_routing_entry_point():
    """assistant_root/AGENTS.md is Hermes's entry point (new-session Step 4 reads it). It must
    be a root-level file (not under Assistant/ or Projects/), carry routing not org detail, and
    the Projects branch root must carry the dynamically generated org-domain organizations table."""
    treg, tmp = _temp_registry()
    outputs = planner.plan_machine(treg, "rig")
    root = treg.machines["rig"]["paths"]["assistant_root"].rstrip("/")
    # the root entry point exists at exactly assistant_root/AGENTS.md
    root_agents = next((o for o in outputs if o.deploy_path == f"{root}/AGENTS.md"), None)
    assert root_agents is not None, "assistant_root/AGENTS.md (the entry point) must be planned"
    # routing content, no org/domain detail leaking into the lean root
    assert "Assistant/AGENTS.md" in root_agents.content
    assert "Projects/AGENTS.md" in root_agents.content
    assert "CTO —" not in root_agents.content, "org roles must not bloat the lean root"
    # org/domain table lives in the Projects branch root (dynamically generated) as the
    # node's `## Skills` section
    projects_root = next(o for o in outputs if o.deploy_path == f"{root}/Projects/AGENTS.md")
    assert "## Skills" in projects_root.content
    assert "org-software" in projects_root.content

def test_compiler_selfcheck_prefers_upstream_then_origin():
    """The compiler self-check compares against the OFFICIAL remote: `upstream` when a
    contributor's fork added it, else `origin` for a plain user. None when no remotes."""
    if not _git_available():
        return
    import tempfile

    from agentic.sync.selfcheck import _pick_remote
    tmp = Path(tempfile.mkdtemp(prefix="ae-selfcheck-"))
    _run_git(tmp, "init")
    assert _pick_remote(tmp) is None, "no remotes → nothing to compare against"
    _run_git(tmp, "remote", "add", "origin", "https://example.com/fork.git")
    assert _pick_remote(tmp) == "origin", "plain user: origin is the official remote"
    _run_git(tmp, "remote", "add", "upstream", "https://example.com/official.git")
    assert _pick_remote(tmp) == "upstream", "contributor: upstream wins over origin"

def test_git_sync_flow_pull_deploy_push():
    if not _git_available():
        return
    import tempfile

    from agentic.sync import git as gitsync
    tmp = Path(tempfile.mkdtemp(prefix="ae-gitsync-flow-"))
    hub = _make_overlay_hub(tmp)
    ra, oa = _clone_overlay(tmp, hub, "machineA")
    rb, ob = _clone_overlay(tmp, hub, "machineB")
    cfg = {"backend": "git",
           "git": {"hub": _run_git(oa, "remote", "get-url", "origin").stdout.strip()}}
    deployed: list = []
    dep = lambda m: deployed.append(m) or 0

    # A authors a change, commits, and syncs → deploy(A) runs between pull and push
    (oa / "identity" / "who.md").write_text("v1-from-A\n", encoding="utf-8")
    _run_git(oa, "commit", "-am", "A edit")
    out = gitsync.git_sync(ra, "machineA", cfg, deploy=dep)
    assert any(line.startswith("push:") for line in out) and deployed == ["machineA"]

    # B syncs → pulls A's change, deploys B, nothing of its own to push
    gitsync.git_sync(rb, "machineB", cfg, deploy=dep)
    assert (ob / "identity" / "who.md").read_text(encoding="utf-8") == "v1-from-A\n"
    assert deployed == ["machineA", "machineB"]

def test_git_sync_halts_on_conflict_without_forcing():
    if not _git_available():
        return
    import tempfile

    from agentic.sync import SyncError
    from agentic.sync import git as gitsync
    tmp = Path(tempfile.mkdtemp(prefix="ae-gitsync-conflict-"))
    hub = _make_overlay_hub(tmp)
    ra, oa = _clone_overlay(tmp, hub, "A")
    rb, ob = _clone_overlay(tmp, hub, "B")
    cfg = {"backend": "git",
           "git": {"hub": _run_git(oa, "remote", "get-url", "origin").stdout.strip()}}
    nodep = lambda m: 0

    (oa / "identity" / "who.md").write_text("A-line\n", encoding="utf-8")
    _run_git(oa, "commit", "-am", "A")
    gitsync.git_sync(ra, "A", cfg, deploy=nodep)                 # A pushes

    (ob / "identity" / "who.md").write_text("B-line\n", encoding="utf-8")  # same line, differs
    _run_git(ob, "commit", "-am", "B")
    try:
        gitsync.git_sync(rb, "B", cfg, deploy=nodep)
        raise AssertionError("expected SyncError on rebase conflict")
    except SyncError as e:
        assert "conflict" in str(e).lower() or "rebase" in str(e).lower()
    # B never forced its change onto the hub — a fresh clone still shows A's version
    _rc, oc = _clone_overlay(tmp, hub, "check")
    assert (oc / "identity" / "who.md").read_text(encoding="utf-8") == "A-line\n"

def test_git_sync_refuses_a_remote_that_is_not_the_hub():
    if not _git_available():
        return
    import tempfile

    from agentic.sync import SyncError
    from agentic.sync import git as gitsync
    tmp = Path(tempfile.mkdtemp(prefix="ae-gitsync-refuse-"))
    hub = _make_overlay_hub(tmp)
    ra, _oa = _clone_overlay(tmp, hub, "A")                      # origin = hub
    cfg = {"backend": "git", "git": {"hub": "https://example.com/not-your-hub/overlay.git"}}
    try:
        gitsync.git_sync(ra, "A", cfg, deploy=lambda m: 0, dry_run=True)
        raise AssertionError("expected SyncError for a remote that isn't the configured hub")
    except SyncError as e:
        assert "hub" in str(e).lower()

def test_machine_sync_git_needs_hub():
    import copy

    from agentic.loader import RegistryError, _validate
    bad = copy.deepcopy(reg)
    bad.machines["example-linux"]["sync"] = {"backend": "git", "git": {}}
    try:
        _validate(bad)
        raise AssertionError("expected RegistryError (git needs hub)")
    except RegistryError as e:
        assert "hub" in str(e)
    ok = copy.deepcopy(reg)
    ok.machines["example-linux"]["sync"] = {"backend": "git",
                                            "git": {"hub": "ssh://h/overlay.git"}}
    _validate(ok)   # well-formed → no raise

# (removed) test_machine_hermes_settings_validation — the hermes_settings validation lane
# retired with Hermes (mitos-agent owns its config file whole; no settings-leaf merge). A
# leftover hermes_settings: in a profile is now silently ignored, not an error (see
# loader._validate note 5).

def test_git_sync_init_creates_bare_hub_and_pushes():
    if not _git_available():
        return
    import tempfile

    from agentic.sync import git as gitsync
    tmp = Path(tempfile.mkdtemp(prefix="ae-gitinit-"))
    hub = tmp / "hub.git"                       # a LOCAL path that does not exist yet
    root = tmp / "boxA"
    _seed_overlay(root)
    out = gitsync.git_init(root, "boxA", str(hub))
    overlay = root / "registry" / "local"
    # repo made, hook installed, machine recorded, bare hub auto-created
    assert (overlay / ".git").exists()
    assert (overlay / ".git" / "hooks" / "post-merge").exists()
    assert _run_git(overlay, "config", "mitos.machine").stdout.strip() == "boxA"
    assert (hub / "HEAD").exists()              # bare repo created
    assert any("pushed initial overlay" in line for line in out)
    # the hub really holds the overlay — a fresh clone sees who.md
    check = tmp / "check"
    _run_git(tmp, "clone", str(hub), str(check))
    assert (check / "identity" / "who.md").read_text(encoding="utf-8") == "v0\n"

def test_git_sync_clone_onboards_a_new_machine():
    if not _git_available():
        return
    import tempfile

    from agentic.sync import git as gitsync
    tmp = Path(tempfile.mkdtemp(prefix="ae-gitclone-"))
    hub = tmp / "hub.git"
    ra = tmp / "boxA"
    _seed_overlay(ra)
    gitsync.git_init(ra, "boxA", str(hub))
    # a brand-new machine clones it
    rb = tmp / "boxB"
    rb.mkdir()
    out = gitsync.git_clone(rb, "boxB", str(hub))
    ob = rb / "registry" / "local"
    assert (ob / "identity" / "who.md").read_text(encoding="utf-8") == "v0\n"
    assert (ob / ".git" / "hooks" / "post-merge").exists()
    assert _run_git(ob, "config", "mitos.machine").stdout.strip() == "boxB"
    assert any("cloned overlay" in line for line in out)

def test_git_sync_init_then_clone_then_sync_end_to_end():
    if not _git_available():
        return
    import tempfile

    from agentic.sync import git as gitsync
    tmp = Path(tempfile.mkdtemp(prefix="ae-gite2e-"))
    hub = tmp / "hub.git"
    ra = tmp / "boxA"
    _seed_overlay(ra)
    gitsync.git_init(ra, "boxA", str(hub))
    rb = tmp / "boxB"
    rb.mkdir()
    gitsync.git_clone(rb, "boxB", str(hub))
    oa, ob = ra / "registry" / "local", rb / "registry" / "local"
    cfg = {"git": {"hub": _run_git(oa, "remote", "get-url", "origin").stdout.strip()}}
    deployed: list = []
    dep = lambda m: deployed.append(m) or 0

    # A edits + syncs (push); B syncs (pull → deploy) and sees A's change
    (oa / "identity" / "who.md").write_text("v1-from-A\n", encoding="utf-8")
    _run_git(oa, "commit", "-am", "A edit")
    gitsync.git_sync(ra, "boxA", cfg, deploy=dep)
    gitsync.git_sync(rb, "boxB", cfg, deploy=dep)
    assert (ob / "identity" / "who.md").read_text(encoding="utf-8") == "v1-from-A\n"
    assert deployed == ["boxA", "boxB"]

def test_post_merge_hook_is_installed_guarded_and_targets_deploy():
    if not _git_available():
        return
    import tempfile

    from agentic.sync import git as gitsync
    tmp = Path(tempfile.mkdtemp(prefix="ae-githook-"))
    hub = tmp / "hub.git"
    root = tmp / "boxA"
    _seed_overlay(root)
    gitsync.git_init(root, "boxA", str(hub))
    body = (root / "registry" / "local" / ".git" / "hooks" / "post-merge").read_text(
        encoding="utf-8")
    # auto-deploys only when the overlay changed, guarded so it no-ops outside a real checkout
    assert "build/compile.py" in body and "deploy" in body
    assert 'git config mitos.machine' in body
    assert '[ -f "$MITOS_ROOT/build/compile.py" ] || exit 0' in body
    assert "ORIG_HEAD HEAD" in body
    assert "--force" not in body                # never force from the hook

def test_git_sync_init_refuses_an_existing_repo():
    if not _git_available():
        return
    import tempfile

    from agentic.sync import SyncError
    from agentic.sync import git as gitsync
    tmp = Path(tempfile.mkdtemp(prefix="ae-gitinit2-"))
    root = tmp / "boxA"
    _seed_overlay(root)
    gitsync.git_init(root, "boxA", str(tmp / "hub.git"))
    try:
        gitsync.git_init(root, "boxA", str(tmp / "hub2.git"))
        raise AssertionError("expected SyncError re-initializing an existing overlay repo")
    except SyncError as e:
        assert "already a git repo" in str(e)

def test_post_merge_hook_fires_deploy_only_on_overlay_change():
    if not _git_available():
        return
    import tempfile

    from agentic.sync import git as gitsync
    tmp = Path(tempfile.mkdtemp(prefix="ae-hookfire-"))
    hub = tmp / "hub.git"
    ra = tmp / "boxA"
    _seed_overlay(ra)
    gitsync.git_init(ra, "boxA", str(hub))
    rb = tmp / "boxB"
    rb.mkdir()
    gitsync.git_clone(rb, "boxB", str(hub))
    oa, ob = ra / "registry" / "local", rb / "registry" / "local"
    # plant a stand-in compile.py in boxB so the hook's guard passes and we can see it fire
    (rb / "build").mkdir(parents=True, exist_ok=True)
    sentinel = rb / "deploy-ran.txt"
    (rb / "build" / "compile.py").write_text(
        "import sys, pathlib\n"
        f"pathlib.Path(r'{sentinel}').write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n",
        encoding="utf-8")

    # no change yet → a pull with nothing new must NOT fire the hook
    _run_git(ob, "pull", "origin", "main")
    assert not sentinel.exists()

    # A pushes a real change; B's plain `git pull` (the cron/consumer path) fast-forwards →
    # post-merge fires → deploy runs for THIS machine
    (oa / "identity" / "who.md").write_text("v1\n", encoding="utf-8")
    _run_git(oa, "commit", "-am", "A edit")
    _run_git(oa, "push", "origin", "main")
    _run_git(ob, "pull", "origin", "main")
    assert sentinel.exists(), "post-merge hook did not fire deploy on overlay change"
    assert sentinel.read_text(encoding="utf-8").strip() == "deploy --machine boxB"

def test_git_sync_ssh_key_pins_core_sshcommand_on_init_and_clone():
    if not _git_available():
        return
    import tempfile

    from agentic.sync import git as gitsync
    tmp = Path(tempfile.mkdtemp(prefix="ae-sshkey-"))
    hub = tmp / "hub.git"
    key = tmp / "mitos_id"
    key.write_text("dummy-key\n", encoding="utf-8")   # must exist — init/clone fail-fast otherwise
    ra = tmp / "boxA"
    _seed_overlay(ra)
    out = gitsync.git_init(ra, "boxA", str(hub), ssh_key=str(key))
    oa = ra / "registry" / "local"
    cmd = _run_git(oa, "config", "core.sshCommand").stdout.strip()
    assert "mitos_id" in cmd and "IdentitiesOnly=yes" in cmd
    assert any("ssh key:" in line for line in out)

    # clone carries the same key into the new machine's overlay repo
    rb = tmp / "boxB"
    rb.mkdir()
    gitsync.git_clone(rb, "boxB", str(hub), ssh_key=str(key))
    ob = rb / "registry" / "local"
    assert "mitos_id" in _run_git(ob, "config", "core.sshCommand").stdout.strip()

    # day-to-day sync reconciles from the profile: dropping the key clears core.sshCommand
    import subprocess
    cfg = {"git": {"hub": _run_git(oa, "remote", "get-url", "origin").stdout.strip()}}
    gitsync.git_sync(ra, "boxA", cfg, action="refresh", deploy=lambda m: 0)
    got = subprocess.run(["git", "-C", str(oa), "config", "--get", "core.sshCommand"],
                         capture_output=True, text=True)   # exit 1 when unset
    assert got.returncode != 0 or not got.stdout.strip(), "key not cleared when profile drops it"

def test_machine_sync_git_ssh_key_must_be_a_string():
    import copy

    from agentic.loader import RegistryError, _validate
    bad = copy.deepcopy(reg)
    bad.machines["example-linux"]["sync"] = {
        "git": {"hub": "ssh://h/overlay.git", "ssh_key": ["not", "a", "string"]}}
    try:
        _validate(bad)
        raise AssertionError("expected RegistryError (ssh_key must be a string)")
    except RegistryError as e:
        assert "ssh_key" in str(e)
    ok = copy.deepcopy(reg)
    ok.machines["example-linux"]["sync"] = {
        "git": {"hub": "ssh://h/overlay.git", "ssh_key": "~/.ssh/mitos_id"}}
    _validate(ok)   # well-formed → no raise

def test_ssh_key_bare_name_resolves_to_an_absolute_dot_ssh_path():
    # the Linux failure: a bare `-i id_github_mitos` resolves against git's cwd, not ~/.ssh, so
    # ssh can't find the key and (IdentitiesOnly) fails hard. A bare name must become ~/.ssh/<name>.
    from agentic.sync import git as gitsync
    cmd = gitsync._ssh_command("id_github_mitos")
    expected = (Path.home() / ".ssh" / "id_github_mitos").as_posix()
    assert f'-i "{expected}"' in cmd and "IdentitiesOnly=yes" in cmd
    # an absolute path is honored unchanged
    abs_key = (Path.home() / "keys" / "k").as_posix()
    assert f'-i "{abs_key}"' in gitsync._ssh_command(abs_key)
    # ~ is expanded to an absolute path
    assert (Path.home() / ".ssh" / "k").as_posix() in gitsync._ssh_command("~/.ssh/k")

def test_ssh_key_missing_file_fails_clearly_not_with_rc128():
    from agentic.sync import SyncError
    from agentic.sync import git as gitsync
    gitsync._check_key(None)        # no key → no-op
    try:
        gitsync._check_key("definitely-not-a-real-key-9d3f1a")
        raise AssertionError("expected SyncError for a missing key file")
    except SyncError as e:
        assert "ssh key not found" in str(e) and ".ssh" in str(e)

def test_prompt_example_loads():
    """The shipped example-prompt loads with the expected frontmatter fields."""
    p = reg.prompts.get("example-prompt")
    assert p is not None, "example-prompt not found in registry"
    assert p.frontmatter.get("category") == "example"
    assert p.targets == []          # console-only — no targets set

def test_prompt_no_targets_is_console_only_not_an_error():
    """A prompt with no targets: compiles clean, appears in prompt_index."""
    import copy
    r = copy.deepcopy(reg)
    r.prompts["console-only"] = loader.Prompt(
        name="console-only", rel="prompts/console-only.md",
        frontmatter={"name": "console-only", "category": "test"},
        body="just a prompt",
    )
    loader._validate(r)   # must not raise
    from agentic.review import prompt_index
    idx = prompt_index(r)
    names = [p["name"] for p in idx["prompts"]]
    assert "console-only" in names

def test_prompt_duplicate_name_refused():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    pdir = tmp / "prompts"
    pdir.mkdir()
    body = "---\nname: dup\ncategory: test\n---\nbody\n"
    (pdir / "a.md").write_text(body, encoding="utf-8")
    (pdir / "b.md").write_text(body, encoding="utf-8")
    try:
        loader._load_prompts(tmp)
        assert False, "should have raised"
    except loader.RegistryError as e:
        assert "duplicate prompt name" in str(e)

def test_prompt_unknown_target_refused():
    import copy
    r = copy.deepcopy(reg)
    r.prompts["bad"] = loader.Prompt(
        name="bad", rel="prompts/bad.md",
        frontmatter={"name": "bad", "targets": ["nonexistent-harness"]},
        body="x",
    )
    try:
        loader._validate(r)
        assert False, "should have raised"
    except loader.RegistryError as e:
        assert "unknown target" in str(e)

def test_prompt_overlay_replaces_by_name():
    import copy
    r = copy.deepcopy(reg)
    r.prompts["example-prompt"] = loader.Prompt(
        name="example-prompt", rel="local/prompts/example-prompt.md",
        frontmatter={"name": "example-prompt", "category": "overridden"},
        body="overlay body",
    )
    p = r.prompts["example-prompt"]
    assert p.category == "overridden"
    assert p.rel.startswith("local/")

def test_antigravity_deploys_no_prompts():
    """The antigravity prompt lane is retired: Antigravity's skill discovery only reads
    <folder>/SKILL.md, so the old flat prompt-<name>.md files were invisible to it. A
    prompt still declaring targets:[antigravity] deploys nowhere (console-only)."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["antigravity"]
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    r.prompts["test-prompt"] = loader.Prompt(
        name="test-prompt", rel="prompts/test-prompt.md",
        frontmatter={"name": "test-prompt", "targets": ["antigravity"]},
        body="My reusable prompt body.",
    )
    outputs = planner.plan_machine(r, "example-windows")
    assert not any(o.target == "antigravity" and "test-prompt" in o.deploy_path
                   for o in outputs)

def test_console_only_prompt_not_deployed():
    """A prompt with no targets produces no file outputs."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["antigravity"]
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    r.prompts["private-prompt"] = loader.Prompt(
        name="private-prompt", rel="prompts/private-prompt.md",
        frontmatter={"name": "private-prompt", "targets": []},
        body="console-only body",
    )
    outputs = planner.plan_machine(r, "example-windows")
    assert not any("private-prompt" in o.deploy_path for o in outputs)

def test_claude_code_deploys_bound_prompt():
    """A manifest-bound prompt with targets:[claude-code] deploys to .claude/commands/.
    Uses an isolated rig with a pinned local_path so the test is overlay-independent."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["claude-code"]
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    r.prompts["review-checklist"] = loader.Prompt(
        name="review-checklist", rel="prompts/review-checklist.md",
        frontmatter={"name": "review-checklist", "description": "Code review checklist",
                     "targets": ["claude-code"]},
        body="Check these items:\n- Security\n- Tests",
    )
    # example-project has example-windows in its core local_path; bind the prompt to it
    r.projects["example-project"]["local_path"]["example-windows"] = "example-project"
    r.projects["example-project"]["prompts"] = ["review-checklist"]
    outputs = planner.plan_machine(r, "example-windows")
    prompt_outs = [o for o in outputs if "review-checklist" in o.deploy_path]
    assert prompt_outs, "no claude-code output for bound prompt"
    o = prompt_outs[0]
    assert ".claude/commands/review-checklist.md" in o.deploy_path
    assert o.target == "claude-code"
    assert "description: Code review checklist" in o.content
    assert "Check these items:" in o.content

def test_claude_code_unbound_prompt_not_deployed():
    """A prompt not listed in the project manifest is not deployed to that project."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["claude-code"]
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    r.prompts["not-bound"] = loader.Prompt(
        name="not-bound", rel="prompts/not-bound.md",
        frontmatter={"name": "not-bound", "targets": ["claude-code"]},
        body="unbound body",
    )
    # no `prompts:` in manifest
    outputs = planner.plan_machine(r, "example-windows")
    assert not any("not-bound" in o.deploy_path for o in outputs)

def test_binding_console_only_prompt_to_project_refused():
    """A manifest that binds a console-only prompt (no claude-code target) is rejected."""
    import copy
    r = copy.deepcopy(reg)
    r.prompts["console-only"] = loader.Prompt(
        name="console-only", rel="prompts/console-only.md",
        frontmatter={"name": "console-only", "targets": []},
        body="console only",
    )
    r.projects["mitos"]["prompts"] = ["console-only"]
    try:
        loader._validate(r)
        assert False, "should have raised"
    except loader.RegistryError as e:
        assert "does not target 'claude-code'" in str(e)

def test_binding_unknown_prompt_to_project_refused():
    """A manifest that binds a prompt name not in reg.prompts is rejected."""
    import copy
    r = copy.deepcopy(reg)
    r.projects["mitos"]["prompts"] = ["nonexistent-prompt"]
    try:
        loader._validate(r)
        assert False, "should have raised"
    except loader.RegistryError as e:
        assert "unknown prompt" in str(e)

def test_claude_code_prompt_render_adds_description_frontmatter():
    """render_prompt('claude-code') emits description: frontmatter before body."""
    from agentic.render import render_prompt
    p = loader.Prompt(
        name="my-prompt", rel="prompts/my-prompt.md",
        frontmatter={"name": "my-prompt", "description": "My test prompt"},
        body="Do the thing.",
    )
    rendered = render_prompt(p, "claude-code")
    assert rendered.startswith("---\n")
    assert "description: My test prompt" in rendered
    assert "Do the thing." in rendered

def test_antigravity_prompt_render_is_plain_body():
    """render_prompt for non-claude-code targets returns plain body (no frontmatter)."""
    from agentic.render import render_prompt
    p = loader.Prompt(
        name="my-prompt", rel="prompts/my-prompt.md",
        frontmatter={"name": "my-prompt", "description": "desc", "targets": ["antigravity"]},
        body="Plain content.",
    )
    rendered = render_prompt(p, "antigravity")
    assert not rendered.startswith("---")
    assert rendered.strip() == "Plain content."

def test_claude_app_desktop_mcp_config_planned():
    """When claude_desktop_config is set, claude-app plans a json_merge MCP bridge."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["claude-app"]
    r.machines["example-windows"]["paths"]["claude_desktop_config"] = (
        "C:/Users/Paul/AppData/Roaming/Claude/claude_desktop_config.json"
    )
    outputs = planner.plan_machine(r, "example-windows")
    mcp_outs = [o for o in outputs if o.target == "claude-app" and o.kind == "json_merge"]
    assert mcp_outs, "no claude-app MCP output"
    o = mcp_outs[0]
    assert o.owned_keys == ["mcpServers"]
    assert o.target_file == o.deploy_path
    assert o.lane == "connections"
    assert "claude_desktop_config.json" in o.deploy_path
    import json
    parsed = json.loads(o.content)
    assert "mcpServers" in parsed
    alias = r.targets["claude-app"]["server_alias"]
    assert alias in parsed["mcpServers"]
    # example-windows is os: windows -> npx is bridged via `cmd /c` (Electron can't
    # spawn the .cmd shim directly). gws is streamable-http, so it gets the bridge.
    entry = parsed["mcpServers"][alias]
    assert entry["command"] == "cmd"
    assert entry["args"][:3] == ["/c", "npx", "-y"]

def test_claude_app_no_desktop_path_no_mcp_output():
    """Without claude_desktop_config, claude-app emits no MCP config (skills still ok)."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["claude-app"]
    # deliberately no claude_desktop_config key in paths
    r.machines["example-windows"]["paths"].pop("claude_desktop_config", None)
    outputs = planner.plan_machine(r, "example-windows")
    assert not any(o.target == "claude-app" and o.kind == "json_merge" for o in outputs)

def test_claude_app_bridge_pins_exact_version():
    """SECURITY: the bridge package must be pinned to an exact version, never a bare or
    floating spec — a floating tag would let a hijacked publish run on every launch."""
    from agentic.render import claude_desktop_mcp_config, MCP_REMOTE_SPEC
    assert "@" in MCP_REMOTE_SPEC, "bridge spec must carry an exact @version"
    assert not MCP_REMOTE_SPEC.endswith("@latest")
    server = {"url": "http://x/mcp", "transport": "streamable-http"}
    for os_name in ("windows", "linux", "darwin"):
        args = claude_desktop_mcp_config(server, "a", os_name=os_name)["mcpServers"]["a"]["args"]
        assert MCP_REMOTE_SPEC in args, "bridge must reference the pinned spec"
        assert "mcp-remote" not in args, "bare/floating package name must not appear"

def test_claude_app_desktop_render():
    """A streamable-http server over plain http: bridged via pinned mcp-remote with
    `--transport http-only` (no SSE fallback) AND `--allow-http` (http opt-in), OS-aware."""
    from agentic.render import claude_desktop_mcp_config, MCP_REMOTE_SPEC
    server = {"url": "http://localhost:8000/mcp", "transport": "streamable-http", "tools": {}}
    win = claude_desktop_mcp_config(server, "my-alias", os_name="windows")
    assert win == {"mcpServers": {"my-alias": {
        "command": "cmd",
        "args": ["/c", "npx", "-y", MCP_REMOTE_SPEC, "http://localhost:8000/mcp",
                 "--transport", "http-only", "--allow-http"]}}}
    nix = claude_desktop_mcp_config(server, "my-alias", os_name="linux")
    assert nix == {"mcpServers": {"my-alias": {
        "command": "npx",
        "args": ["-y", MCP_REMOTE_SPEC, "http://localhost:8000/mcp",
                 "--transport", "http-only", "--allow-http"]}}}

def test_claude_app_desktop_render_https_no_allow_http():
    """An https server gets no --allow-http (only plain http needs the opt-in)."""
    from agentic.render import claude_desktop_mcp_config
    server = {"url": "https://remote.example/mcp", "transport": "streamable-http"}
    args = claude_desktop_mcp_config(server, "a", os_name="linux")["mcpServers"]["a"]["args"]
    assert "--allow-http" not in args
    assert args[-2:] == ["--transport", "http-only"]

def test_claude_app_desktop_render_sse_transport():
    """An SSE server forces --transport sse-only."""
    from agentic.render import claude_desktop_mcp_config
    server = {"url": "https://remote.example/sse", "transport": "sse"}
    args = claude_desktop_mcp_config(server, "a", os_name="linux")["mcpServers"]["a"]["args"]
    assert args[-2:] == ["--transport", "sse-only"]

def test_claude_app_desktop_render_stdio_passthrough():
    """A native stdio server (command/args) is passed through unbridged."""
    from agentic.render import claude_desktop_mcp_config
    server = {"command": "my-server", "args": ["--flag"], "transport": "stdio"}
    result = claude_desktop_mcp_config(server, "my-alias", os_name="windows")
    assert result == {"mcpServers": {"my-alias": {"command": "my-server", "args": ["--flag"]}}}

def test_claude_app_in_known_targets():
    """claude-app is a valid KNOWN_TARGET — machines can list it without error."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["claude-app"]
    loader._validate(r)   # must not raise


def test_load_machine_yaml_prefers_local_overlay():
    """_load_machine_yaml reads local overlay first; falls back to core machines/."""
    import tempfile, shutil
    import yaml as _y
    from mitos import _load_machine_yaml

    tmp = Path(tempfile.mkdtemp(prefix="ae-mymach-"))
    try:
        core_machines = tmp / "registry" / "machines"
        local_machines = tmp / "registry" / "local" / "machines"
        core_machines.mkdir(parents=True)
        local_machines.mkdir(parents=True)

        # core declares "boxA"
        (core_machines / "boxa.yaml").write_text(
            "name: boxA\nos: linux\nsync:\n  git:\n    hub: ssh://core/hub.git\n",
            encoding="utf-8")

        # local overrides "boxA" with a different hub
        (local_machines / "boxa.yaml").write_text(
            "name: boxA\nos: linux\nsync:\n  git:\n    hub: ssh://local/hub.git\n",
            encoding="utf-8")

        # local overlay wins
        result = _load_machine_yaml(tmp, "boxA")
        assert result is not None
        assert result["sync"]["git"]["hub"] == "ssh://local/hub.git"

        # unknown machine → None
        assert _load_machine_yaml(tmp, "ghost") is None

        # core-only machine (not in local) is still found
        (core_machines / "boxc.yaml").write_text(
            "name: boxC\nos: windows\n", encoding="utf-8")
        result_c = _load_machine_yaml(tmp, "boxC")
        assert result_c is not None and result_c["os"] == "windows"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cmd_sync_proceeds_with_stale_registry():
    """_cmd_sync must NOT abort when loader.load() raises RegistryError on pull/all actions, and
    the deploy step must reload the registry FRESH (post-pull), not reuse a captured stale one.

    The chicken-and-egg: a stale overlay (e.g. skill referencing a removed target) blocks
    loader.load(), which previously prevented the pull that would have fixed it. Now _cmd_sync
    falls back to _load_machine_yaml() for the sync config so the pull can fix the overlay,
    then reloads the registry fresh for the deploy step.
    """
    import argparse
    from unittest.mock import patch, MagicMock
    from agentic.loader import RegistryError
    from mitos import _cmd_sync

    hub_cfg = "ssh://hub.example/overlay.git"
    machine_cfg = {"name": "stale-box", "os": "linux",
                   "sync": {"git": {"hub": hub_cfg, "branch": "main"}}}

    args = argparse.Namespace(machine="stale-box", action="pull",
                              dry_run=False, hub=None, remote=None, branch=None,
                              ssh_key=None)

    # loader.load: 1st call (top of _cmd_sync) raises (stale overlay), 2nd call (inside the
    # deploy closure, AFTER the pull) returns a fresh registry sentinel — the pull fixed it.
    fresh_reg = MagicMock(name="fresh_reg")
    load_mock = MagicMock(side_effect=[RegistryError("stale target 'claude-ai'"), fresh_reg])

    deploy_args: list = []

    def fake_cmd_deploy(reg, machine, prune, force):
        deploy_args.append((reg, machine, prune, force))
        return 0

    # fake git_sync mirrors the real pull/all path: it INVOKES the deploy callable between
    # pull and push, so the fresh-reload closure is actually exercised.
    sync_calls: list = []

    def fake_git_sync(root, machine, cfg, *, action, dry_run, deploy):
        sync_calls.append((machine, action))
        rc = deploy(machine)        # the real git_sync raises SyncError if this is nonzero
        assert rc == 0
        return iter([f"deploy: applied overlay to {machine}"])

    with patch("agentic.loader.load", load_mock):
        with patch("mitos._load_machine_yaml", return_value=machine_cfg):
            with patch("agentic.commands.cmd_deploy", side_effect=fake_cmd_deploy):
                with patch("agentic.sync.git_sync", side_effect=fake_git_sync):
                    with patch("mitos._compiler_check"):
                        rc = _cmd_sync(args)

    # must NOT have returned 2 (the old abort-on-RegistryError path)
    assert rc == 0, f"expected 0 (sync proceeded), got {rc}"
    # git_sync was actually called — sync was not short-circuited
    assert sync_calls == [("stale-box", "pull")]
    # loader.load was called twice: the failed pre-pull load + the fresh post-pull reload
    assert load_mock.call_count == 2, "deploy must reload the registry fresh, not reuse the stale one"
    # cmd_deploy received the FRESH registry (the 2nd load), never the stale pre-pull snapshot
    assert len(deploy_args) == 1
    assert deploy_args[0][0] is fresh_reg, "deploy must run against the post-pull registry"
    assert deploy_args[0][1] == "stale-box"

    # init/clone still abort on RegistryError — they need a valid registry to proceed
    for bad_action in ("init", "clone"):
        args2 = argparse.Namespace(machine="stale-box", action=bad_action,
                                   dry_run=False, hub="ssh://h/x.git", remote=None,
                                   branch=None, ssh_key=None)
        with patch("agentic.loader.load", side_effect=RegistryError("stale target")):
            with patch("mitos._compiler_check"):
                rc2 = _cmd_sync(args2)
        assert rc2 == 2, f"expected 2 (abort) for action={bad_action!r}, got {rc2}"


def test_cmd_sync_deploy_fails_when_pull_did_not_fix_overlay():
    """If the registry is STILL invalid after the pull (the fix wasn't in the hub, or it's a
    genuine corruption), the deploy step must fail (rc 1 → SyncError), so a bad deploy is never
    followed by a push."""
    import argparse
    from unittest.mock import patch, MagicMock
    from agentic.loader import RegistryError
    from agentic.sync import SyncError
    from mitos import _cmd_sync

    machine_cfg = {"name": "stale-box", "os": "linux",
                   "sync": {"git": {"hub": "ssh://h/x.git", "branch": "main"}}}
    args = argparse.Namespace(machine="stale-box", action="all",
                              dry_run=False, hub=None, remote=None, branch=None, ssh_key=None)

    # both loads raise — pre-pull AND post-pull (the pull did not carry a fix)
    load_mock = MagicMock(side_effect=RegistryError("still stale"))

    def fake_git_sync(root, machine, cfg, *, action, dry_run, deploy):
        rc = deploy(machine)                 # the deploy closure reloads → still raises → rc 1
        if rc != 0:
            raise SyncError(f"deploy --machine {machine} failed (rc {rc})")
        return iter([])

    with patch("agentic.loader.load", load_mock):
        with patch("mitos._load_machine_yaml", return_value=machine_cfg):
            with patch("agentic.sync.git_sync", side_effect=fake_git_sync):
                with patch("mitos._compiler_check"):
                    rc = _cmd_sync(args)

    assert rc == 1, "a deploy that fails on a still-invalid registry must surface as rc 1"



# ── skill extensions (render-time splice only) — R1/R2 ─────────────────────────
def test_compose_skill_body_no_extension_returns_original():
    parent = reg.skills["org-software"]
    assert render.compose_skill_body(reg, parent) == parent.body

def test_compose_skill_body_splices_extension_under_anchor_never_mutates_registry():
    import copy
    from agentic.loader import Skill
    rig = copy.deepcopy(reg)
    rig.skills["org-data-science"] = Skill(
        name="org-data-science", rel="local/skills/org-data-science/SKILL.md",
        frontmatter={"targets": ["mitos-agent"], "extends_skill": "org-software",
                    "extends_role": "CTO"},
        body="Extra CTO guidance for data science work.")
    parent = rig.skills["org-software"]
    composed = render.compose_skill_body(rig, parent)
    assert "### CTO — org-data-science (extension)" in composed
    assert "Extra CTO guidance for data science work." in composed
    # inserted before the next top-level heading (Red-Team Protocols), not after it —
    # order-independent, unlike matching a specific existing role heading (R2)
    idx_ext = composed.index("### CTO — org-data-science (extension)")
    idx_redteam = composed.index("## Red-Team Protocols")
    assert idx_ext < idx_redteam
    # R1: the loaded Skill.body is never mutated — only the render-time copy is composed
    assert parent.body == reg.skills["org-software"].body
    assert "org-data-science" not in parent.body

def test_compose_skill_resources_merges_and_extension_wins_on_collision():
    import copy
    from agentic.loader import Skill, SkillResource
    rig = copy.deepcopy(reg)
    parent = rig.skills["org-software"]
    parent.resources = {"examples/base.md": SkillResource(
        text="base\n", rel="skills/org-software/examples/base.md")}
    rig.skills["org-ext"] = Skill(
        name="org-ext", rel="local/skills/org-ext/SKILL.md",
        frontmatter={"targets": ["mitos-agent"], "extends_skill": "org-software",
                    "extends_role": "CTO"},
        body="ext body",
        resources={
            "examples/base.md": SkillResource(
                text="override\n", rel="local/skills/org-ext/examples/base.md"),
            "scripts/check.sh": SkillResource(
                text="#!/bin/sh\n", rel="local/skills/org-ext/scripts/check.sh"),
        })
    merged = render.compose_skill_resources(rig, parent)
    assert merged["examples/base.md"].text == "override\n"      # extension wins on collision
    assert merged["examples/base.md"].rel == "local/skills/org-ext/examples/base.md"
    assert "scripts/check.sh" in merged

def test_selected_skills_excludes_extension_skills():
    import copy
    from agentic import planner as plannermod
    from agentic.loader import Skill
    rig = copy.deepcopy(reg)
    rig.skills["org-ext2"] = Skill(
        name="org-ext2", rel="local/skills/org-ext2/SKILL.md",
        frontmatter={"targets": ["mitos-agent"], "extends_skill": "org-software",
                    "extends_role": "CFO"},
        body="ext body")
    selected = plannermod._selected_skills(rig, {"include_target": "mitos-agent"})
    names = {s.name for s in selected}
    assert "org-ext2" not in names
    assert "org-software" in names


# ── skill scope: global (default) | project ─────────────────────────────────────
def test_antigravity_deploys_global_scope_skill_to_shared_dir():
    """Default scope (global): an antigravity-targeted skill deploys to the shared
    antigravity_skills directory, whether or not any project binds it."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["antigravity"]
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    r.skills["global-skill"] = loader.Skill(
        name="global-skill", rel="local/skills/global-skill/SKILL.md",
        frontmatter={"targets": ["antigravity"]}, body="global body")
    outputs = planner.plan_machine(r, "example-windows")
    matches = [o for o in outputs if "global-skill" in o.deploy_path]
    assert len(matches) == 1
    assert matches[0].target == "antigravity"
    # Agent Skills standard shape: a folder per skill, SKILL.md inside, with
    # name/description frontmatter (description drives Antigravity's discovery).
    assert matches[0].deploy_path.replace("\\", "/").endswith("global-skill/SKILL.md")
    assert matches[0].content.startswith("---\n")
    assert "name: global-skill" in matches[0].content

def test_antigravity_excludes_unbound_project_scoped_skill_from_shared_dir_and_everywhere():
    """scope: project skill targeting antigravity, not bound to any project, deploys
    nowhere — NOT the shared antigravity_skills dir (that's the point of scoping it), and
    no project picks it up because none binds it."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["antigravity"]
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    r.skills["proj-skill"] = loader.Skill(
        name="proj-skill", rel="local/skills/proj-skill/SKILL.md",
        frontmatter={"targets": ["antigravity"], "scope": "project"}, body="proj body")
    outputs = planner.plan_machine(r, "example-windows")
    assert not any("proj-skill" in o.deploy_path for o in outputs)

def test_antigravity_deploys_project_scoped_skill_only_to_bound_project_local_path():
    """scope: project skill bound via a project's skills: list deploys to that project's
    own <local_path>/.agents/skills/ — never the shared antigravity_skills directory."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["antigravity"]
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    r.skills["proj-skill"] = loader.Skill(
        name="proj-skill", rel="local/skills/proj-skill/SKILL.md",
        frontmatter={"targets": ["antigravity"], "scope": "project"}, body="proj body")
    r.projects["example-project"]["local_path"]["example-windows"] = "example-project"
    r.projects["example-project"]["skills"] = ["proj-skill"]
    outputs = planner.plan_machine(r, "example-windows")
    matches = [o for o in outputs if "proj-skill" in o.deploy_path]
    assert len(matches) == 1, "must deploy exactly once — project path only, no shared copy"
    o = matches[0]
    assert o.target == "antigravity"
    assert ("example-project/.agents/skills/proj-skill/SKILL.md"
            in o.deploy_path.replace("\\", "/"))

def test_antigravity_project_scoped_skill_not_deployed_to_other_projects():
    """A project-scoped skill bound to one project does not leak into a sibling project
    that doesn't bind it."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["antigravity"]
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    r.skills["proj-skill"] = loader.Skill(
        name="proj-skill", rel="local/skills/proj-skill/SKILL.md",
        frontmatter={"targets": ["antigravity"], "scope": "project"}, body="proj body")
    r.projects["example-project"]["local_path"]["example-windows"] = "example-project"
    r.projects["example-project"]["skills"] = ["proj-skill"]
    r.projects["mitos"]["local_path"]["example-windows"] = "Mitos"
    # mitos does NOT bind proj-skill
    outputs = planner.plan_machine(r, "example-windows")
    matches = [o for o in outputs if "proj-skill" in o.deploy_path]
    assert len(matches) == 1
    assert "example-project" in matches[0].deploy_path.replace("\\", "/")
    assert "Mitos" not in matches[0].deploy_path

def test_mitos_agent_ignores_scope_and_still_deploys_project_scoped_skill_globally():
    """Hermes deliberately does not participate in scoping — a scope: project skill
    that also targets hermes still ships to the global hermes skills dir."""
    treg, tmp = _temp_registry()
    treg.skills["proj-and-hermes"] = loader.Skill(
        name="proj-and-hermes", rel="local/skills/proj-and-hermes/SKILL.md",
        frontmatter={"name": "proj-and-hermes", "targets": ["mitos-agent", "antigravity"],
                    "scope": "project"}, body="body")
    outputs = planner.plan_machine(treg, "rig")
    matches = [o for o in outputs if o.target == "mitos-agent" and "proj-and-hermes" in o.deploy_path]
    assert len(matches) == 1, "hermes must still deploy a scope:project skill globally"

def test_claude_code_deploys_global_scope_skill_to_personal_skills_dir():
    """Default scope (global): a claude-code-targeted skill deploys once to the personal
    claude_code_skills directory (~/.claude/skills/) — no project binding needed. This is
    the new capability that closes the historical claude-code/antigravity asymmetry."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["claude-code"]
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    r.skills["personal-skill"] = loader.Skill(
        name="personal-skill", rel="local/skills/personal-skill/SKILL.md",
        frontmatter={"name": "personal-skill", "targets": ["claude-code"]}, body="global body")
    outputs = planner.plan_machine(r, "example-windows")
    matches = [o for o in outputs if "personal-skill" in o.deploy_path]
    assert len(matches) == 1
    assert matches[0].target == "claude-code"
    assert matches[0].deploy_path.replace("\\", "/").endswith("personal-skill/SKILL.md")

def test_claude_code_project_scoped_skill_deploys_only_to_bound_project():
    """scope: project skill bound via a project's skills: list deploys only to that
    project's .claude/skills/ — never the personal claude_code_skills directory."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["claude-code"]
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    r.skills["proj-cc-skill"] = loader.Skill(
        name="proj-cc-skill", rel="local/skills/proj-cc-skill/SKILL.md",
        frontmatter={"name": "proj-cc-skill", "targets": ["claude-code"], "scope": "project"},
        body="proj body")
    r.projects["example-project"]["local_path"]["example-windows"] = "example-project"
    r.projects["example-project"]["skills"] = ["proj-cc-skill"]
    outputs = planner.plan_machine(r, "example-windows")
    matches = [o for o in outputs if "proj-cc-skill" in o.deploy_path]
    assert len(matches) == 1, "must deploy exactly once — project path only, no personal-dir copy"
    assert ("example-project/.claude/skills/proj-cc-skill/SKILL.md"
            in matches[0].deploy_path.replace("\\", "/"))

def test_claude_code_global_scope_skill_unbound_to_any_project_still_deploys():
    """Unlike scope: project (which requires a project binding to deploy anywhere),
    scope: global needs no project manifest entry at all."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["claude-code"]
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    r.skills["unbound-global"] = loader.Skill(
        name="unbound-global", rel="local/skills/unbound-global/SKILL.md",
        frontmatter={"name": "unbound-global", "targets": ["claude-code"]}, body="body")
    # no project manifest lists "unbound-global" in skills:
    outputs = planner.plan_machine(r, "example-windows")
    assert any("unbound-global" in o.deploy_path for o in outputs)


def test_skill_deploy_warnings_flags_machine_curated_exclusion():
    """A skill compatible with a target (its own frontmatter says so) but filtered out
    by this machine's curation is reported as a warning — the filter is never silent."""
    r = _connected_rig("example-linux")   # gws is otherwise filtered by requires_server
    r.machines["example-linux"]["skills"] = {"mitos-agent": {"exclude": ["gws"]}}
    warnings = planner.skill_deploy_warnings(r, "example-linux")
    assert any("'gws'" in w and "'mitos-agent'" in w and "curation" in w for w in warnings)

def test_skill_deploy_warnings_name_the_missing_connection():
    """A requires_server drop is reported as such, not misattributed to curation — the
    operator needs to know the fix is `document_store:`, not an exclude list."""
    warnings = planner.skill_deploy_warnings(reg, "example-linux")   # ships unconnected
    assert any("'gws'" in w and "requires the 'gws' connection" in w
               and "document_store" in w for w in warnings)
    assert not any("curation" in w for w in warnings)

def test_skill_deploy_warnings_flags_project_scope_leak_on_mitos_agent():
    """A scope: project skill that also targets mitos-agent still deploys globally there —
    warn-only, so the leaked confinement is visible. mitos-agent is the only such target: it
    WRITES the file, automatically, machine-wide."""
    r = _connected_rig("example-linux")
    r.machines["example-linux"]["skills"] = {}
    r.skills["proj-and-agent"] = loader.Skill(
        name="proj-and-agent", rel="local/skills/proj-and-agent/SKILL.md",
        frontmatter={"name": "proj-and-agent", "targets": ["mitos-agent"],
                     "scope": "project"}, body="body")
    warnings = planner.skill_deploy_warnings(r, "example-linux")
    assert any("'proj-and-agent'" in w and "'mitos-agent'" in w
               and "ignores scope" in w for w in warnings)


# ── manual targets stage a menu: no curation, no leak ─────────────────────────
def test_a_manual_target_stages_every_compatible_skill_ignoring_curation():
    """claude-app STAGES a zip; a human uploads it. The choice already happens at upload time,
    so curating the pile only removes options the operator can no longer reach without a
    registry edit and a redeploy."""
    import copy
    r = copy.deepcopy(reg)
    r.skills["stage-me"] = loader.Skill(
        name="stage-me", rel="local/skills/stage-me/SKILL.md",
        frontmatter={"name": "stage-me", "targets": ["claude-app"]}, body="body")
    # a curation list the loader would now reject, forced in to prove the planner ignores it
    r.machines["example-windows"]["skills"] = {"claude-app": {"exclude": ["stage-me"]}}
    sk_spec = r.targets["claude-app"]["skills"]
    selected = {s.name for s in planner._selected_skills(r, sk_spec,
                                                         r.machines["example-windows"])}
    assert "stage-me" in selected


def test_a_manual_target_never_reports_a_scope_leak_or_a_curation_exclusion():
    """Every diagnostic has to leave a configuration that is correct AND quiet. On claude-app
    both lines used to fire whatever the operator did — exclude the skill and it warned that it
    was excluded, keep it and it warned that it leaked — so the only silent configuration was to
    drop the target from the skill's frontmatter, i.e. to give the capability up."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["skills"] = {}
    r.skills["proj-and-claude-app"] = loader.Skill(
        name="proj-and-claude-app", rel="local/skills/proj-and-claude-app/SKILL.md",
        frontmatter={"name": "proj-and-claude-app", "targets": ["claude-app"],
                     "scope": "project"}, body="body")
    warnings = planner.skill_deploy_warnings(r, "example-windows")
    assert not any("proj-and-claude-app" in w for w in warnings)


def test_a_manual_target_still_honours_requires_server():
    """Which MCP connections a box has is a fact about the box, not a preference. A skill that
    is nothing but instructions for a server this machine never wired is a dangling instruction
    whether a human uploaded it or the compiler wrote it."""
    import copy
    r = copy.deepcopy(reg)
    r.skills["needs-gws"] = loader.Skill(
        name="needs-gws", rel="local/skills/needs-gws/SKILL.md",
        frontmatter={"name": "needs-gws", "targets": ["claude-app"],
                     "requires_server": "gws"}, body="body")
    r.machines["example-windows"].pop("document_store", None)
    sk_spec = r.targets["claude-app"]["skills"]
    selected = {s.name for s in planner._selected_skills(r, sk_spec,
                                                         r.machines["example-windows"])}
    assert "needs-gws" not in selected
    assert any("needs-gws" in w and "requires the 'gws' connection" in w
               for w in planner.skill_deploy_warnings(r, "example-windows"))


def test_is_manual_skill_target_is_the_zip_mode_set():
    assert loader.is_manual_skill_target(reg.targets["claude-app"])
    assert not loader.is_manual_skill_target(reg.targets["claude-code"])
    assert not loader.is_manual_skill_target(reg.targets["mitos-agent"])
    assert not loader.is_manual_skill_target({})

# ── delivers: pairing an effort's forward contract with the skill that answers it ──
def _rig_wanting(term: str, *, delivered_by: str | None = None):
    """A connected rig whose example-project effort declares `term`, optionally with a
    mitos-agent skill that declares `delivers: term`."""
    from dataclasses import replace as _replace
    r = _connected_rig("example-linux")
    pg = r.graphs["example-project"]
    pg.efforts = [_replace(pg.efforts[0], deliverables=(term,))] + list(pg.efforts[1:])
    # Drop whatever ships for this term. Otherwise the test asserts "no skill delivers X" while
    # depending on X having no skill in the real registry — which stopped being true the moment
    # the deliverable skills landed, and would keep breaking as more do.
    for name in [n for n, s in r.skills.items() if s.delivers == term]:
        del r.skills[name]
    if delivered_by:
        r.skills[delivered_by] = loader.Skill(
            name=delivered_by, rel=f"skills/{delivered_by}/SKILL.md",
            frontmatter={"name": delivered_by, "targets": ["mitos-agent"],
                         "delivers": term}, body="body")
    return r


def test_declared_deliverable_with_no_delivering_skill_warns():
    """The forward contract only means something if a procedure answers it. Without this an
    effort declares 'deploy-book', every harness reads the compiled line asking for one, and
    no skill anywhere says how to write one — a gap found months later by its absence."""
    warnings = planner.skill_deploy_warnings(_rig_wanting("deploy-book"), "example-linux")
    assert any("deploy-book" in w and "delivers: deploy-book" in w
               and "example-linux" in w for w in warnings)
    # the effort that wants it is named, so the warning is actionable
    assert any("example-project/" in w for w in warnings if "deploy-book" in w)


def test_a_delivering_skill_retires_the_warning():
    r = _rig_wanting("deploy-book", delivered_by="write-deploy-book")
    assert not any("delivers: deploy-book" in w
                   for w in planner.skill_deploy_warnings(r, "example-linux"))


def test_undelivered_warning_groups_by_term_not_by_effort():
    """One line per missing term, listing every effort that wants it — so adding one skill
    retires exactly one warning instead of N."""
    from dataclasses import replace as _replace
    r = _rig_wanting("runbook")
    pg = r.graphs["example-project"]
    second = _replace(pg.efforts[0], id="second-effort", deliverables=("runbook",))
    pg.efforts = list(pg.efforts) + [second]
    lines = [w for w in planner.skill_deploy_warnings(r, "example-linux")
             if "delivers: runbook" in w]
    assert len(lines) == 1
    assert "second-effort" in lines[0] and lines[0].count("runbook") >= 2


def test_skill_deploy_warnings_silent_when_nothing_filtered_or_leaked():
    warnings = planner.skill_deploy_warnings(_connected_rig("example-linux"), "example-linux")
    assert warnings == []


# ── skill supporting files (examples/, scripts/) — R5/R6 ───────────────────────
def test_plan_mitos_agent_emits_skill_resource_outputs():
    from agentic.loader import SkillResource
    treg, tmp = _temp_registry()
    skill = treg.skills["gws"]
    skill.resources = {
        "examples/sample.md": SkillResource(text="ex\n", rel="skills/gws/examples/sample.md"),
        "scripts/check.sh": SkillResource(text="#!/bin/sh\necho ok\n",
                                          rel="skills/gws/scripts/check.sh"),
    }
    outs = planner.plan_machine(treg, "rig")
    skill_md = next(o for o in outs if o.target == "mitos-agent"
                    and o.deploy_path.endswith("gws/SKILL.md"))
    base_dir = skill_md.deploy_path.rsplit("/", 1)[0]
    example_out = next(o for o in outs if o.deploy_path == f"{base_dir}/examples/sample.md")
    script_out = next(o for o in outs if o.deploy_path == f"{base_dir}/scripts/check.sh")
    assert example_out.content == "ex\n"
    assert example_out.sources == ["skills/gws/examples/sample.md"]   # routes to its OWN file
    assert example_out.drift_policy == skill_md.drift_policy
    assert script_out.executable is True
    assert example_out.executable is False

def test_plan_antigravity_emits_skill_resources_and_composed_body():
    """Antigravity mirrors claude-code: supporting files deploy alongside SKILL.md and
    an extension's body is spliced in — the historical antigravity path dropped both."""
    import copy
    from agentic.loader import Skill, SkillResource
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["antigravity"]
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    r.skills["ag-skill"] = Skill(
        name="ag-skill", rel="local/skills/ag-skill/SKILL.md",
        frontmatter={"name": "ag-skill", "targets": ["antigravity"]},
        body="## Extended C-suite Roles\n\nbase body",
        resources={"scripts/check.sh": SkillResource(
            text="#!/bin/sh\necho ok\n", rel="local/skills/ag-skill/scripts/check.sh")})
    r.skills["ag-ext"] = Skill(
        name="ag-ext", rel="local/skills/ag-ext/SKILL.md",
        frontmatter={"name": "ag-ext", "targets": ["antigravity"],
                     "extends_skill": "ag-skill", "extends_role": "CTO"},
        body="extension body")
    outs = planner.plan_machine(r, "example-windows")
    skill_md = next(o for o in outs if o.target == "antigravity"
                    and o.deploy_path.replace("\\", "/").endswith("ag-skill/SKILL.md"))
    assert "extension body" in skill_md.content          # extension spliced at render
    base_dir = skill_md.deploy_path.rsplit("/", 1)[0]
    script_out = next(o for o in outs if o.deploy_path == f"{base_dir}/scripts/check.sh")
    assert script_out.executable is True
    assert script_out.sources == ["local/skills/ag-skill/scripts/check.sh"]
    # the extension itself never deploys standalone
    assert not any(o.deploy_path.replace("\\", "/").endswith("ag-ext/SKILL.md")
                   for o in outs)

def test_plan_claude_app_zip_bundles_resources_deterministically():
    import dataclasses

    from agentic.commands import _payload
    from agentic.loader import SkillResource
    rig = _full_windows_rig()
    rig.skills["gws"].resources = {
        "examples/sample.md": SkillResource(text="ex\n", rel="skills/gws/examples/sample.md"),
    }
    outs = planner.plan_machine(rig, "example-windows")
    # by NAME: `next(...)` used to work only because gws was the sole claude-app skill, so
    # this started picking whichever one sorts first the moment another shipped.
    zip_out = next(o for o in outs if o.target == "claude-app" and o.kind == "zip"
                   and o.deploy_path.endswith("gws.zip"))
    assert zip_out.zip_members
    assert zip_out.zip_members["gws/SKILL.md"] == zip_out.content
    assert zip_out.zip_members["gws/examples/sample.md"] == "ex\n"
    # deterministic payload bytes regardless of dict insertion order (R3)
    payload1 = _payload(zip_out)
    reordered = dataclasses.replace(
        zip_out, zip_members={k: zip_out.zip_members[k]
                              for k in reversed(list(zip_out.zip_members))})
    assert payload1 == _payload(reordered)

def test_plan_claude_app_zip_without_resources_uses_plain_zip_member():
    # the common case (no resources) must not regress to the multi-member path —
    # zip_members stays empty so _payload falls back to zip_member+content.
    rig = _full_windows_rig()
    outs = planner.plan_machine(rig, "example-windows")
    # by NAME: `next(...)` used to work only because gws was the sole claude-app skill, so
    # this started picking whichever one sorts first the moment another shipped.
    zip_out = next(o for o in outs if o.target == "claude-app" and o.kind == "zip"
                   and o.deploy_path.endswith("gws.zip"))
    assert zip_out.zip_members == {}
    assert zip_out.zip_member == "gws/SKILL.md"


def test_project_roster_block_aliases():
    """project_roster_block emits [aliases: ...] between the slug and description."""
    from agentic import render
    projects = [
        {"name": "Apdict", "slug": "apdict", "aliases": ["sensual predictions", "apdicts"],
         "description": "Financial narrative processing"},
        {"name": "Mitos", "slug": "mitos", "description": "Human-agentic harness"},
    ]
    roster = render.project_roster_block(projects)
    assert "- `Projects/Apdict/` (apdict) [aliases: sensual predictions, apdicts] — Financial narrative processing" in roster
    assert "- `Projects/Mitos/` (mitos) — Human-agentic harness" in roster
