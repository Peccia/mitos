---
name: graph-bootstrap
description: "Enumerate a project's Google Drive folder via the gws MCP and propose its documents as a kind:graph candidate in registry/local/inbox/ for the owner to review"
version: 1.0.0
author: Paul Peccia
license: MIT
platforms: [linux, macos, windows]
targets: [hermes]
category: devops
hermes:
  tags: [graph, drive, bootstrap, registry, gws]
---
# Instructions

When asked to "bootstrap the graph for <project>" (or "map <project>'s documents"),
discover that project's Google Workspace documents and propose them as a single
**`kind: graph`** inbox candidate. You **propose**; only the owner accepts (in the operator
console on their main PC). Never write into `registry/` — write only into `registry/local/inbox/`.

You reach Drive through the **`gws` MCP server** (already wired). The compiler never
touches Drive; this enumeration is your job.

1. **Resolve the project and its Drive folder.** Read
   `~/mitos/registry/projects/<slug>.yaml`; use its `drive.root_folder` as
   the search scope. If it is unset or a `TODO:` placeholder, ask the owner for the folder name
   or ID before continuing — **never enumerate the whole Drive** (privacy).
2. **Enumerate.** Call `search_drive_files` scoped to that folder. Collect each document's
   `id`, `name` (title), and `modifiedTime` (use the `YYYY-MM-DD` date only).
3. **Write a one-line description per document** — a short, human-meaningful summary of
   what the doc is for. Infer it from the title and, only if needed, a quick
   `get_drive_file_content` skim. Keep it terse and factual; **never paste document body
   text** and never use filler like "bootstrapped from search". If you cannot summarize a
   doc confidently, leave its description empty for the owner to fill.
4. **Build the candidate fragment** as canonical schema.org JSON-LD — the Project node
   plus one `DigitalDocument` per file (the document `@id` MUST equal
   `http://peccia.net/document/<id>`):
   ```json
   { "@context": { "@vocab": "https://schema.org/" }, "@graph": [
     { "@id": "http://peccia.net/project/<slug>", "@type": "Project", "name": "<Project Name>" },
     { "@id": "http://peccia.net/document/<driveId>", "@type": "DigitalDocument",
       "identifier": "<driveId>", "name": "<title>", "description": "<one-line summary>",
       "dateModified": "<YYYY-MM-DD>",
       "isPartOf": { "@id": "http://peccia.net/project/<slug>" } } ] }
   ```
5. **Drop the candidate into `registry/local/inbox/`** at `~/mitos/registry/local/inbox/<timestamp>--<this-box>--graph-<slug>/`:
   - `meta.yaml`:
     ```yaml
     registry_path: graph/<slug>.jsonld
     kind: graph
     project: <slug>
     source: {machine: <this-box>, tool: hermes}
     captured_at: <ISO-8601 UTC>
     note: <N> document mapping(s) discovered in Drive folder <folder>
     ```
   - `graph.jsonld`: the fragment from step 4.
6. **Surface for review.** The candidate now sits in `registry/local/inbox/`. Push it to the
   review machine via the **private** overlay sync (`mitos sync --machine <this-box> push` then
   `mitos sync --machine <review-pc> pull`) — the queue lives inside `registry/local/` and
   travels with the overlay; it never touches the public-track repo.
7. **Report** to the owner over Telegram: the project, how many documents were proposed, the
   folder searched, and that the candidate is waiting in their operator console
   (`compile.py review`) for accept/reject. Accept upserts it into
   `registry/graph/<slug>.jsonld` and the next deploy regenerates the project's index.

Never accept your own proposal, and never edit `registry/graph/` directly — the human gate
is the point.
