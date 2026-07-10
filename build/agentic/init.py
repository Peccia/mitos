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
OVERLAY_SUBDIRS = ("identity", "context", "projects", "graph", "skills", "agents")


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
    return ("# Personal overlay (private)\n\n"
            "This tree is your Mitos personalization. It is **gitignored** — never committed "
            "to the public repo. It overrides the core registry by last-layer-wins: a file "
            "here with the same logical path/name as a core file replaces it; new files are "
            "added; core-only files remain.\n\n"
            f"Workspace backend: `{backend}` — see the connector docs to connect it, then "
            "`python build/mitos.py connect --project <slug>`.\n")
