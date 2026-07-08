---
name: new-session
description: "Initializes the start of a new session or topic pivot — filters and commits session intelligence, resets context, aligns directory, and routes to the correct branch (Assistant or Project with domain skill)."
version: 3.0.1
author: Paul Peccia
license: MIT
platforms: [linux, macos, windows]
targets: [hermes]
category: productivity
hermes:
  tags: [new, session, project, memory, routing]
---

# New Session

Follow these steps at session inception or when a distinct topic pivot is declared,
before acting on the owner's request. This skill is a checklist to read and follow —
never a callable tool, never scheduled.

## Step 1: Capture Session Intelligence

Note any enduring fact from the exchange — an operational shift, a domain constraint, or
a personal working paradigm. Commit each to memory if a memory tool exists, otherwise
state it plainly in your acknowledgement. Skip transient chatter and anything already in
long-term memory.

## Step 2: Context Reset

Set the prior conversation aside — the clean slate IS the new session; nothing to call,
nothing to schedule. Never reply that you "cannot start a new session".

## Step 3: Directory Alignment

`cd {{project_root}}` and read the local file `AGENTS.md` (the `read_file` file tool, or
`cat` via `terminal` — never `gws`) — your operating root. Follow its `## Navigation`
section to route the request (one-shot vs project work); every node you enter shares the
same layout — `## Navigation`, `## Workflows`, `## Tools`, `## Skills`, and a connection
section per store — so read each by those names as you descend.

## Step 4: Acknowledge

One line: `new-session ✔ — routing: <Assistant | Projects/<name>>`, then handle the
owner's request.
