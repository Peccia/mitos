"""Claude-code, Antigravity, Hermes, skill, prompt, and git-sync tests."""
from __future__ import annotations

import sys
from pathlib import Path

from conftest import (
    REPO_ROOT, reg, loader, planner, render, classify_output,
    _inbox, _temp_registry, _doc, _write_graph,
    _plant_candidate, _skill_meta, _full_windows_rig, _sandbox_deploy,
    _git_available, _run_git, _make_overlay_hub, _clone_overlay, _seed_overlay,
)

def _lint(path, content):
    from agentic.planner import Output, lint_node_markdown
    return lint_node_markdown(Output(
        target="agents-md", kind="text", deploy_path=path, dist_rel="x",
        content=content, drift_policy="protect"))


def test_lint_node_markdown_accepts_conformant_node():
    body = ("# Ascenzio Predictions\n\nA project.\n\n"
            "## Navigation\n- repos\n\n## Tools\n- gws\n\n## Skills\n- a skill\n\n"
            "## Google Workspace suite (`gws`)\n\n- paths\n\n### Launch\n- Doc\n")
    assert _lint("x/Projects/Ascenzio/AGENTS.md", body) == []


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
    assert _lint("x/.hermes/SOUL.md", "## About Me\n\n## How to work\n") == []
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

def test_hermes_mcp_flat_tool_count():
    tools = render.flat_tools(reg.servers["servers"]["gws"])
    assert len(tools) == 31
    assert tools[0] == "list_calendars"

def test_non_hermes_machine_coproduces_agents_md():
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
    assert "Builder Context" in out.content, "self-contained CLAUDE.md inlines the builder prose"
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
    assert "Builder Context" in out.content
    assert "Google Workspace suite" in out.content
    assert "Design Review" in out.content
    assert "`MITOS_DOC_1`" not in out.content, "raw ID belongs in details, not the index"

    # full detail (raw ID) lives in the companion file, under the same connection heading
    assert "Google Workspace suite" in det.content
    assert "`MITOS_DOC_1`" in det.content

    # section-aware drift tracking: prose sections stay separate from the generated tail
    assert out.section_bodies
    assert any(render.is_generated_source(s) for s, _ in out.section_bodies)

def test_project_agents_md_drops_identity_on_hermes_machines():
    """On a machine that also deploys hermes, SOUL.md already carries the identity
    partials on every request — the project-root AGENTS.md (project_agents) must not
    repeat them. An agents-md machine WITHOUT hermes has no SOUL.md, so it keeps the
    full persona header (the persona has to live somewhere)."""
    import copy

    def _rig(targets):
        rig = copy.deepcopy(reg)
        rig.machines["example-windows"]["targets"] = targets
        # hermes needs a home for its own outputs; irrelevant to the assertion
        rig.machines["example-windows"]["paths"]["hermes_home"] = "C:/hermes"
        rig.projects["mitos"]["local_path"]["example-windows"] = "Mitos"
        return rig

    agents_path = "C:/Projects/Mitos/AGENTS.md"

    # hermes co-deployed → identity dropped, builder prose kept
    outs = planner.plan_machine(_rig(["claude-code", "agents-md", "hermes"]),
                                "example-windows")
    out = next(o for o in outs if o.deploy_path == agents_path and o.target == "agents-md")
    assert "About Me" not in out.content, "identity must not duplicate SOUL.md"
    assert not any(s.startswith("identity/") for s in out.sources)
    assert "Builder Context" in out.content

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
    rig.machines["example-windows"]["targets"] = ["hermes", "agents-md"]
    rig.machines["example-windows"]["paths"]["assistant_root"] = "C:/MitosAgent"
    rig.machines["example-windows"]["paths"]["hermes_home"] = "C:/hermes"
    proj = rig.projects["example-project"]
    proj.pop("example", None)
    proj["agentic_tree"] = "MitosAgent"
    proj["local_path"]["example-windows"] = "example-project"

    outs = planner.plan_machine(rig, "example-windows")
    mount_root = "C:/Projects/example-project/MitosAgent"
    paths = {o.deploy_path for o in outs}
    assert f"{mount_root}/AGENTS.md" not in paths, \
        "agentic_tree must be a no-op on an agentic machine"

