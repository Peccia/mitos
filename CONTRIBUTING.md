# Contributing to Mitos

Thank you for your interest in contributing! Mitos is a personal-agent registry
and compiler — contributions that keep the core neutral and the overlay contract
clean are especially welcome.

## Getting Started

Mitos runs from a project virtualenv — every command uses that interpreter directly (never a bare
`python`). The paths below are the venv interpreter; `python3` on Linux/macOS, `python` on Windows.

1. Fork the repo and clone it locally.
2. Create the virtualenv and install dependencies (the canonical install — same as the README
   [Quick start](README.md#quick-start)):

   ```bash
   # Linux / macOS
   python3 -m venv build/.venv
   build/.venv/bin/python -m pip install -r build/requirements.txt

   # Windows (PowerShell)
   python -m venv build/.venv
   build/.venv/Scripts/python.exe -m pip install -r build/requirements.txt
   ```

3. Run the test suite with the venv interpreter:
   `build/.venv/bin/python build/tests/test_compiler.py`
   (Windows: `build/.venv/Scripts/python.exe build/tests/test_compiler.py`.)
4. Initialize your personal overlay: `build/.venv/bin/python build/mitos.py init`.

Working on a connector backend? Install its optional deps too — `requests` for the `mcp`
connector, the Google client libraries for `gws` (see `pyproject.toml` `[connectors]`).

## What to Contribute

- **Skills**: New skills under `registry/skills/<name>/SKILL.md` that are useful
  to a broad audience. Follow the existing frontmatter schema.
- **Bug fixes**: Compiler, loader, planner, or deploy bugs.
- **Documentation**: README improvements, setup guides, examples.
- **Target adapters**: New tools beyond Hermes/Claude/Gemini.

## What NOT to Contribute

- Personal identity, context, or project files — those belong in your
  `registry/local/` overlay (gitignored by design).
- Machine profiles with real hostnames or IP addresses.
- Connection secrets or credentials.

## Pull Request Process

Run both checks with the venv interpreter (`build/.venv/bin/python`, or
`build/.venv/Scripts/python.exe` on Windows):

1. Create a feature branch from `main`.
2. Ensure `build/.venv/bin/python build/tests/test_compiler.py` passes.
3. Run `build/.venv/bin/python build/compile.py compile` to validate the registry schema.
4. A new verb, target, or schema field lands **together with** its schema validation, its docs,
   and a test — or not at all (see the contribution rule in [`AGENTS.md`](AGENTS.md)).
5. Open a PR with a clear description of what changed and why.

## Code Style

- Python: follow the existing style (type hints, dataclasses, no frameworks).
- Markdown partials: YAML frontmatter + clean Markdown body.
- YAML: 2-space indent, no tabs.

## License

By contributing, you agree that your contributions will be licensed under the
MIT License.
