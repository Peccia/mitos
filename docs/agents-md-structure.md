# The tree-node header taxonomy

Every file the assistant reads while navigating the deployed tree — the operating root
`AGENTS.md`, the `Projects/` and `Assistant/` branch roots, each project's `AGENTS.md`,
and every `AGENTS_DETAILS.md` — shares **one header layout**. The persona (`SOUL.md`) and
the skills reference sections *by name*, so the names, levels, and order are a contract,
not a style preference. It is enforced at plan time by `lint_node_markdown`
(`build/agentic/planner.py`); a violation fails `compile`/`deploy` with the offending
file and problem named.

This taxonomy is identical regardless of where the tree is *mounted*: a machine-wide
operating mount at `assistant_root` (the Hermes combo) and a project-wide operating mount
at a project's `agentic_tree:` render through the same `_emit_tree` and are linted the
same way — only the deploy root differs. It does not apply to a reference mount
(`agentic_context_root`/agentic-graph): that lane's files are `drift_policy: generated`
and carry no prose to structure — see the root [`README.md`](../README.md)'s Core
Concepts table for the operating-mount-vs-reference-mount distinction.

## The rules

1. **One H1 = the node's identity.** The project name, `Operating Root`, `Projects`,
   `Personal Assistant`. The description is the prose directly under it — there is no
   `## About` section. A standalone generated file (a wholly-generated project node with
   no prose, an `AGENTS_DETAILS.md`) takes its H1 from the connection section instead.
2. **No heading-level skips.** H1 → H2 → H3, never H1 → H3.
3. **Reserved H2 sections, in this order** (each optional; file-specific sections may sit
   between them):

   | Section | Holds | Act on it with |
   |---|---|---|
   | `## Navigation` | the **local** tree from here — child `AGENTS.md` to open, the routing decision, cloned repo folders | file / `terminal` tools |
   | `## Workflows` | step-by-step procedures the node performs itself (e.g. the Assistant's email/calendar/task categories) | — |
   | `## Tools` | callable capabilities (MCP servers, browser, terminal) **and their rules of use** | invoke the tool |
   | `## Skills` | instruction playbooks in scope at this node | read `SKILL.md`, follow it |
   | `## <Name> (`key`)` | a **connection** section — folder paths and the document map *inside* that store | that connection's tools |

4. **The connection section** is headed by the store's stable label `<Name> (`key`)`
   (`render.connection_label`, from `connections/servers.yaml`) — never the raw
   description sentence, which would rename the section on every edit and orphan every
   reference. Its document map renders effort groups at **`###`** (`### Documents`,
   `### <effort>`), one level under the connection heading, so an effort name can never
   collide with a reserved `##` prose section. A tagged effort's `###` heading carries the
   org-routing line that names the `org-<domain>` skill governing its work.

## Local vs. connection: the split that keeps context lean

`## Navigation` is **local only** (files, repos, routing); store folder paths live in the
**connection section**. The agent learns one rule — *`## Navigation` → file tools; a
connection section → that connection's tools* — and no node loads store paths until it has
landed on the project that needs them. A project's curated store-folder paths are authored
as prose under `## <Name> (`key`)`; the generated document map then attaches beneath that
same heading (the planner detects the ``(`key`)`` marker and suppresses the duplicate
heading via `emit_heading=False`). A project with no curated paths gets the whole
connection section generated.

## Skills

A `SKILL.md` body opens with `# <Skill Title>` (a human-readable name, so the file
self-identifies even where frontmatter is stripped) and a short purpose paragraph, then
`## Instructions`. Org skills keep their parser-bound sections (`## Description`,
`## <n>. <Role> — <mandate>`, `## Extended C-suite Roles`) unchanged — those feed the
generated org-domain table and the extension-splice anchor.

## Exceptions

`SOUL.md` is a stacked system prompt, not a navigable node — it has no file identity, so
it is all-H2 (the identity partials) with no H1, and is **not** linted. It carries only
the session protocol (realign at the root, capture memory, reset); the taxonomy itself is
taught **inside the tree**, by the operating root's `## Navigation` section
(`registry/context/agentic-root.md`) — the first node every session reads — so the tree
stays self-describing and SOUL stays lean.
