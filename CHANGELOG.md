# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Console: the effort editor never opened. `+ Work` and an effort row's `Edit` set the editor state and re-rendered, but the card itself threw while being built and vanished with the throw, so both buttons appeared to do nothing. `bindEnterToApply` walked every field the card had registered and called `addEventListener` on it — and a checkbox GROUP (expected deliverables, requirements coverage) registers itself as a plain `{name: checkbox}` map, which has no such method. Present since expected deliverables introduced the first checkbox group. It now binds only real elements.

### Added
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
