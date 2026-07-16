# Mitos Operator Console Guide

The Mitos **Operator Console** is a local web application that serves as the human steering wheel for your agent organization. 

Run the console to:
1. Review and accept self-improvement proposals or drift from your tools (**Inbox**).
2. Curate and map workspace files into your projects' knowledge graphs (**Knowledge Graph**).
3. Browse, create, and edit skills — including supporting files and org-role extensions — and
   visualize your simulated org structure (**Skills & Orgs**).
4. Search, compose, and copy-paste registry prompts for one-shot chat sessions (**Prompt Library**).
5. Compile the registry and deploy to a machine directly, with a plan preview before you
   confirm and a live log of what ran (**Status bar**, above every tab).

---

## 🚀 Launching the console

The console runs locally on your loopback interface (`127.0.0.1`) and does not listen on the public network. Launch it from the root of your Mitos repository using the virtual environment's Python interpreter:

```bash
# Linux / macOS
build/.venv/bin/python build/compile.py review

# Windows (PowerShell)
build/.venv/Scripts/python.exe build/compile.py review
```

### Options:
- `--port <number>`: Change the local port (default is `8765`). Useful if another application is binding to the default port.
- `--no-open`: Start the server without automatically launching your default web browser.

---

## ⚙️ The Status Bar: Compile & Deploy

A slim bar sits above every tab: a **Compile** badge (green "Compiled" when `dist/` matches
the current registry, orange "Compile needed" otherwise) and a machine selector for the
**Deploy** button. Both actions also live as icon buttons in the sidebar footer, next to
Reload.

- **Compile** (⚙ icon) runs the registry render into `dist/` and opens the log drawer with
  the result — the same work `compile.py compile` does from the CLI.
- **Deploy** (↓ icon) first shows a **plan preview**: every output's classification
  (`create`/`unchanged`/`drift`/`conflict`/…), orphans, skill warnings, and repo clones for
  the selected machine — exactly what `deploy --dry-run` would print. Protected drift is
  flagged but never silently bypassed: the console never sends `--force`, so a blocked file
  still blocks the deploy (resolve it with `adopt`/`harvest` first). Click **Confirm &
  Deploy** to run it for real; a log drawer tracks progress and the final result.
- `--force`, `--prune`, and scoped `--lane`/`--target` deploys stay CLI-only — those bypass
  safety checks or narrow the deploy in ways that deserve a typed, deliberate command rather
  than a button.
- Only one compile or deploy runs at a time; starting a second while one is in flight is
  refused, not queued.

---

## 📥 The Inbox Tab: Drift & Candidate Review

When a self-improving tool (like Hermes) refines its own copy of a skill, or when you edit a deployed file, the changes are captured in your overlay inbox (`registry/local/inbox/`) as **candidates**.

### 🔍 Diffs & Review
- The Inbox lists all pending candidates with their capture timestamps, target tools, and logical paths.
- Selecting a candidate shows a live **Diff View** comparing the proposed changes with the version currently in your registry.
- A **Routing System** determines if the change can be applied automatically:
  - **Acceptable**: Plain Markdown prose edits (e.g. edits to a skill body or identity partial) can be accepted directly. Accepting updates your registry overlay (`registry/local/`) and marks the candidate as resolved.
  - **Unacceptable**: Generated configurations (like `mcp_config.json` or `config.json` permissions) or structural files (like project YAML manifests) must be merged manually in `connections/servers.yaml` or project manifests. The console will display a clear message indicating where the manual change must land.

### 📜 Staleness & Decisions
- **Stale Detection**: If you edit your registry directly while the console is open, it automatically flags inbox candidates as `stale` if they were captured against an older base hash.
- **Procedural Memory**: When you Accept or Reject a candidate, the decision (including an optional text explanation) is appended to `registry/local/inbox/decisions.jsonl`. This log serves as historical procedural metadata for future agent iterations.

---

## 🌐 The Knowledge Graph Tab: Document Curation

The **Knowledge Graph** tab is Stage 3 of mapping your workspace documents into schema.org JSON-LD indexes.

