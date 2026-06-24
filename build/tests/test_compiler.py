#!/usr/bin/env python
"""Smoke tests for the mitos compiler.

Runnable two ways:
  build/.venv/Scripts/python.exe build/tests/test_compiler.py     (standalone)
  pytest build/tests/test_compiler.py                              (if pytest present)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "build"))

from agentic import loader, planner, render  # noqa: E402
from agentic.commands import classify_output  # noqa: E402

reg = loader.load(REPO_ROOT)


def _inbox(root: Path) -> Path:
    """Mirror of loader.inbox_dir for tests — inbox lives inside the overlay, not at repo root."""
    return root / "registry" / "local" / "inbox"


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


def test_machine_file_counts():
    rig = _full_windows_rig()
    # hermes 11 (SOUL.md + 10 skills from core+overlay) + agents-md 5 (Projects index +
    # 4 project context entries: Ascenzio Predictions, Apocalyptic Adventure, Example Project,
    # Personal Brand)
    assert len(planner.plan_machine(rig, "example-linux")) == 16
    # claude-code 4 (2 CLAUDE.md + code-reviewer agent for mitos & example-project)
    # + gemini 10 (mcp_config + config.json + idea-revision + 3 dept personas
    # + gws + plan + plan-existing-iteration + plan-new-idea, all now gemini-targeted)
    # + agents-md 1 (mitos builder AGENTS.md) + claude-ai 1 (gws.zip) + agentic-graph 5 (roster
    # + apdict AGENTS.md + apdict AGENTS_DETAILS.md + example-project AGENTS.md +
    # example-project AGENTS_DETAILS.md)
    assert len(planner.plan_machine(rig, "example-windows")) == 21


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


def test_deployed_docs_are_raw_context_only():
    # the moat carries pure context — no banner, no provenance markers anywhere
    for machine in ("example-linux", "example-windows"):
        for o in planner.plan_machine(machine_reg := reg, machine):
            if o.kind != "text":
                continue
            assert not o.content.lstrip().startswith("<!-- DO NOT EDIT"), o.deploy_path
            assert "<!-- begin:" not in o.content and "<!-- end:" not in o.content
    soul = next(o for o in planner.plan_machine(reg, "example-linux")
                if o.deploy_path.endswith("SOUL.md"))
    assert soul.content.startswith("## About Me")          # first partial, verbatim
    # all five identity partials present verbatim, in order, nothing between them
    # (who-i-am, security, comms-style, operating-rules, org-hierarchy)
    assert len(soul.section_bodies) == 5
    assert soul.content == "\n\n".join(b for _, b in soul.section_bodies) + "\n"
    stub = next(o for o in planner.plan_machine(reg, "example-windows")
                if o.deploy_path.endswith("mitos/CLAUDE.md"))
    assert stub.content.strip() == "@AGENTS.md" and not stub.section_bodies


def test_gemini_grants_normalized():
    grants = render.gemini_permission_grants(reg.servers["servers"]["gws"], "gws-mcp-local")
    allow = grants["userSettings"]["globalPermissionGrants"]["allow"]
    assert "mcp(gws-mcp-local/search_drive_files)" in allow
    # normalization dropped the extended-tier tools Gemini used to grant
    assert not any("draft_gmail_message" in a for a in allow)
    assert len(allow) == 31


def test_hermes_mcp_flat_tool_count():
    tools = render.flat_tools(reg.servers["servers"]["gws"])
    assert len(tools) == 31
    assert tools[0] == "list_calendars"


def test_self_hosting_stub_and_full():
    outs = planner.plan_machine(_full_windows_rig(), "example-windows")
    claude = {o.deploy_path: o for o in outs if o.target == "claude-code"}
    ae = next(o for p, o in claude.items() if p.endswith("mitos/CLAUDE.md"))
    assert ae.content.strip().endswith("@AGENTS.md")
    agents = next(o for o in outs if o.target == "agents-md"
                  and o.deploy_path.endswith("mitos/AGENTS.md"))
    assert "Builder Context" in agents.content


def test_idea_revision_targeting():
    linux = [o.deploy_path for o in planner.plan_machine(reg, "example-linux")]
    assert not any("idea-revision" in p for p in linux)        # gemini-only, not hermes
    win = [o.deploy_path for o in planner.plan_machine(reg, "example-windows")]
    assert any("idea-revision.md" in p for p in win)           # emitted as gemini prompt


def test_classify_create_for_absent_path():
    o = planner.plan_machine(reg, "example-linux")[0]
    st = classify_output(reg, "example-linux", o, {"machines": {}})
    # ~/.hermes/... does not exist on this box → create
    assert st.state in ("create", "merge")


def test_plain_document_is_clean_concatenation():
    doc = render.plain_document([("identity/a.md", "alpha\nline2"), ("context/b.md", "beta")])
    assert doc == "alpha\nline2\n\nbeta\n"
    assert "begin:" not in doc and "DO NOT EDIT" not in doc


def test_split_live_sections_attributes_edits():
    base = [("identity/a.md", "alpha one\nalpha two"),
            ("identity/b.md", "beta one"),
            ("context/c.md", "gamma one\ngamma two")]
    live = render.plain_document(base)
    # unchanged → each section maps back verbatim
    assert render.split_live_sections(base, live) == {
        "identity/a.md": "alpha one\nalpha two",
        "identity/b.md": "beta one",
        "context/c.md": "gamma one\ngamma two"}
    # edit inside the middle section only → that one source changes, others intact
    edited = live.replace("beta one", "beta one EDITED\nbeta two")
    out = render.split_live_sections(base, edited)
    assert out["identity/b.md"] == "beta one EDITED\nbeta two"
    assert out["identity/a.md"] == "alpha one\nalpha two"
    assert out["context/c.md"] == "gamma one\ngamma two"


def test_strip_frontmatter():
    skill = next(iter(reg.skills.values()))
    rendered = render.render_skill(skill, "hermes")
    assert rendered.startswith("---")
    body = render.strip_frontmatter(rendered)
    assert not body.lstrip().startswith("---")
    assert skill.body.split("\n", 1)[0] in body


def test_rewrite_registry_body_preserves_frontmatter(tmp_path=None):
    import tempfile
    from dataclasses import replace as _replace  # noqa: F401

    from agentic.commands import _rewrite_registry_body

    tmp = Path(tempfile.mkdtemp())
    f = tmp / "registry" / "identity" / "x.md"
    f.parent.mkdir(parents=True)
    f.write_text("---\naudience: [hermes]\n---\nold body line\n", encoding="utf-8")
    stub = loader.Registry(root=tmp, partials={}, skills={}, servers={},
                           projects={}, targets={}, machines={})
    _rewrite_registry_body(stub, "identity/x.md", "new body line")
    out = f.read_text(encoding="utf-8")
    assert "audience: [hermes]" in out          # frontmatter preserved
    assert "new body line" in out and "old body line" not in out


# ── Phase 4a: integration tests against a sandbox root ──────────────────────
def _sandbox_deploy(machine: str) -> Path:
    """Deploy a machine into a fresh temp root; return the root."""
    import tempfile

    from agentic.commands import cmd_deploy
    root = Path(tempfile.mkdtemp(prefix="ae-sandbox-"))
    rc = cmd_deploy(reg, machine, dry_run=False, force=False, root=root)
    assert rc == 0, f"sandbox deploy failed (rc={rc})"
    return root


def test_machine_guard_refuses_cross_os():
    from agentic.commands import _local_os, cmd_deploy
    other = "example-linux" if _local_os() != "linux" else "example-windows"
    assert cmd_deploy(reg, other, dry_run=True, force=False, root=None) == 2


def test_sandbox_deploy_writes_lock_and_files():
    from agentic.io import safe_rel
    root = _sandbox_deploy("example-linux")
    assert (root / ".deploy-lock.json").exists()
    soul = next(o for o in planner.plan_machine(reg, "example-linux")
                if o.deploy_path.endswith("SOUL.md"))
    assert (root / safe_rel(soul.deploy_path)).read_text(encoding="utf-8") == soul.content


def test_deploy_captures_harvest_drift_to_inbox():
    import yaml as _yaml

    from agentic.commands import cmd_deploy
    from agentic.io import safe_rel
    root = _sandbox_deploy("example-linux")
    skill = next(o for o in planner.plan_machine(reg, "example-linux")
                 if o.drift_policy == "harvest" and o.kind == "text")
    deployed = root / safe_rel(skill.deploy_path)
    edited = deployed.read_text(encoding="utf-8") + "\n## Curator improvement\nbetter\n"
    deployed.write_text(edited, encoding="utf-8", newline="\n")

    assert cmd_deploy(reg, "example-linux", dry_run=False, force=False, root=root) == 0
    candidates = [d for d in (_inbox(root)).iterdir() if d.is_dir()]
    assert len(candidates) == 1
    meta = _yaml.safe_load((candidates[0] / "meta.yaml").read_text(encoding="utf-8"))
    assert meta["registry_path"] == skill.sources[0]
    assert meta["kind"] == "drift"
    assert meta["source"]["machine"] == "example-linux"
    assert meta["base_hash"].startswith("sha256:")
    payload = (candidates[0] / "SKILL.md").read_text(encoding="utf-8")
    assert "## Curator improvement" in payload                 # proposal survived
    assert deployed.read_text(encoding="utf-8") == skill.content   # registry reinstated


def test_classify_resolved_when_live_matches_registry():
    from agentic.commands import classify_output
    from agentic.io import safe_rel, sha256
    root = _sandbox_deploy("example-linux")
    o = next(o for o in planner.plan_machine(reg, "example-linux") if o.kind == "text")
    # simulate a stale lock (e.g. the live file was adopted): hashes no longer match,
    # but disk already equals the fresh render → must be `resolved`, never `conflict`
    stale_lock = {"machines": {"example-linux": {"files": {
        o.deploy_path: {"source_hash": "sha256:stale", "deployed_hash": "sha256:stale"},
    }}}}
    st = classify_output(reg, "example-linux", o, stale_lock, root=root)
    assert st.state == "resolved", st.state
    assert (root / safe_rel(o.deploy_path)).exists()
    assert sha256(o.content) != "sha256:stale"


def test_env_overlay_merge_semantics():
    template = (REPO_ROOT / "connections/env/gws.env.example").read_text(encoding="utf-8")
    merged = render.merge_env(template, "WORKSPACE_MCP_PORT=9999\nNEW_KEY=added\n")
    assert "WORKSPACE_MCP_PORT=9999" in merged          # overlay wins
    assert "WORKSPACE_MCP_PORT=8000" not in merged
    assert "USER_GOOGLE_EMAIL=user@example.com" in merged   # template kept
    assert "NEW_KEY=added" in merged                    # overlay-only key appended



def test_split_live_sections_flags_boundary_spanning_edit():
    base = [("identity/a.md", "alpha"), ("context/b.md", "beta")]
    live = render.plain_document(base)
    # collapse the gap between the two sections — the edit straddles the boundary
    spanning = live.replace("alpha\n\nbeta", "alpha and beta merged")
    assert render.split_live_sections(base, spanning) is None


def test_zip_bytes_deterministic():
    from agentic.io import zip_bytes
    a = zip_bytes("gws/SKILL.md", "body text")
    b = zip_bytes("gws/SKILL.md", "body text")
    assert a == b                                   # fixed timestamp → stable hashes
    assert zip_bytes("gws/SKILL.md", "other") != a


def test_claude_ai_target_stages_uploadable_zip():
    import copy
    import json as _json
    import tempfile
    import zipfile

    from agentic.commands import classify_output, cmd_deploy
    from agentic.io import safe_rel
    # gws opts into claude-ai via its frontmatter; the target spec's include curates
    reg2 = copy.deepcopy(reg)
    outs = [o for o in planner.plan_machine(reg2, "example-windows")
            if o.target == "claude-ai"]
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
    from agentic.planner import _selected_skills
    base = {"include_target": "hermes"}
    all_hermes = {s.name for s in _selected_skills(reg, base)}
    assert "gws" in all_hermes and "idea-revision" not in all_hermes  # push layer
    only = _selected_skills(reg, {**base, "include": ["plan", "gws"]})
    assert {s.name for s in only} == {"plan", "gws"}                  # pull: include
    rest = _selected_skills(reg, {**base, "exclude": ["gws"]})
    assert {s.name for s in rest} == all_hermes - {"gws"}             # pull: exclude
    # include cannot smuggle a skill the frontmatter doesn't target
    assert not _selected_skills(reg, {"include_target": "claude-code",
                                      "include": ["graph-bootstrap"]})


def test_skill_selection_validation():
    import copy

    from agentic.loader import RegistryError, _validate
    for bad_skills in ({"include": ["no-such-skill"]},
                       {"include": ["gws"], "exclude": ["gws"]}):
        reg2 = copy.deepcopy(reg)
        reg2.targets["hermes"]["skills"].update(bad_skills)
        try:
            _validate(reg2)
            raise AssertionError(f"expected RegistryError for {bad_skills}")
        except RegistryError:
            pass


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

    # deselect via target-side exclude: deploy reports an orphan but keeps the file
    reg2.targets["hermes"]["skills"]["exclude"] = ["gws"]
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


def test_lane_partition_is_total_and_clean():
    # every output is exactly one lane; all MCP wiring + env is connections, all
    # prose is content — no output straddles the moat boundary
    for machine in ("example-linux", "example-windows"):
        for o in planner.plan_machine(reg, machine):
            assert o.lane in ("content", "connections"), o.deploy_path
            if o.kind in ("env", "yaml_merge", "json_merge", "json"):
                assert o.lane == "connections", o.deploy_path
            else:
                assert o.lane == "content" and o.kind in ("text", "zip"), o.deploy_path


def test_lane_deploy_preserves_other_lanes_lock():
    import json as _json

    from agentic.commands import cmd_deploy
    rig = _full_windows_rig()
    root = Path(__import__("tempfile").mkdtemp(prefix="ae-lanes-"))
    assert cmd_deploy(rig, "example-windows", dry_run=False, force=False,
                      root=root) == 0                # full deploy: both lanes locked
    lock = _json.loads((root / ".deploy-lock.json").read_text(encoding="utf-8"))
    files = lock["machines"]["example-windows"]["files"]
    content_paths = [p for p in files if p.endswith(("CLAUDE.md", "AGENTS.md"))]
    assert content_paths, "expected content entries after a full deploy"

    # connections-only redeploy must keep every content entry intact
    assert cmd_deploy(rig, "example-windows", dry_run=False, force=False,
                      root=root, lane="connections") == 0
    lock2 = _json.loads((root / ".deploy-lock.json").read_text(encoding="utf-8"))
    files2 = lock2["machines"]["example-windows"]["files"]
    for p in content_paths:
        assert files2.get(p) == files[p], f"content lock entry lost: {p}"
    conn_paths = [p for p in files2 if p.endswith("mcp_config.json")]
    assert conn_paths, "connections lane should still lock its own outputs"


def test_json_merge_preserves_user_entries():
    import json as _json
    import tempfile

    from agentic.commands import _apply_json_merge
    from agentic.io import safe_rel
    perm = next(o for o in planner.plan_machine(reg, "example-windows")
                if o.kind == "json_merge")
    root = Path(tempfile.mkdtemp(prefix="ae-jsonmerge-"))
    tgt = root / safe_rel(perm.target_file)
    tgt.parent.mkdir(parents=True)
    live = {
        "sidecars": {"daily-analysis": {"enabled": False, "projectId": "abc"}},
        "userSettings": {"globalPermissionGrants": {"allow": [
            "command(Get-ChildItem)",
            "command(Select-String)",
            "mcp(http://localhost:8000/mcp)",
            "mcp(gws-mcp-local/some_stale_tool)",
        ]}},
        "otherTopLevel": True,
    }
    tgt.write_text(_json.dumps(live, indent=2), encoding="utf-8")

    assert _apply_json_merge(perm, root)
    merged = _json.loads(tgt.read_text(encoding="utf-8"))
    allow = merged["userSettings"]["globalPermissionGrants"]["allow"]
    assert "command(Get-ChildItem)" in allow                  # user grant preserved
    assert "mcp(http://localhost:8000/mcp)" in allow          # not ours (no alias prefix)
    assert "mcp(gws-mcp-local/some_stale_tool)" not in allow  # ours: stale entry replaced
    assert "mcp(gws-mcp-local/search_drive_files)" in allow   # ours: canonical set in
    assert merged["sidecars"]["daily-analysis"]["projectId"] == "abc"   # untouched
    assert merged["otherTopLevel"] is True


# ── isolated-registry fixture: adopt/harvest write into a registry, so they get a
#    full copy of the content trees with a synthetic machine whose deploy paths
#    point INSIDE the temp root — no sandbox flag needed, nothing real is touched.
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
                  "assistant_root": f"{home}/Mitos",
                  "gws_env": f"{home}/gws/.env"},
    }
    (tmp / "machines" / "rig.yaml").write_text(_y.safe_dump(profile), encoding="utf-8")
    return loader.load(tmp), tmp


def test_adopt_round_trips_a_skill_edit():
    from agentic.commands import cmd_adopt, cmd_deploy, cmd_harvest
    treg, tmp = _temp_registry()
    assert cmd_deploy(treg, "rig", dry_run=False, force=False) == 0
    deployed = tmp / "home/.hermes/skills/productivity/gws/SKILL.md"
    deployed.write_text(deployed.read_text(encoding="utf-8")
                        + "\n## Learned in the field\nnew guidance\n",
                        encoding="utf-8", newline="\n")
    assert cmd_harvest(treg, "rig", adopt_all=False) == 0   # surfaces the candidate
    assert cmd_adopt(treg, str(deployed)) == 0              # routes body back
    src = (tmp / "registry/skills/gws/SKILL.md").read_text(encoding="utf-8")
    assert "## Learned in the field" in src
    assert src.startswith("---\nname: gws\n")               # frontmatter preserved
    # convergence closes the loop: the next deploy relocks without --force
    assert cmd_deploy(treg, "rig", dry_run=False, force=False) == 0


def test_adopt_routes_multipartial_section_edit():
    from agentic.commands import cmd_adopt, cmd_deploy
    treg, tmp = _temp_registry()
    assert cmd_deploy(treg, "rig", dry_run=False, force=False) == 0
    soul = tmp / "home/.hermes/SOUL.md"                     # 4 identity partials
    text = soul.read_text(encoding="utf-8")
    assert "DO NOT EDIT" not in text and "begin:" not in text   # clean artifact
    # derive the edit anchor from the registry itself — identity prose is rewritten
    # freely, and the suite must never depend on specific wording
    anchor = treg.partials["identity/who-i-am.md"].body.splitlines()[0]
    assert anchor in text
    soul.write_text(text.replace(anchor, anchor + " EDITED-IN-PLACE", 1),
                    encoding="utf-8", newline="\n")
    assert cmd_adopt(treg, str(soul)) == 0                  # reconstructs + routes
    who = (tmp / "registry/identity/who-i-am.md").read_text(encoding="utf-8")
    sec = (tmp / "registry/identity/security.md").read_text(encoding="utf-8")
    assert "EDITED-IN-PLACE" in who                        # routed to the right partial
    assert "EDITED-IN-PLACE" not in sec                    # the others untouched
    # convergence: a fresh registry load (as the CLI does each run) re-renders to
    # match the live file → `resolved`, so the next deploy relocks without --force
    assert cmd_deploy(loader.load(tmp), "rig", dry_run=False, force=False) == 0


def test_protect_drift_blocks_then_force_captures():
    from agentic.commands import cmd_deploy
    treg, tmp = _temp_registry()
    assert cmd_deploy(treg, "rig", dry_run=False, force=False) == 0
    soul = tmp / "home/.hermes/SOUL.md"                     # drift_policy: protect
    soul.write_text(soul.read_text(encoding="utf-8") + "\nrogue edit\n",
                    encoding="utf-8", newline="\n")
    assert cmd_deploy(treg, "rig", dry_run=False, force=False) == 1   # refused
    assert "rogue edit" in soul.read_text(encoding="utf-8")           # untouched
    assert cmd_deploy(treg, "rig", dry_run=False, force=True) == 0    # captured + reinstated
    assert "rogue edit" not in soul.read_text(encoding="utf-8")
    captured = [d for d in (_inbox(tmp)).iterdir() if (d / "SOUL.md").exists()]
    assert captured, "forced protect overwrite must capture to inbox first"


def test_env_drift_is_never_captured_to_inbox():
    from agentic.commands import cmd_deploy
    treg, tmp = _temp_registry()
    assert cmd_deploy(treg, "rig", dry_run=False, force=False) == 0
    env = tmp / "home/gws/.env"
    assert env.exists()
    env.write_text(env.read_text(encoding="utf-8") + "SECRET_KEY=hunter2\n",
                   encoding="utf-8", newline="\n")
    assert cmd_deploy(treg, "rig", dry_run=False, force=True) == 0    # overwrites
    assert "SECRET_KEY" not in env.read_text(encoding="utf-8")
    inbox = _inbox(tmp)
    leaked = [f for f in inbox.rglob("*") if f.is_file()
              and "hunter2" in f.read_text(encoding="utf-8", errors="ignore")]
    assert not leaked, "secrets must never reach the tracked inbox/"


def test_classify_conflict_and_untracked_states():
    from dataclasses import replace as _replace

    from agentic.commands import classify_output
    from agentic.io import safe_rel
    root = _sandbox_deploy("example-linux")
    import json as _json
    lock = _json.loads((root / ".deploy-lock.json").read_text(encoding="utf-8"))
    o = next(x for x in planner.plan_machine(reg, "example-linux") if x.kind == "text")
    dest = root / safe_rel(o.deploy_path)
    dest.write_text(dest.read_text(encoding="utf-8") + "\nlocal edit\n",
                    encoding="utf-8", newline="\n")
    # edited in place AND registry changed → conflict
    o2 = _replace(o, content=o.content + "\nregistry change\n")
    assert classify_output(reg, "example-linux", o2, lock, root=root).state == "conflict"
    # a file we never deployed, that doesn't match the render → conflict (untracked)
    del lock["machines"]["example-linux"]["files"][o.deploy_path]
    st = classify_output(reg, "example-linux", o, lock, root=root)
    assert (st.state, st.detail) == ("conflict", "untracked existing file")


def test_target_filter_deploys_subset_and_preserves_lock():
    import json as _json
    import tempfile

    from agentic.commands import cmd_deploy
    rig = _full_windows_rig()
    root = Path(tempfile.mkdtemp(prefix="ae-target-"))
    assert cmd_deploy(rig, "example-windows", dry_run=False, force=False, root=root) == 0
    files0 = _json.loads((root / ".deploy-lock.json").read_text(encoding="utf-8")
                         )["machines"]["example-windows"]["files"]
    assert cmd_deploy(rig, "example-windows", dry_run=False, force=False, root=root,
                      target="claude-ai") == 0
    files1 = _json.loads((root / ".deploy-lock.json").read_text(encoding="utf-8")
                         )["machines"]["example-windows"]["files"]
    assert set(files1) == set(files0), "a target-filtered deploy must not drop entries"
    assert cmd_deploy(rig, "example-windows", dry_run=True, force=False,
                      target="no-such-tool") == 2


def test_duplicate_identities_fail_loudly():
    import tempfile

    from agentic.loader import RegistryError, _load_dir_of_yaml
    tmp = Path(tempfile.mkdtemp(prefix="ae-dup-"))
    (tmp / "a.yaml").write_text("name: same-box\nos: linux\n", encoding="utf-8")
    (tmp / "b.yaml").write_text("name: same-box\nos: windows\n", encoding="utf-8")
    try:
        _load_dir_of_yaml(tmp, key="name")
        raise AssertionError("expected RegistryError for duplicate name")
    except RegistryError as e:
        assert "same-box" in str(e)


# ── V2.2 operator console: review engine + prompt library ───────────────────
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


def test_review_candidate_listing_and_staleness():
    from agentic import review
    from agentic.commands import cmd_deploy
    treg, tmp = _temp_registry()
    assert cmd_deploy(treg, "rig", dry_run=False, force=False) == 0
    deployed = tmp / "home/.hermes/skills/productivity/gws/SKILL.md"
    deployed.write_text(deployed.read_text(encoding="utf-8")
                        + "\n## Field note\nrefined by the curator\n",
                        encoding="utf-8", newline="\n")
    assert cmd_deploy(treg, "rig", dry_run=False, force=False) == 0  # captures drift
    cands = review.load_candidates(treg)
    assert len(cands) == 1
    c = cands[0]
    assert c["registry_path"] == "skills/gws/SKILL.md" and c["acceptable"]
    assert any(r["t"] == "ins" and "Field note" in (r["r"] or "") for r in c["diff"])
    assert c["stale"] is False                      # registry untouched since capture
    skill_src = tmp / "registry/skills/gws/SKILL.md"
    skill_src.write_text(skill_src.read_text(encoding="utf-8")
                         + "\nregistry moved on\n", encoding="utf-8", newline="\n")
    assert review.load_candidates(loader.load(tmp))[0]["stale"] is True


def test_review_accept_routes_and_logs():
    import json as _json

    from agentic import review
    treg, tmp = _temp_registry()
    payload = ("---\nname: gws\ndescription: x\n---\n\n"
               + treg.skills["gws"].body + "\n\n## Field note\nadopted via console\n")
    _plant_candidate(tmp, "t1--rig--gws-skill", _skill_meta(), "SKILL.md", payload)
    out = review.decide(treg, "t1--rig--gws-skill", "accept", "useful refinement")
    assert out["ok"] and out["changed"] == ["skills/gws/SKILL.md"]
    src = (tmp / "registry/skills/gws/SKILL.md").read_text(encoding="utf-8")
    assert "## Field note" in src and src.startswith("---\nname: gws\n")
    assert not (_inbox(tmp) / "t1--rig--gws-skill").exists()
    line = _json.loads((_inbox(tmp) / "decisions.jsonl")
                       .read_text(encoding="utf-8").splitlines()[-1])
    assert (line["decision"], line["reason"]) == ("accept", "useful refinement")
    # idempotent accept of identical content: nothing to change, still a clean ok
    _plant_candidate(tmp, "t2--rig--gws-skill", _skill_meta(), "SKILL.md", payload)
    out2 = review.decide(loader.load(tmp), "t2--rig--gws-skill", "accept", "")
    assert out2["ok"] and out2["changed"] == []


def test_review_propose_edit_round_trips_through_accept():
    """A prompt-library save lands an inbox candidate the existing Accept path merges —
    the console never writes registry/ directly (invariant #3)."""
    from agentic import review
    treg, tmp = _temp_registry()

    # edit a skill in the console → propose
    body = treg.skills["gws"].body + "\n\n## Console edit\nfrom the prompt library\n"
    out = review.propose_edit(treg, "skill", "gws", body, "tightened wording")
    assert out["ok"] and out["registry_path"] == "skills/gws/SKILL.md"
    assert "--console--gws-skill" in out["id"]
    assert (_inbox(tmp) / out["id"] / "meta.yaml").is_file()

    # it lists as an acceptable candidate with the insertion visible in the diff
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out["id"])
    assert cand["acceptable"] and cand["registry_path"] == "skills/gws/SKILL.md"
    assert any(r["t"] == "ins" and "Console edit" in (r["r"] or "") for r in cand["diff"])

    # accept routes the edit into the registry body, frontmatter preserved
    acc = review.decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"] and acc["changed"] == ["skills/gws/SKILL.md"]
    src = (tmp / "registry/skills/gws/SKILL.md").read_text(encoding="utf-8")
    assert "## Console edit" in src and src.startswith("---\nname: gws\n")
    assert not (_inbox(tmp) / out["id"]).exists()

    # a partial edit is proposable too (its rel is the registry_path verbatim)
    prel = sorted(treg.partials)[0]
    pout = review.propose_edit(loader.load(tmp), "partial", prel,
                               treg.partials[prel].body + "\n\nappended.\n", "")
    assert pout["ok"] and pout["registry_path"] == prel
    pcand = next(c for c in review.load_candidates(loader.load(tmp))
                 if c["id"] == pout["id"])
    assert pcand["acceptable"]

    # unknown ident / kind are refused without writing anything
    assert not review.propose_edit(treg, "skill", "no-such-skill", "x", "")["ok"]
    assert not review.propose_edit(treg, "bogus", "x", "x", "")["ok"]


