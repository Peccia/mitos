---
name: project-update
description: "Pulls the latest Mitos registry and recompiles + deploys this machine's tool configs"
version: 2.3.0
author: Paul Peccia
license: MIT
platforms: [linux, macos, windows]
targets: [hermes]
category: devops
hermes:
  tags: [update, devops, registry, compile, deploy]
---
# Project Update

When asked to "update the project" or "project update", refresh **this machine** from its Mitos
checkout, redeploy its generated tool configs, and surface any captured drift for review. Run
every compiler command with the project's venv interpreter (`build/.venv/bin/python` on
Linux/macOS, `build/.venv/Scripts/python.exe` on Windows) — **never bare `python`**. End by
reporting a brief summary of the outcome.

1. Go to the Mitos checkout and pull the public core: `git pull`. If it reports a conflict,
   stop and report — do **not** force. (Your private overlay in `registry/local/` syncs on its
   own channel; if it has a separate remote, pull that too.)
2. `build/.venv/bin/python build/compile.py compile`. If it errors (a registry/schema problem),
   stop and report — never deploy a broken registry.
3. Preview: `build/.venv/bin/python build/compile.py deploy --machine <this-machine> --dry-run`
   and read the action list.
4. Apply: `build/.venv/bin/python build/compile.py deploy --machine <this-machine>`. Expect one
   of two outcomes:
   - **It deploys** (exit 0). Any `harvest`-policy file a tool edited in place (e.g. a curator
     skill rewrite) is snapshotted to `inbox/` and then reinstated from the registry.
   - **It refuses** (exit 1: `refusing to deploy: N protected file(s) drifted`). A protected
     file (a `SOUL.md`/`AGENTS.md`, MCP wiring) differs from the registry. Stop here and report
     which files; do **not** pass `--force`.
5. **Surface captures for review.** If step 4 reported `captured N inbox candidate(s)`, push
   them to the review machine via the overlay sync (`mitos sync --machine <this-machine> push`
   then `mitos sync --machine <review-pc> pull`) — captures land in `registry/local/inbox/`
   and travel with the overlay. Review and accept/reject in the operator console
   (`build/compile.py review`).

Never run `deploy --force`, or push to a public remote, without explicit approval.
