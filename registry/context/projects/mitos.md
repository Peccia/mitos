---
audience: [claude-code, agents-md]
---
# Mitos — Builder Context

> **Context dedup:** this file compiles into both `AGENTS.md` (at the project root) and `CLAUDE.md`
> (on machines without a co-deployed `AGENTS.md`). If this content is already present in your
> loaded `AGENTS.md`, do not re-read `registry/context/projects/mitos.md` — it is the same source.

You are working on the **Mitos** repo itself: the registry and compiler that materialize an
agent organization across tools. Mitos manages itself — this file is authored at
`registry/context/projects/mitos.md` and compiled into the root `AGENTS.md`. **Read
[`README.md`](README.md) for the architecture and workflows before making structural changes.**

## What this repo is
- `registry/` is the **moat**: the single, canonical home for all content — personas
  (`identity/`), domain/project context (`context/`), skills (`skills/`), agents
  (`agents/`, Claude Code subagents), harness-agnostic prompts (`prompts/`), the knowledge
  graph (`graph/`, schema.org JSON-LD), project manifests (`projects/`), and org seed
  templates (`templates/`). `registry/local/`
  is the **Mitos overlay** (gitignored): a user's private identity/projects/graph/skills,
  loaded on top of the core by last-layer-wins so the same repo can go open source without
  leaking personal content.
- `connections/` is the moat's **tools**: MCP server definitions + env templates.
  Deliberately NOT registry content — wiring doesn't compound and has no harvest
  story. It deploys on its own lane: `deploy --lane connections` touches only MCP
  wiring + env files; `--lane content` touches only prose (default `all` does both).
  Each server's config contract is defined by its **upstream repo** (recorded as
  `repo:` in `servers.yaml`); env templates mirror the upstream-documented variables
  — consult the upstream README before adding or changing keys, never invent them.
- `build/compile.py` renders both into each tool's native format and deploys them.
  The compiler is disposable plumbing; the registry content is the durable asset.
- `dist/` and every deployed file (`SOUL.md`, `CLAUDE.md`, `AGENTS.md`, tool MCP
  configs) are **build artifacts**. Never hand-edit them — edit the registry and
  recompile.

## Invariants (obey these mechanically)
1. **Prose stays prose.** Personas, skills, and context are plain Markdown partials.
   YAML is only for structure (manifests, `servers.yaml`, machines, targets).
2. **The registry wins at deploy.** Tools may mutate their deployed copies; those
   mutations surface via drift detection. Tools propose — only the maintainer commits to
   the registry (via `adopt` / `harvest`).
3. **Never write into `registry/` to propose a change — propose into `registry/local/inbox/`.**
   `registry/local/inbox/` is the intake queue: one folder per candidate (payload snapshot +
   `meta.yaml` with `registry_path`, `kind: drift|new|report`, `source`, `base_hash`).
   `deploy` captures overwritten drift there automatically; agents proposing new
   content or work reports write candidates there by hand. See `docs/managing-state.md` for details.
   Only the maintainer merges candidates into the registry. The queue lives inside the private
   overlay so it syncs to the mitos-local hub via `mitos sync` — never in the public-track repo.
4. **Every emitted path declares a `drift_policy`** (`protect`, `harvest`, or
   `generated`) in its target spec. `generated` files (the knowledge-graph project tree)
   are regenerated from `registry/graph/` every deploy and overwrite in-place edits
   silently — they are non-adoptable, with no registry partial to route an edit back to.
5. **Deployed artifacts are raw context — no banners, no markers.** The model reads
   pure prose; scaffolding would tax every request. Provenance for `adopt` lives in
   the lockfile (a per-section base recorded at deploy), reconstructed at adopt time —
   never embedded in the file. Don't reintroduce in-file markers or `DO NOT EDIT`
   banners.
6. **Secrets never enter git.** Only `*.env.example` templates are tracked; real values
   live in `.local/` (gitignored) and are merged at deploy time — never at compile,
   so `dist/` and `registry/local/inbox/` never contain secret values.
