# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Feature: `repo_ssh_keys:` in a project manifest — a mapping of checkout basename to private key (bare filename or path), same shape and validation as `repo_branches:`/`repo_notes:`. Fixes auto-clone/pull against per-repo GitHub deploy keys: without it, `deploy` authenticated every repo with whatever identity was ambient on the box, which fails outright for any repo scoped to its own deploy key — the failure surfaced as git's generic SSH "Permission denied (publickey)" text, truncated by mitos's own error-tail logic down to a single trailing fragment ("...and the repository exists.") that read as a non-sequitur. A bare filename resolves to `~/.ssh/<name>` (`agentic.sshkey`, shared with the overlay-hub `sync.git.ssh_key`), so one manifest entry authenticates on every machine that carries a matching-named key — no per-machine config needed. `_git_clone` pins `core.sshCommand` on the clone itself and persists it on the checkout; `_git_pull` reconciles it (including clearing it if the entry is removed) before every fetch. A key file missing on the deploying machine now fails fast naming its resolved path, instead of after a real network round-trip.

### Changed
- A skill declaring `delivers:` now deploys **only where some effort in the registry declares that deliverable** — the fourth non-curatable gate in `planner._selected_skills`, and the exact inverse of the `deploy --dry-run` warning that reports a declared deliverable no skill can produce. Before this, the seven return-lane skills carried `targets: [claude-code, antigravity, claude-app, mitos-agent]` and therefore landed on every machine, including a laptop running one coding harness and nothing that reads a return record: seven procedures for a lane that setup had not opted into, paid for in the skill roster of every session. The gate reads the **registry**, not the machine, and that distinction is load-bearing — a coding-only box whose records a Mitos Agent elsewhere harvests still receives them (`{{returns_root}}`'s `.mitos-returns/` fallback exists for exactly that box), which a gate on `mitos-agent` being a target *here* would have deleted. Example graphs step aside once real projects exist, the same rule the graph roster applies, so a shipped sample cannot switch the lane on for a fleet that never asked for it. Deliberately **silent**: unlike curation and `requires_server:`, no declared deliverables is the DEFAULT state, so a warning would fire on every deploy of a correct configuration with no way to silence it but to declare work you do not do. A fresh clone now receives none of the seven; to turn the lane on, declare the deliverable on an effort and redeploy. **Run `deploy --machine <name> --prune`** to remove copies a machine already has.
- `requirements-receipt` (1.1.0): the skill now reads the export's **header fields** instead of scraping its title. A Mitos Agent export opens with a `---` block carrying `work`, `requirements` and `digest`, so the key the whole return lane joins on is a field rather than something lifted out of `# Requirements: <key>` — string interpretation at the one point the lane's parsing-not-interpretation claim is load-bearing. The harness is also told to copy `digest` into its record's `export_digest`, which is how an owner is told their requirements moved on after the document was handed over, and to **omit it rather than guess**: a wrong digest reports requirements as stale when they are not, and a warning that cries wolf is one nobody reads. The title fallback is documented and kept, because skills deploy per machine and a receipt written between the agent shipping and a machine being redeployed must still parse. **Redeploy each machine** for harnesses to pick this up.

### Fixed
- Console: the effort editor never opened. `+ Work` and an effort row's `Edit` set the editor state and re-rendered, but the card itself threw while being built and vanished with the throw, so both buttons appeared to do nothing. `bindEnterToApply` walked every field the card had registered and called `addEventListener` on it — and a checkbox GROUP (expected deliverables, requirements coverage) registers itself as a plain `{name: checkbox}` map, which has no such method. Present since expected deliverables introduced the first checkbox group. It now binds only real elements.

### Added
- Feature: Console — per-project default deliverables, editable through the existing `kind: project` valve. All three states are authorable: inherit (key absent), an explicit set, or an explicit *empty* set meaning "inherit nothing". The registry-wide value is shown read-only beside it — it lives in `registry/user.yaml` and is edited there, and a candidate lane for one rarely-changed key would be more machinery than the edit is worth.
- Feature: Console — the effort editor marks each deliverable with which skill produces it, or `(no skill)` when nothing declares `delivers:` for it. Registry-wide on purpose: `deploy --dry-run` already reports the exact per-machine gap, and a badge that changed meaning with the machine selector would be read as that check without being it.
- Feature: Six deliverable skills — `documentation`, `tests`, `changelog`, `deploy-book`, `runbook`, `migration-notes`. One per term, each declaring `delivers:`, deployed to every harness. Every declared deliverable in the registry now has a procedure that produces it, and `deploy --dry-run` reports zero undelivered warnings on every machine (it reported four per machine before these landed — which is exactly the state that warning exists to surface). Each carries a real procedure rather than a template: `documentation` fixes what the change made FALSE before writing anything new, because stale documentation is worse than missing documentation; `tests` requires that a test would fail with the change reverted, or it is coverage theatre; `changelog` writes for the reader rather than the author and says no entry beats a vague one; `deploy-book` gives every step a way to tell whether it worked and writes the rollback before it is needed; `runbook` is written for 3am, organised by symptom, and names the actions that look right and make things worse; `migration-notes` leads with whether the reader must act and by when.
- Feature: `{{returns_root}}` machine token — where a coding harness writes what it produced. On a machine hosting Mitos Agent this is its state directory's `returns/`, the exact folder `mitos-agent returns` reads; on a coding-only box it falls back to a machine-wide `.mitos-returns/` beside the checkouts. Deliberately NOT reusing `{{project_root}}`, which falls back to `projects_root` there and would have put records inside a path the harness's resolver never looks at while looking like it had worked — a silently wrong path is worse than an obviously separate one, and the fallback is read with `mitos-agent returns --from`.
- Feature: The `requirements-receipt` skill — the return lane's close-out, deployed to every harness (`claude-code`, `antigravity`, `claude-app`, `mitos-agent`). After an implementation it writes a structured record of what happened to each requirement, keyed by the ids the export minted, into `{{returns_root}}/<run>/requirements-receipt.md`. Not a summary: a summary is prose nobody can check, and this is a parseable answer to a document that named its requirements by id. It instructs the harness to separate `evidence:` (a pointer someone can follow) from `claim:` (an assertion), to use `contested` when it believes a requirement itself is wrong — the one way a harness can push back without being able to withdraw anything — and to write nothing rather than something close, because a malformed record is refused and a missing one is a visible "no return filed", while a half-parsing one is neither.
- Feature: `delivers:` skill frontmatter — binds a skill to the `KNOWN_DELIVERABLES` term it satisfies, so the forward contract an effort declares and the procedure that answers it are a checkable pair. One skill per deliverable, never one skill for all of them: the set is meant to grow, so adding a deliverable is an addition (a new file) rather than a modification to a file that keeps getting longer. An unknown value fails the compile — a typo here is worse than a missing skill, because the skill deploys, looks correct, and satisfies nothing. Editable from the console's skill metadata panel.
- Feature: `deploy --dry-run` warns when an effort declares a deliverable no skill on that machine knows how to produce. Without it an effort can declare `deploy-book`, every harness can read the compiled line asking for one, and no skill anywhere describes how to write one — a gap discovered months later by the deploy book's absence. Reported once per term with the efforts that want it, so adding one skill retires exactly one line. Warn-only: an effort may legitimately be ahead of its skills.
- Feature: Default deliverable sets — a new effort starts with the deliverables its project declares in `registry/projects/<slug>.yaml`, falling back to `default_deliverables` in `registry/user.yaml` (shipping as `[documentation, tests]`, the two every kind of work owes regardless of shape). An effort that declares its own set never consults either. `default_deliverables: []` inherits nothing and is deliberately distinct from omitting the key. Both levels validate against the same closed vocabulary a declared deliverable does, because a default is copied onto real efforts and a typo would otherwise mint invalid ones from a file nobody looks at twice. The console resolves the chain server-side and prefills the `+ Work` editor, so the client never reimplements it. `registry/user.yaml` now holds two groups — identity and defaults — and only identity keys become template tokens.
- Feature: Console warns when an effort declares requirements coverage but no `requirements-receipt` — the gathering half of the loop would otherwise close quietly, with work happening and nothing reporting which requirements it met. Declared coverage is the checkable proxy Mitos has for "this effort gathers requirements"; settled requirements live in the agent's dossier, across the boundary. A warning, never a block.
- Feature: Three deliverable terms for the return lane — `runbook`, `migration-notes`, and `requirements-receipt` join `KNOWN_DELIVERABLES`. Appended, never inserted: `_ordered` walks the vocabulary in order and filters, so a term added at the end leaves every existing effort's serialized bytes untouched, while inserting one mid-tuple would reorder every effort declaring a later term and produce a graph diff on projects nobody edited. The boundary between the three adjacent terms is written down at the vocabulary rather than left to be guessed: `deploy-book` is how to ship one change, `runbook` is how to operate the result afterward, `migration-notes` is what changed for existing data and consumers. `requirements-receipt` carries per-requirement outcomes keyed by the ids an export minted — a deliverable, not a "summary", because it has a defined shape a reader can check.
- Feature: Requirements coverage (the interview contract) on graph efforts — a repeated `peccia:requirementsCoverage` predicate on a `CreativeWork` node, authored via the console effort editor's checkbox group over a closed vocabulary (`performance`, `security`, `failure-recovery`, `data-retention`, `access-control`, `scale`). Where expected deliverables name what an implementation must produce, this names the dimensions a requirements-gathering session must not leave unasked. Validated at load and at propose time; compiles to an ungated `_Requirements coverage: …._` line under the effort's heading in every generated view, after the deliverables line.
- Feature: Expected deliverables (the forward contract) on graph efforts — a repeated `peccia:deliverable` predicate on a `CreativeWork` node, authored via the console effort editor's checkbox group over a closed vocabulary (`documentation`, `tests`, `changelog`, `deploy-book`). Validated at load and at propose time; compiles to an ungated `_Expected deliverables: …._` line under the effort's heading in every generated view, which the Mitos Agent planning harness reads to seed a plan's `## Expected Deliverables` checklist.

## [0.1.5] - 2026-08-23

### Major Architectural Shift — Introduction of Mitos Agent
- **Mitos Agent Planning Target (`mitos-agent`)**: Introduced `targets/mitos-agent.yaml` as the first-class target for the Mitos-native planning harness, retiring the legacy Hermes target. Deploys the dedicated planning operating tree under `assistant_root` (`~/MitosAgent/`) with structural node navigation, operating rules, and session protocol.
- **Agentic Repo Clone & Pull Lane**: Added auto-cloning and fast-forward pull lanes for multi-repo project checkouts in agentic operating trees (`~/MitosAgent/Projects/<name>/<basename>/`) and reference mounts, supporting branch tracking (`repo_branches`) without manual workspace management.
- **Coding Harness Decoupling**: Completely decoupled standalone coding harness targets (`claude-code`, `antigravity`) from assistant-level baggage. A clean coding workstation receives only relevant project context and skills, without inheriting unused assistant trees or workspace document stores.

### Added
- Feature: `requires_server:` skill frontmatter — a skill that is nothing but instructions for one MCP server's tools deploys only to machines declaring that server in `document_store:`. Applied to the shipped `gws` and `graph-bootstrap` skills.
- Feature: Scoped console Prompt Library and Skills & Orgs views to active machine configurations.

### Fixed
- Fix: A brand-new coding-harness-only machine (`mitos init` use cases 1 and 2) no longer receives assistant/workspace content it never asked for. `gws` SKILL.md was deployed to every claude-code/antigravity/claude-app surface, and the gws MCP server was spliced into Antigravity/Claude Desktop configs, regardless of whether the user had Google Workspace at all — all of it is now gated on the machine's `document_store:`, which no shipped `machines/example-*.yaml` use-case template declares.
- Fix: `registry/identity/operating-rules.md` claimed `audience: [mitos-agent, claude-code, antigravity, agents-md]` while consisting entirely of agentic-tree rules — every coding-harness `CLAUDE.md` was told to run the assistant-only `new-session` skill and to navigate an `AGENTS.md` tree that does not exist there. Retagged to `[mitos-agent, agents-md]`.
- Fix: Core identity prose named the maintainer literally ("Paul's documents…", "a project of Paul's") and hardcoded Google Workspace; it now uses the `{{users_given_name}}` placeholder and describes the store generically, and no longer points at a `plan` skill that does not ship in core.
- Fix: `planner.skill_deploy_warnings` no longer misattributes a connection-gated skill to machine curation — it names the missing connection and `document_store:` as the fix.
- Fix: Neutralize stdin in the stdlib test runner to avoid hanging on non-interactive test suites.

## [0.1.4] - 2026-07-26

### Added
- Feature: Generate repo roster inside `## Navigation` section of project nodes with manifest `repo_notes:` field.
- Feature: End-to-end editable project properties (`propose_project_edit` + `kind:project` inbox candidates and console Project panel).
- Feature: Multi-region carve and rejoin support in `split_live_sections` for ordered partial sections.

### Changed
- UI: Unified design system tokens, CSS container queries, WCAG 2.5.8 control sizing, ARIA roles, and collapsible project identity header in operator console.

### Fixed
- Fix: Gate org content on `hermes` target rather than `agents-md` to avoid leaking org lines to non-Hermes setups.
- Fix: Stdlib test runner now handles pytest fixture parameters (`monkeypatch`, `tmp_path`) via a test runner shim (`conftest.py`).
- Fix: Operator console layout issues, dock z-index positioning, and invisible stage badges.

## [0.1.3] - 2026-07-18

### Added
- Feature: Added New Prompt creation flow to the operator console.
- Feature: Operators can now rename watched folders and queries.
- Feature: Added multi-scope staging for document enumeration.
- Feature: Added user-defined Goal property to work efforts.

### Changed
- Refactored: Clone project repositories fully rather than using shallow clones.
- UI: Miscellaneous console UX fixes.

## [0.1.2] - 2026-07-11

### Added
- Feature: Multi-store `document_store` support — a project or machine can draw its knowledge graph from more than one document store at once, with per-store document tagging and one generated section per store in `AGENTS.md`/`AGENTS_DETAILS.md`.
- Feature: Diff-aware graph candidate review — the Inbox shows an added/changed/removed summary for knowledge-graph candidates instead of only a raw line diff, and de-emphasizes (never hides) Accept for true no-ops.
- UI: Hover-revealed row-level Copy button on every Prompt Library row, and Ctrl/Cmd+Enter in the command palette to copy without closing it.
- UI: Compact E/M draft-state badges (replacing the old "edited"/"base moved" text tags), shared between the Prompt Library and Skills & Orgs tabs, plus a fullscreen toggle on the contextual editor.

### Changed
- Refactored: Retired the Claude Code subagents lane (`registry/agents/`, the `agents:` manifest field, `Agent`/`render_agent`) — skills already cover the reusable-behavior story, and Claude Code ships a built-in code-reviewer agent.
- UI: Console visual-craft cleanup — softened the light-mode panel color, fixed a z-index collision between the deploy-confirm modal and the command palette, and split the expanded skill card into a two-column layout.
- UI: Unified filter-chip padding/font-size across the Prompt Library and Skills & Orgs tabs so the same control looks identical in both places.

### Fixed
- Fix: A CSS specificity bug that squashed the Favorites "Manage"/"Unpin selected" buttons to crushed padding.
- Fix: The New Skill form being clipped by an inherited max-height, and guarded the Project scope option against selection when a skill has no bound projects.

### Breaking Changes
- Any project manifest with an `agents:` field now fails validation at compile time — remove the field; skills cover the same reusable-behavior story.

## [0.1.1] - 2026-07-09

### Added
- Feature: Compile and deploy directly from the operator console.
- Feature: Machine role exclusivity and `agentic_tree` project mounts.
- Feature: Antigravity IDE support and project-scoped skill curation/scoping.
- Feature: Add Discovery/Recovery dismissal to the Knowledge Graph tab in the operator console.

### Changed
- Refactored: Renamed `gemini` target to `antigravity`.
- Refactored: Moved skill curation to machine profiles.
- Refactored: Brought Antigravity skills into the Agent Skills standard and retired the prompt lane.
- Refactored: Deduplicated session/plan rules, fixed tool names, and restored `project_root` token.
- Refactored: Lead operating root with the boot action in context rendering.
- UI: Hidden example machines from the operator console selector.

### Fixed
- Fix: Eliminated inbox candidate folder race causing "Failed to fetch" errors.

## [0.1.0] - 2026-07-09

### Added
- Core Compiler, Local Connectors, and Multi-Repo Personas.
