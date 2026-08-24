# The tree-node header taxonomy

Every file the assistant reads while navigating the deployed tree — the operating root
`AGENTS.md`, the `Projects/` and `Assistant/` branch roots, each project's `AGENTS.md`,
and every `AGENTS_DETAILS.md` — shares **one header layout**. The persona (`SOUL.md`) and
the skills reference sections *by name*, so the names, levels, and order are a contract,
not a style preference. It is enforced at plan time by `lint_node_markdown`
(`build/agentic/planner.py`); a violation fails `compile`/`deploy` with the offending
file and problem named.

This taxonomy is identical regardless of where the tree is *mounted*: a machine-wide
operating mount at `assistant_root` (the Mitos Agent combo) and a project-wide operating mount
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

## The generated repo roster inside `## Navigation`

A project's cloned checkouts are local paths, so they belong to `## Navigation` — and they
are **generated**, never hand-listed. `render.navigation_block` renders one line per repo
(`- `acore/` — <description>`) from the manifest's `repo:` list plus its optional
`repo_notes:` map (basename → one-line description, editable in the operator console's
Project panel). A project's prose describes *why* its repos exist or how they relate; the
roster states *what* they are. Nothing is duplicated, so nothing can drift out of sync with
the manifest.

The clone URL is deliberately absent: it is deploy-time machinery, recoverable from each
checkout's own `.git/config`, and not worth context on every request.

Placement follows the same prose-opened-the-section convention the connection block uses:

- Prose **already opens `## Navigation`** → the roster attaches beneath the author's
  routing text, no second heading.
- Prose has **no `## Navigation`** → the roster emits the heading itself, positioned after
  the H1 and its description and before the first authored `##`, so the reserved order
  holds.
- **No repos** → no section at all, rather than a bare heading.

Mechanically this is the one place a generated region sits *inside* a document rather than
trailing it, which is why `render.split_live_sections` returns **ordered regions** rather
than a source-keyed map: the prose partial contributes a region on each side of the roster,
and `commands.route_into_registry` rejoins them (`render.rejoin_regions`) before writing
back. A hand-edit to the roster is silently regenerated; a hand-edit to the prose around it
is still ordinary, adoptable drift.

Only project nodes whose checkouts are actually siblings of the file get a roster — the
workstation `local_path` node, the `agentic_context_root` reference mount, and the `mitos-agent`
operating tree (which clones repos into `<assistant_root>/Projects/<name>/<basename>/` as
siblings of the project node). An `agentic_tree:` mount puts clones beside the mount rather
than inside it.

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