### 📋 Using the Curation Checklist
1. First, stage your document list using the connector CLI (see [Connectors & Document Stores Guide](connectors/README.md)):
   ```bash
   python build/mitos.py connect --project <project-slug> --stage
   ```
2. Open the **Knowledge Graph** tab and select your project from the list. (The shipped
   `example: true` sample projects appear here only on a fresh clone — as soon as your
   overlay defines its own projects they step aside, the same convention the compiler
   and the Prompt Library apply.)
3. The console lists all staged files (either from the project-scoped staging file or the unassigned staging pool `unassigned.json`). Files that are already mapped are automatically filtered out.
4. Select the checkboxes for the authoritative documents you want to provide to your agents (e.g. project specifications, designs, or logs).
5. Click **Propose selected**. This writes a `kind: graph` candidate into your Inbox.
6. Navigate to the **Inbox** tab, review the candidate's canonical JSON-LD diff, and click **Accept**. This writes or updates `registry/local/graph/<project-slug>.jsonld`, which compiles into the Agentic Context roster on your next deploy.

### 🗂️ Discovery and Recovery

The left column is tabbed: **Discovery** (staged files not yet mapped — the checklist above) and
**Recovery** (files dismissed from Discovery, or auto-dismissed when an accepted removal drops
them from the graph). A staged file's own **Dismiss** action (per-row, or **Dismiss selected**
for a batch) moves it to Recovery instead of proposing it — useful for staged noise (screenshots,
scratch files) you never intend to map. Because staging snapshots are never pruned, a document
you remove from the graph would otherwise resurface in Discovery the moment it's unmapped again;
accepting a removal auto-dismisses it into Recovery instead, tagged **Removed** (a manual dismissal
is tagged **Dismissed**). **Restore** in Recovery clears the dismissal so the file reappears in
Discovery and can be mapped again. Dismissals live in `inbox/staging/<slug>.dismissed.json` (or
`unassigned.dismissed.json`), mirroring the same project/unassigned pool fallback as staging
itself.

**Permanently dismiss** (Recovery, per row) hides a document for good: the sidecar record stays
(so Discovery keeps filtering the id out) but the row leaves the Recovery list, and there is no
in-console undo — reversing it means editing the `.dismissed.json` sidecar by hand. Nothing is
ever deleted from the document store; the console is not a filesystem actor.

