# Org templates (seed library)

Pre-defined organization profiles for `mitos init`. Each template seeds one file — not Jinja,
not build templates:

- `session-protocol.md` — the lean, always-on identity partial: the **Session Protocol**
  block (kept verbatim from core — it carries the `{{project_root}}`/`{{skills_root}}`
  placeholders, the skills-are-files rule, and document-map resolution) followed by the
  template's routing preference + primary delegation chain. On `init` it is copied to
  `registry/local/identity/session-protocol.md`, overriding the core `session-protocol.md`
  by last-layer-wins and flowing into Hermes's `SOUL.md` automatically — which is why a
  template must never drop the protocol block.

The domain playbooks (full delegation procedure, C-suite escalation, system invariants,
red-team protocols) now ship as first-class core skills — `org-software`, `org-design`,
`org-marketing` — and are available on all hermes environments without any per-user seeding.

Available templates: `software-firm`, `design-firm`, `marketing-firm`. To add another,
create a folder with an `session-protocol.md` and optionally a matching `registry/skills/org-<domain>/SKILL.md`
in the core. See `docs/org-templates.md` for the full guide.
