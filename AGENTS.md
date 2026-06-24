## About Me

You are a personal assistant, focusing on truth, clarity, and usefulness rather than on mere politeness.

**Facts:**
- Email: `user@example.com`
- Location: Your City, State

## How to work

- **Plan if required** - if the request requires more than a one-step answer, use the `plan` skill
- Always read `AGENTS.md` within *project root* and each sub-directory as you navigate
- Write things down - use structured planning before acting on complex requests

# Mitos — Builder Context

You are working on the **Mitos** repo itself: the registry and compiler that materialize an
agent organization across tools. Mitos manages itself — this file is authored at
`registry/context/projects/mitos.md` and compiled into the root `AGENTS.md`. **Read
[`README.md`](README.md) for the architecture and workflows before making structural changes.**

## What this repo is
- `registry/` is the **moat**: the single, canonical home for all content — personas
  (`identity/`), domain/project context (`context/`), skills (`skills/`), agents
  (`agents/`, Claude Code subagents), the knowledge graph (`graph/`, schema.org JSON-LD),
  project manifests (`projects/`), and org seed templates (`templates/`). `registry/local/`
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
3. **Never write into `registry/` to propose a change — propose into `inbox/`.**
   `inbox/` is the intake queue: one folder per candidate (payload snapshot +
   `meta.yaml` with `registry_path`, `kind: drift|new|report`, `source`, `base_hash`).
   `deploy` captures overwritten drift there automatically; agents proposing new
   content or work reports write candidates there by hand. See `inbox/README.md`.
   Only the maintainer merges candidates into the registry.
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
   so `dist/` and `inbox/` never contain secret values.
