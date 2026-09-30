"""Tests for the operator console backend (build/agentic/review.py)."""
from __future__ import annotations

import copy

import yaml

from conftest import loader, reg, _inbox, _plant_candidate, _temp_registry


def _one_machine_rig(**machine):
    """A registry whose fleet is exactly one machine — the fresh-install shape."""
    rig = copy.deepcopy(reg)
    rig.machines.clear()
    rig.machines["box"] = {"name": "box", "os": "windows", "paths": {}, **machine}
    return rig


def test_deploys_here_scopes_the_console_to_what_a_machine_receives():
    """The console shows every registry item but TAGS each with `deploys_here`, so a fresh
    coding-harness install opens on its own content instead of the agent-only core skills.

    The tag is asked of `planner._selected_skills` — the same function deploy uses — so the
    connection gate counts too: `gws` targets claude-code but declares `requires_server:
    gws`, and must read False until the machine declares that store. A `targets`-only test
    would get that one wrong."""
    from agentic.review import prompt_index

    coding = _one_machine_rig(targets=["claude-code"])
    unwired = {s["name"] for s in prompt_index(coding)["skills"] if s["deploys_here"]}
    wired = _one_machine_rig(targets=["claude-code"], document_store="gws")
    connected = {s["name"] for s in prompt_index(wired)["skills"] if s["deploys_here"]}

    # The gate under test: gws and graph-bootstrap target claude-code but need a store this machine lacks.
    assert "gws" not in unwired and "graph-bootstrap" not in unwired, f"an unwired connection must hide its skill: {unwired}"
    assert "gws" in connected and "graph-bootstrap" in connected, f"wiring the store reveals gws: {connected}"
    assert connected - {"gws", "graph-bootstrap"} == unwired
    assert not unwired, f"no core skill deploys to a bare coding box: {unwired}"

    # nothing is dropped from the payload — the console's "All" chip still reveals them
    assert {s["name"] for s in prompt_index(coding)["skills"]} == set(reg.skills)


def test_deploys_here_shows_everything_on_a_fresh_clone():
    """No real machines yet (only the shipped `example: true` templates) — `real_machines`
    falls back to them, so the quick-start browse still shows content. Same step-aside
    convention as planner._suppressed_examples."""
    from agentic.review import prompt_index

    rig = copy.deepcopy(reg)
    assert all(m.get("example") for m in rig.machines.values()), \
        "core ships only example machines — if that changes, this test's premise is gone"
    assert any(s["deploys_here"] for s in prompt_index(rig)["skills"])


def test_console_only_prompt_always_reads_as_available():
    """A prompt with no `targets:` was never meant to deploy (registry/prompts/), so
    'would a machine receive it' is the wrong question — it must not be scoped away."""
    from agentic.review import prompt_index

    rig = _one_machine_rig(targets=["claude-code"])
    for p in prompt_index(rig)["prompts"]:
        if not p["targets"]:
            assert p["deploys_here"], f"console-only prompt {p['name']} was hidden"


def test_state_exposes_machine_targets_separately_from_known_targets():
    """Two lists, not interchangeable: `known_targets` is every adapter (the AUTHORING
    forms — a skill may target a machine you haven't built), `machine_targets` is only what
    your machines declare (the FILTER chips). Mixing them is what offered wrong filter chips."""
    from agentic.review import state

    st = state(_one_machine_rig(targets=["claude-code"]))
    assert st["machine_targets"] == ["claude-code"]
    assert "context-tree" in st["known_targets"], "authoring must still offer every adapter"
    assert "context-tree" not in st["machine_targets"]


def test_graph_index_lists_local_projects_regardless_of_drive_key():
    """graph_index must list every local project — presence or absence of 'drive' is irrelevant.

    Regression guard for the bug where `drive: {}` (falsy dict) hid a project from the
    Knowledge Graph sidebar even when its staging file existed."""
    from agentic.review import graph_index

    rig = copy.deepcopy(reg)
    # project with no drive key at all — must appear
    rig.projects["proj-no-drive"] = {
        "name": "No Drive", "slug": "proj-no-drive", "_is_local": True,
        "local_path": {}, "context": {},
        "document_store": "gws",
    }
    # project with empty drive dict — the original bug trigger
    rig.projects["proj-empty-drive"] = {
        "name": "Empty Drive", "slug": "proj-empty-drive", "_is_local": True,
        "local_path": {}, "context": {},
        "document_store": "gws",
        "drive": {},
    }
    # project with a populated drive block — must continue to appear
    rig.projects["proj-full-drive"] = {
        "name": "Full Drive", "slug": "proj-full-drive", "_is_local": True,
        "local_path": {}, "context": {},
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
        "local_path": {}, "context": {},
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


def test_propose_project_edit_creates_kind_project_candidate_and_accepts_cleanly():
    """propose_project_edit -> decide() round-trip: name/description/stage/repo/repo_notes
    land in the manifest verbatim, everything else (document_store, local_path, context)
    passes through untouched, and the result reloads cleanly from disk."""
    from agentic import loader as loadermod
    from agentic.review import decide, graph_index, load_candidates, propose_project_edit

    treg, tmp = _temp_registry()
    out = propose_project_edit(treg, "example-project", {
        "name": "Example Project Renamed",
        "description": "an updated one-line summary",
        "stage": "maintain",
        "repo": ["git@github.com:you/x.git", "git@github.com:you/y.git"],
        "repo_notes": {"x": "the main checkout"},
    }, "")
    assert out["ok"], out
    assert out["registry_path"] == "projects/example-project.yaml"

    candidates = load_candidates(treg)
    mine = next(c for c in candidates if c["id"] == out["id"])
    assert mine["kind"] == "project"
    assert mine["acceptable"]
    assert mine["project"] == "example-project"

    result = decide(treg, out["id"], "accept", "")
    assert result["ok"], result
    assert result["changed"] == ["projects/example-project.yaml"]
    written = tmp / "registry" / "projects" / "example-project.yaml"
    text = written.read_text(encoding="utf-8")
    assert "Example Project Renamed" in text
    assert "an updated one-line summary" in text
    assert "maintain" in text

    reloaded = loadermod.load(tmp)
    proj = reloaded.projects["example-project"]
    assert proj["name"] == "Example Project Renamed"
    assert proj["stage"] == "maintain"
    assert proj["repo"] == ["git@github.com:you/x.git", "git@github.com:you/y.git"]
    assert proj["repo_notes"] == {"x": "the main checkout"}
    # untouched fields survive the edit
    assert proj["document_store"] == "none"
    assert proj["local_path"] == {"example-windows": "example-project"}

    idx = next(g for g in graph_index(reloaded) if g["slug"] == "example-project")
    assert idx["stage"] == "maintain"
    assert idx["repo_notes"] == {"x": "the main checkout"}


def test_propose_project_edit_rejects_unknown_field():
    from agentic.review import propose_project_edit

    treg, tmp = _temp_registry()
    out = propose_project_edit(treg, "example-project", {"unknown_custom_field": "val"}, "")
    assert not out["ok"]
    assert "unknown_custom_field" in out["error"]


def test_propose_project_edit_rejects_bad_repo_notes():
    """A repo_notes key that doesn't match any repo's checkout basename fails loader
    validation at PROPOSE time — never reaches the inbox."""
    from agentic.review import propose_project_edit

    treg, tmp = _temp_registry()
    out = propose_project_edit(treg, "example-project", {
        "repo": "git@github.com:you/x.git",
        "repo_notes": {"nope": "wrong key"},
    }, "")
    assert not out["ok"]
    assert "does not match any" in out["error"]
    assert not (loader.inbox_dir(treg)).is_dir() or not list(loader.inbox_dir(treg).iterdir())


def test_propose_project_edit_rejects_unknown_project():
    from agentic.review import propose_project_edit

    treg, tmp = _temp_registry()
    out = propose_project_edit(treg, "does-not-exist", {"name": "x"}, "")
    assert not out["ok"]
    assert "unknown project" in out["error"]


def test_propose_project_edit_clearing_repo_removes_repo_notes_too():
    """Clearing `repo` while `repo_notes` is left unset in this edit must still pass
    validation — repo_notes only carries forward if the caller explicitly resends it, and
    an edit that drops repo entirely must not leave an orphaned repo_notes behind."""
    from agentic.review import decide, propose_project_edit

    treg, tmp = _temp_registry()
    treg.projects["example-project"]["repo"] = "git@github.com:you/x.git"
    treg.projects["example-project"]["repo_notes"] = {"x": "note"}

    out = propose_project_edit(treg, "example-project", {"repo": [], "repo_notes": {}}, "")
    assert out["ok"], out
    result = decide(treg, out["id"], "accept", "")
    assert result["ok"], result
    written = tmp / "registry" / "projects" / "example-project.yaml"
    text = written.read_text(encoding="utf-8")
    assert "repo_notes" not in text


def test_graph_index_exposes_effort_keywords_and_project_skills():
    from dataclasses import replace
    from agentic.review import graph_index
    treg, _ = _temp_registry()
    treg.projects["example-project"]["skills"] = ["tests"]
    pg = treg.graphs["example-project"]
    assert pg.efforts, "example-project should have at least one effort"
    pg.efforts = [replace(pg.efforts[0], keywords="alias1, alias2")] + list(pg.efforts[1:])

    idx = graph_index(treg)
    proj_entry = next(p for p in idx if p["slug"] == "example-project")
    assert "skills" in proj_entry
    assert proj_entry["skills"] == ["tests"]

    effort_entry = next(e for e in proj_entry["efforts"] if e["id"] == pg.efforts[0].id)
    assert "keywords" in effort_entry
    assert effort_entry["keywords"] == "alias1, alias2"


def test_propose_project_edit_sets_and_clears_skills():
    """Setting skills lands in the candidate and survives Accept round-trip; passing []
    clears the skills key from the manifest cleanly."""
    from agentic import loader as loadermod
    from agentic.review import decide, load_candidates, propose_project_edit

    treg, tmp = _temp_registry()
    skill_dir = tmp / "registry" / "skills" / "git-auto-commit"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: git-auto-commit\nscope: project\ntargets: [claude-code]\n---\nbody\n",
        encoding="utf-8",
    )
    treg = loadermod.load(tmp)

    out = propose_project_edit(treg, "example-project", {"skills": ["git-auto-commit"]}, "")
    assert out["ok"], out
    assert out["registry_path"] == "projects/example-project.yaml"

    candidates = load_candidates(treg)
    cand = next(c for c in candidates if c["id"] == out["id"])
    assert "skills:" in cand["payload"]
    assert "git-auto-commit" in cand["payload"]

    result = decide(treg, out["id"], "accept", "")
    assert result["ok"], result
    reloaded = loadermod.load(tmp)
    assert reloaded.projects["example-project"].get("skills") == ["git-auto-commit"]

    # Clearing skills with [] removes the key
    out2 = propose_project_edit(reloaded, "example-project", {"skills": []}, "")
    assert out2["ok"], out2
    result2 = decide(reloaded, out2["id"], "accept", "")
    assert result2["ok"], result2
    reloaded2 = loadermod.load(tmp)
    assert "skills" not in reloaded2.projects["example-project"]
    written = tmp / "registry" / "projects" / "example-project.yaml"
    assert "skills:" not in written.read_text(encoding="utf-8")


def test_propose_project_edit_rejects_unknown_skill():
    from agentic.review import propose_project_edit

    treg, _ = _temp_registry()
    out = propose_project_edit(treg, "example-project", {"skills": ["unknown-skill-xyz"]}, "")
    assert not out["ok"]
    assert "unknown skill 'unknown-skill-xyz'" in out["error"]


def test_propose_project_edit_rejects_non_list_skills():
    from agentic.review import propose_project_edit

    treg, _ = _temp_registry()
    out = propose_project_edit(treg, "example-project", {"skills": "git-auto-commit"}, "")
    assert not out["ok"]
    assert "skills must be a list" in out["error"]


def test_propose_project_edit_leaves_skills_untouched_when_absent():
    """Pass-through regression: an edit not naming skills leaves existing bindings untouched."""
    import yaml as _y
    from agentic import loader as loadermod
    from agentic.review import decide, propose_project_edit

    treg, tmp = _temp_registry()
    skill_dir = tmp / "registry" / "skills" / "git-auto-commit"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: git-auto-commit\nscope: project\ntargets: [claude-code]\n---\nbody\n",
        encoding="utf-8",
    )
    proj_path = tmp / "registry" / "projects" / "example-project.yaml"
    proj_data = _y.safe_load(proj_path.read_text(encoding="utf-8"))
    proj_data["skills"] = ["git-auto-commit"]
    proj_path.write_text(_y.safe_dump(proj_data), encoding="utf-8")
    treg = loadermod.load(tmp)

    out = propose_project_edit(treg, "example-project", {"description": "updated description"}, "")
    assert out["ok"], out
    result = decide(treg, out["id"], "accept", "")
    assert result["ok"], result

    reloaded = loadermod.load(tmp)
    assert reloaded.projects["example-project"].get("skills") == ["git-auto-commit"]


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
        {"description": "Helps with widgets.", "targets": ["overlay-harness"], "category": "devops"},
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


def test_propose_new_prompt_creates_kind_new_candidate_and_accepts_cleanly():
    """propose_new_prompt mirrors skill creation but targets the simpler prompts schema."""
    from agentic import loader as loadermod
    from agentic.review import decide, load_candidates, propose_new_prompt

    treg, tmp = _temp_registry()
    out = propose_new_prompt(
        treg, "my-prompt",
        {"description": "A test prompt.", "targets": ["overlay-harness"], "category": "devops"},
        "Prompt body text.", "")
    assert out["ok"], out
    assert out["registry_path"] == "local/prompts/my-prompt.md"

    candidates = load_candidates(treg)
    mine = next(c for c in candidates if c["id"] == out["id"])
    assert mine["kind"] == "new"
    assert mine["acceptable"]

    result = decide(treg, out["id"], "accept", "")
    assert result["ok"], result
    written = tmp / "registry" / "local" / "prompts" / "my-prompt.md"
    assert written.is_file()
    text = written.read_text(encoding="utf-8")
    assert "name: my-prompt" in text
    assert "Prompt body text." in text

    # the new prompt is now loadable from disk
    reloaded = loadermod.load(tmp)
    assert "my-prompt" in reloaded.prompts


def test_propose_new_prompt_rejects_duplicate_name():
    from agentic.review import propose_new_prompt
    treg, _ = _temp_registry()
    out = propose_new_prompt(
        treg, "example-prompt", {"description": "A test prompt.", "targets": []}, "Body")
    assert not out["ok"]
    assert "already exists" in out["error"]


def test_propose_new_prompt_rejects_invalid_name():
    from agentic.review import propose_new_prompt
    treg, _ = _temp_registry()
    out = propose_new_prompt(
        treg, "Bad Name!", {"description": "A test prompt.", "targets": []}, "Body")
    assert not out["ok"]
    assert "lowercase alphanumerics" in out["error"]


