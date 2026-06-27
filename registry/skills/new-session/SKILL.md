---
name: new-session
description: "Initializes the start of a new session or topic pivot — filters and commits session intelligence, resets context, aligns directory, and routes to the correct branch (Assistant or Project with domain skill)."
version: 2.0.0
author: Paul Peccia
license: MIT
platforms: [linux, macos, windows]
targets: [hermes]
category: productivity
hermes:
  tags: [new, session, project, memory, routing]
---

# Instructions

Execute this skill immediately upon session inception or when a distinct topic pivot is declared.
Use the `AGENTS.md` files within the project directory structure as a self-describing capability
map. Complete all steps in order before acknowledging the owner's first command.

## Step 1: Extract & Filter Session Intelligence

Review the immediate conversational initialization text, incoming payload, and environmental
triggers *before* any state modification occurs. Isolate critical facts and evaluate them
against these categories:

- *Operational Shifts:* Changes in project scope, architecture decisions, deployment targets,
  or tool preferences.
- *Domain Constraints:* Technical boundaries, infrastructure limits, or explicit "what not
  to do" directives.
- *Personal Paradigms:* Directives about working style, discourse rules, and collaborative
  boundaries.

**Filtering rules:**
- *Deduplication:* Verify against existing long-term memory. Discard if already captured.
- *Permanence filter:* Do not log transient data, debugging logs, or conversational filler.
  Capture only enduring context.

## Step 2: Commit to System Memory

When a qualifying fact passes the filtering rules, invoke the system memory update tools to
commit the structured fact to long-term storage. Ensure the write succeeds before proceeding.

## Step 3: Context Reset

Flush the short-term conversational history. Clear transient token chains, debugging cruft,
and irrelevant past chat to establish a clean working slate for the upcoming task.

## Step 4: Directory Alignment & Route

1. Change to `assistant_root`.
2. Read `AGENTS.md` — your operating root: it bridges the owner's context and routes you to
   the Assistant branch or the Projects branch.
3. Determine the request type and route accordingly:

### One-shot requests (email, calendar, task, note, quick lookup)
- Navigate to `Assistant/AGENTS.md`.
- Follow the category-specific workflow defined there.

### Project work (planning, multi-step execution, substantive decisions)
- Read `Projects/AGENTS.md` for the project roster and org structure.
- Ask the owner which project (or infer from context if unambiguous).
- Navigate to `Projects/<project>/AGENTS.md`.
- Find the `**Domain:**` line in the project's AGENTS.md header.
- Load the matching domain skill:
  - `**Domain:** software` → run `org-software`
  - `**Domain:** design` → run `org-design`
  - `**Domain:** marketing` → run `org-marketing`
- If no Domain line is present, proceed with the core delegation chain (CEO/VP/Assistant) and
  flag to the owner that the project's `org:` field is unset.

4. Await the owner's initial command with aligned context and the correct domain skill loaded.
