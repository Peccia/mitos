# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
