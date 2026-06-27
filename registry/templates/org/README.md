# Org templates (seed library)

Pre-defined organization profiles for `mitos init`. Each template seeds one file — not Jinja,
not build templates:

- `org-hierarchy.md` — the lean, always-on identity partial (session routing preference +
  primary delegation chain). On `init` it is copied to
  `registry/local/identity/org-hierarchy.md`, overriding the core multi-org router by
  last-layer-wins and flowing into Hermes's `SOUL.md` automatically.

The domain playbooks (full delegation procedure, C-suite escalation, system invariants,
red-team protocols) now ship as first-class core skills — `org-software`, `org-design`,
`org-marketing` — and are available on all hermes environments without any per-user seeding.

Available templates: `software-firm`, `design-firm`, `marketing-firm`. To add another,
create a folder with an `org-hierarchy.md` and optionally a matching `registry/skills/org-<domain>/SKILL.md`
in the core. See `docs/org-templates.md` for the full guide.
