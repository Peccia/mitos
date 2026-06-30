"""Deploy, drift, adopt, harvest, lane, env, and classify tests."""
from __future__ import annotations

import sys
from pathlib import Path

from conftest import (
    REPO_ROOT, reg, loader, planner, render, classify_output,
    _inbox, _temp_registry, _doc, _write_graph,
    _plant_candidate, _skill_meta, _full_windows_rig, _sandbox_deploy,
    _git_available, _run_git, _make_overlay_hub, _clone_overlay, _seed_overlay,
)

def test_idea_revision_targeting():
    import copy
    from agentic.loader import Skill
    rig = copy.deepcopy(reg)
    rig.skills["idea-revision"] = Skill(name="idea-revision", rel="skills/idea-revision/SKILL.md", frontmatter={"targets": ["gemini"]}, body="")
    linux = [o.deploy_path for o in planner.plan_machine(rig, "example-linux")]
    assert not any("idea-revision" in p for p in linux)        # gemini-only, not hermes
    win = [o.deploy_path for o in planner.plan_machine(rig, "example-windows")]
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

def test_mixed_agents_md_protects_prose_regenerates_doc_block():
    """A project AGENTS.md is user prose + a generated document block in ONE file. The prose
    is protected (a hand-edit drifts and adopts back to its partial); the generated block is
    not (a hand-edit of it never blocks deploy and is silently regenerated). Marker-free:
    the split lives in the lockfile, nothing is written into the deployed file."""
    from agentic import lockfile, render
    from agentic.commands import classify_output, cmd_adopt, cmd_deploy
    treg, tmp = _temp_registry()
    assert cmd_deploy(treg, "rig", dry_run=False, force=False) == 0
    f = tmp / "home/MitosAgent/Projects/Example Project/AGENTS.md"
    text = f.read_text(encoding="utf-8")
    assert "# Example Project — documents" in text          # generated titles block present
    assert "<!-- " not in text                              # marker-free (invariant #5)

    o = next(o for o in planner.plan_machine(treg, "rig")
             if o.deploy_path.endswith("Projects/Example Project/AGENTS.md"))
    assert o.drift_policy == "protect" and o.sources == ["context/projects/example-project.md"]
    assert any(render.is_generated_source(s) for s, _ in o.section_bodies)

    def state():
        return classify_output(treg, "rig", o, lockfile.load(tmp)).state
    assert state() == "unchanged"

    # 1. hand-edit ONLY the generated block → not protected drift; deploy regenerates it
    f.write_text(text.replace("# Example Project — documents",
                              "# Example Project — documents\n\n- BOGUS TITLE"),
                 encoding="utf-8", newline="\n")
    assert state() == "unchanged", "a generated-block edit must not surface as prose drift"
    before = sorted(_inbox(tmp).iterdir()) if _inbox(tmp).exists() else []
    assert cmd_deploy(treg, "rig", dry_run=False, force=False) == 0   # NOT blocked
    assert "BOGUS TITLE" not in f.read_text(encoding="utf-8")          # regenerated
    after = sorted(_inbox(tmp).iterdir()) if _inbox(tmp).exists() else []
    assert before == after, "a generated-block edit must not capture an inbox candidate"

    # 2. hand-edit the PROSE → protected drift; deploy blocks; adopt routes ONLY the prose
    anchor = treg.partials["context/projects/example-project.md"].body.splitlines()[0]
    cur = f.read_text(encoding="utf-8")
    assert anchor in cur
    f.write_text(cur.replace(anchor, anchor + " PROSE-EDIT", 1),
                 encoding="utf-8", newline="\n")
    assert state() == "drift"
    assert cmd_deploy(treg, "rig", dry_run=False, force=False) == 1   # protected, blocked
    assert cmd_adopt(treg, str(f)) == 0
    src = (tmp / "registry/context/projects/example-project.md").read_text(encoding="utf-8")
    assert "PROSE-EDIT" in src                              # prose routed back to its partial
    assert "# Example Project — documents" not in src       # generated block never leaks in
    assert "**Domain:**" not in src                         # machine-derived line never leaks

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
                      target="claude-app") == 0
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

def test_deploy_refuses_example_template_but_allows_sandbox():
    from agentic.commands import cmd_deploy
    root = Path(__import__("tempfile").mkdtemp(prefix="ae-ex-deploy-"))
    # a real deploy (no --dry-run, no --root) of a template is refused before it can write
    assert cmd_deploy(reg, "example-windows", dry_run=False, force=False, root=None) == 2
    # sandboxing it (--root) is allowed — the quick-start rehearsal path
    assert cmd_deploy(reg, "example-windows", dry_run=False, force=False, root=root) == 0

