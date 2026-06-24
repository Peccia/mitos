---
audience: [hermes]
---
## Session Protocol

At the beginning of each session and whenever the topic changes, follow these steps to realign before taking action: consult the `AGENTS.md` files located within the project directory for contextual information.

### Step 1: Extract & Filter Session Intelligence

Note any enduring fact from the exchange (preference, constraint, decision). Verify it against existing long-term memory; if the fact is redundant or already captured, discard it. Do not log transient data, debugging output, runtime variables, or conversational filler; capture only enduring context.

### Step 2: Commit to System Memory

When a qualifying fact passes the filter, invoke the profile/memory tools to commit the structured fact to long-term storage. When no memory tool is wired, do nothing.

### Step 3: Context Isolation & Reset

Flush the short-term conversational history window: the clean slate IS the new session; nothing to call, nothing to schedule.

### Step 4: Directory Alignment & Agent Boot

1. Execute a hard directory change to the authoritative root: `cd {{project_root}}`.
2. Read `AGENTS.md` (the `read` file tool, or `cat` via `terminal`) to parse navigation parameters, active skill mappings, and tool configurations.
3. Re-read the `AGENTS.md` in each folder you enter as you navigate.
   - Note: Routing, the project roster, and the org structure live in that tree, not here. Never answer from memory of past sessions what a file can tell you now — re-read it.
   - Note: A *project* is a folder under `{{project_root}}/Projects/` — never a document-store folder. Resolve a named document there and operate on its ID from the project's `AGENTS_DETAILS.md`.
   - Note: If `read` or `terminal` is unavailable, report the exact missing tool name as a configuration problem.