def test_propose_new_prompt_rejects_empty_body():
    from agentic.review import propose_new_prompt
    treg, _ = _temp_registry()
    out = propose_new_prompt(
        treg, "new-prompt", {"description": "A test prompt.", "targets": []}, "   \n")
    assert not out["ok"]
    assert "body is required" in out["error"]


def test_propose_new_prompt_rejects_unknown_targets():
    from agentic.review import propose_new_prompt
    treg, _ = _temp_registry()
    out = propose_new_prompt(
        treg, "new-prompt", {"description": "A test prompt.", "targets": ["not-a-target"]}, "Body")
    assert not out["ok"]
    assert "unknown target" in out["error"]


def test_propose_new_prompt_console_only_no_targets():
    """Omitting targets entirely is valid for prompts (means console-only)."""
    from agentic.review import propose_new_prompt
    treg, _ = _temp_registry()
    out = propose_new_prompt(
        treg, "new-prompt", {"description": "A test prompt.", "targets": []}, "Body")
    assert out["ok"]


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


def _scope_key(scope):
    from agentic import staging
    return staging.scope_key(scope)


def _stage(tmp, docs, *, slug="example-project", scope=None, staged_at="2026-07-15T1200Z"):
    """Write a ONE-listing staging file (the current, canonical multi-listing shape with a
    single entry) — the store's truth snapshot the Recovery in_scope check compares
    against. `scope=None` means a full, unscoped listing (the only kind that alone can
    prove a document's absence, regardless of provenance). Use _stage_listings for
    multiple concurrent watches."""
    scope = scope or {"folder_id": None, "query": None,
                      "exclude_folders": [], "recursive": False, "store": ""}
    _stage_listings(tmp, [(docs, scope, staged_at)], slug=slug)


def _stage_listings(tmp, listings, *, slug="example-project"):
    """Write a MULTI-listing staging file. `listings` is [(docs, scope, staged_at), ...] —
    one entry per watched scope, scope_key computed the same way stage_listing does."""
    import json as _json
    staging_dir = _inbox(tmp) / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    payload = {"slug": slug, "listings": [
        {"scope_key": _scope_key(scope), "staged_at": staged_at, "connector": "mock",
         "scope": scope, "documents": docs}
        for docs, scope, staged_at in listings]}
    (staging_dir / f"{slug}.json").write_text(_json.dumps(payload), encoding="utf-8")


def test_permanent_dismiss_hides_from_recovery_but_stays_in_all_ids():
    """A permanent dismissal leaves Recovery (no undo in the console) while its id stays in
    all_ids — Discovery filters on that set, so the doc can never resurface there."""
    from agentic import review
    treg, tmp = _temp_registry()
    _stage(tmp, [])

    review.dismiss_docs(treg, "example-project", [{"id": "D1", "name": "Doc One"}])
    review.dismiss_docs(treg, "example-project", [{"id": "D2", "name": "Doc Two"}],
                        permanent=True)

    out = review.load_dismissed(treg, "example-project")
    assert [d["id"] for d in out["documents"]] == ["D1"]
    assert sorted(out["all_ids"]) == ["D1", "D2"]


def test_permanent_flag_survives_an_ordinary_redismiss():
    """permanent=False is every ordinary dismissal's default, NOT an instruction to
    un-permanent an existing record — only a hand edit of the sidecar reverses it."""
    from agentic import review
    treg, tmp = _temp_registry()
    _stage(tmp, [])
    doc = {"id": "D1", "name": "Doc One"}
    review.dismiss_docs(treg, "example-project", [doc], permanent=True)
    review.dismiss_docs(treg, "example-project", [doc])          # default permanent=False
    out = review.load_dismissed(treg, "example-project")
    assert out["documents"] == [] and out["all_ids"] == ["D1"]


def test_in_scope_flags_from_full_enumeration():
    """A full listing proves presence/absence: a dismissed doc still listed is in_scope
    True; one the store no longer lists is False."""
    from agentic import review
    treg, tmp = _temp_registry()
    _stage(tmp, [{"id": "D1", "name": "Doc One"}])
    review.dismiss_docs(treg, "example-project", [{"id": "D1", "name": "Doc One"}])
    review.dismiss_docs(treg, "example-project", [{"id": "GONE", "name": "Deleted Doc"}])

    flags = {d["id"]: d["in_scope"] for d in
             review.load_dismissed(treg, "example-project")["documents"]}
    assert flags == {"D1": True, "GONE": False}


def test_in_scope_is_none_for_scoped_or_absent_enumerations():
    """The critical guard: a SCOPED enumeration (one folder/query) says nothing about
    documents outside that scope, so nothing may be flagged missing from it. Same when no
    listing exists at all. None = no claim, and purge refuses to act on it."""
    from agentic import review
    treg, tmp = _temp_registry()

    # no staging file at all
    review.dismiss_docs(treg, "example-project", [{"id": "D1", "name": "Doc One"}])
    out = review.load_dismissed(treg, "example-project")
    assert out["documents"][0]["in_scope"] is None

    # a folder-scoped listing that doesn't include D1
    _stage(tmp, [{"id": "OTHER", "name": "Other"}],
           scope={"folder_id": "F1", "query": None, "exclude_folders": [],
                  "recursive": False, "store": ""})
    review.dismiss_docs(treg, "example-project", [{"id": "D1", "name": "Doc One"}])
    out2 = review.load_dismissed(treg, "example-project")
    assert out2["documents"][0]["in_scope"] is None
    # and it therefore cannot be purged
    assert review.purge_dismissed(treg, "example-project", ["D1"])["ok"] is False


def test_in_scope_present_in_any_listing_wins_over_own_scope_absence():
    """THE critical correctness test for multi-scope watching. Two overlapping watches
    both once produced doc SHARED. Watch A's next refresh drops it (SHARED left that
    folder), but watch B's listing still has it. The doc must read in_scope=True — it's
    still reachable through B — even though it is now absent from A, the very listing that
    (per its own recorded scope_keys) originally produced the dismissal. If presence-in-
    any-listing didn't take precedence over own-scope absence, this would wrongly flag
    (and let the operator purge) a document that's still live."""
    from agentic import review
    treg, tmp = _temp_registry()
    scope_a = {"folder_id": "FOLDER_A", "query": None, "exclude_folders": [],
               "recursive": False, "store": ""}
    scope_b = {"folder_id": "FOLDER_B", "query": None, "exclude_folders": [],
               "recursive": False, "store": ""}
    key_a = _scope_key(scope_a)

    # SHARED is staged under BOTH watches — dismiss it while it's still in both, so the
    # recorded provenance (scope_keys) includes watch A.
    _stage_listings(tmp, [
        ([{"id": "SHARED", "name": "Shared"}], scope_a, "2026-07-15T1000Z"),
        ([{"id": "SHARED", "name": "Shared"}], scope_b, "2026-07-15T1000Z"),
    ])
    staged = review.load_staged(treg, "example-project")
    shared_doc = next(d for d in staged["documents"] if d["id"] == "SHARED")
    assert sorted(shared_doc["scope_keys"]) == sorted([key_a, _scope_key(scope_b)])
    review.dismiss_docs(treg, "example-project", [shared_doc])

    # Watch A refreshes and no longer has SHARED (it left that folder). Watch B is
    # untouched and still has it.
    _stage_listings(tmp, [
        ([{"id": "OTHER_A", "name": "Other A"}], scope_a, "2026-07-15T1100Z"),
        ([{"id": "SHARED", "name": "Shared"}], scope_b, "2026-07-15T1000Z"),
    ])
    out = review.load_dismissed(treg, "example-project")
    flags = {d["id"]: d["in_scope"] for d in out["documents"]}
    assert flags["SHARED"] is True   # still reachable via watch B — must not be "missing"
    assert review.purge_dismissed(treg, "example-project", ["SHARED"])["ok"] is False

    # Now B ALSO drops it — no listing has it anywhere, and A's own recorded provenance
    # proves it: in_scope flips to False and purge succeeds.
    _stage_listings(tmp, [
        ([{"id": "OTHER_A", "name": "Other A"}], scope_a, "2026-07-15T1200Z"),
        ([{"id": "OTHER_B", "name": "Other B"}], scope_b, "2026-07-15T1200Z"),
    ])
    out2 = review.load_dismissed(treg, "example-project")
    assert {d["id"]: d["in_scope"] for d in out2["documents"]}["SHARED"] is False
    result = review.purge_dismissed(treg, "example-project", ["SHARED"])
    assert result["ok"] and result["cleared"] == ["SHARED"]


def test_in_scope_unrelated_scoped_listing_cannot_prove_absence():
    """A doc dismissed with no recorded provenance (legacy, or a "removal" auto-dismissal)
    must stay None even when SOME scoped listing exists — only a FULL listing, or that
    doc's own recorded scope, can prove absence. This is the guard that kept your real
    7-document mitos Recovery list untouched against a query-scoped listing."""
    from agentic import review
    treg, tmp = _temp_registry()
    # A scoped listing exists but has NOTHING to do with this doc's provenance. Staged
    # BEFORE the dismissal so the dismissal lands in this project's own dismissed file
    # (see _dismiss_file's pool fallback), not the shared unassigned one.
    _stage(tmp, [{"id": "UNRELATED", "name": "Unrelated"}],
           scope={"folder_id": "SOME_OTHER_FOLDER", "query": None,
                  "exclude_folders": [], "recursive": False, "store": ""})
    # A doc with no scope_keys provenance (dict has no "scope_keys" key at all)
    review.dismiss_docs(treg, "example-project", [{"id": "LEGACY", "name": "Legacy Doc"}])
    out = review.load_dismissed(treg, "example-project")
    assert out["documents"][0]["in_scope"] is None
    assert review.purge_dismissed(treg, "example-project", ["LEGACY"])["ok"] is False


def test_purge_dismissed_only_clears_what_the_store_lost():
    """purge re-checks in_scope server-side: a stale tab asking to clear a live document
    is refused, and only the genuinely-missing id leaves the sidecar."""
    from agentic import review
    treg, tmp = _temp_registry()
    _stage(tmp, [{"id": "LIVE", "name": "Still There"}])
    review.dismiss_docs(treg, "example-project", [{"id": "LIVE", "name": "Still There"}])
    review.dismiss_docs(treg, "example-project", [{"id": "GONE", "name": "Deleted"}])

    # asking for both clears only GONE
    out = review.purge_dismissed(treg, "example-project", ["LIVE", "GONE"])
    assert out["ok"] and out["cleared"] == ["GONE"]
    assert [d["id"] for d in review.load_dismissed(treg, "example-project")["documents"]] \
        == ["LIVE"]

    # asking for a live doc alone is refused outright
    assert review.purge_dismissed(treg, "example-project", ["LIVE"])["ok"] is False
    # the purged rows carry no in_scope key back onto disk (it's derived, not stored)
    import json as _json
    raw = _json.loads((_inbox(tmp) / "staging" / "example-project.dismissed.json")
                      .read_text(encoding="utf-8"))
    assert all("in_scope" not in d for d in raw["documents"])


def test_purge_and_refresh_reject_invalid_slug():
    from agentic import review
    treg, _tmp = _temp_registry()
    for bad in ("../etc", "", ".", ".."):
        assert review.purge_dismissed(treg, bad, ["X"])["ok"] is False
        assert review.refresh_staging(treg, bad)["ok"] is False


def test_refresh_staging_requires_a_recorded_scope():
    """Without a recorded folder/query scope there's no enumeration to replay — the console
    falls back to the copyable CLI command rather than guessing."""
    from agentic import review
    treg, tmp = _temp_registry()
    # nothing staged yet
    assert review.refresh_staging(treg, "example-project")["ok"] is False
    # staged, but scopeless (a listing written before scopes were recorded)
    _stage(tmp, [{"id": "D1", "name": "Doc"}],
           scope={"folder_id": None, "query": None, "exclude_folders": []})
    out = review.refresh_staging(treg, "example-project")
    assert out["ok"] is False and "scope" in out["error"]


def test_refresh_staging_shells_out_to_mitos_with_the_recorded_scope(monkeypatch):
    """The connector runs in a mitos.py SUBPROCESS — review.py imports no network code
    (invariant #11). Assert the replayed command carries the recorded scope verbatim."""
    import subprocess as _sp

    from agentic import review
    treg, tmp = _temp_registry()
    _stage(tmp, [{"id": "D1", "name": "Doc"}],
           scope={"folder_id": "F123", "query": None, "exclude_folders": [],
                  "recursive": True, "store": "gws"})
    seen = {}

    class _Done:
        returncode = 0
        stdout = "staged 1 document(s)."
        stderr = ""

    def _fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return _Done()

    monkeypatch.setattr(_sp, "run", _fake_run)
    out = review.refresh_staging(treg, "example-project")
    assert out["ok"], out
    cmd = seen["cmd"]
    assert cmd[1].endswith("mitos.py") and "connect" in cmd and "--stage" in cmd
    assert cmd[cmd.index("--project") + 1] == "example-project"
    assert cmd[cmd.index("--folder-id") + 1] == "F123"
    assert cmd[cmd.index("--store") + 1] == "gws"
    assert "--recursive" in cmd and "--query" not in cmd


def test_refresh_staging_surfaces_a_failing_connect(monkeypatch):
    import subprocess as _sp

    from agentic import review
    treg, tmp = _temp_registry()
    _stage(tmp, [{"id": "D1", "name": "Doc"}],
           scope={"folder_id": "F1", "query": None, "exclude_folders": [],
                  "recursive": False, "store": ""})

    class _Fail:
        returncode = 1
        stdout = ""
        stderr = "connector error: token expired"

    monkeypatch.setattr(_sp, "run", lambda cmd, **kw: _Fail())
    out = review.refresh_staging(treg, "example-project")
    assert out["ok"] is False and "token expired" in out["error"]


def test_refresh_staging_with_multiple_listings_requires_scope_key(monkeypatch):
    """More than one watched listing and no scope_key given → refuse rather than guess
    which one to refresh; the right scope_key targets exactly that listing and leaves its
    sibling untouched."""
    import subprocess as _sp

    from agentic import review
    treg, tmp = _temp_registry()
    scope_a = {"folder_id": "FA", "query": None, "exclude_folders": [],
               "recursive": False, "store": ""}
    scope_b = {"folder_id": "FB", "query": None, "exclude_folders": [],
               "recursive": False, "store": ""}
    _stage_listings(tmp, [
        ([{"id": "A1", "name": "A1"}], scope_a, "2026-07-15T1000Z"),
        ([{"id": "B1", "name": "B1"}], scope_b, "2026-07-15T1000Z"),
    ])

    # ambiguous: two listings, no scope_key
    out = review.refresh_staging(treg, "example-project")
    assert out["ok"] is False and "watched listings" in out["error"]

    seen = {}

    class _Done:
        returncode = 0
        stdout = "staged 1 document(s)."
        stderr = ""

    def _fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return _Done()

    monkeypatch.setattr(_sp, "run", _fake_run)
    key_a = _scope_key(scope_a)
    out2 = review.refresh_staging(treg, "example-project", scope_key=key_a)
    assert out2["ok"], out2
    cmd = seen["cmd"]
    assert cmd[cmd.index("--folder-id") + 1] == "FA"   # replayed watch A's scope, not B's

    # unknown scope_key is rejected
    out3 = review.refresh_staging(treg, "example-project", scope_key="nope")
    assert out3["ok"] is False