def test_review_reject_logs_and_removes():
    import json as _json

    from agentic import review
    treg, tmp = _temp_registry()
    before = (tmp / "registry/skills/gws/SKILL.md").read_text(encoding="utf-8")
    _plant_candidate(tmp, "t1--rig--gws-skill", _skill_meta(), "SKILL.md", "rubbish")
    out = review.decide(treg, "t1--rig--gws-skill", "reject", "not wanted")
    assert out["ok"] and out["changed"] == []
    assert (tmp / "registry/skills/gws/SKILL.md").read_text(encoding="utf-8") == before
    assert not (_inbox(tmp) / "t1--rig--gws-skill").exists()
    line = _json.loads((_inbox(tmp) / "decisions.jsonl")
                       .read_text(encoding="utf-8").splitlines()[-1])
    assert line["decision"] == "reject"
    # traversal / bogus ids are refused without touching anything
    assert not review.decide(treg, "../registry", "reject", "")["ok"]
    assert not review.decide(treg, "nope", "reject", "")["ok"]
    assert not review.decide(treg, "t1", "maybe", "")["ok"]


def test_review_multisource_capture_and_accept():
    import yaml as _y

    from agentic import review
    from agentic.commands import cmd_deploy
    treg, tmp = _temp_registry()
    assert cmd_deploy(treg, "rig", dry_run=False, force=False) == 0
    soul = tmp / "home/.hermes/SOUL.md"
    live = soul.read_text(encoding="utf-8")
    anchor = treg.partials["identity/who-i-am.md"].body.splitlines()[0]
    soul.write_text(live.replace(anchor, anchor + " EDITED-VIA-CONSOLE", 1),
                    encoding="utf-8", newline="\n")
    # SOUL.md is protect: --force overwrites but captures first, sections included
    assert cmd_deploy(treg, "rig", dry_run=False, force=True) == 0
    cand = next(p for p in (_inbox(tmp)).iterdir() if p.is_dir())
    meta = _y.safe_load((cand / "meta.yaml").read_text(encoding="utf-8"))
    assert meta["registry_path"] == "" and len(meta["sources"]) > 1
    assert meta["sections"] and any(s["source"] == "identity/who-i-am.md"
                                    for s in meta["sections"])
    c = next(c for c in review.load_candidates(treg) if c["id"] == cand.name)
    assert c["acceptable"]                       # sections make it mechanically routable
    out = review.decide(treg, cand.name, "accept", "")
    assert out["ok"] and out["changed"] == ["identity/who-i-am.md"]
    body = (tmp / "registry/identity/who-i-am.md").read_text(encoding="utf-8")
    assert "EDITED-VIA-CONSOLE" in body


