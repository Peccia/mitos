"""Tests for the operator console backend (build/agentic/review.py)."""
from __future__ import annotations

import copy

from conftest import loader, reg, _inbox, _plant_candidate, _temp_registry


def test_graph_index_lists_local_projects_regardless_of_drive_key():
    """graph_index must list every local project — presence or absence of 'drive' is irrelevant.

    Regression guard for the bug where `drive: {}` (falsy dict) hid a project from the
    Knowledge Graph sidebar even when its staging file existed."""
    from agentic.review import graph_index

    rig = copy.deepcopy(reg)
    # project with no drive key at all — must appear
    rig.projects["proj-no-drive"] = {
        "name": "No Drive", "slug": "proj-no-drive", "_is_local": True,
        "local_path": {}, "agents": [], "context": {},
        "document_store": "gws",
    }
    # project with empty drive dict — the original bug trigger
    rig.projects["proj-empty-drive"] = {
        "name": "Empty Drive", "slug": "proj-empty-drive", "_is_local": True,
        "local_path": {}, "agents": [], "context": {},
        "document_store": "gws",
        "drive": {},
    }
    # project with a populated drive block — must continue to appear
    rig.projects["proj-full-drive"] = {
        "name": "Full Drive", "slug": "proj-full-drive", "_is_local": True,
        "local_path": {}, "agents": [], "context": {},
        "document_store": "gws",
        "drive": {"root_folder": "1abc"},
    }

    result = graph_index(rig)
    slugs = {r["slug"] for r in result}

    assert "proj-no-drive" in slugs, "project with no drive key must appear in graph_index"
    assert "proj-empty-drive" in slugs, "project with drive: {} must appear in graph_index"
    assert "proj-full-drive" in slugs, "project with populated drive block must appear in graph_index"


def test_graph_index_core_projects_step_aside_when_local_overlay_present():
    """When any local project exists the core (non-local) projects are hidden — same convention
    as the example-machine guard in commands.py."""
    from agentic.review import graph_index

    rig = copy.deepcopy(reg)
    # inject exactly one local project
    rig.projects["my-local"] = {
        "name": "My Local", "slug": "my-local", "_is_local": True,
        "local_path": {}, "agents": [], "context": {},
    }

    result = graph_index(rig)
    slugs = {r["slug"] for r in result}

    assert "my-local" in slugs
    # core projects (no _is_local flag) must not appear
    for slug, proj in rig.projects.items():
        if not proj.get("_is_local"):
            assert slug not in slugs, f"core project {slug!r} must step aside when local overlay present"


def test_graph_index_shows_all_when_no_local_overlay():
    """Without any local projects every project appears."""
    from agentic.review import graph_index

    # load a fresh registry with ignore_local=True (conftest.reg does this already)
    result = graph_index(reg)
    slugs = {r["slug"] for r in result}
    # at minimum the core mitos project must be visible
    assert "mitos" in slugs


def test_propose_new_skill_creates_kind_new_candidate_and_accepts_cleanly():
    """propose_new_skill needs no new acceptance-path logic: route_into_registry already
    writes a brand-new file verbatim when the target path doesn't exist (commands.py),
    and _bodies() already reports it as a diff-free "new file" candidate. This test is
    the concrete proof that decide()/load_candidates() need no changes for kind: new."""
    from agentic import loader as loadermod
    from agentic.review import decide, load_candidates, propose_new_skill

    treg, tmp = _temp_registry()
    out = propose_new_skill(
        treg, "widget-helper",
        {"description": "Helps with widgets.", "targets": ["hermes"], "category": "devops"},
        "# Instructions\n\nDo the widget thing.", "")
    assert out["ok"], out
    assert out["registry_path"] == "local/skills/widget-helper/SKILL.md"

    candidates = load_candidates(treg)
    mine = next(c for c in candidates if c["id"] == out["id"])
    assert mine["kind"] == "new"
    assert mine["acceptable"]

    result = decide(treg, out["id"], "accept", "")
    assert result["ok"], result
    written = tmp / "registry" / "local" / "skills" / "widget-helper" / "SKILL.md"
    assert written.is_file()
    text = written.read_text(encoding="utf-8")
    assert "name: widget-helper" in text
    assert "Do the widget thing." in text

    # the new skill is now loadable from disk
    reloaded = loadermod.load(tmp)
    assert "widget-helper" in reloaded.skills


def test_dismiss_and_restore_roundtrip():
    """dismiss_docs moves a doc into the Recovery list; load_dismissed surfaces it;
    restore_docs removes it again."""
    from agentic import review
    treg, tmp = _temp_registry()
    staging_dir = _inbox(tmp) / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "example-project.json").write_text(
        '{"slug": "example-project", "documents": []}', encoding="utf-8")

    doc = {"id": "D1", "name": "Doc One", "dateModified": "2026-01-01",
           "webUrl": "https://example.com/1"}
    out = review.dismiss_docs(treg, "example-project", [doc])
    assert out["ok"], out

    recovered = review.load_dismissed(treg, "example-project")
    assert recovered["ok"] and len(recovered["documents"]) == 1
    entry = recovered["documents"][0]
    assert entry["id"] == "D1" and entry["name"] == "Doc One"
    assert entry["source"] == "manual" and entry["dismissed_at"]

    # dismissing the same id again updates in place rather than duplicating
    review.dismiss_docs(treg, "example-project", [doc])
    recovered2 = review.load_dismissed(treg, "example-project")
    assert len(recovered2["documents"]) == 1

    restored = review.restore_docs(treg, "example-project", ["D1"])
    assert restored["ok"], restored
    recovered3 = review.load_dismissed(treg, "example-project")
    assert recovered3["documents"] == []


