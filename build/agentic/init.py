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

from .loader import LOCAL_OVERLAY

ORG_TEMPLATES_DIR = "registry/templates/org"
OVERLAY_SUBDIRS = ("identity", "projects", "graph", "skills", "agents")


def org_templates(root: Path) -> list[str]:
    """The available org seeds (folder names under registry/templates/org/)."""
    base = root / ORG_TEMPLATES_DIR
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir()
                  if p.is_dir() and (p / "org-hierarchy.md").is_file())


def scaffold_overlay(root: Path, *, given_name: str, family_name: str = "",
                     address: str = "", email: str = "", location: str = "",
                     org_template: str = "solo-assistant",
                     backend: str = "gws", overwrite: bool = False) -> list[str]:
    """Create registry/local/ and seed it: the chosen org template (which overrides the core
    org by key), a starter identity partial from the user's answers, and the empty trees the
    user fills in. **Non-destructive by default** — a seed file is skipped when the user already
    has one (so this can finish an install around existing custom data); pass overwrite=True to
    force a clean re-scaffold. Returns the list of registry-relative paths it *created* (files
    it kept are omitted). Pure (no prompts), so it is testable. Raises ValueError on an unknown
    org template.

    `address` is how the assistant should refer to the user (a given name like "Sam", a
    family form like "Dr. Lee", or any preferred handle); it defaults to the given name. It
    lands in the overlay identity so every tool addresses the user the same way — skills stay
    neutral ("the owner") and read the name from this always-on identity partial."""
    templates = org_templates(root)
    if org_template not in templates:
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

    # 1. Org template → overlay. registry/local/identity/org-hierarchy.md overrides the core
    #    org-hierarchy.md by key, so it flows straight into Hermes's SOUL.md; the playbook
    #    overrides the core `org` skill the same way.
    tdir = root / ORG_TEMPLATES_DIR / org_template
    _seed("identity/org-hierarchy.md", copy_from=tdir / "org-hierarchy.md")
    _seed("skills/org/SKILL.md", copy_from=tdir / "org-skill.md")

    # 2. Starter identity partial from the user's answers.
    _seed("identity/who-i-am.md",
          text=_who_md(given_name, family_name, address, email, location))

    # 3. A README marking the overlay private + recording the chosen backend. It lives at the
    #    overlay root (not under identity/context/skills) so the loader never treats it as
    #    content.
    _seed("README.md", text=_overlay_readme(backend))
    return written


def _who_md(given_name: str, family_name: str, address: str,
            email: str, location: str) -> str:
    full = " ".join(p for p in (given_name.strip(), family_name.strip()) if p)
    addr = address.strip() or given_name.strip() or full
    who = full or addr or "the owner"
    loc = f"\n- **Location:** {location}" if location else ""
    mail = f"\n- **Email:** {email}" if email else ""
    # Match the core who-i-am.md audience so the name/address reach every tool, not just
    # Hermes — this overlay partial replaces the neutral core one by last-layer-wins.
    return (f"---\naudience: [hermes, claude-code, gemini, agents-md]\n---\n## About Me\n\n"
            f"You are {who}'s personal assistant, focused on truth, clarity, and usefulness "
            f"over politeness. Address me as \"{addr}\".\n{mail}{loc}\n")


def _overlay_readme(backend: str) -> str:
    return ("# Personal overlay (private)\n\n"
            "This tree is your Mitos personalization. It is **gitignored** — never committed "
            "to the public repo. It overrides the core registry by last-layer-wins: a file "
            "here with the same logical path/name as a core file replaces it; new files are "
            "added; core-only files remain.\n\n"
            f"Workspace backend: `{backend}` — see the connector docs to connect it, then "
            "`python build/mitos.py connect --project <slug>`.\n")