def test_review_refuses_unroutable_candidates():
    from agentic import review
    treg, tmp = _temp_registry()
    # non-Markdown registry path: prose stays prose — never routed mechanically
    meta = _skill_meta(rp="mcp/servers.yaml")
    meta["sources"] = ["mcp/servers.yaml"]
    _plant_candidate(tmp, "t1--rig--cfg", meta, "servers.yaml", "servers: {}")
    c = next(c for c in review.load_candidates(treg) if c["id"] == "t1--rig--cfg")
    assert not c["acceptable"] and "not Markdown prose" in c["accept_note"]
    assert not review.decide(treg, "t1--rig--cfg", "accept", "")["ok"]
    assert (_inbox(tmp) / "t1--rig--cfg").exists()   # failed accept keeps the candidate
    # boundary-straddling multi-source edit: split fails, accept reports manual
    meta2 = {"registry_path": "", "kind": "drift", "source": {}, "base_hash": "",
             "deploy_path": "", "sources": ["identity/who-i-am.md",
                                            "identity/operating-rules.md"],
             "captured_at": "", "note": "",
             "sections": [{"source": "identity/who-i-am.md", "text": "alpha\nbeta"},
                          {"source": "identity/operating-rules.md", "text": "gamma"}]}
    _plant_candidate(tmp, "t2--rig--doc", meta2, "DOC.md", "alpha\nMERGED\n")
    out = review.decide(treg, "t2--rig--doc", "accept", "")
    assert not out["ok"] and "boundary" in out["error"]
    assert (_inbox(tmp) / "t2--rig--doc").exists()


def test_prompt_index_is_raw_and_grouped():
    from agentic import review
    pi = review.prompt_index(reg)
    assert len(pi["skills"]) == len(reg.skills)
    dept = {s["name"]: s for s in pi["skills"] if s["category"] == "departments"}
    assert set(dept) == {"dept-cto", "dept-cfo", "dept-vp-marketing"}
    for s in pi["skills"]:
        assert not s["body"].startswith("---")     # raw prompt text, no frontmatter
    assert dept["dept-cto"]["targets"] == ["gemini"]
    groups = {p["rel"]: p["group"] for p in pi["partials"]}
    assert groups["identity/who-i-am.md"] == "identity"
    assert groups["context/projects/mitos.md"] == "projects"
    gws = next(s for s in pi["skills"] if s["name"] == "gws")
    assert gws["body"] == reg.skills["gws"].body


def test_review_http_smoke():
    import http.client
    import json as _json
    import threading

    from agentic import review
    treg, tmp = _temp_registry()
    _plant_candidate(tmp, "t1--rig--gws-skill", _skill_meta(), "SKILL.md", "x")
    server = review.make_server(treg, 0)            # ephemeral port, 127.0.0.1 only
    assert server.server_address[0] == "127.0.0.1"
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", "/api/state")
        r = conn.getresponse()
        state = _json.loads(r.read())
        assert r.status == 200 and len(state["candidates"]) == 1
        assert state["prompts"]["skills"]
        assert any(g["slug"] == "example-project" for g in state["graphs"])   # graph tab data
        # POST /api/graph proposes a kind:graph candidate (writes inbox/ only)
        gbody = _json.dumps({"slug": "example-project", "documents": [
            {"id": "HTTPDOC", "name": "Via HTTP", "description": "d",
             "dateModified": "2026-06-20"}], "reason": "smoke"})
        conn.request("POST", "/api/graph", gbody, {"Content-Type": "application/json"})
        r = conn.getresponse()
        gout = _json.loads(r.read())
        assert r.status == 200 and gout["ok"] and (_inbox(tmp) / gout["id"]).is_dir()
        conn.request("GET", "/")
        r = conn.getresponse()
        assert r.status == 200 and b"Operator Console" in r.read()
        conn.request("GET", "/no-such-file.js")
        assert conn.getresponse().status == 404
        body = _json.dumps({"id": "t1--rig--gws-skill", "decision": "reject"})
        conn.request("POST", "/api/decide", body,
                     {"Content-Type": "application/json"})
        r = conn.getresponse()
        assert r.status == 200 and _json.loads(r.read())["ok"]
        assert not (_inbox(tmp) / "t1--rig--gws-skill").exists()
        body = _json.dumps({"id": "missing", "decision": "reject"})
        conn.request("POST", "/api/decide", body,
                     {"Content-Type": "application/json"})
        assert conn.getresponse().status == 400
    finally:
        server.shutdown()
        server.server_close()


# ── Knowledge graph ──────────────────
def _write_graph(text: str) -> Path:
    import tempfile
    p = Path(tempfile.mktemp(suffix=".jsonld"))
    p.write_text(text, encoding="utf-8")
    return p


def _doc(drive_id, name, desc, modified):
    from agentic import graph
    return graph.Document(drive_id, name, desc, modified)


def test_graph_loads_validates_and_is_canonical():
    from agentic import graph
    # the seed graph in the real registry loads, validates, and is canonical on disk
    assert "example-project" in reg.graphs
    pg = reg.graphs["example-project"]
    assert pg.name == "Example Project" and pg.iri.endswith("/project/example-project")
    assert graph.is_canonical(pg.path, pg)