def _identity_fragment(effort_id: str, extra: str = "") -> str:
    """A planning-harness-shaped Implemented Document body carrying the identity fragment
    (docs/implemented-document-identity.md) — mirrors overlay-harness's
    `evaluation.identity_fragment` output exactly, so these tests exercise the real contract
    rather than a stand-in shape."""
    return (
        "# Implemented: demo__launch-prep\n\n"
        "_Run `r-1` · score 100/100._\n\n" + extra +
        "## Identity\n\n```json\n"
        '{\n  "@context": {"@vocab": "https://schema.org/"},\n'
        '  "@type": "DigitalDocument",\n'
        '  "additionalType": "implemented-requirements",\n'
        f'  "isPartOf": {{"@id": "http://peccia.net/creativework/{effort_id}"}},\n'
        '  "identifier": "r-1"\n}\n```\n')


def test_extract_identity_effort_finds_a_known_effort():
    from agentic import review
    treg, _tmp = _temp_registry()
    pg = treg.graphs["example-project"]   # ships an effort with id "launch-prep"
    assert review.extract_identity_effort(_identity_fragment("launch-prep"), pg) == \
        "launch-prep"


def test_extract_identity_effort_ignores_an_unknown_effort_id():
    """The fragment parses fine but names an effort this project's graph has never heard
    of — degrades to no suggestion, never a guess."""
    from agentic import review
    treg, _tmp = _temp_registry()
    pg = treg.graphs["example-project"]
    assert review.extract_identity_effort(_identity_fragment("no-such-effort"), pg) == ""


def test_extract_identity_effort_ignores_malformed_json():
    from agentic import review
    treg, _tmp = _temp_registry()
    pg = treg.graphs["example-project"]
    broken = "## Identity\n\n```json\n{ not: valid json\n```\n"
    assert review.extract_identity_effort(broken, pg) == ""


def _return_record_fragment(effort_id: str, delivers: str = "tests") -> str:
    """A published return record's body — the `return-record` variant of the same contract,
    the shape the seven `delivers:` skills tell a coding harness to append to the STORE copy."""
    return (
        f"# {delivers}\n\n## Added\n\n- a test\n\n"
        "## Identity\n\n```json\n"
        '{\n  "@context": {"@vocab": "https://schema.org/"},\n'
        '  "@type": "DigitalDocument",\n'
        '  "additionalType": "return-record",\n'
        f'  "isPartOf": {{"@id": "http://peccia.net/creativework/{effort_id}"}},\n'
        '  "identifier": "demo__launch-prep-20260828T212400Z",\n'
        f'  "http://peccia.net/deliverable": "{delivers}"\n}}\n```\n')


def test_a_return_record_is_not_offered_as_a_project_document():
    """The regression this exists for. A run's return records are overlay harness's raw input — the
    several per-deliverable documents it reads to produce ONE Implemented Document — and they are
    not project context. Recognizing them here mapped four of them to an effort, which rendered
    them into that project's generated AGENTS.md, which made a finished run's claims ("npm audit
    reports 0 vulnerabilities") always-on fact for every later session.

    The block still parses and still names a real effort; Mitos simply does not claim it."""
    from agentic import review
    treg, _tmp = _temp_registry()
    pg = treg.graphs["example-project"]
    assert review.extract_identity_effort(_return_record_fragment("launch-prep"), pg) == ""


def test_the_implemented_document_is_still_recognized():
    """The narrowing must not take the graduation document with it: ONE evaluated document per
    Work item is exactly what this view exists to map."""
    from agentic import review
    treg, _tmp = _temp_registry()
    pg = treg.graphs["example-project"]
    frag = _return_record_fragment("launch-prep").replace("return-record",
                                                          "implemented-requirements")
    assert review.extract_identity_effort(frag, pg) == "launch-prep"


def test_identity_types_are_a_closed_set():
    from agentic import review
    assert review.IDENTITY_TYPES == ("implemented-requirements",)


def test_extract_identity_effort_ignores_the_wrong_additional_type():
    """Only the two `IDENTITY_TYPES` count — any other JSON-LD block a document happens
    to carry is not this contract and must not be read as one."""
    from agentic import review
    treg, _tmp = _temp_registry()
    pg = treg.graphs["example-project"]
    other = ('```json\n{"@type": "DigitalDocument", "additionalType": "something-else", '
             '"isPartOf": {"@id": "http://peccia.net/creativework/launch-prep"}}\n```\n')
    assert review.extract_identity_effort(other, pg) == ""


def test_extract_identity_effort_with_no_graph_yet_finds_nothing():
    """A project with no knowledge graph at all — `pg` is None — must not crash; there is
    nothing to confirm the suggestion against, so none is offered."""
    from agentic import review
    assert review.extract_identity_effort(_identity_fragment("launch-prep"), None) == ""


def test_peek_identity_effort_prefills_from_a_staged_document(monkeypatch):
    """End-to-end through the console function the API endpoint calls: a staged document
    whose content carries the fragment yields the prefilled suggestion."""
    import subprocess as _sp

    from agentic import review
    treg, tmp = _temp_registry()
    _stage(tmp, [{"id": "D1", "name": "Implemented: demo"}],
           scope={"folder_id": "F1", "query": None, "exclude_folders": [],
                  "recursive": False, "store": "gws"})

    class _Done:
        returncode = 0
        stdout = _identity_fragment("launch-prep")
        stderr = ""

    seen = {}

    def _fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return _Done()

    monkeypatch.setattr(_sp, "run", _fake_run)
    out = review.peek_identity_effort(treg, "example-project", "D1")
    assert out == {"ok": True, "effort_id": "launch-prep"}
    cmd = seen["cmd"]
    assert cmd[1].endswith("mitos.py") and "peek" in cmd
    assert cmd[cmd.index("--store") + 1] == "gws"
    assert cmd[cmd.index("--id") + 1] == "D1"


def test_peek_identity_effort_degrades_silently_when_theres_no_fragment(monkeypatch):
    """The overwhelmingly common case (an ordinary document with no fragment at all): no
    error, just no suggestion — the operator maps by hand exactly as before this existed."""
    import subprocess as _sp

    from agentic import review
    treg, tmp = _temp_registry()
    _stage(tmp, [{"id": "D1", "name": "Some other doc"}],
           scope={"folder_id": "F1", "query": None, "exclude_folders": [],
                  "recursive": False, "store": "gws"})

    class _Done:
        returncode = 0
        stdout = "# Some other doc\n\njust prose, no identity block.\n"
        stderr = ""

    monkeypatch.setattr(_sp, "run", lambda cmd, **kw: _Done())
    assert review.peek_identity_effort(treg, "example-project", "D1") == \
        {"ok": True, "effort_id": ""}


def test_peek_identity_effort_degrades_silently_on_a_failed_fetch(monkeypatch):
    import subprocess as _sp

    from agentic import review
    treg, tmp = _temp_registry()
    _stage(tmp, [{"id": "D1", "name": "Doc"}],
           scope={"folder_id": "F1", "query": None, "exclude_folders": [],
                  "recursive": False, "store": "gws"})

    class _Fail:
        returncode = 1
        stdout = ""
        stderr = "connector error: token expired"

    monkeypatch.setattr(_sp, "run", lambda cmd, **kw: _Fail())
    assert review.peek_identity_effort(treg, "example-project", "D1") == \
        {"ok": True, "effort_id": ""}


def test_peek_identity_effort_with_no_recorded_store_skips_the_fetch(monkeypatch):
    """A document with no `scope_keys`/store provenance (or simply not staged at all) can't
    be fetched — never guess a store, just answer no suggestion without shelling out."""
    import subprocess as _sp

    from agentic import review
    treg, tmp = _temp_registry()
    _stage(tmp, [{"id": "D1", "name": "Doc"}])   # default scope carries store: ""

    called = []
    monkeypatch.setattr(_sp, "run", lambda cmd, **kw: called.append(cmd))
    assert review.peek_identity_effort(treg, "example-project", "D1") == \
        {"ok": True, "effort_id": ""}
    assert not called


def test_remove_watch_drops_one_listing_leaves_the_other():
    from agentic import review
    treg, tmp = _temp_registry()
    scope_a = {"folder_id": "FA", "query": None, "exclude_folders": [],
               "recursive": False, "store": ""}
    scope_b = {"folder_id": "FB", "query": None, "exclude_folders": [],
               "recursive": False, "store": ""}
    _stage_listings(tmp, [
        ([{"id": "A1", "name": "A1"}], scope_a, "2026-07-15T1000Z"),
        ([{"id": "B1", "name": "B1"}], scope_b, "2026-07-15T1000Z"),
    ])
    key_a = _scope_key(scope_a)
    out = review.remove_watch(treg, "example-project", scope_key=key_a)
    assert out["ok"], out
    staged = review.load_staged(treg, "example-project")
    assert len(staged["listings"]) == 1
    assert staged["listings"][0]["scope_key"] == _scope_key(scope_b)
    assert [d["id"] for d in staged["documents"]] == ["B1"]

    # removing the same key again finds nothing left to remove
    out2 = review.remove_watch(treg, "example-project", scope_key=key_a)
    assert out2["ok"] is False

    # removing the last listing leaves an empty (not absent) staging file
    review.remove_watch(treg, "example-project", scope_key=_scope_key(scope_b))
    staged2 = review.load_staged(treg, "example-project")
    assert staged2["ok"] and staged2["listings"] == [] and staged2["documents"] == []


def test_remove_watch_rejects_invalid_slug_or_missing_key():
    from agentic import review
    treg, _tmp = _temp_registry()
    assert review.remove_watch(treg, "../etc", scope_key="x")["ok"] is False
    assert review.remove_watch(treg, "example-project", scope_key="")["ok"] is False
    assert review.remove_watch(treg, "example-project", scope_key="nope")["ok"] is False


def test_rename_watch_names_one_listing_without_touching_identity():
    """A label is cosmetic: the renamed listing keeps its scope_key (so refresh/dedupe are
    unaffected) and its documents, and the sibling watch is untouched."""
    from agentic import review
    treg, tmp = _temp_registry()
    scope_a = {"folder_id": "FA", "query": None, "exclude_folders": [],
               "recursive": False, "store": ""}
    scope_b = {"folder_id": "FB", "query": None, "exclude_folders": [],
               "recursive": False, "store": ""}
    _stage_listings(tmp, [
        ([{"id": "A1", "name": "A1"}], scope_a, "2026-07-15T1000Z"),
        ([{"id": "B1", "name": "B1"}], scope_b, "2026-07-15T1000Z"),
    ])
    key_a = _scope_key(scope_a)
    out = review.rename_watch(treg, "example-project", scope_key=key_a,
                              label="Marketing archive")
    assert out["ok"], out
    by_key = {l["scope_key"]: l for l in review.load_staged(treg, "example-project")["listings"]}
    assert by_key[key_a]["label"] == "Marketing archive"
    assert by_key[key_a]["scope"]["folder_id"] == "FA"
    assert by_key[key_a]["count"] == 1
    assert by_key[_scope_key(scope_b)]["label"] == ""


def test_rename_watch_cleans_and_clears_the_label():
    """Whitespace collapses, over-long names are capped, and an empty label clears the
    name — the console's undo, restoring the derived scope label."""
    from agentic import review, staging
    treg, tmp = _temp_registry()
    scope = {"folder_id": "FA", "query": None, "exclude_folders": [],
             "recursive": False, "store": ""}
    _stage_listings(tmp, [([{"id": "A1", "name": "A1"}], scope, "2026-07-15T1000Z")])
    key = _scope_key(scope)

    review.rename_watch(treg, "example-project", scope_key=key, label="  Docs \n  archive ")
    assert review.load_staged(treg, "example-project")["listings"][0]["label"] == "Docs archive"

    review.rename_watch(treg, "example-project", scope_key=key, label="x" * 200)
    assert len(review.load_staged(treg, "example-project")["listings"][0]["label"]) == staging.LABEL_MAX

    review.rename_watch(treg, "example-project", scope_key=key, label="   ")
    listing = review.load_staged(treg, "example-project")["listings"][0]
    assert listing["label"] == ""
    assert staging.listing_label(listing) == "folder FA"


def test_rename_watch_rejects_invalid_slug_or_missing_key():
    from agentic import review
    treg, tmp = _temp_registry()
    _stage(tmp, [{"id": "A1", "name": "A1"}])
    assert review.rename_watch(treg, "../etc", scope_key="x", label="n")["ok"] is False
    assert review.rename_watch(treg, "example-project", scope_key="", label="n")["ok"] is False
    assert review.rename_watch(treg, "example-project", scope_key="nope", label="n")["ok"] is False


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
    out = propose_new_skill(treg, existing, {"targets": ["overlay-harness"]}, "body")
    assert not out["ok"]

    # bad slug shape (uppercase / underscore)
    out = propose_new_skill(treg, "Bad_Name", {"targets": ["overlay-harness"]}, "body")
    assert not out["ok"]

    # empty targets
    out = propose_new_skill(treg, "new-skill", {"targets": []}, "body")
    assert not out["ok"]

    # unknown target
    out = propose_new_skill(treg, "new-skill", {"targets": ["not-a-real-target"]}, "body")
    assert not out["ok"]


def test_org_tree_reconstructs_context_tree_deploy_paths():
    from agentic.review import org_tree

    machine = next(m for m, cfg in reg.machines.items()
                   if "context-tree" in cfg.get("targets", []))
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


def test_state_lists_only_context_tree_machines():
    from agentic.review import state

    result = state(reg)
    assert "context_tree_machines" in result
    for m in result["context_tree_machines"]:
        assert "context-tree" in reg.machines[m].get("targets", [])
    # every machine that DOES carry context-tree must be listed
    for m, cfg in reg.machines.items():
        if "context-tree" in cfg.get("targets", []):
            assert m in result["context_tree_machines"]


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
                     "favorited", "deploys_here"}
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


def test_propose_graph_change_updates_effort_visibility_and_surfaces_in_graph_index():
    """Effort hidden status reaches the candidate, updates the graph on accept,
    and surfaces in graph_index."""
    from agentic.review import decide, graph_index, propose_graph_change
    from agentic import graph, loader as loadermod

    treg, tmp = _temp_registry()
    slug = next(iter(treg.projects))
    out = propose_graph_change(
        treg, slug, documents=[],
        efforts=[{"id": "eff-hide", "name": "Effort To Hide", "hidden": True}])
    assert out["ok"], out
    assert decide(loadermod.load(tmp), out["id"], "accept", "")["ok"]

    reloaded_reg = loadermod.load(tmp)
    merged = graph.load_project_graph(tmp / "registry" / "graph" / f"{slug}.jsonld")
    eff = next(e for e in merged.efforts if e.id == "eff-hide")
    assert eff.hidden is True

    idx = next(g for g in graph_index(reloaded_reg) if g["slug"] == slug)
    idx_eff = next(e for e in idx["efforts"] if e["id"] == "eff-hide")
    assert idx_eff["hidden"] is True


