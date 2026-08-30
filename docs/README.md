# Mitos Documentation Hub

Welcome to the Mitos documentation. Mitos is a registry and compiler for your personal agent organization, allowing you to author your capabilities once and deploy them seamlessly across all your AI tools and machines.

Use this Documentation Map to navigate the guides and references:

---

## 🧵 Core concepts and configuration

Understand how Mitos models your registry, handles tool configurations, and manages deployment states:

- **[Overlay configuration reference](../registry/README.md)** — Detailed field-by-field reference for project manifests (`projects/<slug>.yaml`), machine profiles (`machines/<name>.yaml`), and server overrides (`connections/servers.yaml`).
- **[Managing state & drift](managing-state.md)** — How `deploy`, `adopt`, and `harvest` work under the hood, and how to resolve drift and conflicts.
- **[The tree-node header taxonomy](agents-md-structure.md)** — The reserved-section contract (`## Navigation`, `## Tools`, `## Skills`, connection sections) every deployed `AGENTS.md` follows, and the plan-time lint that enforces it.
- **[Syncing across machines](lan-sync.md)** — Setting up `mitos sync` to carry your private context overlay across your fleet using git.

---

## 🛠️ Tool and target setup

Guides for configuring Mitos to deploy custom context, skills, and prompts into specific AI tools:

- **[Claude Code target](targets/claude-code.md)** — Integrating per-project `CLAUDE.md`, skills, and slash-command prompts.
- **[Antigravity target](targets/antigravity.md)** — MCP server access, tool permissions, native `AGENTS.md` context, and global/project-scoped skill delivery (`antigravity` target — covers Antigravity IDE + CLI, and Gemini CLI until it retires 2026-06-18; see [the legacy Gemini CLI note](targets/gemini-cli.md)).
- **[Claude app target](targets/claude-app.md)** — The claude.ai account surface (web + Desktop): staging skill zips for manual upload, and the `npx mcp-remote` bridge for LAN/HTTP MCP servers on Desktop.
- **[Mitos Agent target](targets/mitos-agent.md)** — The first-party agentic planning harness (`mitos-agent`): `SOUL.md`, a skills tree, and a whole-file `mcp.json`, deployed into `assistant_root` alongside the `agents-md` tree — one install root the harness reads. Includes the end-to-end install→deploy→run sequence. Replaces the retired `hermes` target.

---

## 🔌 Workspace connectors and document stores

How to index your workspace documents into the Mitos knowledge graph so your agents can find the source of truth:

- **[Connectors and document stores overview](connectors/README.md)** — Core connector stages, recursive scopes, and the unassigned staging pool.
- **[Google Workspace connector](connectors/google-workspace.md)** — Step-by-step OAuth and Docker guide to run the Google Workspace MCP server.
- **[Custom MCP servers](connectors/custom-servers.md)** — How to write custom `graph_enum` specifications to index arbitrary document stores.

---

## 💻 Operations and customization

Take control of your registry, author custom capabilities, and select organizational archetypes:

- **[Operator console](operator-console.md)** — Running the local `review` console to reconcile proposals, curate knowledge graphs, and use the Prompt Library.
- **[Authoring custom capabilities](authoring-capabilities.md)** — A guide to writing and binding custom Skills, Subagents, and Prompts in Mitos.
- **[Organization templates](org-templates.md)** — Selecting and customizing default C-suite delegation models (Solo Assistant, Software Firm, Design Firm).

---

## 🔁 Design and implementation plans

Cross-repo design records for work in flight. These describe intent and sequencing, not shipped behaviour — check the code before relying on one:

- **[Closing the loop](concepts/closing-the-loop-implementation-plan.md)** — Carrying an implementation's own documents back into the shared store and the knowledge graph: deliverable skills publishing to the connection, export planning statistics, grounded-reference curation, the evaluation summary, and the Implemented Document written on graduation.

---

## ⚡ Essential daily commands

| Task | Command |
|---|---|
| **Validate Registry** | `python build/compile.py compile` |
| **Preview Deployment** | `python build/compile.py deploy --machine <name> --dry-run` |
| **Deploy to Tools** | `python build/compile.py deploy --machine <name>` |
| **Inspect Changes / Drift** | `python build/compile.py diff --machine <name>` |
| **Adopt In-Place Edit** | `python build/compile.py adopt <path-to-file>` |
| **Launch Web Console** | `python build/compile.py review` |
