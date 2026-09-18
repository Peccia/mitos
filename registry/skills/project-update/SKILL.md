---
name: project-update
description: "Explains how this agent's context is kept current and reads back the last update"
version: 3.0.0
author: Paul Peccia
license: MIT
platforms: [linux, macos, windows]
targets: [mitos-agent]
category: devops
mitos_agent:
  tags: [update, devops, registry, deploy]
---
# Project Update

You do not run updates from chat. This tree is kept current from Mitos in two ways: on the
`serve` schedule (`update.every`), or when the owner runs `mitos-agent update` on this host.

When asked to "update the project":

1. Tell the owner the command: `mitos-agent update`.
2. Tell them the latest outcome is shown by `mitos-agent updates --last 1`.

When the owner shares an outcome, explain it:

- **Blocked**: a protected file in the tree was edited, so the deploy was refused and all agent
  updates are frozen until it is resolved. Name the files. The owner resolves them with
  `mitos adopt` or `mitos harvest`, then commits and pushes the overlay. Never suggest `--force`.
- **Captured**: an edited file was saved to the inbox as a candidate. The owner reviews it with
  `mitos review`, then commits the overlay.
- **Orphans**: files Mitos no longer plans. They are kept on disk; pruning is the owner's call.
- **Skipped**: a scheduled run found uncommitted edits in the owner's Mitos checkout and did
  nothing. The next run resumes once they are committed or stashed.
- **Error**: repeat the record's error line. A changed `build/requirements.txt` means the owner
  reinstalls the Mitos venv, then runs `mitos-agent update` again.
