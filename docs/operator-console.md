# Mitos Operator Console Guide

The Mitos **Operator Console** is a local web application that serves as the human steering wheel for your agent organization. 

Run the console to:
1. Review and accept self-improvement proposals or drift from your tools (**Inbox**).
2. Curate and map workspace files into your projects' knowledge graphs (**Knowledge Graph**).
3. Browse, create, and edit skills — including supporting files and org-role extensions — and
   visualize your simulated org structure (**Skills & Orgs**).
4. Search, compose, and copy-paste registry prompts for one-shot chat sessions (**Prompt Library**).

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

### 🎭 Org domains on efforts

One structured field in this tab drives the org model — the **effort `Org domain` select**: it tags an effort (Work grouping) with the org domain that governs it — e.g. a `Steam Launch` effort tagged `marketing` inside an otherwise software-heavy project. The tag compiles into an org routing line under that effort's heading in the generated files, which is how a session knows to load `org-marketing` for that work and `org-software` for the rest. **Projects themselves are never bound to one org** — the manifest has no `org:` field; the association lives on the work.

---

## 🧩 The Skills & Orgs Tab: Skill Cards + Org Structure

The **Skills & Orgs** tab is a card grid over every skill in your registry — one card per skill,
with its description, target chips (which tools it deploys to), and — for org-domain skills — an
`org: <domain>` badge. Expanding an org-domain skill's card also reveals its **org structure**
below the static properties (see below); a plain skill's card stops at properties + actions.

- **Edit prompt →**: Opens the skill's body and its authoring metadata — description, version,
  category, and target checkboxes — in the Contextual Editor (Prompt Library). Saving proposes a
  `kind: drift` candidate into the Inbox. A skill's *structural* placement — its supporting files
  and its org-role extension — is edited on the card itself (below), not here.
- **Supporting Files**: On the expanded card, a skill's `examples/` and `scripts/` files
  (deployed alongside `SKILL.md` and bundled into claude.ai zips) are listed inline, each
  editable or deletable, with an **Upload file(s)** button that reads one or more UTF-8 text
  files and auto-routes each to `scripts/` (`.py`/`.js`/`.sh`/`.ps1`) or `examples/` (everything
  else); binary files are rejected with a warning. This section proposes the **full replacement
  set** on save — leave it untouched to propose no change to existing files; explicitly clear
  every entry to delete them all on accept.
- **Extension**: On the expanded card, two dropdowns set `extends_skill`/`extends_role` (see
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
- **Contextual Editor**: Select an item to edit it — a line-numbered textarea with a markdown toolbar (Bold/Italic/Code/Link/Heading/List) and a sanitized live preview toggle.
- **Save to inbox**: If you refine a prompt and want to save it as a permanent registry asset, type a short reasoning note and click **Save to inbox**. It will land in the **Inbox** tab as a new candidate for review.