def test_non_hermes_clone_uses_local_path():
    """plan_clones returns local_path-based destinations on non-Hermes claude-code machines,
    absent-only — never nesting into the Mitos repo root."""
    import copy
    rig = copy.deepcopy(reg)
    if "apoc" not in rig.projects:
        rig.projects["apoc"] = {"name": "Apocalyptic Adventure", "slug": "apoc", "local_path": {}, "context": {}}
    rig.machines["example-windows"]["targets"] = ["claude-code"]
    rig.machines["example-windows"]["paths"].pop("agentic_context_root", None)
    rig.projects["apoc"]["local_path"]["example-windows"] = "apocalyptic_adventure"
    rig.projects["apoc"]["repo"] = "git@github.com:Peccia/apoc.git"

    clones = planner.plan_clones(rig, "example-windows")
    apoc_clone = next((c for c in clones if c.slug == "apoc"), None)
    assert apoc_clone is not None, "apoc with repo + local_path must produce a CloneSpec"
    assert apoc_clone.dest == "C:/Projects/apocalyptic_adventure/apoc"
    assert apoc_clone.repo == "git@github.com:Peccia/apoc.git"

    # agentic_context_root lane still works when both are present on the same machine
    rig2 = copy.deepcopy(reg)
    if "apoc" not in rig2.projects:
        rig2.projects["apoc"] = {"name": "Apocalyptic Adventure", "slug": "apoc", "local_path": {}, "context": {}}
    rig2.machines["example-windows"]["targets"] = ["claude-code"]
    rig2.machines["example-windows"]["paths"]["agentic_context_root"] = "C:/MitosAgent"
    rig2.projects["apoc"]["local_path"]["example-windows"] = "apocalyptic_adventure"
    rig2.projects["apoc"]["repo"] = "git@github.com:Peccia/apoc.git"
    clones2 = planner.plan_clones(rig2, "example-windows")
    dests = {c.dest for c in clones2 if c.slug == "apoc"}
    # both lanes produce a dest for apoc: one under the context root, one under local_path
    assert any("MitosAgent" in d for d in dests), "agentic_context_root lane must still fire"
    assert any("apocalyptic_adventure" in d for d in dests), "local_path lane must also fire"

def test_claude_app_target_stages_uploadable_zip():
    import copy
    import json as _json
    import tempfile
    import zipfile

    from agentic.commands import classify_output, cmd_deploy
    from agentic.io import safe_rel
    # gws opts into claude-app via its frontmatter; it's the only CORE skill that does
    # (registry/local/ skills are excluded here — ignore_local=True), so no machine-side
    # curation is needed to get exactly one output.
    # example-windows sets claude_skills_staging but NOT claude_desktop_config, so the only
    # claude-app output is the skill zip (the Desktop-MCP half is opt-in by path key).
    reg2 = copy.deepcopy(reg)
    outs = [o for o in planner.plan_machine(reg2, "example-windows")
            if o.target == "claude-app"]
    assert len(outs) == 1
    o = outs[0]
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
    base = {"include_target": "hermes"}
    all_hermes = {s.name for s in _selected_skills(reg, base)}
    assert "gws" in all_hermes and "idea-revision" not in all_hermes  # push layer
    only = _selected_skills(reg, base, {"skills": {"hermes": {"include": ["new-session", "gws"]}}})
    assert {s.name for s in only} == {"new-session", "gws"}                  # pull: include
    rest = _selected_skills(reg, base, {"skills": {"hermes": {"exclude": ["gws"]}}})
    assert {s.name for s in rest} == all_hermes - {"gws"}             # pull: exclude
    # include cannot smuggle a skill the frontmatter doesn't target
    assert not _selected_skills(
        reg, {"include_target": "claude-code"},
        {"skills": {"claude-code": {"include": ["graph-bootstrap"]}}})

def test_target_side_skill_curation_rejected():
    """include:/exclude: under a targets/*.yaml skills: block is core, shared by every
    user, and not overlayable — curation belongs on the machine profile instead."""
    import copy

    from agentic.loader import RegistryError, _validate
    for bad_skills in ({"include": ["gws"]}, {"exclude": ["gws"]}):
        reg2 = copy.deepcopy(reg)
        reg2.targets["hermes"]["skills"].update(bad_skills)
        try:
            _validate(reg2)
            raise AssertionError(f"expected RegistryError for {bad_skills}")
        except RegistryError as e:
            assert "not allowed in targets" in str(e)