def test_dismiss_docs_rejects_invalid_slug():
    """dismiss_docs/restore_docs refuse a traversal or empty slug, same as load_staged."""
    from agentic import review
    treg, _tmp = _temp_registry()
    for bad in ("../etc", "", ".", ".."):
        r = review.dismiss_docs(treg, bad, [{"id": "X", "name": "X"}])
        assert r["ok"] is False, f"expected ok=False for slug {bad!r}"
        r2 = review.restore_docs(treg, bad, ["X"])
        assert r2["ok"] is False, f"expected ok=False for slug {bad!r}"


def test_dismiss_pool_fallback_mirrors_load_staged():
    """No per-project staging file yet → dismissal lands in the shared unassigned
    dismissed file (is_unassigned True). Once a project-specific staging file exists,
    a fresh dismissal for that project lands in its own dismissed file instead."""
    from agentic import review
    treg, tmp = _temp_registry()

    out = review.dismiss_docs(treg, "example-project", [{"id": "U1", "name": "Unassigned Doc"}])
    assert out["ok"]
    unassigned_file = _inbox(tmp) / "staging" / "unassigned.dismissed.json"
    assert unassigned_file.is_file()
    result = review.load_dismissed(treg, "example-project")
    assert result["is_unassigned"] is True
    assert result["documents"][0]["id"] == "U1"

    staging_dir = _inbox(tmp) / "staging"
    (staging_dir / "example-project.json").write_text(
        '{"slug": "example-project", "documents": []}', encoding="utf-8")
    out2 = review.dismiss_docs(treg, "example-project", [{"id": "P1", "name": "Project Doc"}])
    assert out2["ok"]
    project_file = staging_dir / "example-project.dismissed.json"
    assert project_file.is_file()
    result2 = review.load_dismissed(treg, "example-project")
    assert result2["is_unassigned"] is False
    assert result2["documents"][0]["id"] == "P1"
    # the earlier unassigned-pool dismissal is untouched, just no longer the active pool
    unassigned_result = review.load_dismissed(treg, "example-project", pool="unassigned")
    assert unassigned_result["documents"][0]["id"] == "U1"


def test_dismiss_file_unreadable_is_tolerated():
    """A corrupt dismissed-list file degrades to empty rather than raising — dismissal
    state is best-effort, unlike staging artifacts which surface ok=False."""
    from agentic import review
    treg, tmp = _temp_registry()
    staging_dir = _inbox(tmp) / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    (staging_dir / "unassigned.dismissed.json").write_text("not json", encoding="utf-8")
    result = review.load_dismissed(treg, "example-project")
    assert result["ok"] and result["documents"] == []
    # a subsequent dismiss still succeeds and overwrites the corrupt file cleanly
    out = review.dismiss_docs(treg, "example-project", [{"id": "D1", "name": "Doc"}])
    assert out["ok"]
    result2 = review.load_dismissed(treg, "example-project")
    assert result2["documents"][0]["id"] == "D1"


def test_accept_removal_auto_dismisses_doc():
    """Accepting a kind:graph candidate that removes a mapped document auto-dismisses
    it (source: "removal") so it stops resurfacing in Discovery from the untouched
    staging snapshot. A rejected removal candidate must NOT dismiss anything."""
    from agentic import graph, review
    treg, tmp = _temp_registry()
    gdir = tmp / "registry" / "graph"
    gdir.mkdir(parents=True, exist_ok=True)

    # map a document first
    mapped = [{"id": "A", "name": "Alpha", "description": "a", "dateModified": "2026-01-01"}]
    out = review.propose_graph_change(treg, "example-project", mapped, reason="seed")
    assert out["ok"]
    reg1 = loader.load(tmp)
    acc = review.decide(reg1, out["id"], "accept", "")
    assert acc["ok"]

    # it must not be dismissed yet — nothing has removed it
    assert review.load_dismissed(loader.load(tmp), "example-project")["documents"] == []

    # propose + REJECT a removal — rejection must not dismiss anything
    reg2 = loader.load(tmp)
    rem_reject = review.propose_graph_change(reg2, "example-project", [], removals=["A"],
                                             reason="removal to reject")
    assert rem_reject["ok"]
    rej = review.decide(loader.load(tmp), rem_reject["id"], "reject", "")
    assert rej["ok"]
    assert review.load_dismissed(loader.load(tmp), "example-project")["documents"] == []
    merged_after_reject = graph.load_project_graph(gdir / "example-project.jsonld")
    assert "A" in {d.drive_id for d in merged_after_reject.documents}

    # propose + ACCEPT a removal — now it must be auto-dismissed
    reg3 = loader.load(tmp)
    rem_accept = review.propose_graph_change(reg3, "example-project", [], removals=["A"],
                                             reason="removal to accept")
    assert rem_accept["ok"]
    acc2 = review.decide(loader.load(tmp), rem_accept["id"], "accept", "")
    assert acc2["ok"]
    merged = graph.load_project_graph(gdir / "example-project.jsonld")
    assert "A" not in {d.drive_id for d in merged.documents}

    dismissed = review.load_dismissed(loader.load(tmp), "example-project")
    assert len(dismissed["documents"]) == 1
    entry = dismissed["documents"][0]
    assert entry["id"] == "A" and entry["name"] == "Alpha" and entry["source"] == "removal"


