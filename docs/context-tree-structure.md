# The tree-node header taxonomy

Every file the assistant reads while navigating the deployed tree — the operating root
`AGENTS.md`, the `Projects/` and `Assistant/` branch roots, each project's `AGENTS.md`,
and every `AGENTS_DETAILS.md` — shares **one header layout**. The persona (`SOUL.md`) and
the skills reference sections *by name*, so the names, levels, and order are a contract,
not a style preference. It is enforced at plan time by `lint_node_markdown`
(`build/agentic/planner.py`); a violation fails `compile`/`deploy` with the offending
file and problem named.

This taxonomy is identical regardless of where the tree is *mounted*: a machine-wide
context tree at `context_root` and a project-wide tree
at a project's `context_tree:` render through the same `_emit_tree` and are linted the
same way — only the deploy root differs.

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
   collide with a reserved `##` prose section.

   An effort's `###` heading is **`<name> (<id>)`** (`graph.effort_heading`) — the same
   human-name-then-stable-id form a project roster line uses (`` - `Projects/Website/`
   (website) — … ``). The id is emitted for every effort and rides the heading
   rather than a line of its own: a harness keying a long-lived record on an effort must key it
   on something a rename cannot move, and the heading text is the NAME, which the owner edits
   freely. Reusing the heading costs no always-on tokens. The id is always the **last**
   parenthesised group, so a name that itself ends in parentheses stays unambiguous.

   Under an effort's `###` heading the generated lines render in a fixed order: the effort
   description, then the `**Goal:** …` intent line (`graph._effort_goal_line`), then the effort's
   documents.

   A document line reads `- **<name>** `<id>` (<date> · <type>) — <description>`. The
   `· <type>` label appears only for a kind other than the default `document` (a sheet, a
   pdf, a picture — the kinds that change which tool to reach for); a plain document, or an
   untyped one, shows the date alone. When
   any document in the project is typed `image` (a `schema:ImageObject` — a picture a
   vision model can view), the details and full views add ONE line directly after the
   connection intro: `_Entries typed `image` are pictures: open one by its ID as an
   image, never as text (see your document store skill's Images section)._`
   (`graph.IMAGE_HINT`). The titles-only index never carries it, and a project without
   images renders byte-identically.

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
workstation `local_path` node, reference mounts, or a harness context root
(which mounts repos beside the project node). That includes a `context.builder` project such as Mitos
self-hosting: its node carries the roster when checkouts are present beside it.
A `context_tree:` mount puts clones beside the mount rather than inside it.

## Skills

A `SKILL.md` body opens with `# <Skill Title>` (a human-readable name, so the file
self-identifies even where frontmatter is stripped) and a short purpose paragraph, then
`## Instructions`.

## Exceptions

Stacked system prompts or identity partials are not navigable tree nodes — having no
single file identity, they are all-H2 (identity partials) with no H1, and are **not**
linted as tree nodes. The taxonomy itself is taught **inside the tree**, by the
operating root's `## Navigation` section (`registry/context/agentic-root.md`) — the
first node read — so the tree stays self-describing.
