---
audience: [hermes, agents-md]
---
# Projects

The owner's substantive work, organized as projects. A *project* is always a folder here
under `Projects/` — never a folder in the document store. Each project's folder contains
an `AGENTS.md` (context + document titles) and an `AGENTS_DETAILS.md` (document IDs —
read it whenever you need to operate on a document).

## Navigation

1. Identify the project — ask the owner, or infer from context if unambiguous.
2. Open `Projects/<project>/AGENTS.md` and read its context; resolve any named document
   to its ID via `AGENTS_DETAILS.md` and operate on the ID — search the document store
   by name only when the maps don't list it, and never create a document whose title the
   map lists.
3. Pick the org skill **per task, never per project** — the same project can hold
   software, design, and marketing work side by side:
   - An effort (a `###` document group under the connection section) tagged "runs under
     the `<domain>` org" names the skill: `org-<domain>`.
   - No matching or tagged effort → classify the request itself:
     building/refactoring/debugging → `org-software`; visual, UX, or brand-asset work →
     `org-design`; positioning, launch, or content work → `org-marketing`.
4. Load that one skill — read `{{skills_root}}/productivity/org-<domain>/SKILL.md` — and
   apply its delegation chain. Re-run this routing whenever the work shifts, not once
   per project.

The project roster and available domain organizations are listed below.