def test_yaml_merge_preserves_user_entries():
    import tempfile

    import yaml as _yaml

    from agentic.commands import _apply_yaml_merge
    from agentic.io import safe_rel

    # pull the real yaml_merge output the same way test_json_merge_preserves_user_entries does
    perm = next(o for o in planner.plan_machine(reg, "example-linux") if o.kind == "yaml_merge")

    root = Path(tempfile.mkdtemp(prefix="ae-yamlmerge-"))
    tgt = root / safe_rel(perm.target_file)
    tgt.parent.mkdir(parents=True)

    live = {
        "mcp_servers": {"old-server": {"url": "http://stale"}},
        "user_custom_key": "must-survive",
    }
    tgt.write_text(_yaml.dump(live), encoding="utf-8")

    assert _apply_yaml_merge(perm, root)

    merged = _yaml.safe_load(tgt.read_text(encoding="utf-8"))
    assert "gws" in merged["mcp_servers"]              # Mitos-owned key updated
    assert "old-server" not in merged["mcp_servers"]   # stale entry replaced
    assert merged.get("user_custom_key") == "must-survive"  # user key preserved

    # absent target file returns False without raising
    absent_root = Path(tempfile.mkdtemp(prefix="ae-yamlmerge-abs-"))
    assert _apply_yaml_merge(perm, absent_root) is False

def test_cmd_diff_smoke():
    import contextlib
    import io

    from agentic.commands import cmd_deploy, cmd_diff

    treg, _tmp = _temp_registry()
    # deploy first so cmd_diff sees [unchanged] rather than [create]
    assert cmd_deploy(treg, "rig", dry_run=False, force=False) == 0

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cmd_diff(treg, "rig", lane="all")
    assert rc == 0
    report = out.getvalue()
    assert "drift report for rig" in report
    assert "[unchanged" in report   # at least one unchanged after a clean deploy

    # unknown machine returns 2
    out2 = io.StringIO()
    with contextlib.redirect_stdout(out2):
        rc2 = cmd_diff(treg, "no-such-machine")
    assert rc2 == 2

def test_cmd_graph_smoke():
    import contextlib
    import io

    from agentic.commands import cmd_graph

    treg, _tmp = _temp_registry()

    # no project: lists all graphs, returns 0
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cmd_graph(treg, None, "documents")
    assert rc == 0
    assert "example-project" in out.getvalue()

    # valid project + valid query: returns 0
    out2 = io.StringIO()
    with contextlib.redirect_stdout(out2):
        rc2 = cmd_graph(treg, "example-project", "documents")
    assert rc2 == 0

    # valid project + invalid query name: returns 2
    out3 = io.StringIO()
    with contextlib.redirect_stdout(out3):
        rc3 = cmd_graph(treg, "example-project", "invalid_query_name")
    assert rc3 == 2

    # invalid project: returns 2
    out4 = io.StringIO()
    with contextlib.redirect_stdout(out4):
        rc4 = cmd_graph(treg, "nonexistent-project", "documents")
    assert rc4 == 2

def test_cmd_connectors_smoke():
    import contextlib
    import importlib
    import io

    sys.path.insert(0, str(REPO_ROOT / "build"))
    mitos_mod = importlib.import_module("mitos")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = mitos_mod._cmd_connectors(None)
    assert rc == 0
    assert "available connectors" in out.getvalue()

def test_cli_compile_and_mitos_entrypoints():
    import contextlib
    import importlib
    import io

    sys.path.insert(0, str(REPO_ROOT / "build"))
    compile_mod = importlib.import_module("compile")
    mitos_mod = importlib.import_module("mitos")

    # --help exits with 0 for both entrypoints
    for mod in (compile_mod, mitos_mod):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                mod.main(["--help"])
            raise AssertionError("expected SystemExit from --help")
        except SystemExit as e:
            assert e.code == 0

    # mock cmd_compile so no real dist/ write happens
    captured = {}
    orig_compile = compile_mod.commands.cmd_compile
    compile_mod.commands.cmd_compile = lambda reg, dist, target: (captured.update(t=target) or 0)
    try:
        rc = compile_mod.main(["compile", "--target", "hermes"])
        assert rc == 0
        assert captured.get("t") == "hermes"
    finally:
        compile_mod.commands.cmd_compile = orig_compile

    # mock _cmd_connectors so no side effects
    conn_called = []
    orig_conn = mitos_mod._cmd_connectors
    mitos_mod._cmd_connectors = lambda args: conn_called.append(True) or 0
    try:
        rc = mitos_mod.main(["connectors"])
        assert rc == 0 and conn_called
    finally:
        mitos_mod._cmd_connectors = orig_conn