def test_propose_new_skill_rejects_name_collision_and_bad_shape():
    from agentic.review import propose_new_skill

    treg, _tmp = _temp_registry()
    existing = next(iter(treg.skills))

    # name collision
    out = propose_new_skill(treg, existing, {"targets": ["hermes"]}, "body")
    assert not out["ok"]

    # bad slug shape (uppercase / underscore)
    out = propose_new_skill(treg, "Bad_Name", {"targets": ["hermes"]}, "body")
    assert not out["ok"]

    # empty targets
    out = propose_new_skill(treg, "new-skill", {"targets": []}, "body")
    assert not out["ok"]

    # unknown target
    out = propose_new_skill(treg, "new-skill", {"targets": ["not-a-real-target"]}, "body")
    assert not out["ok"]


def test_propose_new_org_domain_creates_domain_skill_and_accepts_cleanly():
    """The '+ ORG' button: a single kind:new skill candidate carrying org_domain in its
    frontmatter, immediately valid for a project's org: field once accepted — no separate
    routing table edit required."""
    from agentic import loader as loadermod
    from agentic.review import decide, org_index, propose_new_org_domain

    treg, tmp = _temp_registry()
    out = propose_new_org_domain(treg, "finance", "")
    assert out["ok"], out
    assert out["registry_path"] == "local/skills/org-finance/SKILL.md"

    result = decide(treg, out["id"], "accept", "")
    assert result["ok"], result
    written = tmp / "registry" / "local" / "skills" / "org-finance" / "SKILL.md"
    assert written.is_file()
    text = written.read_text(encoding="utf-8")
    assert "org_domain: finance" in text
    assert "targets:" in text and "hermes" in text

    reloaded = loadermod.load(tmp)
    assert loadermod.known_org_domains(reloaded) >= {"software", "design", "marketing", "finance"}
    idx = org_index(reloaded)
    assert "finance" in idx
    assert idx["finance"]["skill"] == "org-finance"
    assert idx["finance"]["primaryChain"], "scaffolded body must parse into a primary chain"


def test_propose_new_org_domain_rejects_existing_domain_and_bad_slug():
    from agentic.review import propose_new_org_domain

    treg, _tmp = _temp_registry()
    out = propose_new_org_domain(treg, "software", "")
    assert not out["ok"]
    assert "already exists" in out["error"]

    out = propose_new_org_domain(treg, "Bad Domain!", "")
    assert not out["ok"]

    out = propose_new_org_domain(treg, "", "")
    assert not out["ok"]


def test_org_index_parses_hierarchy_table_and_skill_roles():
    from agentic.review import org_index

    result = org_index(reg)
    assert "software" in result
    assert result["software"]["skill"] == "org-software"
    assert result["software"]["primaryChain"], "expected a non-empty primary chain"
    cto = next((r for r in result["software"]["extendedRoles"] if r["title"] == "CTO"), None)
    assert cto is not None
    assert cto["lens"]
    # a Lens/Trigger bullet that wraps onto an indented continuation line must not be
    # truncated at the first physical line
    assert "SEV0 post-mortems" in cto["trigger"]

    # design and marketing share the same authored structure — same shape, no crash
    for domain in ("design", "marketing"):
        assert domain in result
        assert result[domain]["primaryChain"]
        assert result[domain]["extendedRoles"]


def test_org_tree_reconstructs_agents_md_deploy_paths():
    from agentic.review import org_tree

    machine = next(m for m, cfg in reg.machines.items()
                   if "agents-md" in cfg.get("targets", []))
    result = org_tree(reg, machine)
    assert result["ok"]
    assert result["tree"], "expected a non-trivial tree"

    def all_deploy_paths(nodes):
        for n in nodes:
            if n["deployPath"]:
                yield n["deployPath"]
            yield from all_deploy_paths(n["children"])

    assert any(p.endswith("AGENTS.md") for p in all_deploy_paths(result["tree"]))


def test_org_tree_unknown_machine():
    from agentic.review import org_tree

    result = org_tree(reg, "not-a-real-machine")
    assert not result["ok"]


def test_state_lists_only_agents_md_machines():
    from agentic.review import state

    result = state(reg)
    assert "agents_md_machines" in result
    for m in result["agents_md_machines"]:
        assert "agents-md" in reg.machines[m].get("targets", [])
    # every machine that DOES carry agents-md must be listed
    for m, cfg in reg.machines.items():
        if "agents-md" in cfg.get("targets", []):
            assert m in result["agents_md_machines"]


def test_prompt_index_prompts_key_shape():
    """Regression guard for the console's dropped-prompts bug: buildPrompts() in app.js
    renders STATE.prompts.prompts alongside .skills/.partials, so this contract — the
    "prompts" key present, a list, each item carrying exactly the fields the frontend
    depends on — must not silently drift."""
    from agentic.review import prompt_index

    result = prompt_index(reg)
    assert "prompts" in result
    assert isinstance(result["prompts"], list)
    assert result["prompts"], "expected at least one registry/prompts/*.md entry"
    expected_keys = {"name", "description", "category", "targets", "body", "frontmatter",
                     "favorited"}
    for item in result["prompts"]:
        assert set(item.keys()) == expected_keys


def test_prompt_index_hides_example_project_partials_when_local_projects_exist():
    """Example-project context partials step aside in the Prompt Library once the user
    has overlay projects — the same convention graph_index and the planner apply. On a
    fresh clone (no overlay) they stay visible for the quick-start."""
    import copy
    from agentic.review import prompt_index

    example_rels = {str(p).split("registry/", 1)[-1]
                    for proj in reg.projects.values() if proj.get("example")
                    for p in (proj.get("context") or {}).values()}
    assert example_rels, "core must ship at least one example project with context"

    # fresh clone (reg loads with ignore_local): examples visible
    fresh = {i["rel"] for i in prompt_index(reg)["partials"]}
    assert example_rels & fresh, "examples must render on a fresh clone"

    # configured fleet: any overlay project hides them
    rig = copy.deepcopy(reg)
    rig.projects["mitos"]["_is_local"] = True
    configured = {i["rel"] for i in prompt_index(rig)["partials"]}
    assert not (example_rels & configured), \
        "example partials must step aside once overlay projects exist"


