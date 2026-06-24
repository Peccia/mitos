---
name: new-session
description: "Initializes the start of a new session with the owner"
version: 1.2.0
author: Paul Peccia
license: MIT
platforms: [linux, macos, windows]
targets: [hermes]
category: productivity
hermes:
  tags: [new, session, project, memory]
---

# Instructions

Execute this skill immediately upon session inception or when a distinct topic pivot is declared. Use the `AGENTS.md` files within the project directory structure to gain operational context, leveraging the subfolder hierarchy as a self-describing capability map.

## Execution Sequence

### Step 1: Extract & Filter Session Intelligence
Review the immediate conversational initialization text, incoming payload, and environmental triggers *before* any state modification occurs. Isolate critical facts and evaluate them against these categories:

* *Operational Shifts:* Changes in project scopes, architecture decisions, deployment targets, or tool preferences.
* *Domain Constraints:* Technical boundaries, infrastructure limits, or explicit "what *not* to do" directives.
* *Personal Paradigms:* Directives regarding working style, discourse rules, and collaborative boundaries.

#### Filtering Rules:
* *Deduplication:* Verify against existing long-term memory states. If the fact is redundant or already captured, discard it.
* *Permanence Filter:* Do not log transient data, minor debugging logs, runtime variables, or conversational filler. Capture only enduring context.

### Step 2: Commit to System Memory
When a qualifying fact passes the filtering rules, immediately invoke the system profile/memory update tools to commit the structured fact to long-term storage. Ensure this write operation succeeds before proceeding.

### Step 3: Context Isolation & Reset (The Purge)
Now that vital information is safely persisted to long-term memory, flush the short-term conversational history window. Wipe out transient token chains, debugging cruft, and irrelevant past chat logs to establish a completely clean working slate for the upcoming task.

### Step 4: Directory Alignment & Agent Boot
1. Execute a hard directory change to the authoritative directory.
2. Read `AGENTS.md` to parse navigation parameters, active skill mappings, and tool configurations.
3. Await the owner's initial session command with a pristine context window and aligned directory state.