7. **Tool-owned config files get surgical merges, never whole-file overwrites.**
   Hermes `config.yaml` (`yaml_merge`, owns `mcp_servers`) and Antigravity `config.json`
   (`json_merge`, owns only its alias's `mcp(...)` entries inside the allow list) are
   the patterns to copy for any new tool that keeps its own config file.
8. **Deploys are machine-guarded.** `deploy` refuses when the host OS doesn't match
   the machine profile's `os:`; rehearse cross-machine deploys with `--root <dir>`
   (files, lockfile, and inbox captures all land under `<root>/registry/local/inbox/`).
9. **Deletion is explicit, never a side effect.** `deploy` removes nothing on its
   own: outputs no longer planned (a deselected skill, a retired project) become
   *orphans* — reported on every deploy, kept on disk and in the lockfile — until
   `deploy --prune` deletes them. A drifted orphan is captured to `registry/local/inbox/` before
   deletion.
10. **Boring beats clever.** No frameworks, brokers, or chains until a concrete,
    recurring pain forces one. Weigh any new dependency or abstraction against that bar
    before proposing infrastructure.
11. **Network reach lives beside the compiler, never inside it.** Workspace reach
    (connectors, OAuth, the interactive `init` wizard) and cross-machine sync (`mitos sync`,
    `build/agentic/sync/`) are a *separate* entrypoint (`build/mitos.py`) with lazy, optional
    backend deps; the deterministic verbs stay offline and import no network/credential code
    (the loader validates the `sync:` block's *shape* only, never importing the sync package).
    Connectors are producers for the *one* `kind: graph` valve — they never write
    `registry/graph/` directly (invariant #3).
12. **Every deployed tree node obeys the header taxonomy.** One H1 (node identity); the
    reserved H2 sections `## Navigation`, `## Workflows`, `## Tools`, `## Skills` in that
    order; connection sections headed `## <Name> (`key`)` with effort groups at `###`.
    `planner.lint_node_markdown` enforces it at plan time (fails `compile`/`deploy` on a
    violation). `SOUL.md` is the documented exception (all-H2 system prompt, not linted);
    the taxonomy is taught inside the tree by the operating root's `## Navigation`
    (`registry/context/agentic-root.md`), keeping SOUL lean. See
    `docs/agents-md-structure.md`.

## To change X, edit Y
| To change… | Edit… |
|---|---|
| A persona rule / your identity | `registry/identity/*.md` |
| Your name/email/location (personalization) | `registry/user.yaml` (core defaults) + `registry/local/user.yaml` (your overlay, gitignored) — a flat `given_name`/`full_name`/`email`/`location` mapping, field-level merged (`loader._load_user`, unknown keys rejected loudly). The single source of truth every deployed context file's placeholders expand from: `{{user_given_name}}`, `{{users_given_name}}` (possessive), `{{user_full_name}}`, `{{user_email}}`, `{{user_location}}` (`render.expand_placeholders`, applied by `planner._expand_output` to every text/zip output — never to `yaml_merge`/`json_merge` configs or env templates, which are machine wiring, not prose). `mitos init` seeds the overlay file from your answers (`init.scaffold_overlay`) |
| The concrete paths always-on prose names (`{{project_root}}`, `{{skills_root}}`) | the machine's `paths:` in `machines/<name>.yaml` — machine-scoped tokens expand per machine at plan time (`render.expand_placeholders` / `_machine_value`): `project_root` = `assistant_root` > `agentic_context_root` > `projects_root`; `skills_root` = `<hermes_home>/skills`; literal when unset. Reversal on adopt matches any machine's value. Used by `identity/session-protocol.md`, `identity/operating-rules.md`, and the `new-session` skill so the agent is told real directories (e.g. `~/MitosAgent`, `~/.hermes/skills`), not abstract key names |
| Whether a project-root AGENTS.md repeats the persona | nothing to edit — `planner._plan_agents_md` drops the `identity/*` sources from `project_agents` on machines that also deploy hermes (SOUL.md already carries the persona on every request); agents-md-only machines keep the full header |
| Which MCP connections a machine's assistant shows as available | the machine's `document_store:` in `machines/<name>.yaml` (same field/validation as a project's) — feeds the generated connection section (`render.connections_block`), headed `## <Name> (`key`)` (`render.connection_label`, the stable label skills reference), appended to the operating root and `Assistant/AGENTS.md`. Empty (no section) when unset — a machine never claims a connection it doesn't have |
| The header layout of any deployed tree node (`AGENTS.md`/`AGENTS_DETAILS.md`) | it's a contract, not free-form — one H1 identity, reserved `## Navigation`/`## Workflows`/`## Tools`/`## Skills` in order, `## <Name> (`key`)` connection sections with `###` efforts. Enforced by `planner.lint_node_markdown`; taught to the agent by the operating root's `## Navigation` (`registry/context/agentic-root.md`); documented in `docs/agents-md-structure.md`. Local paths go under `## Navigation`, store paths under the connection section (`planner._connection_emit` attaches the generated doc map beneath a curated connection section) |
| The general-skills catalog on the operating root | nothing to edit directly — `render.skills_block` generates a `## Skills` bullet per non-org-domain skill selected for this machine's Hermes deployment, sourced from each skill's frontmatter `description:` (the only place that text lives; mirrors `org_domain_table` for org-domain skills) |
| The Hermes org model (session protocol + routing + domain map) | session protocol: `registry/identity/session-protocol.md` (LEAN — always-on in `SOUL.md`, protocol + navigation facts only; keep it small, the pre-Mitos PoC showed less-is-more beats rule accretion). Per-task org routing: `registry/context/projects-index.md` (the deployed `Projects/AGENTS.md`, plus the generated org-domain table). Domain playbooks + C-suite in `registry/skills/org-software/`, `org-design/`, `org-marketing/` — all deployed to hermes. Routing is **per task, never per project**: a tagged effort's org line in the project's generated `AGENTS.md` names the skill; untagged work routes by the request's nature. There is no manifest `org:` field (the loader rejects one) |
| Which org governs an effort (the Work→Org edge) | the effort's `orgDomain` in `registry/graph/<slug>.jsonld` (`peccia:orgDomain` on a `CreativeWork` node — set via the console's effort editor `Org domain` select); validated against `loader.known_org_domains` (any skill with `org_domain:` frontmatter). Compiles to an org routing line under the effort's heading in the generated AGENTS files. This is the ONLY org edge in the graph — Organization nodes and document→role assignment were retired |
| Domain or project context | `registry/context/**/*.md` |
| A skill | `registry/skills/<name>/SKILL.md` |
| A skill's supporting files (example outputs, executable scripts, references) | the subdirectories in `loader._SKILL_RESOURCE_DIRS` — `registry/skills/<name>/examples/`, `scripts/`, `references/`, `templates/`, `resources/` (the union of the harnesses' documented conventions) — auto-discovered at load (`loader._load_skill_resources`), UTF-8 text only (v1; a binary file fails loudly). Deployed alongside `SKILL.md` on hermes/claude-code/antigravity (own per-file Outputs, inheriting the skill's drift policy) and bundled into claude-app zips (`Output.zip_members`). Each file's OWN path is its adopt/harvest source — an edited script routes back to itself, never `SKILL.md`. Console: the Skills & Orgs tab's Supporting Files panel (full-replacement-set semantics — see `docs/managing-state.md`) |
| Extend a C-suite role in an org skill (e.g. give `org-software`'s CTO a data-science lens) | a skill with `extends_skill: <parent>` + `extends_role: <role>` in its frontmatter — both required together, `<parent>` must exist, not itself be an extension (no chains), and contain the `## Extended C-suite Roles` anchor (`loader.validate_skill_extension`). Spliced into the parent's body **at render time only** (`render.compose_skill_body`) as a new `### <role> — <name> (extension)` subsection at the end of that section — the loaded parent `Skill.body` is never mutated, so the console/adopt/harvest keep reading true registry state. Never deploys standalone (`planner._selected_skills` filters it out). Console: a role card's `+ Extend department` button prefills the New Skill form |
| Which skills a tool receives | the skill's `targets:` frontmatter (compatibility) + optional `include:`/`exclude:` under `skills:` in `targets/<tool>.yaml` (curation); after deselecting, `deploy --prune` removes deployed copies |
| A skill's global vs. project scope | the skill's `scope: global \| project` frontmatter (default `global`, omit = global — `loader.validate_skill_scope`). `global`: deploys to every shared/global directory its `targets:` offer — hermes's skills dir, claude-app's account-wide zip staging, antigravity's `antigravity_skills` (`~/.gemini/config/skills/`, Agent Skills folders `<name>/SKILL.md`), claude-code's personal `claude_code_skills` (`~/.claude/skills/`). `project`: deploys ONLY to the projects naming it in their manifest `skills:` list, on whichever of claude-code/antigravity it targets (`<local_path>/.claude/skills/` and `<local_path>/.agents/skills/`) — never a global directory. hermes and claude-app have no project-scoped surface at all, so they ignore `scope` and stay global regardless (`PROJECT_SCOPE_CAPABLE_TARGETS`). Console: the Skills & Orgs tab's Scope section (Global/Project select + read-only bound-projects list; editing bindings still means editing the project manifest directly) |
| A prompt (harness-agnostic) | `registry/prompts/<name>.md` — frontmatter: `name`, `description`, `version`, `category`, `targets` (optional; omit = console-only). Deployed as plain body text to any target whose `targets/<tool>.yaml` has a `prompts:` block. Always available in the console Prompt Library regardless of `targets:`. |
| Which prompts a tool receives | the prompt's `targets:` frontmatter (omit = console-only); the target's `prompts:` block in `targets/<tool>.yaml` selects them. Today only `claude-code` deploys prompts (per-project manifest `prompts:` binding → `.claude/commands/<name>.md`). The former antigravity prompt lane is retired — Antigravity discovers only `<folder>/SKILL.md`, so discoverable content belongs in a skill. |
| Favorites in the Prompt Library | `registry/local/prompt-favorites.yaml` — toggle via the console UI or via `POST /api/prompts/favorite {"name": "<name>"}` |
| A Claude Code subagent | `registry/agents/<name>.md` (subagent frontmatter: `name`, `description`, optional `tools`/`model` + system-prompt body) — authored once, reused across projects |
| Which skills/agents a project's Claude Code checkout gets | `skills:`/`agents:` lists in `registry/projects/<slug>.yaml`; a bound skill must target `claude-code` or `antigravity` (the two targets with a project-scoped skill surface — `PROJECT_SCOPE_CAPABLE_TARGETS`). Deployed to `<checkout>/.claude/skills/` and `.claude/agents/` (and `.agents/skills/` if the skill also targets `antigravity`) |
| Auto-clone a project's repo | set the project's `repo:` in `registry/projects/<slug>.yaml` — either a single git URL string or a list of git URL strings. Each URL is cloned (clone-if-absent, non-destructive) into its own `<basename>/` subdirectory. On **workstation machines** (`claude-code` without `agents-md`), each clone lands at `<local_path>/<basename>/`. On **Hermes machines** (`agents-md` also in targets), at `<agentic_context_root>/Projects/<slug>/<basename>/`. Basenames within a project must be unique — two repos with the same name fail compile |
| Publish/refresh a skill in claude.ai (web/Desktop) | add `claude-app` to the skill's `targets:`; `deploy` stages `<name>.zip` at the machine's `claude_skills_staging` path; upload is MANUAL (Customize > Skills) — a `pending` zip means the account copy is stale |
| Wire a LAN/HTTP MCP server into Claude Desktop | set `claude_desktop_config` in the machine profile; run `deploy --lane connections` — `claude-app` writes an `npx mcp-remote` stdio bridge directly into `claude_desktop_config.json`. **Do not use the Desktop "Add custom connector" UI** (it rejects non-https URLs and has no knowledge of `servers.yaml`). Restart Desktop and the connector appears automatically. Requires Node.js/npx; bridge version pinned in `build/agentic/render.py` (`MCP_REMOTE_SPEC`). See `docs/targets/claude-app.md` |
| A Hermes config.yaml runtime setting (cwd, memory, toolsets, fallback chain, ...) | `targets/hermes.yaml`'s `settings:` block declares which paths Mitos owns (`owned_keys`) — a dotted LEAF path for a key living inside an otherwise Hermes/user-owned block (`terminal.cwd`, `agent.max_turns`, `platform_toolsets.cli`, ...), or a whole top-level key for a block dedicated entirely to this purpose (`fallback_providers`, `fallback_model`, `custom_providers` — same shape as the `mcp:` block, invariant #7). `render.hermes_settings_block` supplies values — `terminal.cwd` mirrors the machine's `paths.assistant_root` automatically, everything else comes from that machine's `hermes_settings:` (`registry/local/machines/<name>.yaml`, see `_HERMES_SETTINGS_LEAVES`/`_HERMES_SETTINGS_WHOLE_KEYS` in `render.py`). Reasserted on **every** deploy (a merge is never paused for drift review), so deliberately excludes `model.default`/`model.provider` — an interactive `/model` switch may persist back to `config.yaml`, and owning that leaf would fight normal daily use. Add a new leaf/key by listing it in `owned_keys` and adding it to the matching map in `render.py` |
| An MCP server (tools, env, default url) | `connections/servers.yaml` |
| A server's URL as seen from one machine | `urls:` map in `connections/servers.yaml` (per-machine overrides let a host reach a server running elsewhere, e.g. over LAN) |
| Where a merged env file lands | `<server>_env` path key in `machines/<name>.yaml` |
| A project's stage / store / repo | `registry/projects/<slug>.yaml` |
| A project's entry on the generated Project Roster (`Projects/AGENTS.md`) | `name:` + optional `description:` in `registry/projects/<slug>.yaml` — the roster is generated at plan time (`render.project_roster_block`, same pattern as the org-domain table) from exactly the projects deployed as `Projects/<name>/` folders in that tree; never hand-write a roster in `projects-index.md` |
| Which document store backs a project's graph init | `document_store: <server>` in `registry/projects/<slug>.yaml` (a server from `connections/servers.yaml`, or `none`). Resolved by `connector_for_store` at Stage 3 — `none`/unset falls back to the **local-file connector** (no credentials needed; maps files from the project's local directory). A store with a `graph_enum:` mapping uses the generic `mcp` connector (reuse a running server, no second OAuth). Scaffold a project with `python build/mitos.py project add <slug>` |
| How a document store is enumerated for the graph | `graph_enum:` on the server in `connections/servers.yaml` (`list_tool`, `query_syntax`, optional `query_arg`/`folder_tool`, and a `fields:` map onto `{id, name, dateModified, webUrl, type}` — `type` optional, the store's MIME/kind field). The `mcp` connector stays generic; `query_syntax: google-drive` activates Drive-specific query construction; any other store uses the generic path (scope passed verbatim) |
| A document's store-agnostic link (the `url` field) | `web_url` on `Document` in `build/agentic/graph.py`, serialized as `schema:url` in the JSON-LD. The connector-provided URL is stored as-is (e.g. `file://`, `https://notion.so/…`). For Drive documents without an explicit URL, `drive_url` falls back to `https://drive.google.com/open?id=<id>` so existing graphs keep working |
| A project's document map (knowledge graph) | `registry/graph/<slug>.jsonld` — lean schema.org JSON-LD (`schema:Project` + `schema:DigitalDocument`, IRIs under `http://peccia.net/`); inspect/query with `python build/compile.py graph --project <slug>`. See the knowledge-graph recipe in the README |
| A document's kind annotation (the tool-selection hint) | `additionalType` on the `DigitalDocument` node (`doc_type` on `graph.Document`) — optional, friendly form (`spreadsheet`, `document`, `pdf`); captured at enumeration from the store's MIME type (`connectors.base.friendly_doc_type`, `graph_enum.fields.type`) and rendered as `(… · <type>)` in the shared doc line (`graph._concise_entry` — identical in claude-code AGENTS.md and hermes AGENTS_DETAILS.md). Omit-when-absent; older graphs render unchanged |
| Propose a project's document mappings | the operator console's **Knowledge Graph** tab, or `mitos connect --project <slug>` — both land a `kind: graph` inbox candidate that accept upserts into `registry/graph/`. Nothing writes the graph directly (invariant #3) |
| Where a workstation's project AGENTS.md + CLAUDE.md deploys | `local_path.<machine>` in the project manifest — activated automatically when the machine has `claude-code` but **not** `agents-md`. Each project with a knowledge graph gets `<local_path>/AGENTS.md` (prose `protect` + full inline doc block generated) and `<local_path>/CLAUDE.md` (@AGENTS.md stub). The prose partial is read from `context.assistant` under the `agents-md` audience — no frontmatter change needed. Projects without a graph get only CLAUDE.md (existing behaviour). |
| Where the reference mount (agentic-graph) deploys | `agentic_context_root` under `paths:` in `machines/<name>.yaml` — gated on `claude-code` in targets alone (`planner._plan_graph_tree`); `agents-md`/`hermes` are irrelevant to it. A roster + per-project lightweight titles-only doc index generated straight from `registry/graph/`, `drift_policy: generated` — never an editing surface, silently overwritten every deploy. Full per-document detail lives in a companion `AGENTS_DETAILS.md`. Distinct from the operating mount below — see that row for the edit-semantics contrast. |
| Mount the full operating tree inside one project (agentic_tree) | `agentic_tree: <subdir>` in `registry/projects/<slug>.yaml` — the workstation-side counterpart to `assistant_root`. Renders the SAME tree `_emit_tree` (`planner.py`) produces for a Hermes machine — full Navigation/Workflows/Skills, roster, dynamic branches — at `<local_path>/<subdir>/` instead of a machine root, so e.g. Antigravity can operate against one project like an agentic harness. `drift_policy: protect`: unlike the reference mount above, edits here become drift and reconcile back into the registry via `adopt`. Workstation-only (a no-op on an agentic/`hermes` machine, which already hosts the tree at its machine root); validated at load time (single subdirectory name, no collision with a repo checkout basename in the same project) |
| Add a custom branch to an operating tree (e.g. `family/`) | drop an `AGENTS.md` under `registry/context/<branch>/` — any sibling file in that folder deploys alongside it to `<mount-root>/<branch>/…`, whether the mount is a machine's `assistant_root` or a project's `agentic_tree`. Auto-discovered at plan time (`planner._emit_tree`, keyed off the existing `context/` partial scan — no loader change needed) and listed in a `<generated>` section on the root `AGENTS.md`. The only way to extend the tree without forking `targets/agents-md.yaml`, which is **not** overlayable. Branch names may not collide with a reserved top-level entry (`Projects`, `Assistant`) — rejected loudly at plan time |
| Where projects live on a machine (C:\ vs D:\) | `projects_root` under `paths:` in `machines/<name>.yaml` — manifests' `local_path` entries are dir names relative to it (absolute and `~` paths pass through) |
| What a tool emits or where it deploys | `targets/<tool>.yaml` |
| Which targets land on a machine | `machines/<name>.yaml` |
| Whether a machine may run an agentic harness alongside coding harnesses | it may not — `hermes` in a machine's `targets` excludes `antigravity`/`claude-app`/`claude-code` on that same machine, rejected loudly at compile (`loader._validate`). An agentic machine is dedicated to that purpose; a workstation wanting agentic-tree behavior for one project uses `agentic_tree:` above instead of adding `hermes`. `agents-md` itself is exempt — it's the context format both roles consume, not a harness |
| Add a brand-new tool | new `targets/<tool>.yaml` (the output/deploy spec); add a render extension in `build/agentic/render.py` only if the tool needs a format the existing renderers don't cover. There is no `build/templates/` — outputs are raw section concatenation, not `.j2` templates |
| Personalize without forking (the open-source overlay) | put private content under `registry/local/` (gitignored); it overrides the core by **last-layer-wins** — same logical name replaces, new names add, core-only remain. Absent overlay = the public default |
| An org template (routing preference starter) | `registry/templates/org/<name>/` (one `session-protocol.md` seed — the core session protocol plus that template's routing preference); `python build/mitos.py init` copies it into `registry/local/identity/`, overriding the core `session-protocol.md`. Domain skills ship in core — templates no longer seed per-org playbooks. See `docs/org-templates.md` |
| Add a workspace connector backend | `build/agentic/connectors/<name>.py` subclassing `WorkspaceConnector` + register it in `connectors/base.py`; backend deps lazy-imported. It emits `kind: graph` candidates via `bootstrap_to_inbox` — never the graph directly, never from the compiler. For a store that already runs an MCP server, prefer describing it with a `graph_enum:` mapping and reusing the generic `mcp` connector (no new backend). The built-in backends: `local` (local filesystem, the default when no `document_store` set), `mcp` (any MCP server with `graph_enum`), `mock` (tests/demos) |
| Scaffold a new user / connect a workspace | `python build/mitos.py init` (overlay wizard — three paths: scaffold fresh, pull an existing overlay from a hub via `git_clone`, or use files already in `registry/local/`; **non-destructive** — `scaffold_overlay` never clobbers existing files, `overwrite=True` to force) — a **separate** interactive entrypoint, never `compile.py` |
| Build a project's knowledge graph (the three stages) | **Stage 1** `mitos project add <slug>` scaffolds the manifest + optional `document_store` binding (offline); **Stage 2** set up the document MCP server *separately* if needed (never in `init` — see `docs/connectors/`); **Stage 3** `mitos connect --project <slug>` resolves the connector from `document_store` (defaults to the local-file connector when unset), enumerates a scoped folder, and proposes a `kind: graph` candidate. All three are separate, optional, and beside the compiler |
| How a machine syncs its private overlay across hosts | `mitos sync` keeps `registry/local/` as a git repo synced to a hub (`sync.git.hub` in `machines/<name>.yaml` — any git URL, self-hosted or a private GitHub repo). Set it up once with `sync --machine <name> init --hub <url> [--ssh-key <path>]` (first machine) / `clone --hub <url>` (the rest) — both install a post-merge auto-deploy hook, record `mitos.machine`, and pin a chosen ssh key as the overlay's `core.sshCommand` (also settable via `sync.git.ssh_key`). Day-to-day each peer runs `sync --machine <name>`: pull --rebase → deploy → push, stop-on-conflict (`status` reports ahead/behind). Sync is **git-only** — no rsync/ssh/s3 transports. The flow + setup verbs are `build/agentic/sync/git.py`. See `docs/lan-sync.md` |
| Review inbox candidates / copy one-shot prompts / edit the graph | `python build/compile.py review` — the operator console (localhost), four tabs: **Inbox** (accept routes prose into the registry, or upserts a `kind: graph`/`kind: new` candidate into `registry/graph/` or `registry/local/`; appends to `registry/local/inbox/decisions.jsonl`), **Knowledge Graph** (propose document mappings per project; tag efforts with an `Org domain`), **Skills & Orgs** (card grid — edit or create skills, including supporting files and `extends_skill`/`extends_role`; an org-domain card's expanded body embeds its read-only role-tree + Agent-MD folder visualization, a `+ Extend department` button per role, and `+ ORG` to propose a new domain skill — there is no separate Org tab), and **Prompt Library** (all registry prose for copy/compose into chat apps, plus a Ctrl/⌘K command palette across all of it). It edits the working tree, never commits. |
| Create a new skill via the console | The Skills & Orgs tab's **+ New skill** form (optionally prefilled with `extends_skill`/`extends_role` via a role card's **+ Extend department**) → `propose_new_skill()` in `build/agentic/review.py` → `POST /api/skills/new` → a `kind: new` inbox candidate carrying optional `resources` (Supporting Files) → Accept writes `registry/local/skills/<name>/SKILL.md` (+ its resource subdirectories) verbatim (always the overlay, never core) |

## Managing state (the core workflow)
Deploy materializes the registry; drift detection + reconciliation is the heart of the
project. The three-way compare (render vs lockfile `source_hash` vs disk `deployed_hash`),
every plan state (`create`/`unchanged`/`pending`/`drift`/`conflict`/`resolved`/`merge`/
`orphan`/`clone`), the three drift policies (`protect`/`harvest`/`generated`), capture-to-
inbox-before-overwrite, and the reconciliation verbs (`diff`/`adopt`/`harvest`/`review`/
`--force`/`--prune`) are documented end-to-end in `docs/managing-state.md` — keep that page
in sync when you change `build/agentic/commands.py` or a target's `drift_policy`.

A personalized partial (one whose body contains a `{{user_*}}` placeholder) is deployed in
EXPANDED form, so `commands.route_into_registry` and `review._stale()` fold recorded/live
text back through that partial's own placeholder tokens (`render.reverse_expand_placeholders`
— scoped exact-inverse, longest expanded value first) BEFORE comparing against the
registry's placeholder-form body. This runs ahead of the change/staleness check itself, not
inside `_rewrite_registry_body` — comparing expanded text directly against a
placeholder-bearing body would report a phantom change on every adopt/review of a
personalized file and bake real values into the registry. See `render.py`'s "User
placeholders" section and `build/tests/test_personalization.py`.

## Verifying changes
1. `python build/compile.py compile` — schema validation is the first test; it must
   pass with no unknown-partial or missing-field errors.
2. Run the compiler test suite: `pytest build/tests/` (per-area files: `test_graph.py`,
   `test_connectors.py`, `test_commands.py`, `test_loader.py`, `test_targets.py`,
   `test_review.py`, `test_compiler.py`, `test_personalization.py` (user.yaml,
   `{{user_*}}` expansion/reversal, the generated Connections/Skills sections); shared
   helpers in `conftest.py`).
3. `python build/compile.py deploy --machine <m> --dry-run` — read the action list
   before any real deploy.

## Contribution rule
A new verb, target, or schema field lands **together with** its schema validation, its
README section, and an acceptance test — or not at all.
