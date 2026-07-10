# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