**Watching more than one folder or query.** A project isn't limited to one staged scope —
`inbox/staging/<slug>.json` holds a *list* of watched listings, each its own
`(store, folder_id, query, recursive)`. Discovery shows a **watched-scopes strip** above the
staged rows, one entry per listing (its scope, staged-at timestamp, doc count), each with its own
**Rename**, **↻ Refresh** and **Remove watch**. Refresh replays that ONE listing's enumeration — it runs
`build/mitos.py` as a *subprocess*, so the connector never enters the console's own import graph
(invariant #11). Remove watch drops the listing from the file; anything already mapped into the
graph is unaffected, only what Discovery *offers* changes. The first stage of a scope still
happens in a terminal (it may need an interactive OAuth consent); until at least one watch
exists, Discovery shows the copyable command instead. A document reachable through more than one
watch appears once in Discovery, tagged with a small "N watches" chip (hover it to see which
watches by name) — watching two overlapping scopes is never an error, `--stage` just notes the
overlap and stages both.

**Naming a watch.** A raw `folder 1u7GX8M9UZDJlMn7m-2-arxO_QQRPYV8n` says nothing about what's in
it, and several of them side by side say even less. **Rename** gives a listing a human name
(`label` on the listing, ≤60 chars), which then leads its row with the scope demoted to the meta
line beneath — the identifier the system acts on is never hidden, just no longer the headline. The
label is **cosmetic**: identity stays the derived `scope_key` (`store`/`folder_id`/`query`/
`recursive` — `staging.scope_key`), so renaming can't change which documents a watch holds, can't
disturb a sibling watch, and a later Refresh replays the same scope and keeps the name
(`bootstrap.stage_listing` carries the label across a re-stage). Names are free text and not
unique-checked. Submitting an empty name clears the label and the row falls back to its derived
scope — that's the undo. Like Remove watch, it's console-only (`POST /api/graph/rename-watch` →
`review.rename_watch`) — a pure file edit with no connector involved, so a CLI verb would just be
a second way to write the same line.

**Documents that left the store.** Recovery cross-checks its rows against every CURRENT watched
listing and badges any doc absent from all of them as **Not in any watched scope**, offering
**Remove** (per row) and **Clear missing** (bulk) to stop tracking them. This is deliberately
*not* automatic: deletion stays an explicit click (invariant #9), and the check only speaks when
it can prove something. Absence is provable two ways — a FULL (unscoped) listing exists and
doesn't contain the doc (its silence is conclusive, it enumerates everything), or a SCOPED
listing exists that is itself the one this doc's own recorded provenance says produced it, and it
no longer contains the doc (that specific watch lost it). A doc still reachable through *any*
other current listing is never flagged, even if it just dropped out of the watch that first
surfaced it — presence anywhere always wins over absence from one scope. The server re-verifies
this before clearing anything, so a stale browser tab can never purge a document that's still
live in some watch.

### 🎭 Org domains on efforts

One structured field in this tab drives the org model — the **effort `Org domain` select**: it tags an effort (Work grouping) with the org domain that governs it — e.g. a `Steam Launch` effort tagged `marketing` inside an otherwise software-heavy project. The tag compiles into an org routing line under that effort's heading in the generated files, which is how a session knows to load `org-marketing` for that work and `org-software` for the rest. **Projects themselves are never bound to one org** — the manifest has no `org:` field; the association lives on the work.

---

## 🧩 The Skills & Orgs Tab: Skill Cards + Org Structure

The **Skills & Orgs** tab is a card grid over every skill in your registry — one card per skill,
with its description, target chips (which tools it deploys to), and — for org-domain skills — an
`org: <domain>` badge. The card face carries only what *distinguishes* one skill from another;
every skill's uniform detail lives in one reusable **properties drawer** that slides in from the
right (**Properties**, or Esc to close). Version/author/license/platforms are rarely-consulted
provenance, so they sit there as a single compact line rather than a grid of cards.

- **Edit prompt →** (card or drawer): Opens the skill's body and its authoring metadata —
  description, version, category, and target checkboxes — in the Contextual Editor (Prompt
  Library). Saving proposes a `kind: drift` candidate into the Inbox. A skill's *structural*
  placement — its supporting files and its org-role extension — is edited in the drawer (below),
  not here.
- **Supporting Files**: In the drawer, a skill's `examples/` and `scripts/` files
  (deployed alongside `SKILL.md` and bundled into claude.ai zips) are listed inline, each
  editable or deletable, with an **Upload file(s)** button that reads one or more UTF-8 text
  files and auto-routes each to `scripts/` (`.py`/`.js`/`.sh`/`.ps1`) or `examples/` (everything
  else); binary files are rejected with a warning. This section proposes the **full replacement
  set** on save — leave it untouched to propose no change to existing files; explicitly clear
  every entry to delete them all on accept.
- **Extension**: In the drawer, two dropdowns set `extends_skill`/`extends_role` (see
  **Extending a role** below). The skill picker lists only skills eligible to be extended (those
  carrying an `## Extended C-suite Roles` section); choosing one populates the role picker from
  that parent's roles. Setting both turns the skill into an extension; clearing both makes it a
  regular skill again. Saving proposes a `kind: drift` candidate.
- **+ New skill**: A one-screen form — name (slug), description, category, target checkboxes,
  optional `extends_skill`/`extends_role`, and a Supporting Files editor — feeding into the
  Contextual Editor for the body. Creating proposes a `kind: new` candidate; nothing is written to
  `registry/` until you Accept it in the Inbox, and it always lands in your private overlay
  (`registry/local/skills/<name>/SKILL.md`), never core.
- **+ New org**: Scaffolds a brand-new domain as a single `kind: new` skill candidate (an
  `org-<domain>` skill with `org_domain: <domain>` frontmatter). The domain becomes selectable
  everywhere once accepted — domain discovery is dynamic, never a hardcoded table.
- **Disable**: Not yet wired to a candidate — the console can't route a frontmatter-only change
  through the accept path today. Edit the skill's `targets:` list by hand in its `SKILL.md` to
  exclude a tool.
- **Import from .zip**: A placeholder for a future release — no backend yet.

### Org structure: Role Tree, extending a role, and the Agent-MD Folder View

Org structure is a **visualization** — it never edits the `org-*/SKILL.md` playbooks
directly; those stay hand-authored prose. **Orgs are global domain
skills and are never attached to a project** — the only org edge in the graph is an effort's
`Org domain` tag, set in the Knowledge Graph tab.

- **Role Tree**: The primary delegation chain (CEO → ... → Assistant) plus the Extended C-suite
  roles (CTO, CFO, COO, CMO, CHCO) parsed from that domain's `org-*/SKILL.md` — each role expands
  to show its Lens, Team, Vocabulary, Trigger, and any **active extensions** (skills that
  `extends_skill`/`extends_role` it). The C-suite titles are identical across all domains; only
  their lens is domain-flavored.
- **+ Extend department**: On each role card, opens the New Skill form prefilled with
  `extends_skill`/`extends_role` for that role — the console's write path onto an existing role.
  The new skill's body splices into the parent's matching role section **at render time only**;
  the parent skill's own `SKILL.md` is never modified, and the extension never deploys standalone
  (it exists only spliced into its parent).
- **Agent-MD Folder View**: The actual on-disk `AGENTS.md`/`AGENTS_DETAILS.md` tree a chosen
  machine deploys — including any dynamically discovered branches under
  `registry/context/<branch>/AGENTS.md` — reconstructed from the same plan `deploy` would use.

---

## 📚 The Prompt Library Tab: One-Shot Composition

The **Prompt Library** acts as a scratchpad and library for one-shot chat sessions in tools that Mitos does not deploy directly to (like standard web/desktop chat interfaces).

- **Browse & Filter**: Access all authored Skills, first-class Prompts, and Partials (identity/context) from your registry. Filter chips reflect the categories actually present in your registry. The list-scoped filter box narrows what's visible in the current tab. Example-project context partials are listed only on a fresh clone — once your overlay defines its own projects they step aside, like everywhere else in Mitos.
- **Find anything (Ctrl/⌘K)**: Opens a command palette that searches every skill, prompt, and partial at once, from any tab — pick a result to jump straight to it in the Prompt Library.
- **Favorites**: Toggle the star icon to pin a skill or prompt to your favorites list (drag to reorder, or use **Manage** for batch-unpin). Pins persist to `registry/local/prompt-favorites.yaml` and sync across sessions/devices.
- **Fillable inputs on copy**: A prompt body may carry `{{tokens}}`. Mitos-owned tokens are handled for you — the personalization tokens (`{{user_given_name}}`, `{{user_email}}`, …) are substituted from `user.yaml` exactly as a deploy would expand them, and the machine-scoped ones (`{{project_root}}`, `{{skills_root}}`) are left literal, since a copied prompt goes to a chat app rather than a machine. **Every other `{{token}}` is treated as a fillable input**: copying opens a small modal asking for each one, then puts the filled text on your clipboard. Leave a field blank to keep its `{{token}}` literal, so an incomplete prompt is visibly incomplete rather than silently missing a word. A prompt with no custom tokens copies immediately, with no modal.
- **Contextual Editor**: Select an item to edit it — a line-numbered textarea with a markdown toolbar (Bold/Italic/Code/Link/Heading/List) and a sanitized live preview toggle.
- **Save to inbox**: If you refine a prompt and want to save it as a permanent registry asset, type a short reasoning note and click **Save to inbox**. It will land in the **Inbox** tab as a new candidate for review.