def test_machine_side_skill_curation_validation():
    import copy

    from agentic.loader import RegistryError, _validate
    bad_cases = (
        {"hermes": {"include": ["no-such-skill"]}},
        {"hermes": {"include": ["gws"], "exclude": ["gws"]}},
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
    reg2.machines["example-linux"]["skills"] = {"hermes": {"include": ["gws"]}}
    _validate(reg2)

def test_deselect_then_prune():
    import copy

    from agentic.commands import cmd_deploy
    from agentic.io import safe_rel
    reg2 = copy.deepcopy(reg)
    root = Path(__import__("tempfile").mkdtemp(prefix="ae-prune-"))
    assert cmd_deploy(reg2, "example-linux", dry_run=False, force=False, root=root) == 0
    gws_path = next(o.deploy_path for o in planner.plan_machine(reg2, "example-linux")
                    if "skills" in o.deploy_path and o.deploy_path.endswith("gws/SKILL.md"))
    dest = root / safe_rel(gws_path)
    assert dest.exists()

    # deselect via machine-side exclude: deploy reports an orphan but keeps the file
    reg2.machines["example-linux"]["skills"] = {"hermes": {"exclude": ["gws"]}}
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

def test_plan_clones_gated_on_claude_code_env_and_repo():
    from agentic.planner import plan_clones
    assert plan_clones(reg, "example-linux") == []          # no claude-code target
    clones = plan_clones(reg, "example-windows")
    slugs = [c.slug for c in clones]
    # mitos has a non-empty repo → included; example-project's is "" → excluded
    assert "mitos" in slugs
    assert "example-project" not in slugs
    c = next(c for c in clones if c.slug == "mitos")
    assert c.dest.endswith("MitosAgent/Projects/mitos/mitos")
    assert c.repo == "git@github.com:Peccia/mitos.git"

def test_clone_is_idempotent_and_nondestructive(monkeypatch=None):
    from agentic import commands
    from agentic.commands import cmd_deploy
    from agentic.io import safe_rel
    from agentic.planner import plan_clones
    calls: list = []

    def fake_clone(repo, dest):
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

    def failing_clone(repo, dest):
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
        assert "hermes" in reg.skills[skill_name].targets

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

def test_machine_hermes_settings_validation():
    import copy

    from agentic.loader import RegistryError, _validate
    bad_cases = [
        {"memory_enabled": "yes"},                # bool key, wrong type
        {"max_turns": "150"},                      # int key, wrong type
        {"disabled_toolsets": "image_gen"},         # list key, not a list
        {"session_reset_mode": 0},                  # string key, wrong type
        {"fallback_model": ["gemini"]},              # mapping key, wrong type
    ]
    for bad_hs in bad_cases:
        bad = copy.deepcopy(reg)
        bad.machines["example-linux"]["hermes_settings"] = bad_hs
        try:
            _validate(bad)
            raise AssertionError(f"expected RegistryError for {bad_hs}")
        except RegistryError:
            pass

    ok = copy.deepcopy(reg)
    ok.machines["example-linux"]["hermes_settings"] = {
        "memory_enabled": True, "user_profile_enabled": False,
        "max_turns": 150, "restart_drain_timeout": 180,
        "disabled_toolsets": ["image_gen"], "platform_toolsets_cli": ["file"],
        "session_reset_mode": "none", "fallback_providers": ["a:b"],
        "fallback_model": {"provider": "gemini"}, "custom_providers": [{"name": "a"}],
    }
    _validate(ok)   # well-formed → no raise

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
        frontmatter={"targets": ["hermes"], "extends_skill": "org-software",
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
        frontmatter={"targets": ["hermes"], "extends_skill": "org-software",
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
        frontmatter={"targets": ["hermes"], "extends_skill": "org-software",
                    "extends_role": "CFO"},
        body="ext body")
    selected = plannermod._selected_skills(rig, {"include_target": "hermes"})
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

def test_hermes_ignores_scope_and_still_deploys_project_scoped_skill_globally():
    """Hermes deliberately does not participate in scoping — a scope: project skill
    that also targets hermes still ships to the global hermes skills dir."""
    treg, tmp = _temp_registry()
    treg.skills["proj-and-hermes"] = loader.Skill(
        name="proj-and-hermes", rel="local/skills/proj-and-hermes/SKILL.md",
        frontmatter={"name": "proj-and-hermes", "targets": ["hermes", "antigravity"],
                    "scope": "project"}, body="body")
    outputs = planner.plan_machine(treg, "rig")
    matches = [o for o in outputs if o.target == "hermes" and "proj-and-hermes" in o.deploy_path]
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
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-linux"]["skills"] = {"hermes": {"exclude": ["gws"]}}
    warnings = planner.skill_deploy_warnings(r, "example-linux")
    assert any("'gws'" in w and "'hermes'" in w and "curation" in w for w in warnings)

def test_skill_deploy_warnings_flags_project_scope_leak_on_claude_app():
    """A scope: project skill that also targets claude-app (a scope-ignoring target)
    still deploys globally there — warn-only, so the leaked confinement is visible."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["skills"] = {}
    r.skills["proj-and-claude-app"] = loader.Skill(
        name="proj-and-claude-app", rel="local/skills/proj-and-claude-app/SKILL.md",
        frontmatter={"name": "proj-and-claude-app", "targets": ["claude-app"],
                    "scope": "project"}, body="body")
    warnings = planner.skill_deploy_warnings(r, "example-windows")
    assert any("'proj-and-claude-app'" in w and "'claude-app'" in w
              and "ignores scope" in w for w in warnings)

def test_skill_deploy_warnings_silent_when_nothing_filtered_or_leaked():
    warnings = planner.skill_deploy_warnings(reg, "example-linux")
    assert warnings == []


# ── skill supporting files (examples/, scripts/) — R5/R6 ───────────────────────
def test_plan_hermes_emits_skill_resource_outputs():
    from agentic.loader import SkillResource
    treg, tmp = _temp_registry()
    skill = treg.skills["gws"]
    skill.resources = {
        "examples/sample.md": SkillResource(text="ex\n", rel="skills/gws/examples/sample.md"),
        "scripts/check.sh": SkillResource(text="#!/bin/sh\necho ok\n",
                                          rel="skills/gws/scripts/check.sh"),
    }
    outs = planner.plan_machine(treg, "rig")
    skill_md = next(o for o in outs if o.target == "hermes"
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
    zip_out = next(o for o in outs if o.target == "claude-app" and o.kind == "zip")
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
    zip_out = next(o for o in outs if o.target == "claude-app" and o.kind == "zip")
    assert zip_out.zip_members == {}
    assert zip_out.zip_member == "gws/SKILL.md"
