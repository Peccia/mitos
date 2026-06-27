# Mitos Organization Templates Guide

Mitos uses a layered, session-aware context model to give your assistant the right level of
detail at the right time — without loading everything on every request.

When you run the setup wizard (`python build/mitos.py init`), you are offered an optional
org template. **Leaving it blank (recommended for most setups)** keeps the core
**dynamic multi-org router** — all three domain orgs are always available, and the correct one
activates automatically per project via each project's `org:` manifest field. Choosing a named
template seeds a single-domain `org-hierarchy.md` into your private overlay (`registry/local/`),
which **locks the assistant to that one domain's delegation chain** for all project work.

The three domain org skills always ship in core and are available to all environments regardless
of which option you choose — only the routing preference file differs.

---

## Session architecture

Every new session runs the `new-session` skill, navigates to `assistant_root`, reads the root
`AGENTS.md` (the **operating root**: a lean routing + personal-context bridge, no org detail),
and routes to one of two branches:

| Branch | Path | Purpose |
|---|---|---|
| **Assistant** | `assistant_root/Assistant/AGENTS.md` | One-shot workspace tasks: email, calendar, tasks, notes, quick questions. **Non-org-specific** — no domain skill is loaded; works the same regardless of which org templates you have installed. |
| **Projects** | `assistant_root/Projects/AGENTS.md` → `assistant_root/Projects/<project>/AGENTS.md` | Multi-role project work. The Projects **branch root** carries the roster + org/domain structure (where the C-suite roles live — only loaded when entering project work); each project's own `AGENTS.md` carries its context and `**Domain:**` line. Domain skill loaded per project. |

### Domain-aware project routing

Each project manifest declares an `org:` field (one of `software`, `design`, `marketing`).
The compiler materializes this as a **Domain line** in the project's `Projects/<name>/AGENTS.md`:

```
**Domain:** software — load the `org-software` skill for project work.
```

The `new-session` skill reads this line and loads the matching domain skill automatically:

| Domain | Skill | Primary chain |
|---|---|---|
| `software` | `org-software` | CEO → VP Engineering → Assistant |
| `design` | `org-design` | CEO → Creative Director → Studio Manager |
| `marketing` | `org-marketing` | Account Director → Creative Director → Marketing Assistant |

This means all three org models are deployed and available at all times; the correct one activates
per project, per session — no re-running `mitos init` to switch contexts.

---

## Project manifest: setting the domain

Add `org:` to any project's manifest to enable domain routing:

```yaml
name: My App
slug: my-app
stage: build
org: software          # software | design | marketing
```

When `org:` is omitted the `new-session` skill falls back to the core delegation chain
(CEO/VP/Assistant) and flags the missing field to the owner.

---

## Seeded files

Each template seeds **one file** in your private overlay:

| File | Where it goes | What it does |
|---|---|---|
| `org-hierarchy.md` | `registry/local/identity/org-hierarchy.md` | Session routing preference and primary 3-role chain. Flows into `SOUL.md`. |

The domain playbooks (full delegation procedure, C-suite escalation, system invariants,
red-team protocols) live in the three core skills — they do not need to be seeded per-user.

---

## Core domain org skills

Three first-class skills ship with the Mitos core:

### `org-software`
A software engineering organization: CEO/VP Engineering/Assistant as the primary chain.
- **C-suite**: CTO (architecture/security), CFO (cloud cost/vendor ROI), COO (sprint/delivery),
  CMO (developer docs/release comms), CHCO (hiring/onboarding/culture).
- **Domain vocabulary**: `idempotency`, `backpressure`, `race-condition`, `SEV0`, `DORA-metrics`.
- **Invariants**: no code without tests, no hardcoded secrets, naming conventions enforced.
- **Best for**: feature development, architecture decisions, system design, code docs.

### `org-design`
A design studio: CEO/Creative Director/Studio Manager as the primary chain.
- **C-suite**: CTO (design tooling/DAM/pipeline), CFO (project budget/scope), COO (client
  delivery/milestones), CMO (portfolio/brand comms), CHCO (studio culture/hiring).
- **Domain vocabulary**: `kerning`, `negative-space`, `chromatic-harmony`, `typographic-scale`,
  `component-library`, `design-token`.
