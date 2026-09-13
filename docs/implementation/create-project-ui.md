# Plan: Create New Project in Knowledge Graph UI via Backend CLI

## 1. Scope & YAGNI Boundaries
- **In Scope (Immediate Need)**:
  - Add backend endpoint (`POST /api/project/new`) in `build/agentic/review.py` that delegates to `build/mitos.py project add <slug> [--name <name>] [--document-store <store>] [--root <root>]` via `subprocess.run`.
  - Add `--root` support to `mitos project add` CLI in `build/mitos.py` for sandbox/temp registry execution.
  - Expose `known_stores` in `state(reg)` in `build/agentic/review.py` so the UI knows available MCP servers from `connections/servers.yaml`.
  - Add a "+ New" button to the Knowledge Graph sidebar and empty state in `build/review_ui/app.js`.
  - Render an inline "New project" form in the Knowledge Graph workspace collecting slug, display name, and document store dropdown.
  - Support form submission, client validation, keyboard shortcuts (Escape, Enter), and automatic selection of the newly created project.
  - Comprehensive unit/integration tests in `build/tests/test_review.py`.
- **Excluded (Speculative / Defer)**:
  - Speculative project cloning / deletion / rename endpoints.
  - Speculative stage transitions from the creation modal (defaults to standard `ideation` stage created by `mitos project add`).
  - No new external libraries or frontend build steps.

## 2. Blast Radius & Resolution Ladder
- **Affected Files**:
  - `build/mitos.py`: Add `--root` parameter to `project` subparser and use in `_cmd_project`.
  - `build/agentic/review.py`: Add `create_project()` CLI wrapper, expose `known_stores` in `state()`, add `/api/project/new` dispatch.
  - `build/review_ui/app.js`: Add sidebar "+ New" button, empty-state "+ New project" button, `newProjectOpen` state, and `buildNewProjectWorkspace()`.
  - `build/review_ui/style.css`: Minimal styles for `.graph-sidebar-head` and `.new-project-panel`.
  - `build/tests/test_review.py`: Unit and endpoint tests for project creation and known stores exposure.
- **Ladder Level**:
  - Level 1 (Existing Codebase): Reuses `_cmd_project` in `build/mitos.py`, subprocess runner pattern from `refresh_staging`/`peek_identity_effort` in `review.py`, and existing UI form patterns from `newSkillForm`/`projectEditorCard`.

## 3. Implementation Steps
- [x] Step 1: `build/mitos.py` - Add `--root` option to `project` subparser and resolve `root = (args.root.resolve() if getattr(args, "root", None) else REPO_ROOT)` in `_cmd_project`.
- [x] Step 2: `build/agentic/review.py` - Implement `create_project(reg, slug, name, document_store, timeout)` running `mitos.py project add` via `subprocess.run`.
- [x] Step 3: `build/agentic/review.py` - Expose `"known_stores": sorted((reg.servers.get("servers") or {}).keys())` in `state(reg)`.
- [x] Step 4: `build/agentic/review.py` - Add `/api/project/new` handler in `Handler._dispatch_post` which calls `create_project`, reloads `holder["reg"]`, and returns the updated state.
- [x] Step 5: `build/review_ui/app.js` - Add `newProjectOpen` state, sidebar "+ New" button, empty state button, and `buildNewProjectWorkspace()`.
- [x] Step 6: `build/review_ui/style.css` - Add styling for `.graph-sidebar-head` and `.new-project-panel`.
- [x] Step 7: `build/tests/test_review.py` - Add automated tests for CLI subprocess invocation, error surfacing, successful creation, and `/api/project/new` endpoint.

## 4. Verification & Validation
- [x] Run compiler test suite: `python build/tests/test_compiler.py` (544/544 tests passed)
- [x] Run targeted tests: `python build/tests/test_compiler.py build/tests/test_review.py` (all review tests passed)
- [x] Verify schema and compilation: `python build/compile.py compile` (188 files compiled with exit code 0)

## 5. Review & Lessons
- **Review Summary**: Successfully implemented the new project creation functionality in the Operator Console Knowledge Graph view. Manifest scaffolding delegates strictly to the Stage 1 CLI command (`mitos.py project add`), preserving Invariant #11. The frontend provides a responsive form in the Knowledge Graph workspace accessible from both the sidebar header and the empty-state screen, with instant navigation to the newly scaffolded project.
- **Rule/Lesson Added**: When delegating from review.py to CLI subprocesses, threading `--root` enables deterministic sandbox isolation across temporary test fixtures and production deploys.