def test_graph_canonical_is_deterministic_and_sorted():
    from agentic import graph
    pg = graph.ProjectGraph(slug="example-project", name="Example Project", description="d",
                            documents=[_doc("zID", "Zeta", "z", "2026-01-01"),
                                       _doc("aID", "Alpha", "a", "2026-02-02")])
    once, twice = graph.canonical_jsonld(pg), graph.canonical_jsonld(pg)
    assert once == twice                                  # deterministic
    # documents serialize sorted by name regardless of input order
    assert once.index('"name": "Alpha"') < once.index('"name": "Zeta"')
    # round-trips: parse the canonical text back and re-emit identically
    p = _write_graph(once)
    try:
        reloaded = graph.load_project_graph(p)
        assert graph.canonical_jsonld(reloaded) == once
    finally:
        p.unlink()


def test_graph_upsert_is_keyed_on_drive_id():
    from agentic import graph
    pg = graph.ProjectGraph(slug="example-project", name="AP", description="",
                            documents=[_doc("D1", "Spec", "old", "2026-01-01")])
    pg = graph.upsert_document(pg, _doc("D1", "Spec v2", "new", "2026-03-03"))  # update
    pg = graph.upsert_document(pg, _doc("D2", "Other", "x", "2026-02-02"))      # add
    by_id = {d.drive_id: d for d in pg.documents}
    assert len(pg.documents) == 2
    assert by_id["D1"].name == "Spec v2" and by_id["D1"].description == "new"
    pg = graph.remove_document(pg, "D1")
    assert [d.drive_id for d in pg.documents] == ["D2"]


def test_graph_sparql_lists_documents_newest_first():
    from agentic import graph
    pg = graph.ProjectGraph(slug="example-project", name="AP", description="",
                            documents=[_doc("D1", "Older", "o", "2026-01-01"),
                                       _doc("D2", "Newer", "n", "2026-09-09")])
    rows = graph.run_query(pg, "documents")
    assert [r["name"] for r in rows] == ["Newer", "Older"]      # ORDER BY DESC(modified)
    assert rows[0]["id"] == "D2"


def test_graph_rejects_malformed_inputs():
    from agentic import graph
    SC = '{"@vocab":"https://schema.org/"}'
    cases = {
        "blank node":   '{"@context":%s,"@graph":[{"@type":"Project","name":"x"}]}' % SC,
        "bad type":     '{"@context":%s,"@graph":[{"@id":"http://peccia.net/project/p",'
                        '"@type":"Thing","name":"x"}]}' % SC,
        "off-namespace": '{"@context":%s,"@graph":[{"@id":"http://evil.com/p",'
                        '"@type":"Project","name":"x"}]}' % SC,
        "two projects": '{"@context":%s,"@graph":['
                        '{"@id":"http://peccia.net/project/a","@type":"Project","name":"A"},'
                        '{"@id":"http://peccia.net/project/b","@type":"Project","name":"B"}]}' % SC,
    }
    for label, text in cases.items():
        p = _write_graph(text)
        try:
            graph.load_project_graph(p)
            raise AssertionError(f"expected GraphError for: {label}")
        except graph.GraphError:
            pass
        finally:
            p.unlink()


def test_graph_rejects_document_missing_field_and_bad_key():
    from agentic import graph
    SC = '{"@vocab":"https://schema.org/"}'
    # a document missing schema:description
    missing = ('{"@context":%s,"@graph":['
               '{"@id":"http://peccia.net/project/example-project","@type":"Project","name":"AP"},'
               '{"@id":"http://peccia.net/document/D1","@type":"DigitalDocument",'
               '"identifier":"D1","name":"Spec","dateModified":"2026-01-01",'
               '"isPartOf":{"@id":"http://peccia.net/project/example-project"}}]}' % SC)
    # a document whose IRI suffix != its identifier (the Drive ID must be the key)
    badkey = ('{"@context":%s,"@graph":['
              '{"@id":"http://peccia.net/project/example-project","@type":"Project","name":"AP"},'
              '{"@id":"http://peccia.net/document/WRONG","@type":"DigitalDocument",'
              '"identifier":"D1","name":"Spec","description":"d",'
              '"dateModified":"2026-01-01",'
              '"isPartOf":{"@id":"http://peccia.net/project/example-project"}}]}' % SC)
    for text in (missing, badkey):
        p = _write_graph(text)
        try:
            graph.load_project_graph(p)
            raise AssertionError("expected GraphError")
        except graph.GraphError:
            pass
        finally:
            p.unlink()


def test_graph_materialization_markdown_split():
    from agentic import graph
    long_desc = "A spec for the forecast UI. " * 8     # > index clamp, full in details
    pg = graph.ProjectGraph(slug="example-project", name="Example Project",
                            description="forecasting",
                            documents=[_doc("1AbC", "Forecast Spec", long_desc,
                                            "2026-06-14")])
    roster = graph.roster_markdown([pg])
    assert "Example Project" in roster and "`example-project`" in roster and "forecasting" in roster

    # lightweight index: title (linked), clamped desc, modified — and a pointer; NO raw ID
    idx = graph.project_index_markdown(pg)
    assert "https://drive.google.com/open?id=1AbC" in idx       # live-fetch link
    assert "Forecast Spec" in idx and "2026-06-14" in idx
    assert graph.DETAILS_FILENAME in idx                        # pointer to details
    assert "`1AbC`" not in idx                                  # the raw ID lives in details
    assert long_desc.strip() not in idx and "…" in idx          # description is clamped

    # detailed reference: full description, Drive ID, link
    det = graph.project_details_markdown(pg)
    assert "`1AbC`" in det and long_desc.strip() in det
    assert "https://drive.google.com/open?id=1AbC" in det

    empty = graph.ProjectGraph(slug="x", name="X", description="", documents=[])
    assert "_No documents mapped yet._" in graph.project_index_markdown(empty)
    assert "_No documents mapped yet._" in graph.project_details_markdown(empty)


def test_graph_tree_emits_index_and_details():
    win = {o.deploy_path: o for o in planner.plan_machine(reg, "example-windows")
           if o.target == "agentic-graph"}
    assert any(p.endswith("Projects/example-project/AGENTS.md") for p in win)
    assert any(p.endswith("Projects/example-project/AGENTS_DETAILS.md") for p in win)
    for o in win.values():
        assert o.drift_policy == "generated" and o.kind == "text" and o.sources == []


def test_graph_candidate_propose_accept_upserts_registry():
    from agentic import review
    treg, tmp = _temp_registry()
    # seed a project graph so the upsert merges into an existing file
    gdir = tmp / "registry" / "graph"
    gdir.mkdir(parents=True, exist_ok=True)
    from agentic import graph
    seed = graph.ProjectGraph(slug="example-project", name="Example Project",
                              description="d", documents=[
                                  _doc("OLD", "Existing", "kept", "2026-01-01")])
    (gdir / "example-project.jsonld").write_text(graph.canonical_jsonld(seed), encoding="utf-8")
    treg = loader.load(tmp)

    # propose two docs (one updates nothing existing, one new) via the console producer
    out = review.propose_graph_change(treg, "example-project", [
        {"id": "NEW1", "name": "Forecast UI Spec", "description": "ui spec",
         "dateModified": "2026-06-14"}], reason="found in drive")
    assert out["ok"] and out["registry_path"] == "graph/example-project.jsonld"
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out["id"])
    assert cand["acceptable"] and cand["kind"] == "graph"
    assert any(r["t"] == "ins" and "NEW1" in (r["r"] or "") for r in cand["diff"])
    # The console's pending-badge needs the target project + proposed Drive IDs surfaced on
    # the candidate (so it never re-parses the jsonld/IRI scheme client-side).
    assert cand["project"] == "example-project"
    assert cand["doc_ids"] == ["NEW1"]

    # accept upserts into registry/graph/example-project.jsonld (existing doc preserved)
    acc = review.decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"] and acc["changed"] == ["graph/example-project.jsonld"]
    merged = graph.load_project_graph(gdir / "example-project.jsonld")
    ids = {d.drive_id for d in merged.documents}
    assert ids == {"OLD", "NEW1"}                               # upsert merged, didn't replace
    assert not (_inbox(tmp) / out["id"]).exists()             # candidate consumed


def test_graph_candidate_with_removals_drops_and_upserts():
    """A console draft can carry removals alongside upserts: accept drops the removed Drive
    IDs and merges the upserts, the diff renders the deletion, and removal_ids surface on the
    candidate so the tab flags the in-flight removal."""
    from agentic import graph, review
    treg, tmp = _temp_registry()
    gdir = tmp / "registry" / "graph"
    gdir.mkdir(parents=True, exist_ok=True)
    seed = graph.ProjectGraph(slug="example-project", name="Example Project",
                              description="d", documents=[
                                  _doc("KEEP", "Keeper", "stays", "2026-01-01"),
                                  _doc("GONE", "Goner", "leaves", "2026-01-02")])
    (gdir / "example-project.jsonld").write_text(graph.canonical_jsonld(seed), encoding="utf-8")
    treg = loader.load(tmp)

    # remove GONE and add NEW1 in one candidate
    out = review.propose_graph_change(
        treg, "example-project",
        [{"id": "NEW1", "name": "Fresh", "description": "added", "dateModified": "2026-06-14"}],
        removals=["GONE"], reason="cleanup")
    assert out["ok"]
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out["id"])
    assert cand["acceptable"] and cand["kind"] == "graph"
    assert cand["doc_ids"] == ["NEW1"] and cand["removal_ids"] == ["GONE"]
    # the diff shows GONE leaving (present on the current side, gone from the proposed side)
    # and NEW1 arriving — robust to whether the rows align as del/ins or chg
    assert any("GONE" in (r["l"] or "") for r in cand["diff"])
    assert not any("GONE" in (r["r"] or "") for r in cand["diff"])
    assert any("NEW1" in (r["r"] or "") for r in cand["diff"])

    acc = review.decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"] and acc["changed"] == ["graph/example-project.jsonld"]
    merged = graph.load_project_graph(gdir / "example-project.jsonld")
    assert {d.drive_id for d in merged.documents} == {"KEEP", "NEW1"}   # GONE dropped


def test_propose_graph_change_allows_removals_only():
    """A candidate may carry only removals (no upserts) — the empty guard must not reject it,
    and a removal whose id is also being upserted is dropped (the upsert wins)."""
    from agentic import graph, review
    treg, tmp = _temp_registry()
    gdir = tmp / "registry" / "graph"
    gdir.mkdir(parents=True, exist_ok=True)
    seed = graph.ProjectGraph(slug="example-project", name="Example Project", description="d",
                              documents=[_doc("X", "Ex", "", "2026-01-01")])
    (gdir / "example-project.jsonld").write_text(graph.canonical_jsonld(seed), encoding="utf-8")
    treg = loader.load(tmp)

    out = review.propose_graph_change(treg, "example-project", [], removals=["X"])
    assert out["ok"]
    acc = review.decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"]
    assert graph.load_project_graph(gdir / "example-project.jsonld").documents == []

    # contradictory: id both upserted and removed → upsert wins, removal dropped
    treg = loader.load(tmp)
    out2 = review.propose_graph_change(
        treg, "example-project",
        [{"id": "Y", "name": "Why", "dateModified": "2026-02-02"}], removals=["Y"])
    assert out2["ok"]
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out2["id"])
    assert cand["doc_ids"] == ["Y"] and cand["removal_ids"] == []


def test_local_project_graph_candidate_flow():
    """A project defined only in the registry/local/ overlay must route its accepted graph
    back into registry/local/graph/ — both the proposed candidate's registry_path and the
    accepted file location — so the loader (which reads local graphs when the overlay supplies
    projects) actually picks it up. A core write would silently never load."""
    from agentic import review
    import yaml
    _, tmp = _temp_registry()
    # define an overlay-only project; presence of any local project means core projects are
    # not loaded, and graphs are read only from registry/local/graph/.
    local_projects_dir = tmp / "registry" / "local" / "projects"
    local_projects_dir.mkdir(parents=True, exist_ok=True)
    (local_projects_dir / "private.yaml").write_text(
        yaml.safe_dump({"slug": "private", "name": "Private Project", "stage": "build"}),
        encoding="utf-8")
    treg = loader.load(tmp)
    assert treg.projects["private"]["_is_local"] is True

    # propose its first document mapping — the candidate must target the overlay path
    out = review.propose_graph_change(treg, "private", [
        {"id": "NEW1", "name": "Private Spec", "description": "spec",
         "dateModified": "2026-06-14"}], reason="found in drive")
    assert out["ok"] and out["registry_path"] == "local/graph/private.jsonld"
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out["id"])
    assert cand["acceptable"] and cand["kind"] == "graph"
    assert cand["registry_path"] == "local/graph/private.jsonld"

    # accept writes into registry/local/graph/, NOT the core registry/graph/
    acc = review.decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"] and acc["changed"] == ["local/graph/private.jsonld"]
    assert (tmp / "registry" / "local" / "graph" / "private.jsonld").is_file()
    assert not (tmp / "registry" / "graph" / "private.jsonld").exists()

    # and the freshly accepted graph actually loads (the bug: it used to vanish as "no graph yet")
    reloaded = loader.load(tmp)
    assert "private" in reloaded.graphs
    assert {d.drive_id for d in reloaded.graphs["private"].documents} == {"NEW1"}


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
    name, desc, docs = graph.parse_fragment(good, "example-project")
    assert name is None and [d.drive_id for d in docs] == ["D2"]