def test_prompt_index_frontmatter_whitelist_shape():
    """Skills/prompts carry a `frontmatter` dict scoped to the per-kind editable
    whitelist — never the full raw frontmatter (which may carry e.g. a skill's
    `overlay-harness:` block that has no place in the console's metadata panel)."""
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
    """Unlike the target-binding check, scope: project has no per-target
    incompatibility — overlay-harness/claude-app targets simply ignore it (see loader.
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
        treg, "res-skill", {"targets": ["overlay-harness"], "description": "d"},
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
        treg, "res-skill-bad", {"targets": ["overlay-harness"], "description": "d"}, "body",
        resources={"not-allowed/x.md": "text"})
    assert not out["ok"]
    assert "invalid resource path" in out["error"]


def _make_res_skill(treg, tmp):
    from agentic.review import decide, propose_new_skill
    out = propose_new_skill(
        treg, "res-abs-skill", {"targets": ["overlay-harness"], "description": "d"}, "body",
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
        treg, "res-visible-skill", {"targets": ["overlay-harness"], "description": "d"}, "body",
        resources={"examples/x.md": "x\n"})
    assert out["ok"], out
    cand = next(c for c in load_candidates(treg) if c["id"] == out["id"])
    assert cand["resources_provided"] is True
    assert cand["resources"] == {"examples/x.md": "x\n"}

    out2 = propose_new_skill(
        treg, "res-invisible-skill", {"targets": ["overlay-harness"], "description": "d"}, "body")
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


def test_load_candidates_doc_delta_computes_added_changed_removed():
    """batch2 item 2 (diff-aware candidates): load_candidates computes doc_delta by
    set-comparing the candidate's proposed documents against the CURRENT graph — added
    (new IDs), changed (same ID, different name/date/url/type/store), and removed
    (existing IDs absent from this candidate's enumeration — informational only, never
    auto-deleted)."""
    from agentic import graph
    from agentic.review import load_candidates, propose_graph_change

    treg, tmp = _temp_registry()
    slug = next(iter(treg.projects))
    gdir = tmp / "registry" / "graph"
    gdir.mkdir(parents=True, exist_ok=True)
    seed = graph.ProjectGraph(slug=slug, name="P", description="", documents=[
        graph.Document("KEEP", "Keeper", "d", "2026-01-01"),
        graph.Document("CHANGE", "Old Name", "d", "2026-01-01"),
        graph.Document("GONE", "Goner", "d", "2026-01-02")])
    (gdir / f"{slug}.jsonld").write_text(graph.canonical_jsonld(seed), encoding="utf-8")
    treg = loader.load(tmp)

    out = propose_graph_change(treg, slug, [
        {"id": "KEEP", "name": "Keeper", "description": "d", "dateModified": "2026-01-01"},
        {"id": "CHANGE", "name": "New Name", "description": "d", "dateModified": "2026-01-01"},
        {"id": "NEW", "name": "Fresh", "description": "d", "dateModified": "2026-07-01"}])
    assert out["ok"], out
    cand = next(c for c in load_candidates(treg) if c["id"] == out["id"])
    assert cand["doc_delta"] == {"added": ["NEW"], "changed": ["CHANGE"], "removed": ["GONE"]}
    assert cand["no_changes"] is False

def test_load_candidates_doc_delta_empty_sets_no_changes():
    """A candidate that re-proposes exactly what's already in the registry (e.g. a plain
    re-run of `connect` with nothing new in the store) has an empty delta and is flagged
    no_changes — the console de-emphasizes Accept, it doesn't hide or disable it."""
    from agentic import graph
    from agentic.review import load_candidates, propose_graph_change

    treg, tmp = _temp_registry()
    slug = next(iter(treg.projects))
    gdir = tmp / "registry" / "graph"
    gdir.mkdir(parents=True, exist_ok=True)
    seed = graph.ProjectGraph(slug=slug, name="P", description="", documents=[
        graph.Document("SAME", "Unchanged", "d", "2026-01-01")])
    (gdir / f"{slug}.jsonld").write_text(graph.canonical_jsonld(seed), encoding="utf-8")
    treg = loader.load(tmp)

    out = propose_graph_change(treg, slug, [
        {"id": "SAME", "name": "Unchanged", "description": "d", "dateModified": "2026-01-01"}])
    assert out["ok"], out
    cand = next(c for c in load_candidates(treg) if c["id"] == out["id"])
    assert cand["doc_delta"] == {"added": [], "changed": [], "removed": []}
    assert cand["no_changes"] is True

def test_load_candidates_doc_delta_scoped_by_store():
    """A store-scoped candidate (item 1's one-candidate-per-store shape) must never flag
    ANOTHER store's documents as "removed" just because they're absent from THIS
    candidate's enumeration — the delta compares only against the candidate's own store."""
    from agentic import graph
    from agentic.review import load_candidates, propose_graph_change

    treg, tmp = _temp_registry()
    slug = next(iter(treg.projects))
    gdir = tmp / "registry" / "graph"
    gdir.mkdir(parents=True, exist_ok=True)
    seed = graph.ProjectGraph(slug=slug, name="P", description="", documents=[
        graph.Document("GWS1", "Gws Doc", "d", "2026-01-01", store="gws"),
        graph.Document("FAKE1", "Fake Doc", "d", "2026-01-01", store="fake2")])
    (gdir / f"{slug}.jsonld").write_text(graph.canonical_jsonld(seed), encoding="utf-8")
    treg = loader.load(tmp)

    # a fake2-scoped candidate that only re-proposes FAKE1, unchanged — GWS1 must not
    # appear in "removed" even though it's absent from this candidate's fragment
    out = propose_graph_change(treg, slug, [
        {"id": "FAKE1", "name": "Fake Doc", "description": "d", "dateModified": "2026-01-01"}],
        store="fake2")
    assert out["ok"], out
    cand = next(c for c in load_candidates(treg) if c["id"] == out["id"])
    assert cand["store"] == "fake2"
    assert cand["doc_delta"] == {"added": [], "changed": [], "removed": []}
    assert cand["no_changes"] is True

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


def test_state_machine_selector_hides_example_templates():
    """The console's deploy selector follows cmd_compile's convention: example templates
    step aside once a real machine exists (they'd only tempt a guaranteed-refused deploy);
    with no real machine (fresh clone) they stand in so the quick-start works."""
    import copy

    from agentic.review import state

    # _temp_registry copies machines/ (examples) and adds the real "rig" — examples hide
    treg, _tmp = _temp_registry()
    assert state(treg)["machines"] == ["rig"]

    # fresh-clone shape: only example templates exist — they show
    fresh = copy.deepcopy(treg)
    fresh.machines = {n: m for n, m in fresh.machines.items() if m.get("example")}
    assert fresh.machines, "expected example templates in the temp registry copy"
    assert state(fresh)["machines"] == sorted(fresh.machines)


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



def test_project_edit_hides_and_unhides_through_the_same_candidate_valve():
    """The Project panel's Hidden toggle (Batch 3): a kind: project candidate exactly like
    every other project edit — no second write path, and un-hiding restores the manifest to
    having no `hidden:` key at all (the absent/false state), not a stored `false`."""
    from agentic import loader as loadermod
    from agentic.review import decide, graph_index, propose_project_edit

    treg, tmp = _temp_registry()
    out = propose_project_edit(treg, "example-project", {"hidden": True})
    assert out["ok"], out
    result = decide(treg, out["id"], "accept", "")
    assert result["ok"], result

    reloaded = loadermod.load(tmp)
    assert reloaded.projects["example-project"]["hidden"] is True
    idx = next(g for g in graph_index(reloaded) if g["slug"] == "example-project")
    assert idx["hidden"] is True

    out2 = propose_project_edit(reloaded, "example-project", {"hidden": False})
    assert out2["ok"], out2
    result2 = decide(reloaded, out2["id"], "accept", "")
    assert result2["ok"], result2
    twice_reloaded = loadermod.load(tmp)
    assert "hidden" not in twice_reloaded.projects["example-project"]


def test_project_edit_updates_document_store_through_candidate_valve():
    """Updating a project's document_store from none -> gws (or another known store)
    proposes a kind: project candidate, validates against servers.yaml, and applies cleanly."""
    from agentic import loader as loadermod
    from agentic.review import decide, graph_index, propose_project_edit

    treg, tmp = _temp_registry()
    assert treg.projects["example-project"]["document_store"] == "none"

    # 1. Propose updating document_store to 'gws'
    out = propose_project_edit(treg, "example-project", {"document_store": "gws"})
    assert out["ok"], out
    result = decide(treg, out["id"], "accept", "")
    assert result["ok"], result

    reloaded = loadermod.load(tmp)
    assert reloaded.projects["example-project"]["document_store"] == "gws"
    idx = next(g for g in graph_index(reloaded) if g["slug"] == "example-project")
    assert idx["document_store"] == "gws"

    # 2. Reject an unknown document_store
    out_bad = propose_project_edit(reloaded, "example-project", {"document_store": "unknown-server"})
    assert not out_bad["ok"]
    assert "unknown-server" in out_bad["error"]

    # 3. Can revert back to 'none'
    out_none = propose_project_edit(reloaded, "example-project", {"document_store": "none"})
    assert out_none["ok"], out_none
    result_none = decide(reloaded, out_none["id"], "accept", "")
    assert result_none["ok"], result_none
    reloaded_none = loadermod.load(tmp)
    assert reloaded_none.projects["example-project"]["document_store"] == "none"


def test_vendored_ui_libs_match_their_recorded_hashes():
    """VENDOR.md is the provenance record for the two files the preview loads. A bumped or
    hand-edited vendored build with a stale row would leave that record lying."""
    import hashlib
    import re

    from agentic import review
    vendor = (review.UI_DIR / "VENDOR.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| `([\w.]+)` \|.*\| `([0-9a-f]{64})` \|", vendor, re.M)
    assert {name for name, _ in rows} == {"marked.min.js", "dompurify.min.js"}
    for name, recorded in rows:
        blob = (review.UI_DIR / name).read_bytes()
        assert hashlib.sha256(blob).hexdigest() == recorded, f"{name} differs from VENDOR.md"


def test_markdown_preview_loads_marked_and_still_sanitizes():
    """snarkdown cannot render nested lists (its indented-block rule wins over its list
    rule), so the preview renders with marked — which sanitizes nothing itself, making the
    DOMPurify hop the one thing that must never be dropped alongside it."""
    from agentic import review
    html = (review.UI_DIR / "index.html").read_text(encoding="utf-8")
    app = (review.UI_DIR / "app.js").read_text(encoding="utf-8")
    assert '<script src="marked.min.js"></script>' in html
    assert "snarkdown" not in html and "snarkdown" not in app
    assert not (review.UI_DIR / "snarkdown.js").exists()
    assert "window.marked.parse(" in app
    assert "window.DOMPurify.sanitize(html)" in app


def test_create_project_rejects_invalid_slug():
    from agentic import review
    treg, _tmp = _temp_registry()
    for bad in ("", "   ", "has space", "bad/slash", "bad\\slash", "bad.dot"):
        out = review.create_project(treg, bad)
        assert out["ok"] is False
        assert "invalid slug" in out["error"]


def test_create_project_shells_out_to_mitos_cli(monkeypatch):
    import subprocess as _sp
    from agentic import review
    treg, _tmp = _temp_registry()
    seen = {}

    class _Done:
        returncode = 0
        stdout = "created registry/local/projects/newproj.yaml"
        stderr = ""

    def _fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["cwd"] = kw.get("cwd")
        return _Done()

    monkeypatch.setattr(_sp, "run", _fake_run)
    out = review.create_project(treg, "newproj", name="New Project", document_store="gws")
    assert out["ok"] is True
    assert out["slug"] == "newproj"
    cmd = seen["cmd"]
    assert cmd[1].endswith("mitos.py")
    assert cmd[2:4] == ["project", "add"]
    assert cmd[4] == "newproj"
    assert cmd[cmd.index("--name") + 1] == "New Project"
    assert cmd[cmd.index("--document-store") + 1] == "gws"
    assert cmd[cmd.index("--root") + 1] == str(treg.root)
    assert seen["cwd"] == str(treg.root)


def test_create_project_surfaces_cli_error(monkeypatch):
    import subprocess as _sp
    from agentic import review
    treg, _tmp = _temp_registry()

    class _Fail:
        returncode = 2
        stdout = ""
        stderr = "error: a project named 'existing' already exists in the registry\n"

    def _fake_run(cmd, **kw):
        return _Fail()

    monkeypatch.setattr(_sp, "run", _fake_run)
    out = review.create_project(treg, "existing")
    assert out["ok"] is False
    assert out["error"] == "a project named 'existing' already exists in the registry"


def test_create_project_end_to_end_scaffolds_manifest_in_overlay():
    from agentic import loader, review
    treg, tmp = _temp_registry()
    out = review.create_project(treg, "alpha-demo", name="Alpha Demo", document_store="none")
    assert out["ok"] is True, out
    assert out["slug"] == "alpha-demo"
    manifest = tmp / "registry" / loader.LOCAL_OVERLAY / "projects" / "alpha-demo.yaml"
    assert manifest.exists()
    graph_file = tmp / "registry" / loader.LOCAL_OVERLAY / "graph" / "alpha-demo.jsonld"
    assert graph_file.exists()
    reloaded = loader.load(tmp)
    assert "alpha-demo" in reloaded.projects
    assert "alpha-demo" in reloaded.graphs
    pg = reloaded.graphs["alpha-demo"]
    assert pg.name == "Alpha Demo"
    assert pg.documents == []
    assert pg.efforts == []
    proj = reloaded.projects["alpha-demo"]
    assert proj["name"] == "Alpha Demo"
    assert proj["slug"] == "alpha-demo"
    assert proj["document_store"] == "none"


def test_state_exposes_known_stores():
    from agentic import review
    treg, _tmp = _temp_registry()
    st = review.state(treg)
    assert "known_stores" in st
    assert isinstance(st["known_stores"], list)
    assert "gws" in st["known_stores"]


