---
audience: [hermes, agents-md]
---
# Operating Root

This is your operating root — the first context you read each session (the `new-session`
skill brings you here). It bridges who the owner is with how their work is organized, and
routes you to the right branch *before* you act. Keep it lean: routing only, no domain detail.

## Navigation

Route by one question — does the request involve a project or a project's documents?

- **Yes → `Projects/AGENTS.md`** — even for a quick email or note. It holds the roster;
  the named project's own `AGENTS.md` resolves its documents. For a one-shot task inside
  a project (an email, a note), do the task with the `Assistant/AGENTS.md` workflow after
  resolving names there.
- **No → `Assistant/AGENTS.md`** — personal one-shots: email, calendar, task, note,
  quick lookup. Domain-agnostic; no org structure is loaded.

When neither fits, ask the owner rather than guessing.

Every node below shares one header layout — read a node by its section names, never by
guesswork:

- `## Navigation` — the local tree from here: which child `AGENTS.md` to open next, the
  routing decision, cloned repo folders. Act on it with the file/`terminal` tools.
- `## Workflows` — step-by-step procedures the node performs itself (e.g. the Assistant's
  email/calendar/task categories).
- `## Tools` — callable capabilities (MCP servers, browser, terminal) and their rules of
  use. A tool is invoked; a skill is not.
- `## Skills` — instruction files in scope at this node; read `SKILL.md` and follow it.
- A connection section, headed by the store's name and key (e.g. **Google Workspace suite
  (`gws`)**) — folder paths and the document map inside that store, reached with that
  connection's tools. Effort groups are `###` beneath it, each naming the org skill that
  governs its work.

Routing, the project roster, and the org structure live in this tree — never answer from
memory of past sessions what a file can tell you now; re-read it.

## Tools

- **Terminal & file operations** (the `read_file` / `terminal` tools) — use exclusively to
  navigate this tree: `cd` between folders and read `AGENTS.md` / `AGENTS_DETAILS.md`
  files. The owner's documents are never on this filesystem; they live in the connected
  document store.
- **Clarify over guess** — when this map or a document map is ambiguous, stop and ask
  the owner rather than searching blindly.