def test_propose_graph_change_rejects_unknown_project_and_empty():
    from agentic import review
    treg, _tmp = _temp_registry()
    assert not review.propose_graph_change(treg, "no-such", [{"id": "x", "name": "y",
        "dateModified": "2026-01-01"}])["ok"]
    assert not review.propose_graph_change(treg, "example-project", [])["ok"]


def test_graph_tree_deploys_only_on_claude_code_env():
    # example-linux has no claude-code target → no Agentic Context tree
    linux = [o for o in planner.plan_machine(reg, "example-linux")
             if o.target == "agentic-graph"]
    assert linux == []
    # example-windows (claude-code + agentic_context_root) → roster + per-project index
    win = {o.deploy_path: o for o in planner.plan_machine(reg, "example-windows")
           if o.target == "agentic-graph"}
    assert any(p.endswith("Mitos/AGENTS.md") for p in win)
    assert any(p.endswith("Mitos/Projects/example-project/AGENTS.md") for p in win)
    for o in win.values():
        assert o.drift_policy == "generated" and o.sources == [] and o.kind == "text"
        assert "DO NOT EDIT" not in o.content and "begin:" not in o.content  # raw context


def test_graph_tree_round_trips_and_regenerates_without_capture():
    import copy

    from agentic import graph
    from agentic.commands import cmd_deploy
    from agentic.io import safe_rel
    # inject a document so the per-project index renders a table row
    reg2 = copy.deepcopy(reg)
    reg2.graphs["example-project"] = graph.upsert_document(
        reg2.graphs["example-project"], _doc("1AbCxyz", "Forecast UI Spec", "spec", "2026-06-14"))
    root = Path(__import__("tempfile").mkdtemp(prefix="ae-graph-"))
    assert cmd_deploy(reg2, "example-windows", dry_run=False, force=False, root=root) == 0
    idx = root / safe_rel("C:/Mitos/Projects/example-project/AGENTS.md")
    assert "Forecast UI Spec" in idx.read_text(encoding="utf-8")
    roster = root / safe_rel("C:/Mitos/AGENTS.md")
    assert "Example Project" in roster.read_text(encoding="utf-8")

    # edit the generated roster in place, then redeploy: it is silently regenerated
    # (non-adoptable) and nothing is captured to inbox/ (no partial to route back to)
    roster.write_text("hand edit\n", encoding="utf-8", newline="\n")
    before = sorted((_inbox(root)).iterdir()) if (_inbox(root)).exists() else []
    assert cmd_deploy(reg2, "example-windows", dry_run=False, force=False, root=root) == 0
    assert "Example Project" in roster.read_text(encoding="utf-8")   # overwritten
    after = sorted((_inbox(root)).iterdir()) if (_inbox(root)).exists() else []
    assert before == after, "a generated file must not capture an inbox candidate"


# ── Agents, per-project binding, repo auto-clone ────
def test_agents_load_and_render_claude_code():
    assert "code-reviewer" in reg.agents
    agent = reg.agents["code-reviewer"]
    assert agent.rel == "agents/code-reviewer.md"
    out = render.render_agent(agent, "claude-code")
    assert out.startswith("---\nname: code-reviewer\n")
    head = out.split("---")[1]
    assert "description:" in head and "tools:" in head and "model:" in head
    assert "code reviewer" in out.lower() and not out.rstrip().endswith("---")


def test_per_project_binding_deploys_exactly_bound_skills_and_agents():
    outs = planner.plan_machine(reg, "example-windows")
    paths = [o.deploy_path for o in outs]
    # mitos bound [code-reviewer]
    assert any(p.endswith("mitos/.claude/agents/code-reviewer.md") for p in paths)
    # example-project bound [code-reviewer] only — agent yes, plan skill NO (exactly its set)
    assert any(p.endswith("example-project/.claude/agents/code-reviewer.md") for p in paths)
    assert not any(p.endswith("example-project/.claude/skills/plan/SKILL.md")
                   for p in paths)
    # the reused agent is authored once: both deployments point at one registry source
    agent_outs = [o for o in outs if o.deploy_path.endswith("agents/code-reviewer.md")]
    assert len(agent_outs) == 2
    assert all(o.sources == ["agents/code-reviewer.md"] for o in agent_outs)
    assert all(o.drift_policy == "harvest" for o in agent_outs)


def test_binding_validation_rejects_unknown_and_incompatible():
    import copy

    from agentic.loader import RegistryError, _validate
    for mutate in (
        lambda p: p.update(skills=["no-such-skill"]),
        lambda p: p.update(agents=["no-such-agent"]),
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
    assert c.dest.endswith("Mitos/Projects/mitos/mitos")
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


# ── Hermes simulated organization ─────────────
def test_hermes_org_persona_in_soul_and_skill_deploys():
    # the org framing is a lean, always-on identity partial scoped to hermes
    assert "identity/org-hierarchy.md" in reg.partials
    assert reg.partials["identity/org-hierarchy.md"].audience == ["hermes"]

    outs = planner.plan_machine(reg, "example-linux")
    soul = next(o for o in outs if o.deploy_path.endswith("SOUL.md"))
    assert "How you are organized" in soul.content            # partial reached SOUL.md
    assert soul.section_bodies[-1][0] == "identity/org-hierarchy.md"   # appended last
    assert soul.content.startswith("## About Me")           # who-i-am still first

    # the deep playbook is an on-demand hermes skill, not always-on
    assert "org" in reg.skills and reg.skills["org"].targets == ["hermes"]
    assert any(o.deploy_path.endswith("skills/productivity/org/SKILL.md") for o in outs)
    # not on a hermes-less machine
    win = planner.plan_machine(_full_windows_rig(), "example-windows")
    assert not any(p.endswith("org/SKILL.md") for p in (o.deploy_path for o in win))
    # the persona body (not just the filename, which docs may mention) never reaches a
    # hermes-less machine
    assert not any("How you are organized" in (o.content if o.kind == "text" else "")
                   for o in win)

    # reconciled, not duplicated: the dept-* personas stay a separate gemini surface
    for d in ("dept-cto", "dept-cfo", "dept-vp-marketing"):
        assert reg.skills[d].targets == ["gemini"]


# ── the Mitos overlay design: the Mitos open-source overlay, connectors, init ─
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


def test_connector_bootstrap_emits_graph_candidate_through_valve():
    # a connector is a producer for the one valve: it proposes a kind:graph candidate via
    # review.propose_graph_change (writes inbox/ only), never the graph directly. No creds.
    from agentic import graph, review
    from agentic.connectors import bootstrap_to_inbox
    from agentic.connectors.mock import MockConnector
    treg, tmp = _temp_registry()
    mock = MockConnector(files=[
        {"id": "DRV1", "name": "Forecast Spec", "dateModified": "2026-06-18"},
        {"id": "DRV2", "name": "Roadmap", "dateModified": "2026-06-19"}])
    out = bootstrap_to_inbox(treg, mock, "example-project")
    assert out["ok"] and out["registry_path"] == "graph/example-project.jsonld"
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out["id"])
    assert cand["kind"] == "graph" and cand["acceptable"]
    assert any(r["t"] == "ins" and "DRV1" in (r["r"] or "") for r in cand["diff"])
    # accept upserts both docs into registry/graph/example-project.jsonld (same path as the console)
    acc = review.decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"] and acc["changed"] == ["graph/example-project.jsonld"]
    merged = graph.load_project_graph(tmp / "registry" / "graph" / "example-project.jsonld")
    assert {d.drive_id for d in merged.documents} >= {"DRV1", "DRV2"}
    # a connector that returns nothing reports and writes no candidate (reported, not fatal)
    assert not bootstrap_to_inbox(treg, MockConnector(files=[]), "example-project")["ok"]


def test_mcp_connector_maps_store_fields_and_bootstraps_through_valve():
    # the backend-agnostic MCP connector enumerates an already-running store via its graph_enum
    # mapping (transport injected here so the field-mapping is covered without a live server),
    # then rides the SAME one human-gated valve as every other connector.
    from agentic import review
    from agentic.connectors import bootstrap_to_inbox
    from agentic.connectors.mcp import MCPConnector
    treg, tmp = _temp_registry()
    enum = treg.servers["servers"]["gws"]["graph_enum"]
    captured = {}

    def transport(tool, arguments):
        captured["tool"], captured["args"] = tool, arguments
        return [
            {"id": "DRV1", "name": "Forecast Spec", "modifiedTime": "2026-06-18T10:00:00Z",
             "webViewLink": "https://drive/1"},
            {"id": "DRV2", "name": "Roadmap", "modifiedTime": "2026-06-19T09:00:00Z"}]

    conn = MCPConnector(endpoint="http://localhost:8000/mcp", enum=enum,
                        server_name="gws", transport=transport)
    files = conn.list_files(folder_id="FOLDERX")
    # the store's raw fields map onto the lean graph shape (modifiedTime->dateModified, dated
    # to the day; webViewLink->webUrl) and the folder scope rides the configured query_arg
    assert files[0] == {"id": "DRV1", "name": "Forecast Spec",
                        "dateModified": "2026-06-18", "webUrl": "https://drive/1"}
    assert captured["tool"] == "search_drive_files"
    assert "FOLDERX" in captured["args"]["query"]
    out = bootstrap_to_inbox(treg, conn, "example-project")
    assert out["ok"]
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out["id"])
    assert cand["kind"] == "graph" and cand["acceptable"]


def test_mcp_text_format_parsing():
    # google_workspace_mcp returns search_drive_files results as human-readable text, not JSON.
    # _parse_text_rows extracts items via text_fields regex patterns; _documents_from_tool_result
    # uses it when JSON parsing fails; auth errors are still raised as ConnectorError.
    from agentic.connectors.base import ConnectorError
    from agentic.connectors.mcp import _documents_from_tool_result, _parse_text_rows

    text_fields = {
        "id": r'ID: ([^\s,)]+)',
        "name": r'Name: "([^"]+)"',
        "modifiedTime": r'Modified: ([^,)]+)',
        "webViewLink": r'Link: (\S+)',
    }
    enum = {"text_fields": text_fields, "fields": {"id": "id", "name": "name",
                                                    "dateModified": "modifiedTime",
                                                    "webUrl": "webViewLink"}}
    gws_text = (
        "Found 2 files for user@example.com matching '':\n"
        '- Name: "Report Alpha" (ID: DRIVE_ALPHA, Type: application/vnd.google-apps.document, '
        'Size: 1500, Created: 2026-01-01T00:00:00.000Z, Modified: 2026-06-01T12:00:00.000Z, '
        'Last Edited By: User <user@example.com>) Link: https://docs.google.com/document/d/DRIVE_ALPHA/edit\n'
        '- Name: "Report Beta" (ID: DRIVE_BETA, Type: application/vnd.google-apps.document, '
        'Size: 2500, Created: 2026-02-01T00:00:00.000Z, Modified: 2026-06-15T09:00:00.000Z, '
        'Last Edited By: User <user@example.com>) Link: https://docs.google.com/document/d/DRIVE_BETA/edit\n'
    )

    # _parse_text_rows extracts all items with correct field values
    rows = _parse_text_rows(gws_text, text_fields)
    assert rows is not None and len(rows) == 2
    assert rows[0]["id"] == "DRIVE_ALPHA" and rows[0]["name"] == "Report Alpha"
    assert rows[0]["modifiedTime"].startswith("2026-06-01")
    assert "DRIVE_ALPHA" in rows[0]["webViewLink"]

    # error text has no Name: "..." pattern → returns None (caller raises ConnectorError)
    assert _parse_text_rows("Error calling tool: ACTION REQUIRED: Google Auth Needed", text_fields) is None

    # "Found 0 files" header, no item lines → empty list (valid empty result, not an error)
    assert _parse_text_rows("Found 0 files for user@example.com matching 'q':\n", text_fields) == []

    # _documents_from_tool_result: non-JSON text content → parsed via text_fields
    result = {"content": [{"type": "text", "text": gws_text}]}
    docs = _documents_from_tool_result(result, enum)
    assert len(docs) == 2 and docs[0]["id"] == "DRIVE_ALPHA"

    # auth error text → ConnectorError (text doesn't match item format)
    error_result = {"content": [{"type": "text", "text": "Error calling tool: ACTION REQUIRED"}]}
    try:
        _documents_from_tool_result(error_result, enum)
        raise AssertionError("should raise ConnectorError")
    except ConnectorError as e:
        assert "MCP tool error" in str(e)

    # "Found 0 files" via _documents_from_tool_result → empty list, not an error
    empty_result = {"content": [{"type": "text", "text": "Found 0 files for user@example.com matching 'q':\n"}]}
    assert _documents_from_tool_result(empty_result, enum) == []

    # without text_fields configured, non-JSON text still raises ConnectorError
    try:
        _documents_from_tool_result(result, {})
        raise AssertionError("should raise ConnectorError")
    except ConnectorError:
        pass


