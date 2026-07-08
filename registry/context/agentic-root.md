---
audience: [hermes, agents-md]
---
# Operating Root

You reached this file by `cd {{project_root}}` and reading `AGENTS.md` — the first thing
you do each session. It routes you to the right branch *before* you act. Keep it lean:
routing only, no domain detail.

## Navigation

Route by one question — does the request involve a project or a project's documents?

- **Yes → open `Projects/AGENTS.md`** (read it with `read_file`) — even for a quick email
  or note. It holds the roster; the named project's own `AGENTS.md` resolves its documents.
  For a one-shot task inside a project (an email, a note), do the task with the
  `Assistant/AGENTS.md` workflow after resolving names there.
- **No → open `Assistant/AGENTS.md`** — personal one-shots: email, calendar, task, note,
  quick lookup. Domain-agnostic; no org structure is loaded.

When neither fits, ask the owner rather than guessing. Routing, the project roster, and the
org structure live in this tree — never answer from memory what a file can tell you now;
`cd` into each folder and re-read its `AGENTS.md` with `read_file` as you go.

Every node shares the same section layout, so read it by section name, not guesswork:
`Navigation` (which child to open next + cloned repos), `Workflows` (procedures the node
runs itself), `Tools` (callable capabilities), `Skills` (instruction files — read the
`SKILL.md`), and a connection section headed by the store's name and key (e.g. **Google
Workspace suite (`gws`)**) holding that store's document map.

## Tools

- **Terminal & file operations** (the `read_file` / `terminal` tools) — use exclusively to
  navigate this tree: `cd` between folders and read `AGENTS.md` / `AGENTS_DETAILS.md`
  files. The owner's documents are never on this filesystem; they live in the connected
  document store.
- **Clarify over guess** — when this map or a document map is ambiguous, stop and ask
  the owner rather than searching blindly.
