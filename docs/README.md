# Mitos Documentation Hub

Welcome to the Mitos documentation. Mitos is a registry and compiler for your personal agent organization, allowing you to author your capabilities once and deploy them seamlessly across all your AI tools and machines.

Use this Documentation Map to navigate the guides and references:

---

## 🧵 Core concepts and configuration

Understand how Mitos models your registry, handles tool configurations, and manages deployment states:

- **[Overlay configuration reference](../registry/README.md)** — Detailed field-by-field reference for project manifests (`projects/<slug>.yaml`), machine profiles (`machines/<name>.yaml`), and server overrides (`connections/servers.yaml`).
- **[Managing your moat's state](managing-state.md)** — How `deploy`, `adopt`, and `harvest` work under the hood, and how to resolve drift and conflicts.
- **[The tree-node header taxonomy](agents-md-structure.md)** — The reserved-section contract (`## Navigation`, `## Tools`, `## Skills`, connection sections) every deployed `AGENTS.md` follows, and the plan-time lint that enforces it.
- **[Syncing across machines](lan-sync.md)** — Setting up `mitos sync` to carry your private context overlay across your fleet using git.

---

## 🛠️ Tool and target setup

Guides for configuring Mitos to deploy custom context, skills, and prompts into specific AI tools:

- **[Claude Code target](targets/claude-code.md)** — Integrating per-project `CLAUDE.md`, subagents, skills, and slash-command prompts.
- **[Gemini CLI target](targets/gemini-cli.md)** — Configuring MCP server access, tool permissions, and global/project-level context.
- **[Claude app target](targets/claude-app.md)** — The claude.ai account surface (web + Desktop): staging skill zips for manual upload, and the `npx mcp-remote` bridge for LAN/HTTP MCP servers on Desktop.
- **[Antigravity target](targets/antigravity.md)** — IDE-level integration, native `AGENTS.md` context, and skill delivery.

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