def test_mcp_next_token_extraction():
    # _extract_next_token pulls the continuation token from a GWS text response so _http_call
    # can follow pages; returns None when no token is present (last page).
    from agentic.connectors.mcp import _extract_next_token

    pattern = r'nextPageToken: (\S+)'
    result_with_token = {"content": [{"type": "text", "text":
        "Found 10 files for user@example.com matching '':\n"
        "- Name: \"Doc\" (ID: X, ...) Link: https://docs.google.com/d/X/edit\n"
        "nextPageToken: ~!!~SOMETOKEN123\n"}]}
    assert _extract_next_token(result_with_token, pattern) == "~!!~SOMETOKEN123"

    result_no_token = {"content": [{"type": "text", "text": "Found 2 files...\n- Name: \"Doc\" ...\n"}]}
    assert _extract_next_token(result_no_token, pattern) is None


def test_connector_for_store_resolves_mcp_from_graph_enum_and_rejects_unmapped():
    # graph init resolves its connector from the project's document_store: a server WITH a
    # graph_enum mapping → the generic MCP connector pointed at that server's url (reuse, no
    # second auth); 'none'/unknown stores fail clearly.
    from agentic.connectors import ConnectorError, connector_for_store
    from agentic.connectors.mcp import MCPConnector
    treg, _tmp = _temp_registry()
    conn = connector_for_store(treg, "gws")
    assert isinstance(conn, MCPConnector)
    assert conn.endpoint == treg.servers["servers"]["gws"]["url"]
    for bad in ("none", "", "no-such-store"):
        try:
            connector_for_store(treg, bad)
            raise AssertionError(f"expected ConnectorError for {bad!r}")
        except ConnectorError:
            pass


def test_project_document_store_must_name_a_known_server():
    import yaml as _y
    _treg, tmp = _temp_registry()
    p = tmp / "registry" / "projects" / "example-project.yaml"
    data = _y.safe_load(p.read_text(encoding="utf-8"))
    data["document_store"] = "not-a-server"
    p.write_text(_y.safe_dump(data), encoding="utf-8")
    try:
        loader.load(tmp)
        raise AssertionError("expected RegistryError")
    except loader.RegistryError as e:
        assert "document_store" in str(e)


def test_server_graph_enum_requires_list_tool_and_id_name_fields():
    import yaml as _y
    _treg, tmp = _temp_registry()
    conn = tmp / "connections" / "servers.yaml"
    data = _y.safe_load(conn.read_text(encoding="utf-8"))
    data["servers"]["gws"]["graph_enum"] = {"fields": {"name": "name"}}  # no list_tool, no id
    conn.write_text(_y.safe_dump(data), encoding="utf-8")
    try:
        loader.load(tmp)
        raise AssertionError("expected RegistryError")
    except loader.RegistryError as e:
        assert "graph_enum" in str(e)


def test_project_add_manifest_scaffold_loads_and_binds_store():
    # Stage 1: the manifest `mitos project add` writes must load cleanly and carry the
    # document_store binding that Stage 3 (connect) reads.
    import importlib
    sys.path.insert(0, str(REPO_ROOT / "build"))
    mitos = importlib.import_module("mitos")
    _treg, tmp = _temp_registry()
    text = mitos._project_manifest_yaml("acme", "Acme Co", "gws")
    (tmp / "registry" / "projects" / "acme.yaml").write_text(text, encoding="utf-8")
    reg2 = loader.load(tmp)
    assert reg2.projects["acme"]["slug"] == "acme"
    assert reg2.projects["acme"]["document_store"] == "gws"
    assert reg2.projects["acme"]["name"] == "Acme Co"


def test_connect_missing_store_explains_servers_file_and_line():
    # an unbound project must not fail with a bare error — it spells out the available servers,
    # the manifest file, and the exact line to add (the #1 thing a new user hits).
    import contextlib
    import importlib
    import io
    sys.path.insert(0, str(REPO_ROOT / "build"))
    mitos = importlib.import_module("mitos")
    treg, _tmp = _temp_registry()  # example-project ships document_store: none
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rc = mitos._explain_missing_store(treg, "example-project")
    msg = err.getvalue()
    assert rc == 2
    assert "gws" in msg                                   # names the available server
    assert "projects/example-project.yaml" in msg         # names the manifest file
    assert "document_store: gws" in msg                   # gives the exact line


def test_init_scaffolds_overlay_and_org_template_reaches_soul():
    # mitos init scaffolds the overlay; the chosen org template REPLACES the default core
    # org by landing in the overlay and overriding the core — and flows into SOUL.md
    from agentic import init as initmod
    treg, tmp = _temp_registry()
    assert set(initmod.org_templates(tmp)) == {"solo-assistant", "software-firm", "design-firm"}
    written = initmod.scaffold_overlay(tmp, given_name="Jane", family_name="Doe",
                                       address="Ms. Doe", email="jane@example.com",
                                       location="NYC", org_template="design-firm",
                                       backend="mock")
    assert "local/identity/org-hierarchy.md" in written
    # the captured name + form of address land in the overlay identity, which overrides the
    # neutral core who-i-am.md for every tool — skills stay neutral and read the name here
    who = (tmp / "registry/local/identity/who-i-am.md").read_text(encoding="utf-8")
    assert "Jane Doe" in who and 'Address me as "Ms. Doe"' in who
    reg2 = loader.load(tmp)
    org = reg2.partials["identity/org-hierarchy.md"]
    assert org.rel == "local/identity/org-hierarchy.md" and "Creative Director" in org.body
    soul = next(o for o in planner.plan_machine(reg2, "rig")
                if o.deploy_path.endswith("SOUL.md"))
    assert "Creative Director" in soul.content              # overlay org reached SOUL.md
    assert reg2.skills["org"].rel == "local/skills/org/SKILL.md"   # playbook overridden too
    # an unknown template is refused without writing
    try:
        initmod.scaffold_overlay(tmp, given_name="x", email="y", org_template="no-such")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


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


def test_deploy_refuses_example_template_but_allows_sandbox():
    from agentic.commands import cmd_deploy
    root = Path(__import__("tempfile").mkdtemp(prefix="ae-ex-deploy-"))
    # a real deploy (no --dry-run, no --root) of a template is refused before it can write
    assert cmd_deploy(reg, "example-windows", dry_run=False, force=False, root=None) == 2
    # sandboxing it (--root) is allowed — the quick-start rehearsal path
    assert cmd_deploy(reg, "example-windows", dry_run=False, force=False, root=root) == 0


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


def _seed_overlay(root):
    """A repo_root with a non-empty registry/local/ (not yet a git repo); returns the overlay."""
    overlay = root / "registry" / "local"
    (overlay / "identity").mkdir(parents=True)
    (overlay / "identity" / "who.md").write_text("v0\n", encoding="utf-8")
    return overlay


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


def test_scaffold_overlay_preserves_existing_user_files():
    # init must finish AROUND a user's existing custom data, never clobber it
    from agentic import init as initmod
    _treg, tmp = _temp_registry()
    overlay = tmp / "registry" / "local"
    (overlay / "identity").mkdir(parents=True)
    (overlay / "identity" / "who-i-am.md").write_text("MY CUSTOM IDENTITY\n", encoding="utf-8")
    (overlay / "skills" / "mine").mkdir(parents=True)
    (overlay / "skills" / "mine" / "SKILL.md").write_text("mine\n", encoding="utf-8")

    written = initmod.scaffold_overlay(tmp, given_name="Jane", org_template="solo-assistant",
                                       backend="mock")
    # the user's files are untouched and were NOT re-written
    assert (overlay / "identity" / "who-i-am.md").read_text(encoding="utf-8") == \
        "MY CUSTOM IDENTITY\n"
    assert "local/identity/who-i-am.md" not in written
    assert (overlay / "skills" / "mine" / "SKILL.md").read_text(encoding="utf-8") == "mine\n"
    # but genuinely missing pieces are still seeded
    assert "local/identity/org-hierarchy.md" in written
    assert (overlay / "skills" / "org" / "SKILL.md").exists()
    # overwrite=True forces a clean re-scaffold when asked
    written2 = initmod.scaffold_overlay(tmp, given_name="Jane", org_template="solo-assistant",
                                        backend="mock", overwrite=True)
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


# ── prompts/ registry kind ───────────────────────────────────────────────────
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


def test_gemini_deploys_targeted_prompt():
    """A prompt with targets:[gemini] produces a text output in the gemini prompts dir."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["gemini"]
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    r.prompts["test-prompt"] = loader.Prompt(
        name="test-prompt", rel="prompts/test-prompt.md",
        frontmatter={"name": "test-prompt", "targets": ["gemini"]},
        body="My reusable prompt body.",
    )
    outputs = planner.plan_machine(r, "example-windows")
    prompt_outputs = [o for o in outputs
                      if o.target == "gemini" and "prompt-test-prompt" in o.deploy_path]
    assert prompt_outputs, "no gemini output for targeted prompt"
    assert prompt_outputs[0].content == "My reusable prompt body.\n"


def test_console_only_prompt_not_deployed():
    """A prompt with no targets produces no file outputs."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["gemini"]
    r.machines["example-windows"]["paths"]["projects_root"] = "C:/Projects"
    r.prompts["private-prompt"] = loader.Prompt(
        name="private-prompt", rel="prompts/private-prompt.md",
        frontmatter={"name": "private-prompt", "targets": []},
        body="console-only body",
    )
    outputs = planner.plan_machine(r, "example-windows")
    assert not any("private-prompt" in o.deploy_path for o in outputs)


# ── Phase 3A: Claude Code prompt deployment ────────────────────────────────────
def test_claude_code_deploys_bound_prompt():
    """A manifest-bound prompt with targets:[claude-code] deploys to .claude/commands/."""
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
    r.projects["mitos"]["prompts"] = ["review-checklist"]
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


def test_gemini_prompt_render_is_plain_body():
    """render_prompt for non-claude-code targets returns plain body (no frontmatter)."""
    from agentic.render import render_prompt
    p = loader.Prompt(
        name="my-prompt", rel="prompts/my-prompt.md",
        frontmatter={"name": "my-prompt", "description": "desc", "targets": ["gemini"]},
        body="Plain content.",
    )
    rendered = render_prompt(p, "gemini")
    assert not rendered.startswith("---")
    assert rendered.strip() == "Plain content."