# ── Track A: structured skill/prompt metadata editing ─────────────────────────
def test_state_exposes_known_targets():
    from agentic import loader as loadermod
    from agentic.review import state

    result = state(reg)
    assert result["known_targets"] == sorted(loadermod.KNOWN_TARGETS)


def test_prompt_index_frontmatter_whitelist_shape():
    """Skills/prompts carry a `frontmatter` dict scoped to the per-kind editable
    whitelist — never the full raw frontmatter (which may carry e.g. a skill's
    `hermes:` block that has no place in the console's metadata panel)."""
    from agentic.review import _PROMPT_META_WHITELIST, _SKILL_META_WHITELIST, prompt_index

    result = prompt_index(reg)
    for item in result["skills"]:
        assert set(item["frontmatter"].keys()) == _SKILL_META_WHITELIST
    for item in result["prompts"]:
        assert set(item["frontmatter"].keys()) == _PROMPT_META_WHITELIST
    # partials carry no frontmatter concept at all
    for item in result["partials"]:
        assert "frontmatter" not in item


def test_propose_meta_edit_frontmatter_only_yields_nonempty_diff_and_accepts():
    """A metadata-only edit (body unchanged) must NOT vanish into a diff-free accept —
    the regression this whole track exists to prevent: _bodies() must diff the FULL file
    (frontmatter included) for a verbatim candidate, not the frontmatter-stripped body."""
    from agentic.review import decide, load_candidates, propose_meta_edit

    treg, tmp = _temp_registry()
    skill = next(iter(treg.skills.values()))
    out = propose_meta_edit(treg, "skill", skill.name,
                            {"version": "9.9.9"}, skill.body, "bump version")
    assert out["ok"], out
    assert out["registry_path"] == skill.rel

    cand = next(c for c in load_candidates(treg) if c["id"] == out["id"])
    assert cand["acceptable"], cand
    assert cand["diff"], "a frontmatter-only edit must produce a non-empty diff"
    assert any("9.9.9" in (r["r"] or "") for r in cand["diff"])

    acc = decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"], acc
    assert acc["changed"] == [skill.rel]
    written = (tmp / "registry" / skill.rel).read_text(encoding="utf-8")
    assert "version: 9.9.9" in written
    assert skill.body.strip() in written   # body untouched


def test_propose_meta_edit_rejects_unknown_field_and_unknown_target():
    from agentic.review import propose_meta_edit

    treg, _tmp = _temp_registry()
    skill = next(iter(treg.skills.values()))

    # a field outside the editable whitelist (e.g. 'name') is rejected
    out = propose_meta_edit(treg, "skill", skill.name, {"name": "renamed"}, skill.body)
    assert not out["ok"]

    # an unknown target is rejected
    out = propose_meta_edit(treg, "skill", skill.name,
                            {"targets": ["not-a-real-target"]}, skill.body)
    assert not out["ok"]

    # empty targets list is rejected
    out = propose_meta_edit(treg, "skill", skill.name, {"targets": []}, skill.body)
    assert not out["ok"]


def test_propose_meta_edit_rejects_breaking_project_binding():
    """Removing 'claude-code' from a skill's targets must be refused at propose time
    when a project still binds that skill (the binding requires claude-code)."""
    from agentic.review import propose_meta_edit

    treg, _tmp = _temp_registry()
    skill = next(s for s in treg.skills.values() if "claude-code" in s.targets)
    treg.projects["mitos"]["skills"] = [skill.name]

    remaining = [t for t in skill.targets if t != "claude-code"]
    out = propose_meta_edit(treg, "skill", skill.name, {"targets": remaining}, skill.body)
    assert not out["ok"]
    assert "mitos" in out["error"]


def test_decide_revalidates_verbatim_candidate_at_accept_time():
    """A verbatim candidate is untrusted text that sat on disk since propose — decide()
    must re-run the same target/binding checks, not just trust the propose-time pass."""
    from agentic import review

    treg, tmp = _temp_registry()
    skill = next(s for s in treg.skills.values() if "claude-code" in s.targets)

    # unknown target smuggled directly into a planted candidate (bypassing propose_meta_edit)
    bad_fm = dict(skill.frontmatter)
    bad_fm["targets"] = ["not-a-real-target"]
    import yaml as _y
    bad_payload = ("---\n" + _y.safe_dump(bad_fm, sort_keys=False) + "---\n\n"
                  + skill.body + "\n")
    meta = {"registry_path": skill.rel, "kind": "drift", "verbatim": True,
           "source": {"machine": "test", "tool": "console"}, "base_hash": "",
           "deploy_path": "", "sources": [skill.rel], "captured_at": "2026-07-02T00:00:00Z",
           "note": "test"}
    _plant_candidate(tmp, "bad-target-cand", meta, "SKILL.md", bad_payload)
    result = review.decide(loader.load(tmp), "bad-target-cand", "accept", "")
    assert not result["ok"]

    # binding-break smuggled the same way
    good_fm = dict(skill.frontmatter)
    good_fm["targets"] = [t for t in skill.targets if t != "claude-code"]
    good_payload = ("---\n" + _y.safe_dump(good_fm, sort_keys=False) + "---\n\n"
                   + skill.body + "\n")
    _plant_candidate(tmp, "bad-binding-cand", meta, "SKILL.md", good_payload)
    treg2 = loader.load(tmp)
    treg2.projects["mitos"]["skills"] = [skill.name]
    result2 = review.decide(treg2, "bad-binding-cand", "accept", "")
    assert not result2["ok"]
    assert "mitos" in result2["error"]