7. **Tool-owned config files get surgical merges, never whole-file overwrites.**
   Hermes `config.yaml` (`yaml_merge`, owns `mcp_servers`) and Gemini `config.json`
   (`json_merge`, owns only its alias's `mcp(...)` entries inside the allow list) are
   the patterns to copy for any new tool that keeps its own config file.
8. **Deploys are machine-guarded.** `deploy` refuses when the host OS doesn't match
   the machine profile's `os:`; rehearse cross-machine deploys with `--root <dir>`
   (files, lockfile, and inbox land in the sandbox).
9. **Deletion is explicit, never a side effect.** `deploy` removes nothing on its
   own: outputs no longer planned (a deselected skill, a retired project) become
   *orphans* — reported on every deploy, kept on disk and in the lockfile — until
   `deploy --prune` deletes them. A drifted orphan is captured to `inbox/` before
   deletion.
10. **Boring beats clever.** No frameworks, brokers, or chains until a concrete,
    recurring pain forces one. Weigh any new dependency or abstraction against that bar
    before proposing infrastructure.
11. **The Mitos connector lives beside the compiler, never inside it.** Workspace reach
    (connectors, OAuth, the interactive `init` wizard) is a *separate* entrypoint
    (`build/mitos.py`) with lazy, optional backend deps; the deterministic verbs stay
    offline and import no network/credential code. Connectors are producers for the *one*
    `kind: graph` valve — they never write `registry/graph/` directly (invariant #3).

## To change X, edit Y
| To change… | Edit… |
|---|---|
| A persona rule / your identity | `registry/identity/*.md` |
| The Hermes org model (CEO/VP-Eng/Assistant) | `registry/identity/org-hierarchy.md` (lean, always-on in `SOUL.md`) + `registry/skills/org/SKILL.md` (on-demand playbook). Distinct from the upstream `dept-*` Gemini refinement personas |
| Domain or project context | `registry/context/**/*.md` |
| A skill | `registry/skills/<name>/SKILL.md` |
| Which skills a tool receives | the skill's `targets:` frontmatter (compatibility) + optional `include:`/`exclude:` under `skills:` in `targets/<tool>.yaml` (curation); after deselecting, `deploy --prune` removes deployed copies |
| A Claude Code subagent | `registry/agents/<name>.md` (subagent frontmatter: `name`, `description`, optional `tools`/`model` + system-prompt body) — authored once, reused across projects |
| Which skills/agents a project's Claude Code checkout gets | `skills:`/`agents:` lists in `registry/projects/<slug>.yaml`; a bound skill must also target `claude-code`. Deployed to `<checkout>/.claude/skills/` and `.claude/agents/` |
| Auto-clone a project's repo into the Agentic Context tree | set the project's `repo:` in `registry/projects/<slug>.yaml`; on Claude Code deploys it is cloned (clone-if-absent, non-destructive) into `<agentic_context_root>/Projects/<slug>/` |
| Publish/refresh a skill in claude.ai (web/Desktop) | add `claude-ai` to the skill's `targets:`; `deploy` stages `<name>.zip` at the machine's `claude_ai_staging` path; upload is MANUAL (Customize > Skills) — a `pending` zip means the account copy is stale |
| An MCP server (tools, env, default url) | `connections/servers.yaml` |
| A server's URL as seen from one machine | `urls:` map in `connections/servers.yaml` (per-machine overrides let a host reach a server running elsewhere, e.g. over LAN) |
| Where a merged env file lands | `<server>_env` path key in `machines/<name>.yaml` |
| A project's stage / Drive IDs / repo | `registry/projects/<slug>.yaml` |
| A project's document map (knowledge graph) | `registry/graph/<slug>.jsonld` — lean schema.org JSON-LD (`schema:Project` + `schema:DigitalDocument`, IRIs under `http://peccia.net/`); inspect/query with `python build/compile.py graph --project <slug>`. See the knowledge-graph recipe in the README |
| Propose a project's document mappings | message Hermes "bootstrap the graph for `<project>`" (the `graph-bootstrap` skill enumerates its Drive folder via `gws`), or the operator console's **Knowledge Graph** tab — both land a `kind: graph` inbox candidate that accept upserts into `registry/graph/`. Nothing writes the graph directly (invariant #3) |
| Where the Agentic Context tree deploys (graph-derived AGENTS.md roster + `Projects/<slug>/` indexes) | `agentic_context_root` under `paths:` in `machines/<name>.yaml` — emitted only on Claude Code environments |
| Where projects live on a machine (C:\ vs D:\) | `projects_root` under `paths:` in `machines/<name>.yaml` — manifests' `local_path` entries are dir names relative to it (absolute and `~` paths pass through) |
| What a tool emits or where it deploys | `targets/<tool>.yaml` (+ template) |
| Which targets land on a machine | `machines/<name>.yaml` |
| Add a brand-new tool | new `targets/<tool>.yaml` + `build/templates/<tool>/…` |
| Personalize without forking (the open-source overlay) | put private content under `registry/local/` (gitignored); it overrides the core by **last-layer-wins** — same logical name replaces, new names add, core-only remain. Absent overlay = the public default |
| An org template (the selectable C-suite) | `registry/templates/org/<name>/` (an `org-hierarchy.md` identity seed + `org-skill.md` playbook); `python build/mitos.py init` copies the chosen one into the overlay, overriding the core org. These templates are the selectable default org model |
| Add a workspace connector backend | `build/agentic/connectors/<name>.py` subclassing `WorkspaceConnector` + register it in `connectors/base.py`; backend deps lazy-imported. It emits `kind: graph` candidates via `bootstrap_to_inbox` — never the graph directly, never from the compiler |
| Scaffold a new user / connect a workspace | `python build/mitos.py init` (overlay wizard) / `mitos connect --project <slug>` (connector → inbox candidate) — a **separate** interactive entrypoint, never `compile.py` |
| Review inbox candidates / copy one-shot prompts / edit the graph | `python build/compile.py review` — the operator console (localhost), three tabs: **Inbox** (accept routes prose into the registry, or upserts a `kind: graph` candidate into `registry/graph/`; appends to `inbox/decisions.jsonl`), **Knowledge Graph** (propose document mappings per project), and **Prompt Library** (all registry prose for copy/compose into chat apps). It edits the working tree, never commits. |

## Verifying changes
1. `python build/compile.py compile` — schema validation is the first test; it must
   pass with no unknown-partial or missing-field errors.
2. Run the compiler test suite.
3. `python build/compile.py deploy --machine <m> --dry-run` — read the action list
   before any real deploy.

## Contribution rule
A new verb, target, or schema field lands **together with** its schema validation, its
README section, and an acceptance test — or not at all.
