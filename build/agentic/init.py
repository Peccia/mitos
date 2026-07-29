"""`mitos init` scaffolding — create the gitignored personal overlay (the Mitos overlay design).

Interactive setup belongs to a SEPARATE entrypoint (build/mitos.py), never the deterministic
compiler verbs (Phase E constraint #1). This module holds the pure, testable scaffolding;
mitos.py wraps it with prompts. Selecting an org template here is how the selectable templates
**replace** the single fixed Phase C′ org: the chosen seed lands in the overlay and overrides
the core by last-layer-wins.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from .loader import LOCAL_OVERLAY

ORG_TEMPLATES_DIR = "registry/templates/org"
OVERLAY_SUBDIRS = ("identity", "context", "projects", "graph", "skills")

# The named machine shapes (see machines/example-*.yaml for the shipped templates these
# mirror) — each maps directly to a `targets:` list. These are PRESETS, not the full set
# of legal profiles: `scaffold_machine` also takes an arbitrary `targets=` list, which is
# how `mitos init` offers the coding harnesses as an independent multi-select (there is
# nothing special about the claude-code-only shape — it was simply the only single-harness
# preset anyone had written down). `hermes` in a machine's targets excludes the
# coding-harness targets on that same machine (loader._validate's machine-role exclusivity
# check), so "coding harnesses" and "full agentic assistant" are mutually exclusive by
# construction, not just by this wizard's framing. Org skills
# (`org-software`/`org-design`/`org-marketing`) declare `targets: [hermes]` only, and the
# org-domain routing table/lines render solely on the agents-md/hermes tree
# (render.org_domain_table, graph._effort_domain_line) — so only a hermes machine ever
# deploys orgs; a coding-harness machine never does.
MACHINE_USE_CASES: dict[str, list[str]] = {
    "workstation": ["claude-code"],
    "coding": ["antigravity", "claude-app", "claude-code"],
    "hermes": ["hermes", "agents-md"],
}

# The coding harnesses a user picks from independently, with the label the wizard shows.
CODING_TARGETS: dict[str, str] = {
    "claude-code": "Claude Code",
    "antigravity": "Antigravity",
    "claude-app": "Claude Desktop / claude.ai",
}

# Which `paths:` keys each target actually needs, and the starter value to write for each.
# A profile's paths block is the UNION over its targets (deduped, in _PATH_ORDER) — that
# is what makes an arbitrary target subset scaffoldable instead of only the three presets.
# Key order doubles as the emit order of `targets:`, matching machines/example-*.yaml.
_TARGET_PATH_KEYS: dict[str, tuple[str, ...]] = {
    "antigravity": ("projects_root", "antigravity_config", "antigravity_skills"),
    "claude-app": ("claude_skills_staging",),
    "claude-code": ("projects_root", "claude_code_skills"),
    "hermes": ("hermes_home", "hermes_config", "assistant_root"),
    "agents-md": (),          # a context FORMAT, not a harness — owns no path of its own
}

# Stable emit order, so two profiles with overlapping targets read the same way.
_PATH_ORDER = ("projects_root", "antigravity_config", "antigravity_skills",
               "claude_code_skills", "claude_skills_staging",
               "hermes_home", "hermes_config", "assistant_root")

_PATH_VALUES: dict[str, str] = {
    "antigravity_config": "~/.gemini/config",
    "antigravity_skills": "~/.gemini/config/skills",
    "claude_code_skills": "~/.claude/skills",
    "claude_skills_staging": "~/ClaudeSkills",
    "hermes_home": "~/.hermes",
    "hermes_config": "~/.hermes/config.yaml",
    "assistant_root": "~/MitosAgent",
}


def known_servers(root: Path) -> list[str]:
    """The MCP server keys a machine may name in `document_store:` (connections/servers.yaml,
    plus any the overlay adds). Read directly rather than through `loader.load` — init runs
    before an overlay exists, and a half-built registry must not stop the wizard asking."""
    names: list[str] = []
    for conn in (root / "connections" / "servers.yaml",
                 root / "registry" / LOCAL_OVERLAY / "connections" / "servers.yaml"):
        if not conn.is_file():
            continue
        try:
            data = yaml.safe_load(conn.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for name in (data.get("servers") or {}):
            if name not in names:
                names.append(name)
    return names


def org_templates(root: Path) -> list[str]:
    """The available org seeds (folder names under registry/templates/org/)."""
    base = root / ORG_TEMPLATES_DIR
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir()
                  if p.is_dir() and (p / "session-protocol.md").is_file())


def scaffold_overlay(root: Path, *, given_name: str, family_name: str = "",
                     address: str = "", email: str = "", location: str = "",
                     org_template: str | None = None,
                     backend: str = "gws", overwrite: bool = False) -> list[str]:
    """Create registry/local/ and seed it: the optional org template seed, a starter identity
    partial from the user's answers, and the empty trees the user fills in. **Non-destructive by
    default** — a seed file is skipped when the user already has one (so this can finish an
    install around existing custom data); pass overwrite=True to force a clean re-scaffold.
    Returns the list of registry-relative paths it *created* (files it kept are omitted). Pure
    (no prompts), so it is testable. Raises ValueError on an unknown org template.

    `org_template` is optional — pass None (the default) to skip seeding `session-protocol.md`
    and use the core session protocol as-is. Domain org skills (`org-software`, `org-design`,
    `org-marketing`) always ship in core; only the routing preference file is seeded here.

    `address` is how the assistant should refer to the user (a given name like "Sam", a
    family form like "Dr. Lee", or any preferred handle); it defaults to the given name. It
    lands in the overlay identity so every tool addresses the user the same way — skills stay
    neutral ("the owner") and read the name from this always-on identity partial."""
    templates = org_templates(root)
    if org_template is not None and org_template not in templates:
        raise ValueError(f"unknown org template {org_template!r}; available: {templates}")
    overlay = root / "registry" / LOCAL_OVERLAY
    written: list[str] = []

    for sub in OVERLAY_SUBDIRS:
        (overlay / sub).mkdir(parents=True, exist_ok=True)

    def _seed(relpath: str, *, text: str | None = None, copy_from=None) -> None:
        """Write a seed file — but **never clobber** one the user already has. Existing custom
        data always wins (so init can finish an install around files you brought yourself);
        pass overwrite=True only to force a clean re-scaffold. Records only what it creates."""
        dest = overlay / relpath
        if dest.exists() and not overwrite:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        if copy_from is not None:
            shutil.copyfile(copy_from, dest)
        else:
            dest.write_text(text or "", encoding="utf-8")
        written.append(f"{LOCAL_OVERLAY}/{relpath}")

    # 1. Org template → overlay (optional). When provided, registry/local/identity/session-protocol.md
    #    overrides the core session-protocol.md by key and flows into Hermes's SOUL.md. When None,
    #    the core session protocol is used as-is — domain skills ship in core regardless.
    if org_template is not None:
        tdir = root / ORG_TEMPLATES_DIR / org_template
        _seed("identity/session-protocol.md", copy_from=tdir / "session-protocol.md")

    # 2. Starter identity partial: style/address only. Facts (name, email, location) live
    #    in user.yaml below — the single source of truth the core partials' placeholders
    #    ({{user_given_name}}, {{user_email}}, {{user_location}}, ...) expand from, so
    #    they're captured once, not duplicated into prose that can drift out of sync.
    _seed("identity/who-i-am.md", text=_who_md(given_name, family_name, address))

    # 2b. user.yaml — the personalization config every tool's deployed context expands
    #     placeholders from (render.expand_placeholders). Skipped (no file written) when
    #     the caller supplied no answers at all, exactly like the other conditional seeds.
    user_yaml = _user_yaml(given_name, family_name, email, location)
    if user_yaml:
        _seed("user.yaml", text=user_yaml)

    # 3. A README marking the overlay private + recording the chosen backend. It lives at the
    #    overlay root (not under identity/context/skills) so the loader never treats it as
    #    content.
    _seed("README.md", text=_overlay_readme(backend))
    return written


def _who_md(given_name: str, family_name: str, address: str) -> str:
    """Style/address only — NOT name/email/location facts, which now live in user.yaml
    (seeded separately below) and reach every core partial via its placeholders. Keeping
    facts in one place means they can't drift out of sync between this prose override
    and the config a future `mitos init` re-run or console edit might update."""
    full = " ".join(p for p in (given_name.strip(), family_name.strip()) if p)
    addr = address.strip() or given_name.strip() or full
    who = full or addr or "the owner"
    # Match the core who-i-am.md audience so the name/address reach every tool, not just
    # Hermes — this overlay partial replaces the neutral core one by last-layer-wins.
    return (f"---\naudience: [hermes, claude-code, antigravity, agents-md]\n---\n## About Me\n\n"
            f"You are {who}'s personal assistant, focused on truth, clarity, and usefulness "
            f"over politeness. Address me as \"{addr}\".\n")


def _user_yaml(given_name: str, family_name: str, email: str, location: str) -> str:
    """The personalization config (registry/local/user.yaml) — every deployed context
    file's {{user_*}} placeholders expand from this. Only fields the user actually
    supplied are written; unset ones fall back to the core registry/user.yaml defaults."""
    full = " ".join(p for p in (given_name.strip(), family_name.strip()) if p)
    data = {}
    if given_name.strip():
        data["given_name"] = given_name.strip()
    if full:
        data["full_name"] = full
    if email.strip():
        data["email"] = email.strip()
    if location.strip():
        data["location"] = location.strip()
    if not data:
        return ""
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _overlay_readme(backend: str) -> str:
    """`backend` is the document store chosen at init, or "none" — it is a NOTE here, not
    the wiring. The live setting is the machine profile's `document_store:`, which is what
    gates every connection-bound output; this file only records the answer for a reader."""
    store_note = (
        "Workspace connection: none yet. Add `document_store: <server>` to your machine "
        "profile once the server is running (see docs/connectors/), then re-deploy — the "
        "MCP wiring and any `requires_server:` skill appear on that deploy.\n"
        if backend in ("", "none") else
        f"Workspace connection: `{backend}` — see the connector docs to connect it, then "
        f"`python build/mitos.py connect --project <slug>`.\n")
    return ("# Personal overlay (private)\n\n"
            "This tree is your Mitos personalization. It is **gitignored** — never committed "
            "to the public repo. It overrides the core registry by last-layer-wins: a file "
            "here with the same logical path/name as a core file replaces it; new files are "
            "added; core-only files remain.\n\n"
            "Your own skills live in `skills/<name>/SKILL.md` here — the skills that ship in "
            "core target the agentic assistant (`hermes`), so a coding-harness machine "
            "installs none of them. Author one by hand or from the console's Skills & Orgs "
            "tab (`python build/compile.py review`).\n\n"
            + store_note)


def resolve_targets(*, use_case: str | None = None,
                    targets: list[str] | None = None) -> list[str]:
    """The `targets:` list for a machine, from either a named preset or an explicit set.
    Exactly one of the two must be given. An explicit set is normalized (deduped, emitted
    in `_TARGET_PATH_KEYS` order) and `hermes` pulls in `agents-md`, since the operating
    tree is the whole point of that target. Raises ValueError on an unknown name, an empty
    set, or a hermes+coding mix — the last one mirrors `loader._validate`'s machine-role
    exclusivity check, so the wizard refuses before writing a profile that cannot compile."""
    if (use_case is None) == (targets is None):
        raise ValueError("pass exactly one of use_case= or targets=")
    if use_case is not None:
        if use_case not in MACHINE_USE_CASES:
            raise ValueError(f"unknown use case {use_case!r}; available: "
                             f"{sorted(MACHINE_USE_CASES)}")
        return list(MACHINE_USE_CASES[use_case])

    chosen = set(targets or ())
    if not chosen:
        raise ValueError("targets= must name at least one target")
    unknown = sorted(chosen - set(_TARGET_PATH_KEYS))
    if unknown:
        raise ValueError(f"unknown target(s) {unknown}; available: "
                         f"{sorted(_TARGET_PATH_KEYS)}")
    if "hermes" in chosen:
        clash = sorted(chosen & set(CODING_TARGETS))
        if clash:
            raise ValueError(
                f"'hermes' cannot share a machine with {clash} — an agentic machine is "
                f"dedicated to that purpose. Use a project's `agentic_tree:` instead.")
        chosen.add("agents-md")
    return [t for t in _TARGET_PATH_KEYS if t in chosen]


def scaffold_machine(root: Path, *, name: str, os_name: str, use_case: str | None = None,
                     targets: list[str] | None = None, document_store: str | None = None,
                     overwrite: bool = False) -> str | None:
    """Write `registry/local/machines/<name>.yaml` — the profile that actually decides what
    `deploy` materializes on this box. Takes either a named preset (`use_case`, see
    `MACHINE_USE_CASES`) or an explicit `targets` list; the `paths:` block is derived as the
    union of what those targets need, so any legal subset scaffolds, not just the presets.
    Mirrors `machines/example-*.yaml`'s field/path conventions.

    `document_store` is the machine's connection — the one signal every connection-bound
    output is gated on (MCP wiring, plus any skill declaring `requires_server:`). Pass None
    (the default) to omit the field entirely, which is the honest state for a box whose
    server is not running yet: nothing connection-bound deploys, and `deploy` says what it
    withheld and why. Not validated here against `connections/servers.yaml` — the loader
    owns that check, and duplicating it would mean two places to keep in sync.

    **Non-destructive by default** (matches `scaffold_overlay`): does nothing and returns
    None when the profile already exists, unless `overwrite=True`. Returns the
    registry-relative path it wrote, or None when it skipped. Raises ValueError on an
    unknown use case/target or an illegal target mix."""
    resolved = resolve_targets(use_case=use_case, targets=targets)
    dest = root / "registry" / LOCAL_OVERLAY / "machines" / f"{name}.yaml"
    if dest.exists() and not overwrite:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_machine_yaml(name, os_name, resolved, document_store),
                    encoding="utf-8")
    return f"{LOCAL_OVERLAY}/machines/{name}.yaml"


def _machine_yaml(name: str, os_name: str, targets: list[str],
                  document_store: str | None) -> str:
    keys: list[str] = []
    for target in targets:
        for key in _TARGET_PATH_KEYS[target]:
            if key not in keys:
                keys.append(key)
    values = dict(_PATH_VALUES,
                  projects_root="C:/Projects" if os_name == "windows" else "~/Projects")

    lines = [f"name: {name}", f"os: {os_name}", f"targets: [{', '.join(targets)}]"]
    if document_store:
        lines.append(f"document_store: {document_store}")
    else:
        lines += [
            "# The connections this box has. Everything connection-bound is gated on it:",
            "# the MCP wiring spliced into each harness's config AND any skill declaring",
            "# `requires_server:`. Uncomment once the server is really running, so this",
            "# machine never receives instructions for tools it cannot call.",
            "# document_store: gws",
        ]
    lines.append("paths:")
    lines += [f'  {key}: "{values[key]}"' for key in _PATH_ORDER if key in keys]
    return "\n".join(lines) + "\n"