- **Invariants**: grid compliance, WCAG AA contrast, no unnamed layers, licensed assets only.
- **Best for**: design systems, branding, layout production, client-facing deliverables.

### `org-marketing`
A marketing agency: Account Director/Creative Director/Marketing Assistant as the primary chain.
- **C-suite**: CTO (martech/analytics/attribution), CFO (ROAS/budget), COO (campaign
  delivery/timelines), CMO (brand strategy/positioning), CHCO (agency culture/talent).
- **Domain vocabulary**: `conversion-funnel`, `audience-persona`, `ROAS`, `CTR`, `UTM`,
  `brand-equity`.
- **Invariants**: UTM tags on all URLs, platform character limits verified, brand voice checked,
  audience data required before targeting copy.
- **Best for**: campaigns, copy generation, brand strategy, marketing operations.

---

## Available template archetypes

Templates are starting points for the `org-hierarchy.md` routing preference. Select one during
`mitos init`; edit the seeded file to customize afterwards.

### 1. Software Firm (`software-firm`)
Lean routing toward `org-software` with a CEO/VP Engineering/Assistant primary chain.
Best for software products, developer tools, and technical projects.

### 2. Design Firm (`design-firm`)
Lean routing toward `org-design` with a CEO/Creative Director/Studio Manager primary chain.
Best for visual systems, branding, and client-facing design work.

### 3. Marketing Firm (`marketing-firm`)
Lean routing toward `org-marketing` with an Account Director/Creative Director/Marketing
Assistant primary chain. Best for campaigns, copy, and brand strategy.

---

## Customizing your organization

The template only seeds the initial `org-hierarchy.md`. Once copied, **you own it completely**.

- **Adjusting the routing preference**: edit `registry/local/identity/org-hierarchy.md`.
- **Extending a domain playbook**: the domain skills (`org-software`, etc.) live in
  `registry/skills/org-<domain>/SKILL.md`. Override in `registry/local/skills/` using the
  last-layer-wins convention.
- **Applying changes**:
  ```bash
  python build/compile.py compile
  python build/compile.py deploy --machine <machine-name>
  ```

---

## Best practices for creating additional organization templates

When extending Mitos with a new organization archetype:

1. **Directory structure** — create `registry/templates/org/<slug>/` with one file:
   `org-hierarchy.md`. Domain playbooks belong in `registry/skills/org-<domain>/SKILL.md`
   (core) or `registry/local/skills/org-<domain>/SKILL.md` (private overlay).

2. **Keep `org-hierarchy.md` lean** — it lands in `SOUL.md` on every request. Include only:
   the session-routing table (Assistant vs Projects) and the primary 3-role chain reference.
   Point to the domain skill for all deeper detail.

3. **Standard frontmatter**: `audience: [hermes]`.

4. **Standardize the routing table** — always bifurcate into Assistant (one-shot) and
   Projects (multi-role), referencing `assistant_root`-relative paths:
   `Assistant/AGENTS.md` and `Projects/<project>/AGENTS.md`.

5. **Reference the domain skill** — the last line of `org-hierarchy.md` should point to the
   relevant `org-<domain>` skill: "For the full delegation playbook, run the `org-<domain>` skill."

6. **Domain skills are composable** — a custom org can mix roles from different domain skills,
   or extend a core skill by overriding it in `registry/local/skills/`. Keep them generic and
   public-safe; personal details belong in the overlay.

7. **Author concrete red-team rules** — define specific trigger phrases ("skip tests",
   "bypass grid") and the required defensive response in the domain skill. Vague rules are
   not enforced.

8. **Keep templates generic and public-safe** — personal details (your name, company, real
   workspace paths) belong in `registry/local/`, not in the template. Templates are suitable
   for open-source contribution; overlays are private.

---

## Contributing new templates

1. Create `registry/templates/org/<template-slug>/` with `org-hierarchy.md`.
2. If the template introduces a new domain, add `registry/skills/org-<domain>/SKILL.md` with
   the full playbook, `targets: [hermes]`, `category: productivity`.
3. Run `python build/compile.py compile` to validate frontmatter.
4. Add a template and domain section to this document following the pattern above.
5. Submit a Pull Request. Keep content generic; no personal or company data.