def test_api_project_new_endpoint():
    import json
    import threading
    import urllib.request
    from agentic import review
    treg, tmp = _temp_registry()
    server = review.make_server(treg, port=0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/api/project/new"
        payload = json.dumps({"slug": "beta-proj", "name": "Beta Proj", "document_store": "none"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert resp.status == 200
            assert data["ok"] is True
            assert data["slug"] == "beta-proj"
            assert "state" in data
            assert any(g["slug"] == "beta-proj" for g in data["state"]["graphs"])
    finally:
        server.shutdown()
        server.server_close()


def test_skills_tab_filters_exclude_context_tree_and_support_hiding_targets():
    """Regression test: within the Skills & Org tab, the target filter chips must
    not display 'context-tree' (as it never deploys skills), and operators must be able
    to hide skills associated with a target via the hide mode."""
    from agentic import review
    app = (review.UI_DIR / "app.js").read_text(encoding="utf-8")
    css = (review.UI_DIR / "style.css").read_text(encoding="utf-8")

    # context-tree must be excluded from targetOpts in Skills & Org. The rule now lives in
    # the shared isTargetVisible predicate (which also carries the overlay_harness gate), so
    # the chips read it rather than spelling the exclusion out a second time.
    assert 'const isTargetVisible = (t) => t !== "context-tree"' in app
    assert ".filter(isTargetVisible)" in app

    # Target filter mode (show vs hide) and hidden targets tracking must exist
    assert "skillFilterTargetMode" in app
    assert "skillHiddenTargets" in app
    assert 'skillFilterTargetMode === "hide"' in app

    # CSS styling for active hidden chips must exist
    assert ".pool-opt.active.hide-active" in css


def test_app_js_console_source_scan_no_agents_md_and_viewer_reachable():
    """Console source scan test ensuring no 'agents-md' or 'Agent-MD' in app.js
    and that the Context Tree viewer is reachable outside the org drawer."""
    from agentic import review
    app = (review.UI_DIR / "app.js").read_text(encoding="utf-8")

    assert "agents-md" not in app
    assert "Agent-MD" not in app
    assert "renderContextTreeSection" in app
    assert "contextTreeOpen" in app


def test_app_js_propose_graph_draft_includes_hidden():
    """Ensure app.js maps the hidden property in proposeGraphDraft so the UI
    sends visibility state to /api/graph."""
    from agentic import review
    app = (review.UI_DIR / "app.js").read_text(encoding="utf-8")
    assert "hidden: !!x.hidden" in app


def test_app_js_hides_hidden_efforts_with_drawer():
    """Ensure app.js excludes hidden efforts from the main registry list and provides
    the slide-out Hidden drawer with unhide capabilities, and excludes ID column."""
    from agentic import review
    app = (review.UI_DIR / "app.js").read_text(encoding="utf-8")
    css = (review.UI_DIR / "style.css").read_text(encoding="utf-8")
    html = (review.UI_DIR / "index.html").read_text(encoding="utf-8")

    # State and functions exist
    assert "let hiddenDrawerOpen = false;" in app
    assert "function hiddenEffortsFor(g)" in app
    assert "function renderHiddenDrawer(g)" in app
    assert "toggleHiddenBtn" in app
    assert "effort.hidden && !isCurrentEffortEditor" in app
    assert "!e.hidden" in app
    assert "rrow-name-content" in app

    # HTML and CSS drawer exist
    assert 'id="hidden-work-drawer"' in html
    assert "#hidden-work-drawer" in css
    assert "#hidden-work-drawer.open" in css
    assert ".hidden-effort-card" in css
    assert ".hidden-effort-actions" in css




def test_api_graph_effort_hidden_toggle_end_to_end():
    """HTTP API test: toggle effort hidden on and off via /api/graph and /api/decide,
    verifying it reflects in /api/state."""
    import json
    import threading
    import urllib.request
    from agentic import review
    treg, tmp = _temp_registry()
    server = review.make_server(treg, port=0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        port = server.server_address[1]
        slug = next(iter(treg.projects))

        # 1. Propose hiding an effort via /api/graph
        url_graph = f"http://127.0.0.1:{port}/api/graph"
        payload_hide = json.dumps({
            "slug": slug,
            "documents": [],
            "removals": [],
            "efforts": [{"id": "launch-prep", "name": "Launch prep", "hidden": True}],
            "effortRemovals": []
        }).encode("utf-8")
        req = urllib.request.Request(url_graph, data=payload_hide, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            cid = data["id"]

        # 2. Accept the candidate via /api/decide
        url_decide = f"http://127.0.0.1:{port}/api/decide"
        payload_decide = json.dumps({"id": cid, "decision": "accept"}).encode("utf-8")
        req = urllib.request.Request(url_decide, data=payload_decide, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True

        # 3. Verify /api/state returns hidden: True
        url_state = f"http://127.0.0.1:{port}/api/state"
        with urllib.request.urlopen(url_state) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            g = next(proj for proj in data["graphs"] if proj["slug"] == slug)
            eff = next(e for e in g["efforts"] if e["id"] == "launch-prep")
            assert eff["hidden"] is True

        # 4. Propose unhiding via /api/graph
        payload_unhide = json.dumps({
            "slug": slug,
            "documents": [],
            "removals": [],
            "efforts": [{"id": "launch-prep", "name": "Launch prep", "hidden": False}],
            "effortRemovals": []
        }).encode("utf-8")
        req = urllib.request.Request(url_graph, data=payload_unhide, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            cid2 = data["id"]

        # 5. Accept the unhide candidate
        payload_decide2 = json.dumps({"id": cid2, "decision": "accept"}).encode("utf-8")
        req = urllib.request.Request(url_decide, data=payload_decide2, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True

        # 6. Verify /api/state returns hidden: False
        with urllib.request.urlopen(url_state) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            g = next(proj for proj in data["graphs"] if proj["slug"] == slug)
            eff = next(e for e in g["efforts"] if e["id"] == "launch-prep")
            assert eff["hidden"] is False
    finally:
        server.shutdown()
        server.server_close()





def test_app_js_syntax_is_valid():
    """app.js is 4,800+ lines of hand-written vanilla JS with no bundler — one stray
    bracket takes the whole console down, and nothing else in the suite would notice.

    Node is not a Mitos dependency, so its absence must not fail the suite: without it we
    fall back to a cheap balance check and warn, which is what a minimal Python-only CI
    container gets. Any normal developer box runs the real V8 parse."""
    import shutil
    import subprocess
    import warnings
    from agentic import review

    path = review.UI_DIR / "app.js"
    node = shutil.which("node")
    if node:
        out = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
        assert out.returncode == 0, f"node --check failed:\n{out.stderr}"
        return
    src = path.read_text(encoding="utf-8")
    for open_c, close_c in (("{", "}"), ("(", ")"), ("[", "]")):
        assert src.count(open_c) == src.count(close_c), f"unbalanced {open_c}{close_c}"
    warnings.warn("node not found — app.js checked for bracket balance only, not syntax")


def test_propose_graph_change_preserves_effort_keywords_when_key_absent():
    """Pin the review.py:795 behavior: re-proposing an effort without naming keywords
    preserves the existing aliases on disk, protecting against stale/partial drafts."""
    import json
    from agentic import review, loader as loadermod

    treg, tmp = _temp_registry()
    slug = next(iter(treg.projects))

    out1 = review.propose_graph_change(treg, slug, [], [], efforts=[
        {"id": "launch-prep", "name": "Launch Prep", "keywords": "legacy-alias, alt-tag"}])
    assert out1["ok"], out1
    review.decide(treg, out1["id"], "accept", "")
    treg = loadermod.load(tmp)

    # Now propose an edit without "keywords" in the effort dict
    out2 = review.propose_graph_change(treg, slug, [], [], efforts=[
        {"id": "launch-prep", "name": "Launch Prep Renamed"}])
    assert out2["ok"], out2

    cand = sorted((tmp / "registry" / "local" / "inbox").glob("*/*.jsonld"))[-1]
    body = json.loads(cand.read_text(encoding="utf-8"))
    work_nodes = [n for n in body["@graph"] if str(n.get("@id", "")).endswith("launch-prep")]
    assert work_nodes, "launch-prep effort node must exist in candidate"
    assert any("legacy-alias" in json.dumps(n) for n in work_nodes), \
        "existing keywords must be preserved when the key is omitted in the proposal"



# ── Effort Done state through the Inbox valve ─────────────────────────────────
def _done_rig():
    """A temp registry whose first project has one Implemented Document under effort
    `ship`, accepted and reloaded — the starting point for Done-state valve tests."""
    from agentic import loader as loadermod, review
    treg, tmp = _temp_registry()
    slug = next(iter(treg.projects))
    out = review.propose_graph_change(
        treg, slug,
        documents=[{"id": "EXAMPLEDOCID", "name": "Implemented", "dateModified": "2026-09-01",
                    "parentId": "ship"}],
        efforts=[{"id": "ship", "name": "Ship It", "goal": "g"},
                 {"id": "other", "name": "Other Work"}])
    assert out["ok"], out
    assert review.decide(treg, out["id"], "accept", "")["ok"]
    return loadermod.load(tmp), tmp, slug


def _accept(treg, tmp, out):
    from agentic import loader as loadermod, review
    assert out["ok"], out
    res = review.decide(treg, out["id"], "accept", "")
    assert res["ok"], res
    return loadermod.load(tmp)


def _effort(treg, slug, eid):
    return next(e for e in treg.graphs[slug].efforts if e.id == eid)


def _mark_done(treg, slug):
    from agentic import review
    return review.propose_graph_change(treg, slug, [], efforts=[
        {"id": "ship", "name": "Ship It", "goal": "g", "status": "done",
         "evaluation": "EXAMPLEDOCID"}])


def test_propose_effort_edit_without_status_keys_preserves_done():
    from agentic import review
    treg, tmp, slug = _done_rig()
    treg = _accept(treg, tmp, _mark_done(treg, slug))
    treg = _accept(treg, tmp, review.propose_graph_change(
        treg, slug, [], efforts=[{"id": "ship", "name": "Ship It Renamed", "hidden": True}]))
    e = _effort(treg, slug, "ship")
    assert (e.name, e.status, e.evaluation) == ("Ship It Renamed", "done", "EXAMPLEDOCID")


def test_propose_effort_explicit_empty_status_clears_done():
    from agentic import review
    treg, tmp, slug = _done_rig()
    treg = _accept(treg, tmp, _mark_done(treg, slug))
    treg = _accept(treg, tmp, review.propose_graph_change(
        treg, slug, [], efforts=[{"id": "ship", "name": "Ship It", "status": "",
                                  "evaluation": ""}]))
    e = _effort(treg, slug, "ship")
    assert (e.status, e.evaluation) == ("", "")


def test_propose_rejects_unknown_status():
    from agentic import review
    treg, _tmp, slug = _done_rig()
    for bad in ("in-progress", "Done"):
        out = review.propose_graph_change(treg, slug, [], efforts=[
            {"id": "ship", "name": "Ship It", "status": bad}])
        assert not out["ok"] and "status" in out["error"], out


def test_propose_rejects_dangling_evaluation():
    from agentic import review
    treg, _tmp, slug = _done_rig()
    out = review.propose_graph_change(treg, slug, [], efforts=[
        {"id": "ship", "name": "Ship It", "status": "done", "evaluation": "MISSINGDOC"}])
    assert not out["ok"] and "MISSINGDOC" in out["error"], out
    out = review.propose_graph_change(treg, slug, [], efforts=[
        {"id": "ship", "name": "Ship It", "evaluation": "EXAMPLEDOCID"}])
    assert not out["ok"], "an evaluation without status done must be rejected"


def test_propose_rejects_removing_the_evaluation_document():
    from agentic import review
    treg, tmp, slug = _done_rig()
    treg = _accept(treg, tmp, _mark_done(treg, slug))
    out = review.propose_graph_change(treg, slug, [], removals=["EXAMPLEDOCID"])
    assert not out["ok"] and "EXAMPLEDOCID" in out["error"], out
    # clearing the evaluation in the same proposal makes the removal legal
    out = review.propose_graph_change(treg, slug, [], removals=["EXAMPLEDOCID"], efforts=[
        {"id": "ship", "name": "Ship It", "evaluation": ""}])
    assert out["ok"], out


def test_propose_doc_mapping_alone_never_changes_effort_status():
    from agentic import review
    treg, tmp, slug = _done_rig()
    treg = _accept(treg, tmp, review.propose_graph_change(treg, slug, documents=[
        {"id": "EXAMPLEDOCID", "name": "Implemented", "dateModified": "2026-09-02",
         "parentId": "ship"}]))
    assert _effort(treg, slug, "ship").status == ""
    treg = _accept(treg, tmp, _mark_done(treg, slug))
    treg = _accept(treg, tmp, review.propose_graph_change(treg, slug, documents=[
        {"id": "OTHERDOCID", "name": "Other", "dateModified": "2026-09-03",
         "parentId": "other"}]))
    assert _effort(treg, slug, "ship").status == "done"


def test_two_candidates_accepted_out_of_order_preserves_done():
    """Candidate A (a goal tweak on `other`) is proposed BEFORE candidate B marks `ship` done;
    accepting A after B must not roll `ship` back — A's fragment carries a stale `ship`."""
    from agentic import review
    treg, tmp, slug = _done_rig()
    a = review.propose_graph_change(treg, slug, [], efforts=[
        {"id": "other", "name": "Other Work", "goal": "new goal"}])
    assert a["ok"], a
    treg = _accept(treg, tmp, _mark_done(treg, slug))
    treg = _accept(treg, tmp, a)
    assert _effort(treg, slug, "ship").status == "done"
    assert _effort(treg, slug, "other").goal == "new goal"


def test_graph_candidate_summary_includes_effort_delta():
    from agentic import review
    treg, _tmp, slug = _done_rig()
    out = _mark_done(treg, slug)
    assert out["ok"], out
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out["id"])
    assert cand["effort_delta"] == [{"id": "ship", "status": ["", "done"],
                                     "evaluation": ["", "EXAMPLEDOCID"]}]
    assert cand["no_changes"] is False


def test_graph_index_exposes_effort_status_and_evaluation():
    from agentic import review
    treg, tmp, slug = _done_rig()
    treg = _accept(treg, tmp, _mark_done(treg, slug))
    idx = next(g for g in review.graph_index(treg) if g["slug"] == slug)
    e = next(e for e in idx["efforts"] if e["id"] == "ship")
    assert (e["status"], e["evaluation"]) == ("done", "EXAMPLEDOCID")


def _ui_src(name):
    from agentic import review
    return (review.UI_DIR / name).read_text(encoding="utf-8")


def test_app_js_propose_graph_draft_includes_status_and_evaluation():
    """The draft payload forwards completion state only when the draft carries the key — an
    absent key is the server's preserve-when-absent signal, so a stale draft cannot un-mark Done."""
    src = _ui_src("app.js")
    body = src[src.index("async function proposeGraphDraft"):]
    body = body[:body.index("\n}\n")]
    assert 'if ("status" in x) item.status = x.status ?? "";' in body
    assert 'if ("evaluation" in x) item.evaluation = x.evaluation ?? "";' in body
    # both Edit-button draft seeds and the effort editor carry the fields
    assert src.count('status: effort.status || ""') == 2
    assert 'status: inputs.status.checked ? "done" : ""' in src


def test_app_js_tweak_offers_done_only_on_identity_peek():
    src = _ui_src("app.js")
    tweak = src[src.index("async function openTweak"):]
    tweak = tweak[:tweak.index("\n}\n")]
    assert "openEditor.vals.implementedFor = effortId;" in tweak
    assert "Mark effort as Done with this Implemented Document" in src
    assert 'status: "done", evaluation: doc.id' in src


def test_app_js_renders_done_badge_and_evaluation_ref():
    src = _ui_src("app.js")
    assert '"badge badge-done", "Done"' in src
    assert 'el("div", "effort-evaluation")' in src
    assert "effortDeltaSummary(c)" in src


def test_style_css_defines_badge_done_classes():
    css = _ui_src("style.css")
    assert ".badge.badge-done" in css and ".effort-evaluation" in css


def _seed_and_accept(docs):
    from agentic import review
    treg, tmp = _temp_registry()
    out = review.propose_graph_change(treg, "example-project", docs, reason="seed")
    assert out["ok"], out
    assert review.decide(loader.load(tmp), out["id"], "accept", "")["ok"]
    return tmp


def _graph_doc(tmp, did):
    from agentic import graph
    pg = graph.load_project_graph(tmp / "registry" / "graph" / "example-project.jsonld")
    return next(d for d in pg.documents if d.drive_id == did)


def test_propose_graph_change_normalizes_image_type():
    """A hand-typed `png`/`image/png` becomes the one `image` kind (stored as ImageObject)."""
    tmp = _seed_and_accept([
        {"id": "I1", "name": "Board", "description": "whiteboard", "dateModified": "2026-01-01",
         "type": "png"},
        {"id": "I2", "name": "Shot", "description": "screenshot", "dateModified": "2026-01-01",
         "type": "image/png"}])
    assert _graph_doc(tmp, "I1").doc_type == "image"
    assert _graph_doc(tmp, "I2").doc_type == "image"
    raw = (tmp / "registry" / "graph" / "example-project.jsonld").read_text(encoding="utf-8")
    assert '"@type": "ImageObject"' in raw


def test_propose_graph_change_preserves_web_url_when_omitted():
    """The console's editor sends no webUrl; an edit must not strip the stored link."""
    from agentic import review
    tmp = _seed_and_accept([
        {"id": "I1", "name": "Board", "description": "d", "dateModified": "2026-01-01",
         "webUrl": "https://example.com/board", "type": "image"}])
    reg = loader.load(tmp)
    out = review.propose_graph_change(reg, "example-project", [
        {"id": "I1", "name": "Board v2", "description": "d", "dateModified": "2026-01-02"}])
    assert review.decide(loader.load(tmp), out["id"], "accept", "")["ok"]
    d = _graph_doc(tmp, "I1")
    assert d.name == "Board v2" and d.web_url == "https://example.com/board"
    assert d.doc_type == "image"


def test_app_js_refuses_empty_description_for_image_type():
    """Contract on the console: `type` rides stagedDoc and proposeGraphDraft, the editor has
    a Type field, and Apply refuses an image with no description."""
    import re
    from agentic import review
    app = (review.UI_DIR / "app.js").read_text(encoding="utf-8")
    staged = app[app.index("function stagedDoc("):]
    assert re.search(r"type:\s*d\.type", staged[:staged.index("\n}")])
    draft = app[app.index("async function proposeGraphDraft("):]
    assert "type: x.type" in draft[:draft.index("const removals")]
    card = app[app.index("function editorCard("):]
    card = card[:card.index("\nfunction ")]
    assert 'wrap.append(el("label", "", "Type"))' in card and "inputs.type = sel" in card
    assert "STATE.known_doc_types" in card
    assert "isImageKind(doc.type) && !doc.description" in card
    guard = card.index("isImageKind(doc.type) && !doc.description")
    assert card.index("return;", guard) < card.index("draftUpsert(", guard)


def test_remove_image_object_moves_to_recovery():
    """Removing an ImageObject runs the shared document path: gone from the graph,
    auto-dismissed into Recovery."""
    from agentic import graph, review
    tmp = _seed_and_accept([
        {"id": "I1", "name": "Board", "description": "d", "dateModified": "2026-01-01",
         "type": "image"}])
    out = review.propose_graph_change(loader.load(tmp), "example-project", [],
                                      removals=["I1"], reason="drop image")
    assert review.decide(loader.load(tmp), out["id"], "accept", "")["ok"]
    pg = graph.load_project_graph(tmp / "registry" / "graph" / "example-project.jsonld")
    assert "I1" not in {d.drive_id for d in pg.documents}
    dismissed = review.load_dismissed(loader.load(tmp), "example-project")["documents"]
    assert [x["id"] for x in dismissed] == ["I1"]


def test_add_document_type_dropdown_defaults_to_document():
    """The console's Type dropdown offers graph.KNOWN_DOC_TYPES (served in state), and a
    hand-added document starts on the first of them, `document`."""
    from agentic import graph, review
    treg, _tmp = _temp_registry()
    assert review.state(treg)["known_doc_types"] == list(graph.KNOWN_DOC_TYPES)
    assert graph.KNOWN_DOC_TYPES[0] == graph.DEFAULT_DOC_KIND == "document"
    assert graph.IMAGE_KIND in graph.KNOWN_DOC_TYPES
    app = (review.UI_DIR / "app.js").read_text(encoding="utf-8")
    add = app[app.index('"+ Doc"'):]
    add = add[:add.index("renderRegistryRows(g)")]
    assert 'type: (STATE.known_doc_types || ["document"])[0]' in add


# ── Milestone 2: Agents in console ───────────────────────────────────────────
def test_api_agents_shape():
    """GET /api/agents returns the expected payload shape: agents list with
    name, description, targets, goal, skills, machines, source; machines list with
    name, selected."""
    from agentic import review

    treg, tmp = _temp_registry()
    adir = tmp / "registry" / "local" / "agents"
    adir.mkdir(parents=True, exist_ok=True)
    agent_file = adir / "test-agent.md"
    agent_file.write_text(
        "---\n"
        "name: test-agent\n"
        "description: Test agent description.\n"
        "targets: [overlay-harness]\n"
        "goal: Help test.\n"
        "skills: [graph-bootstrap]\n"
        "---\n\n"
        "# Instructions\n\nDo test things.\n",
        encoding="utf-8"
    )
    loaded = loader.load(tmp)
    res = review.agents_index(loaded)
    assert "agents" in res
    assert "machines" in res
    assert isinstance(res["agents"], list)
    assert isinstance(res["machines"], list)

    agent_entry = next((a for a in res["agents"] if a["name"] == "test-agent"), None)
    assert agent_entry is not None
    expected_agent_keys = {"name", "description", "targets", "goal", "skills", "machines", "source"}
    assert expected_agent_keys <= set(agent_entry.keys())
    assert agent_entry["description"] == "Test agent description."
    assert agent_entry["targets"] == ["overlay-harness"]
    assert agent_entry["goal"] == "Help test."
    assert agent_entry["skills"] == ["graph-bootstrap"]
    assert "local/agents/test-agent.md" in agent_entry["source"]

    for m in res["machines"]:
        assert {"name", "selected"} <= set(m.keys())
        assert isinstance(m["selected"], int)


def test_propose_new_agent_lands_in_inbox_not_registry():
    """propose_new_agent writes only to inbox/ (kind: new), never touching registry/
    directly (invariant #3). Deciding accept routes it into registry/local/agents/."""
    from agentic import review

    treg, tmp = _temp_registry()
    out = review.propose_new_agent(
        treg, "scout-agent",
        {"description": "Scout things.", "targets": ["overlay-harness"], "goal": "Find stuff.", "skills": ["graph-bootstrap"]},
        "# Instructions\n\nScout around.",
        reason="initial scaffold"
    )
    assert out["ok"], out
    assert out["registry_path"] == "local/agents/scout-agent.md"

    # Invariant #3: registry has not been modified
    reg_target = tmp / "registry" / "local" / "agents" / "scout-agent.md"
    assert not reg_target.exists()

    candidates = review.load_candidates(treg)
    cand = next((c for c in candidates if c["id"] == out["id"]), None)
    assert cand is not None
    assert cand["kind"] == "new"
    assert cand["acceptable"]

    # Accept the candidate
    dec_res = review.decide(treg, out["id"], "accept", "")
    assert dec_res["ok"], dec_res
    assert reg_target.is_file()
    content = reg_target.read_text(encoding="utf-8")
    assert "name: scout-agent" in content
    assert "description: Scout things." in content
    assert "targets:" in content
    assert "goal: Find stuff." in content
    assert "skills:" in content
    assert "Scout around." in content

    # The new agent is now loadable
    reloaded = loader.load(tmp)
    assert "scout-agent" in reloaded.agents


def test_propose_new_agent_validates():
    """propose_new_agent enforces agent validation rules on candidate text."""
    from agentic import review

    treg, _tmp = _temp_registry()

    # Empty name
    assert not review.propose_new_agent(treg, "", {"description": "d", "targets": ["overlay-harness"], "goal": "g", "skills": ["graph-bootstrap"]}, "body")["ok"]
    # Bad slug
    assert not review.propose_new_agent(treg, "Bad_Slug", {"description": "d", "targets": ["overlay-harness"], "goal": "g", "skills": ["graph-bootstrap"]}, "body")["ok"]
    # Empty description
    assert not review.propose_new_agent(treg, "valid-slug", {"description": "", "targets": ["overlay-harness"], "goal": "g", "skills": ["graph-bootstrap"]}, "body")["ok"]
    # Missing targets
    assert not review.propose_new_agent(treg, "valid-slug", {"description": "d", "targets": [], "goal": "g", "skills": ["graph-bootstrap"]}, "body")["ok"]
    # Unknown skill
    res = review.propose_new_agent(treg, "valid-slug", {"description": "d", "targets": ["overlay-harness"], "goal": "g", "skills": ["unknown-skill-xyz"]}, "body")
    assert not res["ok"]
    assert "unknown skill" in res["error"]
    # Empty body
    assert not review.propose_new_agent(treg, "valid-slug", {"description": "d", "targets": ["overlay-harness"], "goal": "g", "skills": ["graph-bootstrap"]}, "")["ok"]


def test_propose_agent_meta_edit_lands_in_inbox():
    """propose_meta_edit accepts kind='agent' for description, goal, skills, targets,
    writing a verbatim candidate that updates the agent file when accepted."""
    from agentic import review
    import yaml as _y

    treg, tmp = _temp_registry()
    adir = tmp / "registry" / "local" / "agents"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "worker.md").write_text(
        "---\n"
        "name: worker\n"
        "description: Original description.\n"
        "targets: [overlay-harness]\n"
        "goal: Original goal.\n"
        "skills: [graph-bootstrap]\n"
        "---\n\n"
        "# Instructions\n\nWork hard.\n",
        encoding="utf-8"
    )
    loaded = loader.load(tmp)
    out = review.propose_meta_edit(
        loaded, "agent", "worker",
        {"description": "Updated description.", "goal": "Updated goal."},
        "Work hard."
    )
    assert out["ok"], out
    assert out["registry_path"] == "local/agents/worker.md"

    candidates = review.load_candidates(loaded)
    cand = next(c for c in candidates if c["id"] == out["id"])
    assert cand["acceptable"]
    meta_on_disk = _y.safe_load((tmp / "registry" / "local" / "inbox" / out["id"] / "meta.yaml").read_text(encoding="utf-8"))
    assert meta_on_disk.get("verbatim") is True

    dec_res = review.decide(loaded, out["id"], "accept", "")
    assert dec_res["ok"], dec_res

    text = (adir / "worker.md").read_text(encoding="utf-8")
    assert "description: Updated description." in text
    assert "targets: [overlay-harness]" in text or "targets:\n- overlay-harness" in text
    assert "goal: Updated goal." in text
    assert "Work hard." in text


def test_propose_agent_body_edit():
    """propose_edit accepts kind='agent' for body editing, preserving frontmatter on accept."""
    from agentic import review

    treg, tmp = _temp_registry()
    adir = tmp / "registry" / "local" / "agents"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "coder.md").write_text(
        "---\n"
        "name: coder\n"
        "description: Code agent.\n"
        "targets: [overlay-harness]\n"
        "goal: Write code.\n"
        "skills: [graph-bootstrap]\n"
        "---\n\n"
        "# Instructions\n\nInitial instructions.\n",
        encoding="utf-8"
    )
    loaded = loader.load(tmp)
    out = review.propose_edit(
        loaded, "agent", "coder",
        "# Instructions\n\nUpdated instructions.\n",
        reason="improve prompt"
    )
    assert out["ok"], out
    assert out["registry_path"] == "local/agents/coder.md"

    dec_res = review.decide(loaded, out["id"], "accept", "")
    assert dec_res["ok"], dec_res

    text = (adir / "coder.md").read_text(encoding="utf-8")
    assert "name: coder" in text
    assert "description: Code agent." in text
    assert "targets: [overlay-harness]" in text or "targets:\n- overlay-harness" in text
    assert "goal: Write code." in text
    assert "Updated instructions." in text
    assert "Initial instructions." not in text


def test_agents_section_hidden_without_flag():
    """Agents is a core lane: no hasContextTree() gate on agents in app.js, no 'of 20'."""
    from agentic import review
    app = (review.UI_DIR / "app.js").read_text(encoding="utf-8")

    # No hasContextTree() gating agents
    assert "if (hasContextTree()) {\n    const agentsChip = el" not in app
    assert "if (skillShowingAgents && hasContextTree()) {\n    renderAgentsGrid" not in app
    assert "if (skillShowingAgents && hasContextTree()) {\n    const newAgentBtn" not in app
    assert "if (!agentsData && hasContextTree())" not in app
    assert "of 20" not in app


def test_accept_new_target_candidate():
    """A valid target is accepted and appears in reg.target_names; malformed YAML,
    schema-invalid YAML, a core-name collision and a ../ path are each refused, with
    nothing written. The same cases are mirrored for identity."""
    from agentic import review

    treg, tmp = _temp_registry()

    # 1. Valid target accepted
    target_payload = (
        "target: scratch-target\n"
        "context_file:\n"
        "  deploy_to_key: context_root\n"
        "  filename: CONTEXT.md\n"
    )
    meta = {
        "registry_path": "local/targets/scratch-target.yaml",
        "kind": "new",
        "source": {"machine": "test", "tool": "overlay-harness"},
        "base_hash": "",
        "deploy_path": "",
        "captured_at": "2026-09-28T00:00:00Z",
        "note": "test candidate",
    }
    _plant_candidate(tmp, "valid-target", meta, "scratch-target.yaml", target_payload)
    res = review.decide(loader.load(tmp), "valid-target", "accept", "")
    assert res["ok"], res
    written_target = tmp / "registry" / "local" / "targets" / "scratch-target.yaml"
    assert written_target.is_file()
    treg2 = loader.load(tmp)
    assert "scratch-target" in treg2.target_names

    # 2. Malformed YAML refused
    bad_meta = dict(meta, registry_path="local/targets/malformed.yaml")
    _plant_candidate(tmp, "malformed-target", bad_meta, "malformed.yaml", ": bad: [yaml")
    res = review.decide(loader.load(tmp), "malformed-target", "accept", "")
    assert not res["ok"]
    assert "malformed" in res["error"]
    assert not (tmp / "registry" / "local" / "targets" / "malformed.yaml").exists()

    # 3. Schema-invalid YAML:
    # 3a. Target name doesn't match stem
    bad_schema_meta = dict(meta, registry_path="local/targets/mismatched.yaml")
    _plant_candidate(tmp, "mismatched-target", bad_schema_meta, "mismatched.yaml", "target: other-name\n")
    res = review.decide(loader.load(tmp), "mismatched-target", "accept", "")
    assert not res["ok"]
    assert not (tmp / "registry" / "local" / "targets" / "mismatched.yaml").exists()

    # 3b. Skills block has include/exclude
    bad_skills_meta = dict(meta, registry_path="local/targets/bad-skills.yaml")
    _plant_candidate(tmp, "bad-skills-target", bad_skills_meta, "bad-skills.yaml",
                     "target: bad-skills\nskills:\n  include: [test]\n")
    res = review.decide(loader.load(tmp), "bad-skills-target", "accept", "")
    assert not res["ok"]
    assert not (tmp / "registry" / "local" / "targets" / "bad-skills.yaml").exists()

    # 4. Core-name collision refused
    core_collision_meta = dict(meta, registry_path="local/targets/context-tree.yaml")
    _plant_candidate(tmp, "core-collision", core_collision_meta, "context-tree.yaml", "target: context-tree\n")
    res = review.decide(loader.load(tmp), "core-collision", "accept", "")
    assert not res["ok"]
    assert "collides with a core target" in res["error"]
    assert not (tmp / "registry" / "local" / "targets" / "context-tree.yaml").exists()

    # 5. Traversal path refused
    traversal_meta = dict(meta, registry_path="local/targets/../machines/evil.yaml")
    _plant_candidate(tmp, "traversal-target", traversal_meta, "evil.yaml", "target: evil\n")
    res = review.decide(loader.load(tmp), "traversal-target", "accept", "")
    assert not res["ok"]
    assert "path traversal refused" in res["error"]
    assert not (tmp / "machines" / "evil.yaml").exists()

    # --- Identity partial mirrored cases ---

    # 1. Valid identity accepted
    id_payload = "---\naudience: [context-tree]\n---\n# Identity\n\nCustom rules.\n"
    id_meta = {
        "registry_path": "local/identity/custom-rules.md",
        "kind": "new",
        "source": {"machine": "test", "tool": "overlay-harness"},
        "base_hash": "",
        "deploy_path": "",
        "captured_at": "2026-09-28T00:00:00Z",
        "note": "test identity",
    }
    _plant_candidate(tmp, "valid-id", id_meta, "custom-rules.md", id_payload)
    res = review.decide(loader.load(tmp), "valid-id", "accept", "")
    assert res["ok"], res
    written_id = tmp / "registry" / "local" / "identity" / "custom-rules.md"
    assert written_id.is_file()
    treg3 = loader.load(tmp)
    assert "identity/custom-rules.md" in treg3.partials

    # 2. Malformed YAML frontmatter refused
    bad_id_meta = dict(id_meta, registry_path="local/identity/bad-frontmatter.md")
    _plant_candidate(tmp, "bad-id-fm", bad_id_meta, "bad-frontmatter.md", "---\n: bad: [yaml\n---\nbody\n")
    res = review.decide(loader.load(tmp), "bad-id-fm", "accept", "")
    assert not res["ok"]
    assert not (tmp / "registry" / "local" / "identity" / "bad-frontmatter.md").exists()

    # 3. Schema-invalid YAML: missing audience
    no_aud_meta = dict(id_meta, registry_path="local/identity/no-audience.md")
    _plant_candidate(tmp, "no-aud-id", no_aud_meta, "no-audience.md", "---\nname: not-audience\n---\nbody\n")
    res = review.decide(loader.load(tmp), "no-aud-id", "accept", "")
    assert not res["ok"]
    assert not (tmp / "registry" / "local" / "identity" / "no-audience.md").exists()

    # 4. Unknown audience / retired target refused
    bad_aud_meta = dict(id_meta, registry_path="local/identity/bad-audience.md")
    _plant_candidate(tmp, "bad-aud-id", bad_aud_meta, "bad-audience.md", "---\naudience: [not-a-real-target]\n---\nbody\n")
    res = review.decide(loader.load(tmp), "bad-aud-id", "accept", "")
    assert not res["ok"]
    assert "unknown audience" in res["error"]
    assert not (tmp / "registry" / "local" / "identity" / "bad-audience.md").exists()

    # 5. Traversal path refused
    id_traversal_meta = dict(id_meta, registry_path="local/identity/../evil.md")
    _plant_candidate(tmp, "traversal-id", id_traversal_meta, "evil.md", "---\naudience: [context-tree]\n---\n")
    res = review.decide(loader.load(tmp), "traversal-id", "accept", "")
    assert not res["ok"]
    assert "path traversal refused" in res["error"]
    assert not (tmp / "registry" / "local" / "evil.md").exists()


def test_upgrade_path_unknown_target_then_accept_seed():
    """TEST-02: core target removed, an overlay machine targeting it, the seed pending;
    the registry loads with the warning; accept; plan_machine('rig') is non-empty."""
    from agentic import review, planner

    treg, tmp = _temp_registry()

    target_file = tmp / "registry" / "local" / "targets" / "overlay-harness.yaml"
    if not target_file.is_file():
        target_file = tmp / "targets" / "overlay-harness.yaml"
    seed_content = target_file.read_text(encoding="utf-8")
    target_file.unlink()

    # In post-M6 core, partials/skills no longer name overlay-harness; only machines do
    for p in (tmp / "registry").rglob("*.md"):
        text = p.read_text(encoding="utf-8")
        if "overlay-harness" in text:
            p.write_text(text.replace("overlay-harness, ", "").replace(", overlay-harness", "").replace("overlay-harness", "context-tree"), encoding="utf-8")

    # Machine targets overlay-harness (which is now unknown)
    loaded_warn = loader.load(tmp)
    assert "rig" in loaded_warn.skipped_machines

    # Seed is pending in inbox
    meta = {
        "registry_path": "local/targets/overlay-harness.yaml",
        "kind": "new",
        "source": {"machine": "rig", "tool": "overlay-harness"},
        "base_hash": "",
        "deploy_path": "",
        "captured_at": "2026-09-28T00:00:00Z",
        "note": "seed target",
    }
    _plant_candidate(tmp, "seed-overlay-harness", meta, "overlay-harness.yaml", seed_content)

    # Accept the seed
    res = review.decide(loaded_warn, "seed-overlay-harness", "accept", "")
    assert res["ok"], res

    # Registry now loads cleanly, machine is not skipped, outputs are non-empty
    loaded_fixed = loader.load(tmp)
    assert "rig" not in loaded_fixed.skipped_machines
    outputs = planner.plan_machine(loaded_fixed, "rig")
    assert len(outputs) > 0



# ── {{#name}}: multi-line one-shot prompt inputs ─────────────────────────────

def test_app_js_prompt_token_regex_accepts_optional_hash_and_reports_multiline():
    src = _ui_src("app.js")
    assert r"const PROMPT_TOKEN_RE = /\{\{(#?)(\w+)\}\}/g;" in src
    tokens = src[src.index("function promptTokens"):src.index("function fillPrompt")]
    assert "multiline" in tokens and 'm[1] === "#"' in tokens
    # both forms fill from ONE value, and a blank value leaves the token as written
    fill = src[src.index("function fillPrompt"):src.index("function copyPrompt")]
    assert "(whole, _hash, tok)" in fill and "return v ? v : whole;" in fill


def test_app_js_multiline_prompt_input_has_no_enter_handler():
    """Enter must type a newline in a multi-line field and copy from a single-line one."""
    src = _ui_src("app.js")
    fn = src[src.index("function openPromptInputs"):]
    fn = fn[:fn.index("\n}\n")]
    multi, single = fn.split("} else {", 1)
    assert 'el("textarea", "prompt-input-field multiline")' in multi
    assert "onkeydown" not in multi
    assert 'e.key === "Enter"' in single and "go();" in single
    assert "Ctrl" not in fn and "metaKey" not in fn     # no copy shortcut (ARB-09)
    assert ".prompt-input-field.multiline" in _ui_src("style.css")


# ── full-size file editor: supporting-file diffs, on-disk staleness, workspace scans ──

def _edit_script_rig():
    """A skill with two supporting files, accepted into a temp registry's overlay."""
    from agentic.review import decide, propose_new_skill
    treg, tmp = _temp_registry()
    out = propose_new_skill(
        treg, "ws-skill", {"targets": ["overlay-harness"], "description": "d"}, "body",
        resources={"scripts/run.sh": "echo one\n", "examples/a.md": "a\n"})
    assert out["ok"], out
    assert decide(loader.load(tmp), out["id"], "accept", "")["ok"]
    treg = loader.load(tmp)
    script = tmp / "registry" / "local" / "skills" / "ws-skill" / "scripts" / "run.sh"
    return treg, tmp, treg.skills["ws-skill"], script


def test_skill_propose_with_edited_script_names_it_as_changed_and_leaves_disk_alone():
    from agentic.review import decide, load_candidates, propose_meta_edit

    treg, tmp, skill, script = _edit_script_rig()
    out = propose_meta_edit(treg, "skill", skill.name, {}, skill.body, "",
                            resources={"scripts/run.sh": "echo two\n", "examples/a.md": "a\n"})
    assert out["ok"], out
    assert script.read_text(encoding="utf-8") == "echo one\n"        # nothing written yet
    cand = next(c for c in load_candidates(treg) if c["id"] == out["id"])
    assert [(r["path"], r["status"]) for r in cand["resource_changes"]] == \
        [("scripts/run.sh", "changed")]                                # changed files only
    diff = cand["resource_changes"][0]["diff"]
    assert any(r["l"] == "echo one" and r["r"] == "echo two" for r in diff)
    assert decide(loader.load(tmp), out["id"], "accept", "")["ok"]
    assert script.read_text(encoding="utf-8") == "echo two\n"


def test_resource_changes_report_added_and_removed_files():
    from agentic.review import load_candidates, propose_meta_edit

    treg, _tmp, skill, _script = _edit_script_rig()
    out = propose_meta_edit(treg, "skill", skill.name, {}, skill.body, "",
                            resources={"scripts/run.sh": "echo one\n", "templates/t.md": "t\n"})
    cand = next(c for c in load_candidates(treg) if c["id"] == out["id"])
    assert {(r["path"], r["status"]) for r in cand["resource_changes"]} == \
        {("examples/a.md", "removed"), ("templates/t.md", "added")}


def test_supporting_file_edited_on_disk_after_propose_is_stale_even_when_skill_md_is_not():
    """ARCH-02: `_sync_skill_resources` replaces the resource dirs wholesale on accept, so a
    file changed on disk after propose must flag the candidate — against the DISK, not the
    registry the console loaded at startup (`treg` below is never reloaded)."""
    from agentic.review import _stale, decide, load_candidates, propose_meta_edit

    treg, tmp, skill, script = _edit_script_rig()
    out = propose_meta_edit(treg, "skill", skill.name, {}, skill.body, "",
                            resources={"scripts/run.sh": "echo two\n", "examples/a.md": "a\n"})
    assert out["ok"], out
    cand = next(c for c in load_candidates(treg) if c["id"] == out["id"])
    assert cand["stale"] is False
    script.write_text("echo edited by hand\n", encoding="utf-8")        # external edit
    meta = yaml.safe_load((loader.inbox_dir(treg) / out["id"] / "meta.yaml").read_text(encoding="utf-8"))
    assert _stale(treg, meta) is True
    refused = decide(treg, out["id"], "accept", "")
    assert not refused["ok"] and refused.get("stale") is True
    assert script.read_text(encoding="utf-8") == "echo edited by hand\n"
    assert decide(treg, out["id"], "accept", "", force=True)["ok"]
    assert script.read_text(encoding="utf-8") == "echo two\n"


def test_propose_right_after_an_external_disk_edit_is_not_stale():
    """The base comes from disk at propose time too, so a console that has been running
    while a file changed does not report a false stale on its own fresh candidate."""
    from agentic.review import _stale, propose_meta_edit

    treg, _tmp, skill, script = _edit_script_rig()
    script.write_text("echo edited before propose\n", encoding="utf-8")
    out = propose_meta_edit(treg, "skill", skill.name, {}, skill.body, "",
                            resources={"scripts/run.sh": "echo two\n", "examples/a.md": "a\n"})
    meta = yaml.safe_load((loader.inbox_dir(treg) / out["id"] / "meta.yaml").read_text(encoding="utf-8"))
    assert _stale(treg, meta) is False


def _fn_src(src, start):
    body = src[src.index(start):]
    return body[:body.index("\n}\n")]


def test_app_js_drawer_points_at_the_workspace_and_the_workspace_hides_fullscreen():
    src = _ui_src("app.js")
    assert "renderSkillFilesSection(s)" in _fn_src(src, "function renderSkillDrawer")   # one-line pointer
    assert "Edit files →" in _fn_src(src, "function renderSkillFilesSection")
    assert "buildResourceEditor" not in _fn_src(src, "function renderSkillFilesSection")
    assert "hideFullscreen: true" in _fn_src(src, "function buildFileWorkspace")
    assert "if (!opts.hideFullscreen)" in _fn_src(src, "function buildContextualEditor")


def test_app_js_workspace_keeps_every_keystroke_in_the_hosts_drafts():
    """Switching files rebuilds the editor, so nothing may live only in the textarea."""
    src = _ui_src("app.js")
    ws = _fn_src(src, "function buildFileWorkspace")
    assert "opts.setText(path, value);" in ws
    host = _fn_src(src, "function skillFilesWorkspace")
    assert "drafts[key] = value;" in host and "setRes({ ...res(), [path]: value })" in host
    assert "resourceDrafts[key] = next;" in host
    assert 'skillFilesSelected = "SKILL.md";' in _fn_src(src, "function renderSkillFilesSection")
    assert "skillFilesSelected = path;" in host


def test_agent_edit_propose_leaves_the_definition_unchanged_until_accept():
    from agentic import review

    treg, tmp = _temp_registry()
    adir = tmp / "registry" / "local" / "agents"
    adir.mkdir(parents=True, exist_ok=True)
    f = adir / "ws-agent.md"
    f.write_text("---\nname: ws-agent\ndescription: d\ntargets: [overlay-harness]\n"
                 "goal: g\nskills: [graph-bootstrap]\n---\n\n# Instructions\n\nOld.\n",
                 encoding="utf-8")
    treg = loader.load(tmp)
    before = f.read_text(encoding="utf-8")
    out = review.propose_meta_edit(
        treg, "agent", "ws-agent",
        {"description": "d", "targets": ["overlay-harness"], "goal": "g", "skills": ["graph-bootstrap"]},
        "# Instructions\n\nNew.")
    assert out["ok"], out
    assert f.read_text(encoding="utf-8") == before
    assert review.decide(treg, out["id"], "accept", "")["ok"]
    assert "New." in f.read_text(encoding="utf-8")


def test_app_js_agent_form_saves_the_draft_not_the_textarea_and_can_revert():
    src = _ui_src("app.js")
    form = _fn_src(src, "function editAgentForm")
    assert ".textarea.value" not in form                      # ARB-03: one source of truth
    assert "body: draft.body," in form
    assert "buildFileWorkspace(" in form
    assert "delete agentEditDraft[agentName];" in form        # Revert
    assert 'el("button", "reject", "Revert")' in form


def test_app_js_workspace_upload_refuses_binary_and_candidate_card_lists_file_diffs():
    src = _ui_src("app.js")
    assert "looksBinary(text)" in _fn_src(src, "function buildFileWorkspace")
    card = _fn_src(src, "function candidateCard")
    assert "c.resource_changes" in card and "diffTable(rc.diff)" in card


# ── Permissions: the shared skill gate, the index, and machine curation ──────────────

_WS_MAIN = """# Workstation profile: comments like windows-main.yaml's
name: ws-main
os: windows
targets: [claude-app, claude-code]
paths:
  projects_root: "C:/Projects"
  claude_code_skills: "~/.claude/skills"   # the personal skills dir
  claude_skills_staging: "~/ClaudeSkills"

# NOTE: claude-app takes no `skills:` curation.
sync:
  git:
    hub: "git@example.com:me/overlay.git"
    branch: "main"
"""


def _machine_rig(text=_WS_MAIN, *, file_name="ws-main.yaml", eol="\n"):
    """A temp registry with one real overlay machine (no document_store) beside `rig`."""
    treg, tmp = _temp_registry()
    folder = tmp / "registry" / "local" / "machines"
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / file_name
    f.write_bytes(text.replace("\n", eol).encode("utf-8"))
    # the public core ships only connection-bound skills; plant one a coding harness gets
    sk = tmp / "registry" / "local" / "skills" / "ws-demo"
    sk.mkdir(parents=True, exist_ok=True)
    (sk / "SKILL.md").write_text(
        "---\nname: ws-demo\ndescription: d\ntargets: [claude-app, claude-code]\n---\n\nBody.\n",
        encoding="utf-8")
    return loader.load(tmp), tmp, f


def test_skill_gate_agrees_with_the_selection_deploy_uses():
    """`_selected_skills` filters on `skill_gate`, so the two cannot drift: for every
    machine shape below, a skill is selected exactly when its gate returns None."""
    from agentic.planner import _selected_skills, skill_gate
    from agentic import loader as lm

    skills = sorted(reg.skills)
    machines = [
        {}, {"document_store": "gws"},
        {"document_store": "gws", "skills": {"claude-code": {"exclude": [skills[0]]}}},
        {"document_store": "gws", "skills": {"claude-code": {"include": [skills[-1], "gws"]}}},
    ]
    for tgt in ("claude-code", "antigravity", "claude-app"):
        spec = {"include_target": tgt, **({"mode": "zip"} if tgt == "claude-app" else {})}
        manual = lm.is_manual_skill_target({"skills": spec})
        for m in machines:
            curation = {} if manual else ((m.get("skills") or {}).get(tgt) or {})
            stores = set(lm.document_stores(m.get("document_store")))
            picked = {s.name for s in _selected_skills(reg, spec, m)}
            gated = {n for n, sk in reg.skills.items()
                     if skill_gate(sk, tgt, manual, curation, stores) is None}
            assert picked == gated, (tgt, m)


def test_permissions_index_states_reach_and_reason_for_every_relationship():
    from agentic.review import permissions_index

    treg, _tmp, _f = _machine_rig()
    idx = permissions_index(treg)
    assert {m["name"] for m in idx["machines"]} >= {"ws-main"}
    assert "ws-main" in {m["name"] for m in idx["machines"] if m["editable"]}
    # FR-4: a connection-bound skill does not reach a machine that never wired the store
    row = next(r for r in idx["skill_reach"]
               if r["machine"] == "ws-main" and r["target"] == "claude-code" and r["skill"] == "gws")
    assert row["reaches"] is False and "gws" in row["reason"]
    # CON-3: one row type per relationship
    assert {"name", "manual", "project_surface"} <= set(idx["targets"][0])            # target
    assert {"requires_server", "scope", "bound_projects"} <= set(idx["skills"][0])   # scope/projects
    assert {"name", "targets", "skills"} <= set(idx["agents"][0]) if idx["agents"] else True  # agent
    assert {"machine", "target", "skill", "reaches", "reason", "note", "curatable"} <= set(row)
    assert "curation" in idx["machines"][0] and "document_stores" in idx["machines"][0]
    if idx["agent_reach"]:
        assert {"machine", "agent", "reaches", "reason"} <= set(idx["agent_reach"][0])


def test_permissions_index_manual_target_rows_are_not_curatable():
    """FR-8: claude-app stages a menu the operator picks from at upload time."""
    from agentic.review import permissions_index

    treg, _tmp, _f = _machine_rig()
    rows = [r for r in permissions_index(treg)["skill_reach"]
            if r["machine"] == "ws-main" and r["target"] == "claude-app"]
    assert rows and all(r["curatable"] is False for r in rows)
    code = [r for r in permissions_index(treg)["skill_reach"]
            if r["machine"] == "ws-main" and r["target"] == "claude-code" and r["reaches"]]
    assert code and all(r["curatable"] is True for r in code)


def test_overlay_machine_file_is_found_by_name_not_file_name():
    from agentic.review import _overlay_machine_file

    treg, _tmp, f = _machine_rig(file_name="some-other-name.yaml")
    assert _overlay_machine_file(treg, "ws-main") == f
    assert _overlay_machine_file(treg, "rig") is None          # a core-layer profile
    assert _overlay_machine_file(treg, "no-such-machine") is None


def _curation_skill(treg):
    return next(n for n in sorted(treg.skills) if "claude-code" in treg.skills[n].targets
                and treg.skills[n].requires_server is None)


def test_propose_machine_curation_builds_the_profile_and_leaves_disk_alone():
    from agentic.review import load_candidates, propose_machine_curation

    treg, _tmp, f = _machine_rig()
    before = f.read_bytes()
    skill = _curation_skill(treg)
    out = propose_machine_curation(treg, "ws-main", {"claude-code": {"exclude": [skill]}}, "trim")
    assert out["ok"], out
    assert f.read_bytes() == before                              # nothing written yet
    cand = next(c for c in load_candidates(treg) if c["id"] == out["id"])
    assert cand["kind"] == "machine" and cand["stale"] is False and cand["acceptable"]
    assert f"- {skill}" in cand["payload"] and "claude-code:" in cand["payload"]
    assert "# Workstation profile" in cand["payload"]            # comments survive
    assert any(r["t"] == "ins" for r in cand["diff"])


def test_accepted_machine_curation_changes_only_the_skills_block():
    """CON-2: every original line byte-identical, plus the `skills:` block — in the file's
    own line ending (Windows profiles are CRLF)."""
    from agentic.review import decide, propose_machine_curation

    for eol in ("\n", "\r\n"):
        treg, tmp, f = _machine_rig(eol=eol)
        before = f.read_bytes()
        skill = _curation_skill(treg)
        out = propose_machine_curation(treg, "ws-main", {"claude-code": {"exclude": [skill]}})
        assert out["ok"], out
        res = decide(treg, out["id"], "accept", "")
        assert res["ok"], res
        after = f.read_bytes()
        assert after.startswith(before.rstrip(b"\r\n")), "original bytes must be untouched"
        added = after[len(before.rstrip(b"\r\n")):].decode("utf-8")
        assert added.replace("\r\n", "\n").split() == ["skills:", "claude-code:", "exclude:", "-", skill]
        assert (b"\r\n" in after) == (eol == "\r\n")
        assert (b"\n" not in after.replace(b"\r\n", b"")) == (eol == "\r\n")
        # the same profile, read back by the loader
        assert loader.load(tmp).machines["ws-main"]["skills"] == {"claude-code": {"exclude": [skill]}}


def test_machine_curation_accept_reports_the_change_and_the_reloaded_index_shows_it():
    """ARB-01: `changed` is what makes the HTTP handler reload the registry, so the
    Permissions view reflects an accepted curation without a manual Reload from disk."""
    from agentic.review import decide, permissions_index, propose_machine_curation

    treg, tmp, _f = _machine_rig()
    skill = _curation_skill(treg)
    out = propose_machine_curation(treg, "ws-main", {"claude-code": {"exclude": [skill]}})
    res = decide(treg, out["id"], "accept", "")
    assert res["changed"] == ["local/machines/ws-main.yaml"], res
    row = next(r for r in permissions_index(loader.load(tmp))["skill_reach"]
               if r["machine"] == "ws-main" and r["target"] == "claude-code" and r["skill"] == skill)
    assert row["reaches"] is False and row["reason"].startswith("excluded by")


def test_machine_curation_is_refused_where_it_cannot_apply():
    from agentic.review import propose_machine_curation

    treg, _tmp, f = _machine_rig()
    before = f.read_bytes()
    skill = _curation_skill(treg)
    manual = propose_machine_curation(treg, "ws-main", {"claude-app": {"exclude": [skill]}})
    assert not manual["ok"] and "claude-app" in manual["error"]
    core_only = propose_machine_curation(treg, "rig", {"claude-code": {"exclude": [skill]}})
    assert not core_only["ok"] and "no profile" in core_only["error"]
    unknown = propose_machine_curation(treg, "ws-main", {"claude-code": {"exclude": ["no-such-skill"]}})
    assert not unknown["ok"]
    assert not propose_machine_curation(treg, "ws-main", {"claude-code": {"bogus": []}})["ok"]
    assert not propose_machine_curation(treg, "ws-main", {})["ok"]          # nothing to change
    assert f.read_bytes() == before


def test_machine_candidate_goes_stale_when_the_profile_changes_on_disk():
    from agentic.review import decide, propose_machine_curation

    treg, _tmp, f = _machine_rig()
    skill = _curation_skill(treg)
    out = propose_machine_curation(treg, "ws-main", {"claude-code": {"exclude": [skill]}})
    f.write_bytes(f.read_bytes() + b"# edited by hand\n")
    refused = decide(treg, out["id"], "accept", "")
    assert not refused["ok"] and refused.get("stale") is True


def test_machine_curation_endpoint_is_routed():
    src = (__import__("agentic.review", fromlist=["x"]).__file__)
    text = open(src, encoding="utf-8").read()
    assert '"/api/machines/curation"' in text and '"/api/permissions"' in text


# ── Permissions view: source scans (the UI has no DOM test harness) ─────────────────

def _perm_src():
    src = _ui_src("app.js")
    start = src.index("// ── Permissions: what reaches each machine, and why")
    return src, src[start:src.index("function orgTreeNode")]


def test_app_js_permissions_links_open_the_editors_that_own_each_relationship():
    src, perm = _perm_src()
    agent = perm[perm.index("function permAgentPanel"):perm.index("function permSkillPanel")]
    assert "editingAgentName = name;" in agent                      # FR-5: the existing agent form
    assert "openProjectEdit(slug)" in perm                          # project chip -> project editor
    assert "function openProjectEdit(slug)" in src
    assert "editBtn.onclick = () => openProjectEdit(g.slug);" in src   # the old button shares it
    assert 'openContextualEditor({ kind: "skill", ident: name, returnTab: "skills" })' in perm
    assert "openSkillDrawer(s, null)" in perm


def test_app_js_permissions_view_has_an_exit_to_the_skills_grid():
    _src, perm = _perm_src()
    view = perm[perm.index("function renderPermissionsView"):perm.index("function permSkillRows")]
    assert '"← Back to skills"' in view
    assert "permissionsOpen = false; renderSkills();" in view


def test_app_js_curation_drafts_survive_navigation_and_revert_clears_them():
    src, perm = _perm_src()
    assert "\nlet curationDrafts = {};" in src                      # module-level, not per render
    machine = perm[perm.index("function permMachinePanel"):perm.index("function permChips")]
    assert "delete curationDrafts[m.name];" in machine and '"Revert"' in machine
    assert "curationDrafts[x.name]" in perm and 'aria-label", "Edited"' in perm   # the row's dot
    assert "/api/machines/curation" in machine


def test_app_js_permissions_reach_glyphs_are_hidden_from_assistive_tech_and_not_live_regions():
    _src, perm = _perm_src()
    glyph = perm[perm.index("function permGlyph"):perm.index("function renderPermissionsView")]
    assert 'setAttribute("aria-hidden", "true")' in glyph
    assert '"sr-only"' in glyph and '"Does not reach"' in glyph
    assert 'role", "status"' not in perm and "aria-live" not in perm


def test_app_js_permissions_groups_build_their_rows_lazily():
    _src, perm = _perm_src()
    machine = perm[perm.index("function permMachinePanel"):perm.index("function permChips")]
    assert 'det.addEventListener("toggle"' in machine and "det.dataset.built" in machine


def test_app_js_refresh_rereads_permissions_while_the_view_is_open():
    src = _ui_src("app.js")
    refresh = src[src.index("async function refresh(pre)"):src.index("async function reloadFromDisk")]
    assert "if (permissionsOpen) await loadPermissions();" in refresh


def test_machine_curation_keeps_an_empty_include_list_because_it_means_deploy_nothing():
    from agentic.review import _machine_skills_block

    block, err = _machine_skills_block({"claude-code": {"include": [], "exclude": []}, "antigravity": {"exclude": []}})
    assert err is None
    assert block == {"claude-code": {"include": []}}               # empty exclude / empty block dropped


def test_permissions_endpoint_round_trip_and_cache_follows_the_reloaded_registry():
    """Over HTTP: GET /api/permissions, propose a curation, accept it, and the next GET
    reflects it. The answer is memoised per registry object, so this only holds if an accept
    that changed a file replaces the registry (the handler's reload) and so drops the cache."""
    import json
    import threading
    import urllib.request
    from agentic import review

    treg, _tmp, _f = _machine_rig()
    skill = _curation_skill(treg)
    server = review.make_server(treg, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"

        def call(path, body=None):
            req = urllib.request.Request(
                base + path, data=None if body is None else json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))

        def reach():
            idx = call("/api/permissions")
            return next(r for r in idx["skill_reach"] if r["machine"] == "ws-main"
                        and r["target"] == "claude-code" and r["skill"] == skill)["reaches"]

        assert reach() is True and reach() is True                      # second hit is the cached one
        out = call("/api/machines/curation", {"machine": "ws-main",
                                              "skills": {"claude-code": {"exclude": [skill]}}})
        assert out["ok"], out
        assert reach() is True                                          # proposing changes nothing
        assert call("/api/decide", {"id": out["id"], "decision": "accept"})["ok"]
        assert reach() is False                                         # accept -> reload -> fresh answer
    finally:
        server.shutdown()
        server.server_close()
