---
audience: [hermes, agents-md]
---
# Operating Root

This is your operating root — the first context you read each session (the `new-session`
skill brings you here). It bridges who the owner is with how their work is organized, and
routes you to the right branch *before* you act. Keep it lean: routing only, no domain detail.

## Routing

Classify the request, then read the matching branch:

- **One-shot personal task** — email, calendar, task, note, quick lookup. Read
  `Assistant/AGENTS.md` and follow the workflow for the request's category. This branch is
  domain-agnostic; no org structure is loaded.
- **Substantive project work** — planning, multi-step execution, or decisions tied to a
  project. Read `Projects/AGENTS.md` for the project roster and org structure, then open the
  specific project at `Projects/<project>/AGENTS.md` and load its domain skill.

When it is unclear which branch a request belongs to, ask the owner rather than guessing.
