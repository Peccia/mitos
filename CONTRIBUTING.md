# Contributing to Mitos

Thank you for your interest in contributing! Mitos is a personal-agent registry
and compiler — contributions that keep the core neutral and the overlay contract
clean are especially welcome.

## Getting Started

Setup mirrors the [README Quick start](README.md#quick-start) with two contributor differences:
you clone your **fork** (not the official repo) and add `upstream`, and you clone into a parent
`Mitos/` folder so Mitos can manage its own repo as a self-hosted project. The virtualenv and
interpreter paths are identical.

Mitos runs from a project virtualenv — every command uses that interpreter directly (never a bare
`python`). The paths below are the venv interpreter; `python3` on Linux/macOS, `python` on Windows.

1. **Create a parent `Mitos/` directory, clone your fork into it as `mitos`, and add `upstream`**
   (replace `YOUR-USERNAME`). The parent folder is what lets Mitos track its own repo as a project,
   like any other project it manages:

   ```bash
   # Linux / macOS
   mkdir Mitos && cd Mitos
   git clone https://github.com/YOUR-USERNAME/mitos.git mitos && cd mitos
   git remote add upstream https://github.com/Peccia/mitos.git

   # Windows (PowerShell)
   mkdir Mitos; cd Mitos
   git clone https://github.com/YOUR-USERNAME/mitos.git mitos; cd mitos
   git remote add upstream https://github.com/Peccia/mitos.git
   ```

   The `upstream` remote lets you pull the latest official changes — and the compiler self-check
   (run by `mitos.py init`/`sync`) compares your `build/` against `upstream/main`, so you are told
   when the compiler falls behind. Keep your fork's `main` in step with `upstream/main`.

2. Create the virtualenv and install dependencies:

   ```bash
   # Linux / macOS
   python3 -m venv build/.venv
   build/.venv/bin/python -m pip install -r build/requirements.txt

   # Windows (PowerShell)
   python -m venv build/.venv
   build\.venv\Scripts\python.exe -m pip install -r build/requirements.txt
   ```

3. Run the test suite with the venv interpreter (the stdlib runner — no pytest needed):

   ```bash
   # Linux / macOS
   build/.venv/bin/python build/tests/test_compiler.py

   # Windows (PowerShell)
   build\.venv\Scripts\python.exe build/tests/test_compiler.py
   ```

   Prefer pytest? Install the dev extra (`build/.venv/bin/python -m pip install pytest`) and run
   `pytest build/tests/` — both run the same suite.

4. Initialize your personal overlay: `build/.venv/bin/python build/mitos.py init`.

5. **Set up Mitos as a self-managed project on your machine.** Add a machine profile under
   `registry/local/machines/` whose `projects_root` is the parent of your `Mitos/` folder, and
   point the `mitos` project's `local_path` for that machine at your `Mitos/mitos` checkout.
   Deploying that machine then materializes Mitos's own `AGENTS.md` / `CLAUDE.md` and keeps the
   repo in your project tree like any other — see
   [Make it yours](README.md#make-it-yours) for the machine-profile walkthrough.

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
2. Ensure `build/.venv/bin/python build/tests/test_compiler.py` passes (179/179).
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
