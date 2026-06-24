# Mitos Organization Templates Guide

Mitos uses a layered, session-aware context model to give your assistant the right level of
detail at the right time — without loading everything on every request.

When you run the setup wizard (`python build/mitos.py init`), you are offered an optional
org template. **Leaving it blank (recommended for most setups)** keeps the core
**dynamic multi-org router** — all three domain orgs are always available, and the correct one
activates **per task**: projects are never bound to a single org, and the same project can hold
software, design, and marketing work side by side. Choosing a named template seeds a
single-domain `session-protocol.md` into your private overlay (`registry/local/`), which **locks
the assistant to that one domain's delegation chain** for all project work.

The three domain org skills always ship in core and are available to all environments regardless
of which option you choose — only the routing preference file differs.

---

## Session architecture

Every new session runs the `new-session` skill, changes directory to the project root (the
machine's `assistant_root` path, rendered concretely into `SOUL.md` via the
`{{project_root}}` placeholder), reads the root `AGENTS.md` (the **operating root**: a lean
routing + personal-context bridge, no org detail), and routes to one of two branches:

| Branch | Path | Purpose |
|---|---|---|
| **Assistant** | `assistant_root/Assistant/AGENTS.md` | One-shot workspace tasks: email, calendar, tasks, notes, quick questions. **Non-org-specific** — no domain skill is loaded; works the same regardless of which org templates you have installed. |
| **Projects** | `assistant_root/Projects/AGENTS.md` → `assistant_root/Projects/<project>/AGENTS.md` | Multi-role project work. The Projects **branch root** carries the roster + a dynamically generated table of the available domain org skills; each project's own `AGENTS.md` carries its context and document index. Domain skill (including its delegation procedure and C-suite roles) loaded **per task**, not per project. |

### Task-aware org routing

**Projects are never bound to a single org** — the org association lives on the project's
**efforts** (the `CreativeWork` groupings in its knowledge graph), never on the project
manifest. Tag an effort with an org domain in the operator console's Knowledge Graph tab (the
effort editor's `Org domain` select), and the compiler materializes a routing line under that
effort's heading in the generated `AGENTS.md`:

```
## Steam Launch
_Work in this effort runs under the `marketing` org — load the `org-marketing` skill._
```

On each task, the session matches the request to an effort and loads that effort's domain
skill; when no tagged effort matches, it classifies the request itself
(building/refactoring → `org-software`; visual/brand → `org-design`; positioning/launch/content
→ `org-marketing`):

| Domain | Skill | Primary chain |
|---|---|---|
| `software` | `org-software` | CEO → VP Engineering → Assistant |
| `design` | `org-design` | CEO → Creative Director → Studio Manager |
| `marketing` | `org-marketing` | Account Director → Creative Director → Marketing Assistant |

This means all three org models are deployed and available at all times, and a single project
can switch orgs task by task — the engine-refactor effort runs under `org-software` while the
launch effort in the same project runs under `org-marketing`. No re-running `mitos init`, no
redeploy to switch contexts. The C-suite roles (CEO, CTO, CFO, COO, CMO, CHCO) are the same
identities in every domain — only the active domain colors their lens.

---

## Seeded files

Each template seeds **one file** in your private overlay:

| File | Where it goes | What it does |
|---|---|---|
| `session-protocol.md` | `registry/local/identity/session-protocol.md` | The **Session Protocol** block (identical to core — run `new-session`, `cd {{project_root}}`, read `AGENTS.md`, plus the navigation facts) followed by the template's **routing preference** and primary 3-role chain. Flows into `SOUL.md`. |

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

Templates are starting points for the `session-protocol.md` routing preference. Select one during
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

The template only seeds the initial `session-protocol.md`. Once copied, **you own it completely**.

- **Adjusting the routing preference**: edit `registry/local/identity/session-protocol.md`.
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
   `session-protocol.md`. Domain playbooks belong in `registry/skills/org-<domain>/SKILL.md`
   (core) or `registry/local/skills/org-<domain>/SKILL.md` (private overlay).

2. **Keep `session-protocol.md` lean** — it lands in `SOUL.md` on every request. Include only:
   the **Session Protocol** block and your routing preference + primary 3-role chain.
   Point to the domain skill for all deeper detail. Routing tables, the project roster,
   and the org-domain table live in the deployed `AGENTS.md` tree, never here.

3. **Standard frontmatter**: `audience: [hermes]`.

4. **Never drop the Session Protocol** — copy it verbatim from a shipped template (or
   `registry/identity/session-protocol.md`). It carries the `{{project_root}}` and
   `{{skills_root}}` placeholders that tell the agent the concrete directories to
   navigate, how skills work (instruction files, not tools), and how named documents
   resolve through the project maps. A seed without it masks the core protocol —
   last-layer-wins — and breaks session alignment for that user.

5. **Reference the domain skill** — the last line of `session-protocol.md` should point to the
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

1. Create `registry/templates/org/<template-slug>/` with `session-protocol.md`.
2. If the template introduces a new domain, add `registry/skills/org-<domain>/SKILL.md` with
   the full playbook, `targets: [hermes]`, `category: productivity`.
3. Run `python build/compile.py compile` to validate frontmatter.
4. Add a template and domain section to this document following the pattern above.
5. Submit a Pull Request. Keep content generic; no personal or company data.