def test_propose_meta_edit_on_overlay_skill_routes_to_local():
    """A skill overridden by the Mitos overlay must have its metadata edit accepted into
    registry/local/, never the shadowed core copy — same overlay-routing contract as
    every other accept path."""
    from agentic.review import decide, propose_meta_edit

    treg, tmp = _temp_registry()
    core_name = next(iter(treg.skills))
    core_rel = treg.skills[core_name].rel
    core_text = (tmp / "registry" / core_rel).read_text(encoding="utf-8")

    overlay_dir = tmp / "registry" / "local" / "skills" / core_name
    overlay_dir.mkdir(parents=True)
    (overlay_dir / "SKILL.md").write_text(core_text, encoding="utf-8")

    treg = loader.load(tmp)
    assert treg.skills[core_name].rel == f"local/skills/{core_name}/SKILL.md"

    out = propose_meta_edit(treg, "skill", core_name, {"version": "3.3.3"},
                            treg.skills[core_name].body)
    assert out["ok"], out
    assert out["registry_path"] == f"local/skills/{core_name}/SKILL.md"

    acc = decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"], acc
    assert acc["changed"] == [f"local/skills/{core_name}/SKILL.md"]

    overlay_text = (overlay_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "version: 3.3.3" in overlay_text
    # the core copy is untouched
    assert (tmp / "registry" / core_rel).read_text(encoding="utf-8") == core_text


# ── skill extensions via the console (extends_skill/extends_role) — R1/R2 ──────
def test_propose_new_skill_with_extension_fields_validates_and_accepts():
    from agentic.review import decide, propose_new_skill

    treg, tmp = _temp_registry()
    assert "org-software" in treg.skills
    out = propose_new_skill(
        treg, "org-data-science",
        {"description": "Data science CTO extension.", "targets": ["hermes"],
        "category": "productivity", "extends_skill": "org-software",
        "extends_role": "CTO"},
        "Extra CTO guidance for data science work.", "")
    assert out["ok"], out

    acc = decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"], acc
    written = (tmp / "registry" / "local" / "skills" / "org-data-science"
              / "SKILL.md").read_text(encoding="utf-8")
    assert "extends_skill: org-software" in written
    assert "extends_role: CTO" in written

    # the extension never deploys standalone; it only appears spliced into the parent
    reloaded = loader.load(tmp)
    from agentic import planner as plannermod
    selected = plannermod._selected_skills(reloaded, {"include_target": "hermes"})
    assert "org-data-science" not in {s.name for s in selected}
    parent = reloaded.skills["org-software"]
    from agentic import render as rendermod
    assert "Extra CTO guidance for data science work." in rendermod.compose_skill_body(
        reloaded, parent)


def test_propose_new_skill_rejects_extension_without_matching_role_field():
    from agentic.review import propose_new_skill

    treg, _tmp = _temp_registry()
    out = propose_new_skill(
        treg, "org-half-ext", {"targets": ["hermes"], "extends_skill": "org-software"},
        "body")
    assert not out["ok"]
    assert "must be specified together" in out["error"]


def test_propose_new_skill_rejects_extension_of_unknown_parent():
    from agentic.review import propose_new_skill

    treg, _tmp = _temp_registry()
    out = propose_new_skill(
        treg, "org-bad-ext",
        {"targets": ["hermes"], "extends_skill": "no-such-org", "extends_role": "CTO"},
        "body")
    assert not out["ok"]
    assert "is not a known skill" in out["error"]


def test_propose_meta_edit_rejects_bad_extension_pair():
    from agentic.review import propose_meta_edit

    treg, _tmp = _temp_registry()
    skill = next(iter(treg.skills.values()))
    out = propose_meta_edit(treg, "skill", skill.name,
                            {"extends_skill": "org-software"}, skill.body)
    assert not out["ok"]
    assert "must be specified together" in out["error"]


# ── skill scope: global (default) | project — the Skills & Orgs Scope control ───
def test_propose_meta_edit_accepts_valid_scope_and_it_survives_accept():
    from agentic.review import decide, propose_meta_edit

    treg, tmp = _temp_registry()
    skill = next(iter(treg.skills.values()))
    out = propose_meta_edit(treg, "skill", skill.name,
                            {"scope": "project"}, skill.body, "scope to specific projects")
    assert out["ok"], out
    acc = decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"], acc
    written = (tmp / "registry" / skill.rel).read_text(encoding="utf-8")
    assert "scope: project" in written

def test_propose_meta_edit_rejects_invalid_scope_value():
    from agentic.review import propose_meta_edit

    treg, _tmp = _temp_registry()
    skill = next(iter(treg.skills.values()))
    out = propose_meta_edit(treg, "skill", skill.name,
                            {"scope": "workspace"}, skill.body)
    assert not out["ok"]
    assert "invalid scope" in out["error"]

def test_propose_meta_edit_allows_scope_project_regardless_of_targets():
    """Unlike the extends_skill/target-binding checks, scope: project has no per-target
    incompatibility — hermes/claude-app targets simply ignore it (see loader.
    validate_skill_scope, PROJECT_SCOPE_CAPABLE_TARGETS)."""
    from agentic.review import propose_meta_edit

    treg, _tmp = _temp_registry()
    skill = next(iter(treg.skills.values()))
    out = propose_meta_edit(treg, "skill", skill.name,
                            {"scope": "project", "targets": ["claude-app"]}, skill.body)
    assert out["ok"], out

def test_prompt_index_exposes_bound_projects_per_skill():
    """The console's Scope section reads bound_projects to show which projects a
    scope: project skill actually reaches — computed from each project's skills: list."""
    from agentic.review import prompt_index

    treg, _tmp = _temp_registry()
    slug = next(iter(treg.projects))
    skill = next(iter(treg.skills.values()))
    treg.projects[slug]["skills"] = [skill.name]
    payload = prompt_index(treg)
    entry = next(s for s in payload["skills"] if s["name"] == skill.name)
    assert entry["bound_projects"] == [slug]


# ── skill supporting files via the console (examples/, scripts/) — R4/R5 ───────
def test_propose_new_skill_with_resources_writes_files_and_accepts():
    from agentic.review import decide, propose_new_skill

    treg, tmp = _temp_registry()
    out = propose_new_skill(
        treg, "res-skill", {"targets": ["hermes"], "description": "d"},
        "# Instructions\n\nBody.", "",
        resources={"examples/sample.md": "expected output\n",
                  "scripts/validate.sh": "#!/bin/sh\necho ok\n"})
    assert out["ok"], out
    acc = decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"], acc
    skill_dir = tmp / "registry" / "local" / "skills" / "res-skill"
    assert (skill_dir / "examples" / "sample.md").read_text(encoding="utf-8") == \
        "expected output\n"
    assert (skill_dir / "scripts" / "validate.sh").read_text(encoding="utf-8") == \
        "#!/bin/sh\necho ok\n"
    reloaded = loader.load(tmp)
    assert set(reloaded.skills["res-skill"].resources) == \
        {"examples/sample.md", "scripts/validate.sh"}


def test_propose_new_skill_rejects_invalid_resource_path():
    from agentic.review import propose_new_skill

    treg, _tmp = _temp_registry()
    out = propose_new_skill(
        treg, "res-skill-bad", {"targets": ["hermes"], "description": "d"}, "body",
        resources={"not-allowed/x.md": "text"})
    assert not out["ok"]
    assert "invalid resource path" in out["error"]


def _make_res_skill(treg, tmp):
    from agentic.review import decide, propose_new_skill
    out = propose_new_skill(
        treg, "res-abs-skill", {"targets": ["hermes"], "description": "d"}, "body",
        resources={"examples/a.md": "a\n"})
    assert out["ok"], out
    acc = decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"], acc
    return loader.load(tmp)


def test_resources_absent_leaves_existing_files_untouched():
    """R4: omitting `resources` (None) on a metadata edit must never touch a skill's
    existing examples/scripts — the absent-vs-empty distinction is the whole point."""
    from agentic.review import decide, propose_meta_edit

    treg, tmp = _temp_registry()
    treg = _make_res_skill(treg, tmp)
    skill = treg.skills["res-abs-skill"]
    out = propose_meta_edit(treg, "skill", skill.name, {"version": "2.0.0"}, skill.body)
    assert out["ok"], out
    acc = decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"], acc
    assert (tmp / "registry" / "local" / "skills" / "res-abs-skill"
           / "examples" / "a.md").is_file()


def test_resources_empty_dict_deletes_all():
    """R4: an explicit empty resources block deletes examples/ and scripts/ wholesale."""
    from agentic.review import decide, propose_meta_edit

    treg, tmp = _temp_registry()
    treg = _make_res_skill(treg, tmp)
    skill = treg.skills["res-abs-skill"]
    out = propose_meta_edit(treg, "skill", skill.name, {}, skill.body, resources={})
    assert out["ok"], out
    acc = decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"], acc
    assert not (tmp / "registry" / "local" / "skills" / "res-abs-skill"
               / "examples").exists()


def test_resources_populated_dict_replaces_wholesale():
    """A non-empty resources block on an edit replaces the whole set, not a merge."""
    from agentic.review import decide, propose_meta_edit

    treg, tmp = _temp_registry()
    treg = _make_res_skill(treg, tmp)
    skill = treg.skills["res-abs-skill"]
    out = propose_meta_edit(treg, "skill", skill.name, {}, skill.body,
                            resources={"examples/b.md": "b\n"})
    assert out["ok"], out
    acc = decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"], acc
    skill_dir = tmp / "registry" / "local" / "skills" / "res-abs-skill"
    assert not (skill_dir / "examples" / "a.md").exists()
    assert (skill_dir / "examples" / "b.md").read_text(encoding="utf-8") == "b\n"


def test_load_candidates_surfaces_resources_and_provided_flag():
    from agentic.review import load_candidates, propose_new_skill

    treg, _tmp = _temp_registry()
    out = propose_new_skill(
        treg, "res-visible-skill", {"targets": ["hermes"], "description": "d"}, "body",
        resources={"examples/x.md": "x\n"})
    assert out["ok"], out
    cand = next(c for c in load_candidates(treg) if c["id"] == out["id"])
    assert cand["resources_provided"] is True
    assert cand["resources"] == {"examples/x.md": "x\n"}

    out2 = propose_new_skill(
        treg, "res-invisible-skill", {"targets": ["hermes"], "description": "d"}, "body")
    cand2 = next(c for c in load_candidates(treg) if c["id"] == out2["id"])
    assert cand2["resources_provided"] is False


# ── stale-gate (P0/P0.5 — registry moved since capture) ────────────────────────
def test_stale_candidate_blocks_accept_without_force():
    """A candidate whose registry_base_hash no longer matches the current file must be
    refused at accept time — the disabled Accept button is cosmetic only, the server
    must enforce it (FM1: stale accepts must never silently clobber newer disk state)."""
    from agentic.review import decide, load_candidates, propose_edit

    treg, tmp = _temp_registry()
    partial_name = next(iter(treg.partials))
    out = propose_edit(treg, "partial", partial_name,
                       treg.partials[partial_name].body + "\nedited by console\n")
    assert out["ok"], out

    # the registry moves on disk after capture (a manual edit / git pull)
    dest = tmp / "registry" / partial_name
    dest.write_text(dest.read_text(encoding="utf-8") + "\nchanged on disk\n", encoding="utf-8")

    reg2 = loader.load(tmp)
    cand = next(c for c in load_candidates(reg2) if c["id"] == out["id"])
    assert cand["stale"] is True

    result = decide(reg2, out["id"], "accept", "")
    assert not result["ok"]
    assert result.get("stale") is True
    # the candidate must still be sitting in the inbox — nothing was written
    assert (tmp / "registry" / "local" / "inbox" / out["id"]).is_dir()


def test_force_accept_overrides_stale_gate_and_logs_decision():
    """force=True bypasses the staleness refusal but must still run the full accept path
    (revalidation + decisions.jsonl) — it is not a trusted bypass (Q2)."""
    from agentic import render
    from agentic.review import decide, propose_edit

    treg, tmp = _temp_registry()
    partial_name = next(iter(treg.partials))
    new_body = treg.partials[partial_name].body + "\nedited by console\n"
    out = propose_edit(treg, "partial", partial_name, new_body)
    assert out["ok"], out

    dest = tmp / "registry" / partial_name
    dest.write_text(dest.read_text(encoding="utf-8") + "\nchanged on disk\n", encoding="utf-8")

    reg2 = loader.load(tmp)
    result = decide(reg2, out["id"], "accept", "override reason", force=True)
    assert result["ok"], result
    # accept keeps the file's frontmatter and rewrites only the body
    assert render.strip_frontmatter(dest.read_text(encoding="utf-8")).strip() \
        == new_body.strip()

    decisions = (tmp / "registry" / "local" / "inbox" / "decisions.jsonl").read_text(
        encoding="utf-8")
    assert "override reason" in decisions


def test_console_candidate_reports_stale_none_when_untouched():
    """Without any registry change, a console-proposed candidate must read stale: None
    or False, never True — a false positive would block every ordinary accept."""
    from agentic.review import load_candidates, propose_edit

    treg, tmp = _temp_registry()
    partial_name = next(iter(treg.partials))
    out = propose_edit(treg, "partial", partial_name,
                       treg.partials[partial_name].body + "\nedited by console\n")
    assert out["ok"], out

    cand = next(c for c in load_candidates(loader.load(tmp)) if c["id"] == out["id"])
    assert cand["stale"] is not True


def test_propose_meta_edit_verbatim_candidate_goes_stale_on_registry_change():
    """The verbatim (metadata-edit) path must independently capture registry_base_hash —
    it snapshots the whole file, not just the body, so it needs its own base."""
    from agentic.review import decide, load_candidates, propose_meta_edit

    treg, tmp = _temp_registry()
    skill = next(s for s in treg.skills.values() if "claude-code" in s.targets)
    out = propose_meta_edit(treg, "skill", skill.name, {"version": "9.9.9"}, skill.body)
    assert out["ok"], out

    dest = tmp / "registry" / skill.rel
    dest.write_text(dest.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    reg2 = loader.load(tmp)
    cand = next(c for c in load_candidates(reg2) if c["id"] == out["id"])
    assert cand["stale"] is True
    result = decide(reg2, out["id"], "accept", "")
    assert not result["ok"]
    assert result.get("stale") is True


def test_graph_propose_then_decide_chain_upserts_and_leaves_inbox_on_failure():
    """P1 (Propose & Accept): the client is expected to chain propose_graph_change →
    decide client-side with no new server endpoint. Confirm the chain both succeeds for
    a valid fragment and, on a decide-time failure, leaves the candidate in the inbox
    rather than silently discarding it."""
    from agentic.review import decide, load_candidates, propose_graph_change

    treg, tmp = _temp_registry()
    slug = next(iter(treg.projects))
    out = propose_graph_change(
        treg, slug,
        documents=[{"id": "doc-1", "name": "Doc One", "dateModified": "2026-07-01T00:00:00Z"}])
    assert out["ok"], out

    result = decide(loader.load(tmp), out["id"], "accept", "")
    assert result["ok"], result
    graph_text = (tmp / "registry" / "graph" / f"{slug}.jsonld").read_text(encoding="utf-8")
    assert "doc-1" in graph_text

    # decide-time failure (unknown project, simulating a slug that vanished between
    # propose and decide) must fail cleanly without deleting the candidate
    out2 = propose_graph_change(
        loader.load(tmp), slug,
        documents=[{"id": "doc-2", "name": "Doc Two", "dateModified": "2026-07-01T00:00:00Z"}])
    assert out2["ok"], out2
    treg3 = loader.load(tmp)
    del treg3.projects[slug]
    result2 = decide(treg3, out2["id"], "accept", "")
    assert not result2["ok"]
    assert (tmp / "registry" / "local" / "inbox" / out2["id"]).is_dir()


def test_graph_propose_carries_and_preserves_doc_type():
    """`type` on a proposed document lands in the graph as additionalType; a later
    upsert of the same document WITHOUT the key (an older console payload) must
    preserve the existing annotation, never wipe it."""
    from agentic.review import decide, propose_graph_change

    treg, tmp = _temp_registry()
    slug = next(iter(treg.projects))
    out = propose_graph_change(
        treg, slug,
        documents=[{"id": "doc-t", "name": "Budget", "dateModified": "2026-07-01",
                    "type": "spreadsheet"}])
    assert out["ok"], out
    assert decide(loader.load(tmp), out["id"], "accept", "")["ok"]
    graph_file = tmp / "registry" / "graph" / f"{slug}.jsonld"
    assert '"additionalType": "spreadsheet"' in graph_file.read_text(encoding="utf-8")

    # re-upsert the same doc with no `type` key → annotation survives
    treg2 = loader.load(tmp)
    out2 = propose_graph_change(
        treg2, slug,
        documents=[{"id": "doc-t", "name": "Budget (renamed)",
                    "dateModified": "2026-07-02"}])
    assert out2["ok"], out2
    assert decide(loader.load(tmp), out2["id"], "accept", "")["ok"]
    text = graph_file.read_text(encoding="utf-8")
    assert "Budget (renamed)" in text
    assert '"additionalType": "spreadsheet"' in text, \
        "an upsert without `type` must not wipe the existing annotation"


# ── ops: compile/deploy from the console ─────────────────────────────────────

def _wait_until_idle(timeout=5.0):
    """Poll ops_status() until running is False or timeout — the test analogue of the
    frontend's poll loop. Bounded so a stuck job fails the test instead of hanging it."""
    import time

    from agentic.review import ops_status

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = ops_status()
        if not snap["running"]:
            return snap
        time.sleep(0.02)
    raise AssertionError("op did not finish before timeout")


def test_ops_status_shape_when_idle():
    from agentic.review import ops_status

    snap = ops_status()
    assert snap["running"] is False
    assert set(snap) == {"running", "kind", "machine", "log", "rc", "started_at", "finished_at"}


def test_run_compile_success_and_lock_contention():
    from agentic import review

    treg, tmp = _temp_registry()
    treg.root = tmp  # dist/ lands in the temp registry, never the real repo's dist/

    result = review.run_compile(treg)
    assert result["ok"] is True
    assert result["rc"] == 0
    assert "compiled" in result["log"]
    assert (tmp / "dist").is_dir()

    snap = _wait_until_idle()
    assert snap["kind"] == "compile"
    assert snap["rc"] == 0

    # a second op while one is (still, or again) mid-flight must be refused, never queued —
    # simulate contention directly since compile finishes before the harness can race it
    assert review._OPS_LOCK.acquire(blocking=False)
    try:
        assert review.run_compile(treg) == {"ok": False, "error": "an operation is already running"}
        assert review.run_deploy_apply(treg, "rig") == \
            {"ok": False, "error": "an operation is already running"}
    finally:
        review._OPS_LOCK.release()


def test_run_deploy_plan_reflects_compute_deploy_plan():
    from agentic.commands import compute_deploy_plan
    from agentic.review import run_deploy_plan

    result = run_deploy_plan(reg, "example-linux")
    assert result["ok"] is True
    plan = compute_deploy_plan(reg, "example-linux")
    assert len(result["statuses"]) == len(plan.statuses)
    assert {s["path"] for s in result["statuses"]} == {s.output.deploy_path for s in plan.statuses}
    assert result["blocked_count"] == len(plan.blocked)
    assert sorted(result["orphans"]) == sorted(plan.orphans)

    assert run_deploy_plan(reg, "no-such-machine") == \
        {"ok": False, "error": "unknown machine 'no-such-machine'"}


def test_run_deploy_plan_surfaces_hard_refusal_for_example_machine():
    """Regression guard: the preview must warn about a guaranteed refusal (example-template
    machine) up front — a plan that looks normal but whose Confirm & Deploy would always be
    refused is worse than not previewing at all."""
    from agentic.review import run_deploy_plan

    result = run_deploy_plan(reg, "example-linux")
    assert result["ok"] is True
    assert result["refusal"] is not None
    assert "example template" in result["refusal"]

    # a non-example machine profile is not pre-emptively refused (may still have drift, but
    # that's compute_deploy_plan's softer, recoverable signal — not this hard guard)
    treg, tmp = _temp_registry()
    assert run_deploy_plan(treg, "rig")["refusal"] is None


def test_deploy_apply_refusal_matches_cmd_deploy_guard_messages():
    from agentic.commands import cmd_deploy, deploy_apply_refusal

    refusal = deploy_apply_refusal(reg, "example-windows")
    assert refusal is not None
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cmd_deploy(reg, "example-windows", dry_run=False, force=False, root=None)
    assert rc == 2
    assert refusal in out.getvalue()


def test_run_deploy_apply_writes_files_and_updates_ops_state():
    from agentic import commands, review

    treg, tmp = _temp_registry()
    root = tmp / "sandbox"
    # run_deploy_apply always calls cmd_deploy without root=, so point it at a sandbox by
    # wrapping cmd_deploy for the duration of this test — mirrors how the console never
    # deploys to real paths from a temp registry rig.
    orig = commands.cmd_deploy
    commands.cmd_deploy = lambda r, m, dry_run, force: orig(r, m, dry_run, force, root=root)
    try:
        result = review.run_deploy_apply(treg, "rig")
        assert result == {"ok": True, "started": True}
        snap = _wait_until_idle()
        assert snap["kind"] == "deploy"
        assert snap["machine"] == "rig"
        assert snap["rc"] == 0
        assert "deployed" in snap["log"]
        assert any(root.rglob("SOUL.md"))
    finally:
        commands.cmd_deploy = orig

    # unknown machine is rejected before any lock is taken
    assert review.run_deploy_apply(treg, "no-such-machine") == \
        {"ok": False, "error": "unknown machine 'no-such-machine'"}
