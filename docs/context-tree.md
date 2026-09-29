# One context, every harness

A **Context Tree** is a vendor-neutral, directory-based markdown tree containing project nodes,
documentation maps, operating workflows, and identity context. Rather than authoring separate,
redundant context files for each agentic harness (e.g., Claude Code, Antigravity, Cursor,
or custom scripts), Mitos compiles a single canonical context tree that every
tool on every machine can navigate and ground on.

---

## What is a Context Tree?

Modern AI harnesses require context: knowledge of your projects, available tools, operating
guidelines, communication style, and documentation. When every harness invents its own file
format or siloed configuration, context drifts and diverges.

A Mitos Context Tree solves this by organizing your operating context as a filesystem tree:
- **`AGENTS.md` (Root):** High-level navigation roster pointing to projects and personal workflows.
- **`Projects/<name>/AGENTS.md`:** Per-project context, repositories, and documentation graphs.
- **`Projects/<name>/AGENTS_DETAILS.md`:** On-demand document index with deep links and summaries.
- **`Assistant/`:** Personal assistant workflows (tasks, notes, reminders, routines).

---

## How Harnesses Read It

Any AI harness with basic filesystem and file-reading tools can navigate a context tree:
1. **Entry Point:** The harness starts at the operating root `AGENTS.md` (or a project checkout's root `AGENTS.md`).
2. **Navigation:** Harnesses read the `## Navigation` section to discover child nodes, project directories, and cloned repositories.
3. **Progressive Disclosure:** High-level indexes provide immediate orientation, while deep files (`AGENTS_DETAILS.md`) are read only when needed for specific tasks.
4. **Symlinks and Stubs:** Coding harnesses that expect specific filenames (e.g. `CLAUDE.md`) receive lightweight stubs pointing to `@AGENTS.md`, ensuring all tools share the same ground truth without duplicated text.

---

## Operating Mount (`context_root`) vs. Project Mount (`context_tree`)

A context tree can be deployed at two distinct scopes:

### 1. Operating Mount (`context_root`)
Configured on a machine profile (`registry/local/machines/<name>.yaml` or `machines/<name>.yaml`):
```yaml
targets:
  - context-tree
  - claude-code
paths:
  context_root: "~/context-tree"
```
- Deploys the complete machine-wide operating tree at `context_root` (e.g., `~/context-tree`).
- Clones project repositories beside project nodes in `Projects/<Name>/<repo>`.
- Deploys universal identity partials (`who-i-am.md`, `operating-rules.md`, `security.md`).

### 2. Project Mount (`context_tree`)
Configured on an individual project (`registry/projects/<slug>.yaml`):
```yaml
name: Family
context_tree: context
```
- Mounts an operating tree directly inside that specific project repository's checkout under the named subdirectory (e.g., `<checkout>/context/`).
- Allows a project checkout to host its own self-contained operating tree without requiring a dedicated machine profile.
- The project's root `AGENTS.md` automatically cross-references the operating tree.

---

## Header Taxonomy

Every node in a context tree follows a strict header hierarchy (see [`context-tree-structure.md`](context-tree-structure.md)):
1. **`# <Title>` (H1):** The node's identity and primary description.
2. **Reserved `##` Sections (in strict order):**
   - `## Navigation`: Local filesystem hierarchy and relative links to child nodes.
   - `## Workflows`: Step-by-step operational playbooks.
   - `## Tools`: Rules for using tools and environment capabilities.
   - `## Skills`: Available skill playbooks.
   - `## <Connection> (<key>)`: External document stores (Google Workspace, Notion, local documents) and their effort hierarchies.
3. **No Header Skips:** Strict `H1` → `H2` → `H3` hierarchy ensures consistent readability across LLM models.

---

## Vendor Neutrality

The Mitos Context Tree is completely open and vendor-neutral:
- **Standard Markdown:** Authored in standard GitHub-Flavored Markdown.
- **Tool Agnostic:** Works with Claude Code, Antigravity, custom agent runners, or human operators reading directly in a terminal or editor.
- **Interoperable SDLC:** A planning harness can plan work against the context tree, while a coding harness (such as Claude Code or Antigravity) executes the work against the exact same context.