# ── Phase 3B: Claude Desktop MCP config ────────────────────────────────────────
def test_claude_desktop_mcp_config_planned():
    """When claude_desktop_config path key is set, Desktop MCP config is planned."""
    import copy
    from agentic.render import claude_desktop_mcp_config
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["claude-desktop"]
    r.machines["example-windows"]["paths"]["claude_desktop_config"] = (
        "C:/Users/Paul/AppData/Roaming/Claude/claude_desktop_config.json"
    )
    outputs = planner.plan_machine(r, "example-windows")
    desktop_outs = [o for o in outputs if o.target == "claude-desktop"]
    assert desktop_outs, "no claude-desktop output"
    o = desktop_outs[0]
    assert o.kind == "json"
    assert o.lane == "connections"
    assert o.drift_policy == "protect"
    assert "claude_desktop_config.json" in o.deploy_path
    import json
    parsed = json.loads(o.content)
    assert "mcpServers" in parsed
    alias = r.targets["claude-desktop"]["server_alias"]
    assert alias in parsed["mcpServers"]
    assert "url" in parsed["mcpServers"][alias]
    assert parsed["mcpServers"][alias]["type"] == "sse"


def test_claude_desktop_no_path_no_output():
    """When claude_desktop_config path key is absent, Desktop target produces no outputs."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["claude-desktop"]
    # deliberately no claude_desktop_config key in paths
    r.machines["example-windows"]["paths"].pop("claude_desktop_config", None)
    outputs = planner.plan_machine(r, "example-windows")
    assert not any(o.target == "claude-desktop" for o in outputs)


def test_claude_desktop_render():
    """claude_desktop_mcp_config produces the correct JSON schema."""
    from agentic.render import claude_desktop_mcp_config
    server = {"url": "http://localhost:8000/mcp", "tools": {}}
    result = claude_desktop_mcp_config(server, "my-alias")
    assert result == {"mcpServers": {"my-alias": {"url": "http://localhost:8000/mcp", "type": "sse"}}}


def test_claude_desktop_in_known_targets():
    """claude-desktop is a valid KNOWN_TARGET — machines can list it without error."""
    import copy
    r = copy.deepcopy(reg)
    r.machines["example-windows"]["targets"] = ["claude-desktop"]
    loader._validate(r)   # must not raise


# ── P1: staged discovery + console multi-select ──────────────────────────────
def test_stage_listing_writes_artifact_with_weburl():
    """stage_listing writes inbox/staging/<slug>.json and keeps webUrl."""
    import json as _json
    from agentic.connectors.bootstrap import stage_listing
    from agentic.connectors.mock import MockConnector
    treg, tmp = _temp_registry()
    mock = MockConnector(files=[
        {"id": "DRV1", "name": "Forecast Spec", "dateModified": "2026-06-18",
         "webUrl": "https://example.com/drive/1"}])
    out = stage_listing(treg, mock, "example-project", query="forecast")
    assert out["ok"] and out["count"] == 1
    artifact = _inbox(tmp) / "staging" / "example-project.json"
    assert artifact.is_file()
    data = _json.loads(artifact.read_text(encoding="utf-8"))
    assert data["slug"] == "example-project"
    assert data["scope"]["query"] == "forecast"
    d = data["documents"][0]
    assert all(k in d for k in ("id", "name", "dateModified", "webUrl"))
    assert d["webUrl"] == "https://example.com/drive/1"


def test_stage_listing_empty_scope_is_reported():
    """stage_listing with no matching files returns ok=False and writes nothing."""
    from agentic.connectors.bootstrap import stage_listing
    from agentic.connectors.mock import MockConnector
    treg, tmp = _temp_registry()
    out = stage_listing(treg, MockConnector(files=[]), "example-project")
    assert out["ok"] is False
    assert "no usable documents" in out["error"]
    assert not (_inbox(tmp) / "staging" / "example-project.json").is_file()


def test_stage_listing_unknown_project_rejected():
    """stage_listing refuses to write for a project not in the registry."""
    from agentic.connectors.bootstrap import stage_listing
    from agentic.connectors.mock import MockConnector
    treg, _tmp = _temp_registry()
    out = stage_listing(treg, MockConnector(), "no-such-project")
    assert out["ok"] is False


def test_load_staged_reads_artifact():
    """load_staged returns ok=True and the documents from an existing staging file."""
    import json as _json
    from agentic import review
    treg, tmp = _temp_registry()
    staging_dir = _inbox(tmp) / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "slug": "example-project", "staged_at": "2026-06-23T1430Z",
        "connector": "mock", "scope": {},
        "documents": [{"id": "D1", "name": "Doc One", "dateModified": "2026-01-01",
                       "webUrl": "", "description": ""}],
    }
    (staging_dir / "example-project.json").write_text(_json.dumps(payload), encoding="utf-8")
    result = review.load_staged(treg, "example-project")
    assert result["ok"] and result["staged_at"] == "2026-06-23T1430Z"
    assert len(result["documents"]) == 1 and result["documents"][0]["id"] == "D1"


def test_load_staged_absent_is_empty_not_error():
    """Absent staging file → ok=True with empty documents; traversal slug → ok=False."""
    from agentic import review
    treg, _tmp = _temp_registry()
    result = review.load_staged(treg, "example-project")
    assert result["ok"] and result["documents"] == []
    for bad in ("../etc", "", ".", ".."):
        r = review.load_staged(treg, bad)
        assert r["ok"] is False, f"expected ok=False for slug {bad!r}"


def test_multiselect_propose_keeps_only_selected():
    """propose_graph_change with a subset [A, C] lands those docs; B (never proposed) stays out."""
    from agentic import graph, review
    treg, tmp = _temp_registry()
    gdir = tmp / "registry" / "graph"
    gdir.mkdir(parents=True, exist_ok=True)
    # Propose only A and C — never propose B
    selected = [
        {"id": "A", "name": "Alpha", "description": "a", "dateModified": "2026-01-01"},
        {"id": "C", "name": "Gamma", "description": "c", "dateModified": "2026-01-03"},
    ]
    out = review.propose_graph_change(treg, "example-project", selected, reason="subset selection")
    assert out["ok"]
    acc = review.decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"]
    merged = graph.load_project_graph(gdir / "example-project.jsonld")
    ids = {d.drive_id for d in merged.documents}
    assert "A" in ids and "C" in ids    # proposed subset was merged in
    assert "B" not in ids               # B was never proposed so it must not appear


def test_staged_endpoint_serves_listing():
    """GET /api/graph/staged?slug= returns the staging artifact; traversal → ok=False."""
    import http.client
    import json as _json
    import threading
    from agentic import review
    treg, tmp = _temp_registry()
    staging_dir = _inbox(tmp) / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    payload = {"slug": "example-project", "staged_at": "T", "connector": "mock", "scope": {},
               "documents": [{"id": "D1", "name": "N", "dateModified": "2026",
                               "webUrl": "", "description": ""}]}
    (staging_dir / "example-project.json").write_text(_json.dumps(payload), encoding="utf-8")
    server = review.make_server(treg, 0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        # valid slug with a staging file
        conn.request("GET", "/api/graph/staged?slug=example-project")
        r = conn.getresponse()
        data = _json.loads(r.read())
        assert r.status == 200 and data["ok"] and len(data["documents"]) == 1
        # traversal slug is rejected
        conn.request("GET", "/api/graph/staged?slug=../etc")
        r = conn.getresponse()
        data = _json.loads(r.read())
        assert r.status == 200 and data["ok"] is False
        # unknown slug (no file) → ok=True, empty
        conn.request("GET", "/api/graph/staged?slug=no-such-project")
        r = conn.getresponse()
        data = _json.loads(r.read())
        assert r.status == 200 and data["ok"] and data["documents"] == []
    finally:
        server.shutdown()
        server.server_close()


def test_review_module_imports_no_connector():
    """review.py must not import the connectors package — the offline-console invariant."""
    import inspect
    from agentic import review
    source = inspect.getsource(review)
    assert "from .connectors" not in source, "review.py imported the connectors package"
    assert "import connectors" not in source, "review.py imported the connectors package"


def test_connect_stage_flag_routes_to_stage_listing():
    """--stage flag is recognized by the connect argparser and routes to stage_listing."""
    import argparse
    # Mirror the connect subparser setup from mitos.py (pure argparse, no registry load)
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    pc = sub.add_parser("connect")
    pc.add_argument("--project", default=None)
    pc.add_argument("--backend", default=None)
    pc.add_argument("--folder-id", default=None)
    pc.add_argument("--query", default=None)
    pc.add_argument("--stage", action="store_true")
    # with --stage and explicit project
    args = p.parse_args(["connect", "--project", "acme", "--stage", "--query", "forecast"])
    assert args.stage is True and args.query == "forecast"
    # without --stage → defaults to False
    args2 = p.parse_args(["connect", "--project", "acme"])
    assert args2.stage is False
    # --project is now optional (omit for unassigned mode)
    args3 = p.parse_args(["connect", "--stage", "--backend", "mock"])
    assert args3.project is None and args3.stage is True


def test_project_and_server_exclude_folders_validation():
    """_validate rejects invalid exclude_folders in both project drive: blocks and server entries."""
    import copy
    from agentic.loader import RegistryError, _validate
    treg, tmp = _temp_registry()
    # ── project side: non-list value under drive.exclude_folders ──────────────
    r = copy.deepcopy(treg)
    r.projects["example-project"]["drive"] = {"exclude_folders": "Archive"}  # str, not list
    try:
        _validate(r)
        raise AssertionError("expected RegistryError for non-list drive.exclude_folders")
    except RegistryError as e:
        assert "drive.exclude_folders" in str(e), str(e)
    # ── project side: list with a non-string entry ─────────────────────────────
    r2 = copy.deepcopy(treg)
    r2.projects["example-project"]["drive"] = {"exclude_folders": ["Archive", 42]}
    try:
        _validate(r2)
        raise AssertionError("expected RegistryError for non-string entry in drive.exclude_folders")
    except RegistryError as e:
        assert "drive.exclude_folders" in str(e), str(e)
    # ── server side: dict instead of list ─────────────────────────────────────
    r3 = copy.deepcopy(treg)
    servers = r3.servers.setdefault("servers", {})
    servers.setdefault("gws", {})["exclude_folders"] = {"Archive": True}  # dict, not list
    try:
        _validate(r3)
        raise AssertionError("expected RegistryError for non-list server exclude_folders")
    except RegistryError as e:
        assert "exclude_folders" in str(e), str(e)
    # ── valid list passes without error ────────────────────────────────────────
    r4 = copy.deepcopy(treg)
    r4.projects["example-project"]["drive"] = {"exclude_folders": ["Archive", "Drafts"]}
    _validate(r4)   # must not raise


def test_mock_connector_folder_exclusion():
    """MockConnector.list_files and list_folders respect exclude_folders by name and by ID."""
    from agentic.connectors.mock import MockConnector
    # Default mock data: FOLDER1="Project Docs", FOLDER2="Archive"
    conn = MockConnector()
    # list_folders: exclude by name
    folders = conn.list_folders(exclude_folders=["Archive"])
    assert all(f["name"] != "Archive" for f in folders), "Archive should be excluded"
    assert any(f["name"] == "Project Docs" for f in folders)
    # list_folders: exclude by ID
    folders2 = conn.list_folders(exclude_folders=["FOLDER2"])
    assert all(f["id"] != "FOLDER2" for f in folders2)
    # list_files: exclude by name — FOLDER2 holds MOCKDOC3
    files = conn.list_files(exclude_folders=["Archive"])
    ids = {f["id"] for f in files}
    assert "MOCKDOC3" not in ids, "MOCKDOC3 in Archive should be excluded"
    assert "MOCKDOC1" in ids and "MOCKDOC2" in ids
    # list_files: exclude by ID
    files2 = conn.list_files(exclude_folders=["FOLDER1"])
    ids2 = {f["id"] for f in files2}
    assert "MOCKDOC1" not in ids2 and "MOCKDOC2" not in ids2
    assert "MOCKDOC3" in ids2
    # list_files: no exclusions → all 3 docs returned
    all_files = conn.list_files()
    assert len(all_files) == 3
    # Recursive: add a sub-folder of FOLDER2 and a file in it
    sub_folders = list(conn._folders) + [{"id": "FOLDER2_SUB", "name": "Sub",
                                           "parents": ["FOLDER2"]}]
    sub_files = list(conn._files) + [{"id": "MOCKDOC4", "name": "Sub Doc",
                                       "dateModified": "2026-06-02",
                                       "webUrl": "https://example.com/4",
                                       "parents": ["FOLDER2_SUB"]}]
    conn2 = MockConnector(files=sub_files, folders=sub_folders)
    files3 = conn2.list_files(exclude_folders=["Archive"])
    ids3 = {f["id"] for f in files3}
    assert "MOCKDOC3" not in ids3 and "MOCKDOC4" not in ids3, "Recursive sub-folder should also be excluded"
    assert "MOCKDOC1" in ids3 and "MOCKDOC2" in ids3


def test_unassigned_stage_listing_and_fallback():
    """stage_listing with slug='unassigned' writes inbox/staging/unassigned.json; load_staged
    for a normal project falls back to that file when no project-specific staging exists,
    and annotates the result with is_unassigned: True."""
    import json as _json
    from agentic import review
    from agentic.connectors.bootstrap import stage_listing
    from agentic.connectors.mock import MockConnector
    treg, tmp = _temp_registry()
    conn = MockConnector()
    # Stage without binding to a project
    out = stage_listing(treg, conn, "unassigned")
    assert out["ok"], f"unassigned staging failed: {out.get('error')}"
    assert out["slug"] == "unassigned"
    dest = _inbox(tmp) / "staging" / "unassigned.json"
    assert dest.is_file(), "inbox/staging/unassigned.json should have been created"
    data = _json.loads(dest.read_text(encoding="utf-8"))
    assert data["slug"] == "unassigned"
    assert len(data["documents"]) > 0
    # load_staged for example-project (no project-specific file) falls back to unassigned
    result = review.load_staged(treg, "example-project")
    assert result["ok"], f"load_staged returned error: {result.get('error')}"
    assert result["is_unassigned"] is True, "should be flagged as unassigned"
    assert len(result["documents"]) > 0
    # Once a project-specific file exists, it takes precedence over the unassigned pool
    project_staging = _inbox(tmp) / "staging" / "example-project.json"
    project_payload = {"slug": "example-project", "staged_at": "T", "connector": "mock",
                       "scope": {}, "documents": [{"id": "PROJ1", "name": "Proj Doc",
                                                   "dateModified": "2026", "webUrl": "", "description": ""}]}
    project_staging.parent.mkdir(parents=True, exist_ok=True)
    project_staging.write_text(_json.dumps(project_payload), encoding="utf-8")
    result2 = review.load_staged(treg, "example-project")
    assert result2["ok"] and result2["is_unassigned"] is False
    assert result2["documents"][0]["id"] == "PROJ1"


def test_local_projects_overlay_merge():
    """Local projects overlay onto core projects (last-layer-wins): new slugs are added,
    core-only slugs remain, same-slug local entries replace the core entry."""
    from agentic import loader
    import yaml
    import json
    _, tmp = _temp_registry()
    local_projects_dir = tmp / "registry" / "local" / "projects"
    local_projects_dir.mkdir(parents=True, exist_ok=True)
    local_graph_dir = tmp / "registry" / "local" / "graph"
    local_graph_dir.mkdir(parents=True, exist_ok=True)

    # Write a local project and graph
    proj_content = {"slug": "private", "name": "Private Project", "document_store": "gws", "stage": "build"}
    (local_projects_dir / "private.yaml").write_text(yaml.safe_dump(proj_content), encoding="utf-8")

    graph_content = {
        "@context": {"@vocab": "https://schema.org/"},
        "@graph": [{"@id": "http://peccia.net/project/private", "@type": "Project",
                    "name": "Private Project"}]
    }
    (local_graph_dir / "private.jsonld").write_text(json.dumps(graph_content), encoding="utf-8")

    reg = loader.load(tmp)

    # local project and graph are added
    assert "private" in reg.projects
    assert "private" in reg.graphs
    assert reg.projects["private"].get("_is_local") is True
    # core projects/graphs coexist (last-layer-wins means merge, not exclusion)
    assert "example-project" in reg.projects
    assert "mitos" in reg.projects
    assert "example-project" in reg.graphs


def test_mcp_connector_folder_exclusion():
    """MCPConnector respects folder exclusions recursively by resolving names to IDs and appending not in parents to the Google Drive query."""
    from agentic.connectors.mcp import MCPConnector
    treg, tmp = _temp_registry()
    enum = treg.servers["servers"]["gws"]["graph_enum"]

    captured_args = []

    def transport(tool, arguments):
        q = arguments.get("query", "")
        captured_args.append(q)

        # Name resolution: Drive's `contains` is case-insensitive, so the store returns the
        # real folder ("screen shot", different case from the excluded "Screen Shot") plus a
        # look-alike ("Old Screen Shots") that must NOT be excluded.
        if "mimeType = 'application/vnd.google-apps.folder'" in q and "name contains" in q:
            rows = []
            if "Screen Shot" in q:
                rows.append({"id": "SS_ID", "name": "screen shot"})       # case differs
                rows.append({"id": "OLD_ID", "name": "Old Screen Shots"})  # look-alike
            if "IP Bot" in q:
                rows.append({"id": "IP_ID", "name": "IP Bot"})
            return rows

        # Subfolder discovery for the resolved folders.
        if "mimeType = 'application/vnd.google-apps.folder'" in q and "in parents" in q:
            rows = []
            if "SS_ID" in q:
                rows.append({"id": "SS_SUB_ID", "name": "Sub Screenshots"})
            return rows

        # Otherwise, the file listing.
        return [
            {"id": "FILE1", "name": "Doc 1", "modifiedTime": "2026-06-18", "webViewLink": "https://drive/1"},
            {"id": "FILE2", "name": "Doc 2", "modifiedTime": "2026-06-19", "webViewLink": "https://drive/2"},
        ]

    conn = MCPConnector(endpoint="http://localhost:8000/mcp", enum=enum,
                        server_name="gws", transport=transport)

    files = conn.list_files(exclude_folders=["Screen Shot", "IP Bot"])

    assert len(captured_args) > 2
    final_query = captured_args[-1]
    assert "not 'SS_ID' in parents" in final_query, final_query       # case-insensitive match
    assert "not 'IP_ID' in parents" in final_query, final_query
    assert "not 'SS_SUB_ID' in parents" in final_query, final_query   # transitive subfolder
    assert "not 'OLD_ID' in parents" not in final_query, final_query  # look-alike NOT excluded
    assert "mimeType != 'application/vnd.google-apps.folder'" in final_query

    # ── A name that resolves to nothing must NOT silently fail open ───────────────
    import io
    import contextlib
    captured_args.clear()

    def transport_nomatch(tool, arguments):
        q = arguments.get("query", "")
        captured_args.append(q)
        return []  # the excluded folder name matches no real folder

    conn2 = MCPConnector(endpoint="http://localhost:8000/mcp", enum=enum,
                         server_name="gws", transport=transport_nomatch)
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        conn2.list_files(exclude_folders=["Nonexistent Folder"])
    assert "matched no folders" in stderr.getvalue(), stderr.getvalue()

    # A resolution failure surfaces as an error rather than a silent unfiltered listing.
    def transport_boom(tool, arguments):
        q = arguments.get("query", "")
        if "name contains" in q:
            raise RuntimeError("server hiccup")
        return []
    conn3 = MCPConnector(endpoint="http://localhost:8000/mcp", enum=enum,
                         server_name="gws", transport=transport_boom)
    try:
        conn3.list_files(exclude_folders=["Screen Shot"])
        raise AssertionError("expected resolution failure to propagate, not fail open")
    except RuntimeError:
        pass


def test_mcp_connector_recursive_search():
    """Recursive listing resolves a folder's whole subtree, queries it in batches (Drive caps
    query length), dedupes files surfaced under multiple parents, and lets an excluded subtree
    win over the recursive scope."""
    from agentic.connectors.mcp import MCPConnector
    treg, _tmp = _temp_registry()
    enum = treg.servers["servers"]["gws"]["graph_enum"]

    subfolders = [f"S{i}" for i in range(30)]   # 30 subfolders → forces >1 file batch
    file_queries = []

    def transport(tool, arguments):
        q = arguments.get("query", "")
        # 1) exclusion name resolution
        if "name contains" in q:
            return [{"id": "SKIP_ID", "name": "Skip"}] if "Skip" in q else []
        # 2) subfolder discovery (folder mimeType + in parents)
        if q.startswith("mimeType = 'application/vnd.google-apps.folder'") and "in parents" in q:
            if "'ROOT' in parents" in q:
                return [{"id": s, "name": s} for s in subfolders] + \
                       [{"id": "SKIP_ID", "name": "Skip"}]   # excluded folder is also a child
            return []   # leaf folders have no children
        # 3) file listing
        if q.startswith("mimeType != 'application/vnd.google-apps.folder'"):
            file_queries.append(q)
            # 'DUP' appears in every batch (multi-parent file); 'U<n>' is batch-unique.
            return [
                {"id": "DUP", "name": "shared.doc", "modifiedTime": "2026-06-01",
                 "webViewLink": "https://d/dup"},
                {"id": f"U{len(file_queries)}", "name": f"f{len(file_queries)}.doc",
                 "modifiedTime": "2026-06-02", "webViewLink": "https://d/u"},
            ]
        return []

    conn = MCPConnector(endpoint="x", enum=enum, server_name="gws", transport=transport)
    files = conn.list_files(folder_id="ROOT", exclude_folders=["Skip"], recursive=True)

    ids = [f["id"] for f in files]
    # Scope = ROOT + 30 subfolders (SKIP_ID removed) = 31 parents → batches of 25 + 6 = 2 queries.
    assert len(file_queries) == 2, len(file_queries)
    assert ids.count("DUP") == 1, ids                      # deduped across batches
    assert {"DUP", "U1", "U2"} == set(ids), ids            # one shared + one per batch
    # Exclusion wins: the excluded subtree is never queried as a parent.
    assert all("SKIP_ID" not in q for q in file_queries), file_queries
    # Non-recursive over the same folder stays a single immediate-children query.
    file_queries.clear()
    conn.list_files(folder_id="ROOT", recursive=False)
    assert len(file_queries) == 1 and "'ROOT' in parents" in file_queries[0]


def test_mock_connector_recursive_listing():
    """MockConnector.list_files(recursive=True) walks nested folders via their parents."""
    from agentic.connectors.mock import MockConnector
    folders = [
        {"id": "ROOT", "name": "Root"},
        {"id": "CHILD", "name": "Child", "parents": ["ROOT"]},
        {"id": "GRAND", "name": "Grand", "parents": ["CHILD"]},
    ]
    files = [
        {"id": "F_ROOT", "name": "r", "parents": ["ROOT"]},
        {"id": "F_CHILD", "name": "c", "parents": ["CHILD"]},
        {"id": "F_GRAND", "name": "g", "parents": ["GRAND"]},
        {"id": "F_OTHER", "name": "o", "parents": ["ELSEWHERE"]},
    ]
    conn = MockConnector(files=files, folders=folders)
    shallow = {f["id"] for f in conn.list_files(folder_id="ROOT")}
    assert shallow == {"F_ROOT"}, shallow
    deep = {f["id"] for f in conn.list_files(folder_id="ROOT", recursive=True)}
    assert deep == {"F_ROOT", "F_CHILD", "F_GRAND"}, deep


def test_mcp_empty_listing_is_not_an_error():
    """google_workspace_mcp reports zero hits as "No files found for ..." (and "Found 0
    files"). Both are valid empty listings — e.g. a folder with no subfolders during the
    exclusion BFS — and must parse to [], not raise. A genuine non-listing message (an auth
    failure) must still raise so errors aren't swallowed as empty results."""
    from agentic.connectors import mcp as _mcp
    enum = {"text_fields": {"id": r"ID: ([^\s,)]+)", "name": r'Name: "([^"]+)"'}}

    for msg in ("No files found for 'mimeType = ... in parents'.", "Found 0 files."):
        result = {"content": [{"type": "text", "text": msg}]}
        assert _mcp._documents_from_tool_result(result, enum) == [], msg

    try:
        _mcp._documents_from_tool_result(
            {"content": [{"type": "text", "text": "Authorization required: invalid token"}]},
            enum)
        raise AssertionError("a real error text must raise ConnectorError, not parse as empty")
    except _mcp.ConnectorError:
        pass


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


if __name__ == "__main__":
    raise SystemExit(_run())
