# Org templates (seed library)

Pre-defined organization profiles for `mitos init` (the Mitos overlay design). Each template
is a pair of **registry content** seeds — not Jinja, not build templates:

- `org-hierarchy.md` — the lean, always-on identity partial (the delegation chain). On
  `init` it is copied to `registry/local/identity/org-hierarchy.md`, where it **overrides**
  the core default by last-layer-wins and flows into Hermes's `SOUL.md` automatically.
- `org-skill.md` — the on-demand playbook. Copied to `registry/local/skills/org/SKILL.md`,
  overriding the core `org` skill.

This is how selectable templates **replace** the single fixed org of Phase C′: the core
ships a default, `init` picks a template into the overlay, and the user edits their copy
freely. Available: `solo-assistant`, `software-firm`, `design-firm`. Add a folder here with
the same two files to contribute another.
