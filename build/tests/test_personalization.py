"""Dynamic personalization: user.yaml load/merge, {{user_*}} placeholder expansion,
scoped-exact-inverse reversal on adopt, and the generated Connections/Skills sections
(the 0.1.4 Dynamic Context Enhancements design)."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

from conftest import REPO_ROOT, reg, loader, planner, render, _temp_registry


class _FakeReg:
    """A minimal stand-in for Registry — expand/reverse read `.user` and `.machines`."""
    def __init__(self, user: dict, machines: dict | None = None):
        self.user = user
        self.machines = machines or {}


# ── user.yaml: load, merge, validation ───────────────────────────────────────
def test_user_defaults_when_no_user_yaml_overlay():
    treg, tmp = _temp_registry()
    assert treg.user == {"given_name": "User", "full_name": "Mitos User",
                         "email": "user@example.com", "location": "Your City, State"}

def test_user_yaml_overlay_merges_field_level():
    treg, tmp = _temp_registry()
    local = tmp / "registry" / "local"
    local.mkdir(parents=True, exist_ok=True)
    (local / "user.yaml").write_text("given_name: Sam\nemail: sam@example.com\n",
                                     encoding="utf-8")
    reg2 = loader.load(tmp)
    assert reg2.user["given_name"] == "Sam"
    assert reg2.user["email"] == "sam@example.com"
    # unset overlay keys keep the core default — field-level merge, not whole-file replace
    assert reg2.user["location"] == "Your City, State"

def test_user_yaml_rejects_unknown_key():
    _treg, tmp = _temp_registry()
    (tmp / "registry" / "user.yaml").write_text(
        "given_name: X\nbogus_key: y\n", encoding="utf-8")
    try:
        loader.load(tmp)
        raise AssertionError("expected RegistryError for an unknown user.yaml key")
    except loader.RegistryError as e:
        assert "bogus_key" in str(e)

def test_user_yaml_rejects_non_string_value():
    _treg, tmp = _temp_registry()
    (tmp / "registry" / "user.yaml").write_text("given_name: 5\n", encoding="utf-8")
    try:
        loader.load(tmp)
        raise AssertionError("expected RegistryError for a non-string value")
    except loader.RegistryError:
        pass

def test_machine_document_store_validated_like_project():
    _treg, tmp = _temp_registry()
    md = tmp / "machines" / "rig.yaml"
    data = yaml.safe_load(md.read_text(encoding="utf-8"))
    data["document_store"] = "not-a-real-server"
    md.write_text(yaml.safe_dump(data), encoding="utf-8")
    try:
        loader.load(tmp)
        raise AssertionError("expected RegistryError for an unknown document_store")
    except loader.RegistryError as e:
        assert "document_store" in str(e)


# ── expand_placeholders ───────────────────────────────────────────────────────
def test_expand_substitutes_all_five_tokens():
    user = {"given_name": "Paul", "full_name": "Paul Peccia",
            "email": "example@domain.com", "location": "Buffalo, NY"}
    text = ("{{user_given_name}} / {{users_given_name}} / {{user_full_name}} / "
            "{{user_email}} / {{user_location}}")
    out = render.expand_placeholders(_FakeReg(user), text)
    assert out == "Paul / Paul's / Paul Peccia / example@domain.com / Buffalo, NY"

def test_expand_possessive_trailing_s_uses_bare_apostrophe():
    user = {"given_name": "Chris", "full_name": "", "email": "", "location": ""}
    assert render.expand_placeholders(_FakeReg(user), "{{users_given_name}} book") == \
        "Chris' book"

def test_expand_leaves_unknown_token_untouched():
    user = {"given_name": "Paul", "full_name": "", "email": "", "location": ""}
    out = render.expand_placeholders(_FakeReg(user), "{{not_a_real_token}} and {{user_given_name}}")
    assert out == "{{not_a_real_token}} and Paul"

def test_expand_leaves_placeholder_with_no_value_untouched():
    user = {"given_name": "", "full_name": "", "email": "", "location": ""}
    out = render.expand_placeholders(_FakeReg(user), "Hi {{user_given_name}}")
    assert out == "Hi {{user_given_name}}"   # never silently drops to an empty string


# ── {{project_root}} (the machine-scoped token) ──────────────────────────────
def test_expand_project_root_prefers_assistant_root():
    user = {"given_name": "", "full_name": "", "email": "", "location": ""}
    paths = {"assistant_root": "~/MitosAgent/", "agentic_context_root": "C:/MitosAgent",
             "projects_root": "C:/Projects"}
    out = render.expand_placeholders(_FakeReg(user), "cd {{project_root}}", paths)
    assert out == "cd ~/MitosAgent"   # trailing slash normalized, assistant_root wins

def test_expand_project_root_fallback_chain():
    user = {"given_name": "", "full_name": "", "email": "", "location": ""}
    r = _FakeReg(user)
    assert render.expand_placeholders(
        r, "{{project_root}}", {"agentic_context_root": "C:/MitosAgent"}) == "C:/MitosAgent"
    assert render.expand_placeholders(
        r, "{{project_root}}", {"projects_root": "D:/Projects"}) == "D:/Projects"

def test_expand_project_root_literal_without_machine_paths():
    user = {"given_name": "", "full_name": "", "email": "", "location": ""}
    r = _FakeReg(user)
    assert render.expand_placeholders(r, "cd {{project_root}}") == "cd {{project_root}}"
    assert render.expand_placeholders(r, "cd {{project_root}}", {}) == "cd {{project_root}}"

def test_expand_skills_root_from_hermes_home():
    user = {"given_name": "", "full_name": "", "email": "", "location": ""}
    r = _FakeReg(user)
    assert render.expand_placeholders(
        r, "ls {{skills_root}}", {"hermes_home": "~/.hermes/"}) == "ls ~/.hermes/skills"
    # no hermes_home on this machine → literal
    assert render.expand_placeholders(
        r, "ls {{skills_root}}", {"projects_root": "C:/Projects"}) == "ls {{skills_root}}"

def test_reverse_expand_skills_root_matches_any_machines_value():
    user = {"given_name": "", "full_name": "", "email": "", "location": ""}
    r = _FakeReg(user, {"linux-box": {"paths": {"hermes_home": "~/.hermes"}}})
    original = "Skills live at {{skills_root}}."
    assert render.reverse_expand_placeholders(
        r, original, "Skills live at ~/.hermes/skills.") == original

def test_reverse_expand_project_root_matches_any_machines_root():
    # adopt/review don't always know which machine expanded the live text — every
    # machine's root value must fold back, still scoped to token-bearing partials.
    user = {"given_name": "", "full_name": "", "email": "", "location": ""}
    machines = {"linux-box": {"paths": {"assistant_root": "~/MitosAgent"}},
                "win": {"paths": {"agentic_context_root": "C:/MitosAgent"}}}
    r = _FakeReg(user, machines)
    original = "Navigate to {{project_root}} first."
    assert render.reverse_expand_placeholders(
        r, original, "Navigate to ~/MitosAgent first. EXTRA.") == \
        "Navigate to {{project_root}} first. EXTRA."
    assert render.reverse_expand_placeholders(
        r, original, "Navigate to C:/MitosAgent first.") == original
    # scoping: a partial without the token is never touched
    assert render.reverse_expand_placeholders(
        r, "No token here.", "Path ~/MitosAgent stays.") == "Path ~/MitosAgent stays."

def test_soul_and_new_session_skill_expand_project_root():
    # acceptance: on the rig machine (hermes + agents-md, assistant_root set) SOUL.md
    # and the deployed new-session skill name the concrete root, no literal token left.
    treg, _tmp = _temp_registry()
    outs = planner.plan_machine(treg, "rig")
    by_path = {o.deploy_path: o for o in outs}
    soul = next(o for p, o in by_path.items() if p.endswith("/SOUL.md"))
    skill = next(o for p, o in by_path.items()
                 if p.endswith("new-session/SKILL.md"))
    for out in (soul, skill):
        assert "MitosAgent" in out.content
        assert "{{project_root}}" not in out.content
    # the session protocol is inlined in SOUL (no skill-file hop) and the skill's own
    # copy stays in lock-step wording; neither leaves a literal token behind
    assert "clean slate IS the new session" in soul.content
    assert "clean slate IS the new session" in skill.content
    assert "{{skills_root}}" not in soul.content


# ── reverse_expand_placeholders (scoped exact-inverse) ───────────────────────
def test_reverse_expand_round_trips_a_simple_edit():
    user = {"given_name": "Paul", "full_name": "", "email": "", "location": ""}
    original = "Hello {{user_given_name}}, welcome."
    live = "Hello Paul, welcome. EXTRA SENTENCE."
    out = render.reverse_expand_placeholders(_FakeReg(user), original, live)
    assert out == "Hello {{user_given_name}}, welcome. EXTRA SENTENCE."

def test_reverse_expand_longest_value_first():
    # user_full_name's expansion ("Paul Peccia") contains user_given_name's ("Paul") as a
    # prefix — reversing the shorter one first would strand " Peccia" instead of
    # restoring {{user_full_name}} whole.
    user = {"given_name": "Paul", "full_name": "Paul Peccia", "email": "", "location": ""}
    original = "{{user_full_name}} says hi. {{user_given_name}} agrees."
    live = "Paul Peccia says hi. Paul agrees."
    out = render.reverse_expand_placeholders(_FakeReg(user), original, live)
    assert out == original

def test_reverse_expand_is_scoped_to_the_partials_own_tokens():
    # the default given_name "User" coincidentally appears as an ordinary English word in
    # this live text. Because {{user_given_name}} was never in `original`, it must NOT be
    # folded back — that's the corruption a global reverse-replace would cause.
    user = {"given_name": "User", "full_name": "", "email": "user@example.com", "location": ""}
    original = "Contact {{user_email}} for help."
    live = "Contact user@example.com for help. The User already knows about this."
    out = render.reverse_expand_placeholders(_FakeReg(user), original, live)
    assert out == "Contact {{user_email}} for help. The User already knows about this."

def test_reverse_expand_noop_when_nothing_changed():
    user = {"given_name": "Paul", "full_name": "", "email": "", "location": ""}
    original = "Hello {{user_given_name}}."
    live = "Hello Paul."
    assert render.reverse_expand_placeholders(_FakeReg(user), original, live) == original


# ── connections_block / skills_block ─────────────────────────────────────────
def test_connection_label_is_stable_name_and_key():
    label = render.connection_label(reg.servers["servers"], "gws")
    assert label is not None
    heading, detail = label
    assert heading.endswith("(`gws`)")            # stable, key-anchored heading
    assert "`" not in heading.split("(`gws`)")[0] # name is plain text before the key
    # unset / unknown stores name no connection
    assert render.connection_label(reg.servers["servers"], None) is None
    assert render.connection_label(reg.servers["servers"], "none") is None
    assert render.connection_label(reg.servers["servers"], "nope") is None


def test_connections_block_empty_without_document_store():
    assert render.connections_block(reg.servers["servers"], {}, reg.user) == ""
    assert render.connections_block(reg.servers["servers"], {"document_store": "none"},
                                    reg.user) == ""

def test_connections_block_lists_the_bound_server():
    block = render.connections_block(reg.servers["servers"], {"document_store": "gws"},
                                     reg.user)
    assert block.lstrip().startswith("## ")   # a `## <Name> (`key`)` connection section
    assert "(`gws`)" in block                 # stable heading carries the server key
    assert "calendar" in block   # derived from servers.yaml's tools: groups

def test_skills_block_excludes_org_domain_skills():
    block = render.skills_block(list(reg.skills.values()))
    assert "## Skills" in block
    assert "`gws`" in block
    assert "org-software" not in block   # org-domain skills get org_domain_table instead
    # usage line: skills are files to read, never callable tools; the token expands
    # later via the planner's machine-token pass
    assert "never a callable tool" in block
    assert "{{skills_root}}" in block

def test_skills_block_empty_for_no_general_skills():
    org_only = [s for s in reg.skills.values() if s.frontmatter.get("org_domain")]
    assert render.skills_block(org_only) == ""

def test_project_roster_block_lists_projects():
    block = render.project_roster_block([
        {"name": "Example Project", "slug": "example-project",
         "description": "a sample"},
        {"name": "Bare", "slug": "bare"}])
    assert "## Project Roster" in block
    assert "- `Projects/Example Project/` (example-project) — a sample" in block
    assert "- `Projects/Bare/` (bare)" in block          # no description → no dash
    assert render.project_roster_block([]) == ""


# ── planner: expansion pass + generated sections ─────────────────────────────
def test_expand_output_skips_merge_and_env_kinds_but_expands_text():
    from agentic.planner import Output, _expand_output
    merge = Output(target="x", kind="yaml_merge", deploy_path="p", dist_rel="p",
                   content="mcp_servers:\n  note: '{{user_given_name}}'\n",
                   drift_policy="protect")
    assert _expand_output(reg, merge).content == merge.content
    env = Output(target="x", kind="env", deploy_path="p", dist_rel="p",
                content="FOO={{user_given_name}}\n", drift_policy="protect")
    assert _expand_output(reg, env).content == env.content
    text = Output(target="x", kind="text", deploy_path="p", dist_rel="p",
                 content="Hello {{user_given_name}}", drift_policy="protect")
    assert _expand_output(reg, text).content == "Hello User"

def test_expand_output_expands_zip_members():
    from agentic.planner import Output, _expand_output
    o = Output(target="claude-app", kind="zip", deploy_path="p", dist_rel="p",
              content="unused", drift_policy="protect",
              zip_members={"skill/SKILL.md": "Hi {{user_given_name}}"})
    out = _expand_output(reg, o)
    assert out.zip_members["skill/SKILL.md"] == "Hi User"

def test_root_agents_md_gets_one_combined_generated_section():
    treg, tmp = _temp_registry()
    treg.machines["rig"]["document_store"] = "gws"
    outs = planner.plan_machine(treg, "rig")
    root = next(o for o in outs if o.deploy_path.endswith("MitosAgent/AGENTS.md"))
    assert "(`gws`)" in root.content   # the connection section, headed by the store key
    assert "## Skills" in root.content
    gen = [s for s, _ in root.section_bodies if render.is_generated_source(s)]
    assert len(gen) == 1, "connections + skills + branches must merge into ONE <generated> section"

def test_projects_agents_md_gets_generated_roster_and_org_table():
    # acceptance: Projects/AGENTS.md carries the manifest-driven Project Roster and the
    # org-domain table merged into ONE <generated> section; the roster line comes from
    # the manifest's name/slug/description, not hand-written prose.
    treg, tmp = _temp_registry()
    outs = planner.plan_machine(treg, "rig")
    pa = next(o for o in outs if o.deploy_path.endswith("Projects/AGENTS.md"))
    assert "## Project Roster" in pa.content
    assert "- `Projects/Example Project/` (example-project) — one-line summary" \
        in pa.content
    assert "## Skills" in pa.content   # the org-domain table is the Projects node's Skills
    gen = [s for s, _ in pa.section_bodies if render.is_generated_source(s)]
    assert len(gen) == 1, "roster + org table must merge into ONE <generated> section"

def test_root_agents_md_omits_connections_without_document_store():
    treg, tmp = _temp_registry()   # rig has no document_store set
    outs = planner.plan_machine(treg, "rig")
    root = next(o for o in outs if o.deploy_path.endswith("MitosAgent/AGENTS.md"))
    assert "## Connections" not in root.content

def test_assistant_agents_md_gets_connections_block():
    treg, tmp = _temp_registry()
    treg.machines["rig"]["document_store"] = "gws"
    outs = planner.plan_machine(treg, "rig")
    assistant = next(o for o in outs if o.deploy_path.endswith("Assistant/AGENTS.md"))
    assert "(`gws`)" in assistant.content   # the connection section on the Assistant branch


# ── adopt: reversal is applied before the registry write ─────────────────────
def test_adopt_reverses_expanded_placeholder_in_who_i_am():
    from agentic.commands import cmd_adopt, cmd_deploy
    treg, tmp = _temp_registry()
    assert cmd_deploy(treg, "rig", dry_run=False, force=False) == 0
    soul = tmp / "home/.hermes/SOUL.md"
    text = soul.read_text(encoding="utf-8")
    expanded_line = ("You are User's personal assistant, focusing on truth, clarity, and "
                     "usefulness rather than on mere politeness.")
    assert expanded_line in text, "SOUL.md must carry the EXPANDED placeholder, not the token"
    assert "{{users_given_name}}" not in text
    soul.write_text(text.replace(expanded_line, expanded_line + " EDITED-IN-PLACE", 1),
                    encoding="utf-8", newline="\n")
    assert cmd_adopt(treg, str(soul)) == 0
    who = (tmp / "registry/identity/who-i-am.md").read_text(encoding="utf-8")
    assert "{{users_given_name}} personal assistant" in who   # placeholder restored, not baked-in
    assert "EDITED-IN-PLACE" in who                            # the edit landed
    assert "User's personal assistant" not in who
    # convergence: a fresh load re-renders to match the live file → next deploy relocks
    assert cmd_deploy(loader.load(tmp), "rig", dry_run=False, force=False) == 0


# ── review._stale(): personalized sections must not show permanently stale ──
def test_review_console_candidate_not_stale_from_expansion_alone():
    """A captured multi-source candidate's `sections` hold EXPANDED text (planner runs
    the personalization pass before it lands in the lockfile). review._stale() must fold
    that back through each section's own placeholder tokens before comparing against the
    registry partial's (placeholder-form) body — otherwise every personalized partial
    would look permanently stale even with zero actual registry drift."""
    from agentic import review
    from agentic.commands import cmd_deploy
    treg, tmp = _temp_registry()
    assert cmd_deploy(treg, "rig", dry_run=False, force=False) == 0
    soul = tmp / "home/.hermes/SOUL.md"
    live = soul.read_text(encoding="utf-8")
    anchor = treg.partials["identity/who-i-am.md"].body.splitlines()[0]
    soul.write_text(live.replace(anchor, anchor + " EDITED-VIA-CONSOLE", 1),
                    encoding="utf-8", newline="\n")
    assert cmd_deploy(treg, "rig", dry_run=False, force=True) == 0   # captures to inbox/
    from conftest import _inbox
    cand = next(p for p in _inbox(tmp).iterdir() if p.is_dir())
    c = next(c for c in review.load_candidates(treg) if c["id"] == cand.name)
    assert c["acceptable"] and c["stale"] is False   # no registry drift actually occurred
    out = review.decide(treg, cand.name, "accept", "")
    assert out["ok"] and out["changed"] == ["identity/who-i-am.md"]


# ── init: scaffold_overlay writes user.yaml, who-i-am.md drops facts ─────────
def test_scaffold_overlay_writes_user_yaml_and_slims_who_i_am():
    from agentic import init as initmod
    _treg, tmp = _temp_registry()
    written = initmod.scaffold_overlay(tmp, given_name="Sam", family_name="Lee",
                                       email="sam@example.com", location="Austin, TX",
                                       backend="mock")
    assert "local/user.yaml" in written
    data = yaml.safe_load((tmp / "registry/local/user.yaml").read_text(encoding="utf-8"))
    assert data == {"given_name": "Sam", "full_name": "Sam Lee",
                    "email": "sam@example.com", "location": "Austin, TX"}
    who = (tmp / "registry/local/identity/who-i-am.md").read_text(encoding="utf-8")
    assert "sam@example.com" not in who and "Austin, TX" not in who
    reg2 = loader.load(tmp)
    assert reg2.user["email"] == "sam@example.com"
    assert reg2.user["location"] == "Austin, TX"

def test_scaffold_overlay_skips_user_yaml_with_no_answers():
    from agentic import init as initmod
    _treg, tmp = _temp_registry()
    written = initmod.scaffold_overlay(tmp, given_name="", backend="mock")
    assert "local/user.yaml" not in written
    assert not (tmp / "registry/local/user.yaml").exists()
