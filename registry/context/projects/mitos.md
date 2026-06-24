---
audience: [claude-code, agents-md]
---
# Mitos — Builder Context

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
   content or work reports write candidates there by hand. See `registry/local/inbox/README.md`.
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
   Hermes `config.yaml` (`yaml_merge`, owns `mcp_servers`) and Gemini `config.json`
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

## To change X, edit Y
| To change… | Edit… |
|---|---|
| A persona rule / your identity | `registry/identity/*.md` |
| The Hermes org model (CEO/VP-Eng/Assistant) | `registry/identity/org-hierarchy.md` (lean, always-on in `SOUL.md`) + `registry/skills/org/SKILL.md` (on-demand playbook). Distinct from the upstream `dept-*` Gemini refinement personas |
| Domain or project context | `registry/context/**/*.md` |
| A skill | `registry/skills/<name>/SKILL.md` |
| Which skills a tool receives | the skill's `targets:` frontmatter (compatibility) + optional `include:`/`exclude:` under `skills:` in `targets/<tool>.yaml` (curation); after deselecting, `deploy --prune` removes deployed copies |
| A prompt (harness-agnostic) | `registry/prompts/<name>.md` — frontmatter: `name`, `description`, `version`, `category`, `targets` (optional; omit = console-only). Deployed as plain body text to any target whose `targets/<tool>.yaml` has a `prompts:` block. Always available in the console Prompt Library regardless of `targets:`. |
| Which prompts a tool receives | the prompt's `targets:` frontmatter (omit = console-only); the target's `prompts:` block in `targets/<tool>.yaml` selects them. Today only `gemini` deploys prompts (to `gemini_prompts/prompt-<name>.md`). |
| Favorites in the Prompt Library | `registry/local/prompt-favorites.yaml` — toggle via the console UI or via `POST /api/prompts/favorite {"name": "<name>"}` |
| A Claude Code subagent | `registry/agents/<name>.md` (subagent frontmatter: `name`, `description`, optional `tools`/`model` + system-prompt body) — authored once, reused across projects |
| Which skills/agents a project's Claude Code checkout gets | `skills:`/`agents:` lists in `registry/projects/<slug>.yaml`; a bound skill must also target `claude-code`. Deployed to `<checkout>/.claude/skills/` and `.claude/agents/` |
| Auto-clone a project's repo into the Agentic Context tree | set the project's `repo:` in `registry/projects/<slug>.yaml`; on Claude Code deploys it is cloned (clone-if-absent, non-destructive) into `<agentic_context_root>/Projects/<slug>/` |
| Publish/refresh a skill in claude.ai (web/Desktop) | add `claude-ai` to the skill's `targets:`; `deploy` stages `<name>.zip` at the machine's `claude_ai_staging` path; upload is MANUAL (Customize > Skills) — a `pending` zip means the account copy is stale |
| An MCP server (tools, env, default url) | `connections/servers.yaml` |
| A server's URL as seen from one machine | `urls:` map in `connections/servers.yaml` (per-machine overrides let a host reach a server running elsewhere, e.g. over LAN) |
| Where a merged env file lands | `<server>_env` path key in `machines/<name>.yaml` |
| A project's stage / Drive IDs / repo | `registry/projects/<slug>.yaml` |
| Which document store backs a project's graph init | `document_store: <server>` in `registry/projects/<slug>.yaml` (a server from `connections/servers.yaml`, or `none`). Resolved by `connector_for_store` at Stage 3 — a store with a `graph_enum:` mapping uses the generic `mcp` connector (reuse a running server, no second OAuth), one without falls back to a direct backend (`gws` OAuth). Scaffold a project with `python build/mitos.py project add <slug>` |
| How a document MCP server is enumerated for the graph | `graph_enum:` on the server in `connections/servers.yaml` (`list_tool`, optional `query_arg`/`folder_tool`, and a `fields:` map onto `{id, name, dateModified, webUrl}`). The `mcp` connector stays generic; each server describes itself |
| A project's document map (knowledge graph) | `registry/graph/<slug>.jsonld` — lean schema.org JSON-LD (`schema:Project` + `schema:DigitalDocument`, IRIs under `http://peccia.net/`); inspect/query with `python build/compile.py graph --project <slug>`. See the knowledge-graph recipe in the README |
| Propose a project's document mappings | message Hermes "bootstrap the graph for `<project>`" (the `graph-bootstrap` skill enumerates its Drive folder via `gws`), or the operator console's **Knowledge Graph** tab — both land a `kind: graph` inbox candidate that accept upserts into `registry/graph/`. Nothing writes the graph directly (invariant #3) |
| Where the Agentic Context tree deploys (graph-derived AGENTS.md roster + `Projects/<slug>/` indexes) | `agentic_context_root` under `paths:` in `machines/<name>.yaml` — emitted only on Claude Code environments |
| Where projects live on a machine (C:\ vs D:\) | `projects_root` under `paths:` in `machines/<name>.yaml` — manifests' `local_path` entries are dir names relative to it (absolute and `~` paths pass through) |
| What a tool emits or where it deploys | `targets/<tool>.yaml` |
| Which targets land on a machine | `machines/<name>.yaml` |
| Add a brand-new tool | new `targets/<tool>.yaml` (the output/deploy spec); add a render extension in `build/agentic/render.py` only if the tool needs a format the existing renderers don't cover. There is no `build/templates/` — outputs are raw section concatenation, not `.j2` templates |
| Personalize without forking (the open-source overlay) | put private content under `registry/local/` (gitignored); it overrides the core by **last-layer-wins** — same logical name replaces, new names add, core-only remain. Absent overlay = the public default |
| An org template (the selectable C-suite) | `registry/templates/org/<name>/` (an `org-hierarchy.md` identity seed + `org-skill.md` playbook); `python build/mitos.py init` copies the chosen one into the overlay, overriding the core org. These templates are the selectable default org model |
| Add a workspace connector backend | `build/agentic/connectors/<name>.py` subclassing `WorkspaceConnector` + register it in `connectors/base.py`; backend deps lazy-imported. It emits `kind: graph` candidates via `bootstrap_to_inbox` — never the graph directly, never from the compiler. For a store that already runs an MCP server, prefer describing it with a `graph_enum:` mapping and reusing the generic `mcp` connector (no new backend) |
| Scaffold a new user / connect a workspace | `python build/mitos.py init` (overlay wizard — three paths: scaffold fresh, pull an existing overlay from a hub via `git_clone`, or use files already in `registry/local/`; **non-destructive** — `scaffold_overlay` never clobbers existing files, `overwrite=True` to force) — a **separate** interactive entrypoint, never `compile.py` |
| Build a project's knowledge graph (the three stages) | **Stage 1** `mitos project add <slug>` scaffolds the manifest + `document_store` binding (offline); **Stage 2** set up the document MCP server *separately* (never in `init` — see `docs/connectors/`); **Stage 3** `mitos connect --project <slug>` resolves the connector from `document_store`, enumerates a scoped folder (interactive picker on a tty), and proposes a `kind: graph` candidate. All three are separate, optional, and beside the compiler |
| How a machine syncs its private overlay across hosts | `mitos sync` keeps `registry/local/` as a git repo synced to a hub (`sync.git.hub` in `machines/<name>.yaml` — any git URL, self-hosted or a private GitHub repo). Set it up once with `sync --machine <name> init --hub <url> [--ssh-key <path>]` (first machine) / `clone --hub <url>` (the rest) — both install a post-merge auto-deploy hook, record `mitos.machine`, and pin a chosen ssh key as the overlay's `core.sshCommand` (also settable via `sync.git.ssh_key`). Day-to-day each peer runs `sync --machine <name>`: pull --rebase → deploy → push, stop-on-conflict (`status` reports ahead/behind). Sync is **git-only** — no rsync/ssh/s3 transports. The flow + setup verbs are `build/agentic/sync/git.py`. See `docs/lan-sync.md` |
| Review inbox candidates / copy one-shot prompts / edit the graph | `python build/compile.py review` — the operator console (localhost), three tabs: **Inbox** (accept routes prose into the registry, or upserts a `kind: graph` candidate into `registry/graph/`; appends to `registry/local/inbox/decisions.jsonl`), **Knowledge Graph** (propose document mappings per project), and **Prompt Library** (all registry prose for copy/compose into chat apps). It edits the working tree, never commits. |

## Managing state (the core workflow)
Deploy materializes the registry; drift detection + reconciliation is the heart of the
project. The three-way compare (render vs lockfile `source_hash` vs disk `deployed_hash`),
every plan state (`create`/`unchanged`/`pending`/`drift`/`conflict`/`resolved`/`merge`/
`orphan`/`clone`), the three drift policies (`protect`/`harvest`/`generated`), capture-to-
inbox-before-overwrite, and the reconciliation verbs (`diff`/`adopt`/`harvest`/`review`/
`--force`/`--prune`) are documented end-to-end in `docs/managing-state.md` — keep that page
in sync when you change `build/agentic/commands.py` or a target's `drift_policy`.

## Verifying changes
1. `python build/compile.py compile` — schema validation is the first test; it must
   pass with no unknown-partial or missing-field errors.
2. Run the compiler test suite.
3. `python build/compile.py deploy --machine <m> --dry-run` — read the action list
   before any real deploy.

## Contribution rule
A new verb, target, or schema field lands **together with** its schema validation, its
README section, and an acceptance test — or not at all.
