# The Mitos 'local' repo

Your private context lives in **`registry/local/`** — the gitignored *overlay* that overrides the
public core by last-layer-wins. When you sync across machines (see
[`lan-sync.md`](../docs/lan-sync.md)), that directory becomes its **own git repository** — the one you host
as `mitos-local.git`. This document is the map of what that repo holds.

> **The repo root *is* the overlay directory.** `git init` runs *inside* `registry/local/`, so the
> `.git/` folder lives there and the tracked files sit at the top level — `identity/`, `skills/`,
> and friends. There is **no extra `local/` wrapper** on the hub; when another machine clones it,
> the files land directly in *its* `registry/local/`.

## Layout

The overlay mirrors the public core's layout (`registry/<same subdirs>`) on purpose: a file at
`identity/who-i-am.md` in your overlay **replaces** the core file at the same path. Same name →
replace; new name → add; untouched core file → remains.

```
registry/local/              ← repo root  (.git lives HERE, not at the project root)
├── .git/
│   └── hooks/post-merge     ← auto-deploys THIS machine after a pull brings new content
├── README.md                ← "private overlay" marker — NOT content (the loader skips it)
│
├── identity/                ← who you are; overrides core personas by filename
│   ├── who-i-am.md          ← from `mitos init` (your name + how to be addressed)
│   └── org-hierarchy.md     ← from your chosen org template
├── context/                 ← your domain / project prose (background the agents read)
│   └── projects/<slug>.md
├── skills/                  ← your private or overriding skills
│   └── org/SKILL.md
├── agents/                  ← your Claude Code subagents
│   └── <name>.md
├── prompts/                 ← harness-agnostic reusable prompts
│   └── <name>.md
├── projects/                ← project manifests (stage, repo, document_store)
│   └── <slug>.yaml
├── graph/                   ← knowledge-graph document maps (schema.org JSON-LD)
│   └── <slug>.jsonld
├── machines/                ← per-host profiles — incl. each host's `sync:` block
│   ├── windows-main.yaml
│   └── linux-box.yaml
└── connections/             ← MCP server overrides (e.g. LAN URLs seen from one host)
    └── servers.yaml
```

## What each folder is for

| Folder | Holds | Overrides the core by… |
|---|---|---|
| `identity/` | Personas and your "about me" — name, form of address, org hierarchy | filename (e.g. `who-i-am.md`, `org-hierarchy.md`) |
| `context/` | Domain and project background prose the agents read | partial path |
| `skills/<name>/SKILL.md` | Your own skills, or overrides of a core skill | skill name |
| `agents/<name>.md` | Claude Code subagents (frontmatter + system prompt) | agent name |
| `prompts/<name>.md` | Harness-agnostic reusable prompts (the substrate every harness understands) | prompt name |
| `projects/<slug>.yaml` | Project manifests — stage, repo, document_store, bound skills/agents | project slug |
| `graph/<slug>.jsonld` | Per-project document maps (where each authoritative doc lives) | project slug |
| `machines/<name>.yaml` | Per-host profiles: targets, path keys, and the `sync:` block | machine `name` |
| `connections/servers.yaml` | MCP server overrides (e.g. a server reachable over your LAN) | server key |

`README.md` at the root is a marker, not content — `mitos init` writes it so the directory
announces itself as private, and the loader deliberately ignores it.

## Config-file reference

Most overlay files are **config + prose** — a skill, an agent, an identity persona, a context
partial: a little YAML frontmatter on top of a Markdown body. Those are self-explanatory once you
see one. The files below are different: they are **pure structured config** with several fields
that drive real behaviour (where projects check out, which tools deploy where, how a server is
reached). This section is the field-by-field map for those three. Every rule here is enforced by
the loader at compile time — an unknown machine name, a bad stage, a dangling skill reference is a
hard error, not a warning, so a malformed overlay never deploys silently.

### Project manifest — `projects/<slug>.yaml`

One file per project. It is the spine that ties a project's prose, repo, document store, per-machine
checkout, and bound capabilities together. The `mitos` slug below is the live self-manifest;
[`registry/projects/example-project.yaml`](../registry/projects/example-project.yaml) shows every
field at once.

```yaml
name: Acme Redesign           # display name (shown in rosters / the operator console)
slug: acme-redesign           # unique key — keep it == the filename stem
stage: build                  # ideation | speccing | build | maintain
repo: "git@github.com:you/acme.git"   # optional; a single URL or a list of URLs — each cloned
# into its own <basename>/ dir (clone-if-absent). List example:
# repo:
#   - "git@github.com:you/frontend.git"
#   - "git@github.com:you/backend.git"
# Basenames within a project must be unique — two repos with the same name fail compile.
document_store: gws           # optional; an MCP server from connections/servers.yaml, or `none`
local_path:
  windows-main: acme          # per-machine checkout dir (relative → under that machine's projects_root)
  linux-box: ~/code/acme      # absolute (~, /, or D:/…) passes through unchanged
exclude_folders:              # optional; folder names or IDs to skip during `mitos connect` staging
  - Archive
skills: [plan]                # optional; each skill must exist AND target claude-code
agents: [code-reviewer]       # optional; each agent must exist in registry/agents/
context:                      # label → registry-relative partial (must resolve to a real file)
  assistant: registry/context/projects/acme-redesign.md
```

| Field | Required | What it does / how it's validated |
|---|---|---|
| `slug` | **yes** | Unique identity of the project; keys the manifest, the knowledge graph (`graph/<slug>.jsonld`), and `local_path`. Duplicate slugs are refused. |
| `name` | recommended | Human-readable label used in rosters and the console. |
| `example` | no | Set `true` on shipped sample projects (e.g. `example-project.yaml`). Example projects step aside automatically once you add your own overlay projects. Must be a boolean if set. |
| `stage` | **yes** | Lifecycle phase — must be exactly one of `ideation`, `speccing`, `build`, `maintain`. Anything else aborts compile. |
| `repo` | no | Git URL. How it clones depends on the machine's targets: on **workstation machines** (`claude-code` without `agents-md`), the repo is **cloned if absent** (non-destructive) into `<local_path>/<basename>` — co-located with the project's workspace folder. On **Hermes machines** (`agents-md` also in targets), it clones into `<agentic_context_root>/Projects/<slug>/<basename>` instead. |
| `document_store` | no | Binds the project to the MCP server that backs knowledge-graph init (`mitos connect`). Must name a server in `connections/servers.yaml`, or the literal `none`. An unknown name is refused. |
| `local_path` | no | Map of **machine name → checkout directory**. Each key must be a machine the loader knows. A *relative* value resolves under that machine's `projects_root`; a value starting `~`, `/`, or a drive letter (`D:/…`) is taken as-is. This is how one manifest stays correct on a C:\ box and a D:\ box at once. |
| `exclude_folders` | no | List of folder **names or IDs** to skip during `mitos connect` staging. Merged with any `exclude_folders` defined on the server in `connections/servers.yaml` (server entries first, then project entries, deduped). |
| `skills` | no | Skills bound to *this project's* Claude Code checkout (deployed to `<checkout>/.claude/skills/`). Each must exist **and** list `claude-code` in its own `targets:` — the manifest decides *which projects*, the skill decides *which tools*. |
| `agents` | no | Subagents bound to this project's checkout (`.claude/agents/`). Each must exist in `registry/agents/`. |
| `context` | no | Map of **label → partial path** (under `registry/…`). Each must resolve to a real partial; a dangling reference aborts compile. These prose files are what the agents actually read for the project. |

> **Overriding a core project.** Drop a file with the same `slug` into `registry/local/projects/` and
> it replaces the core manifest wholesale (last-layer-wins) — useful for pointing a public example
> project at your own repo without editing tracked files.

### Machine profile — `machines/<name>.yaml`

One file per host. It answers three questions: *what is this box* (`os`), *what gets deployed here*
(`targets`), and *where do things live* (`paths`) — plus an optional `sync` block describing how the
overlay reaches its hub. `machines/` is **shared** across peers (everyone holds everyone's profile),
but each box deploys only its own with `deploy --machine <name>`.

```yaml
name: windows-main            # unique; this is the `deploy --machine` target
os: windows                   # windows | linux | darwin — deploy REFUSES on a host whose OS differs
targets: [claude-code, gemini, claude-ai, agents-md, claude-desktop]   # which adapters emit here
paths:
  projects_root: "C:/Projects"          # base for relative project local_paths
  agentic_context_root: "C:/Mitos"      # where the graph-derived AGENTS.md roster + Projects/<slug>/ land
  gemini_config: "~/.gemini/config"
  antigravity_skills: "~/.gemini/skills"
  claude_ai_staging: "~/ClaudeSkills"   # where skill .zip bundles are staged for manual upload
  gws_env: ".local/gws.env"             # <server>_env → where a merged MCP env file is written
sync:                                   # optional — consumed only by `mitos sync`, never the compiler
  backend: git                          # git is the only backend (may be omitted)
  git:
    hub: "git@github.com:you/mitos-local.git"   # required when sync is set: the overlay repo's remote
    remote: origin                      # optional (default origin)
    branch: main                        # optional (default main)
    ssh_key: "~/.ssh/mitos"             # optional: a specific private key for an ssh hub
```

| Field | Required | What it does / how it's validated |
|---|---|---|
| `name` | **yes** | Unique host identity and the `deploy --machine` selector. Two files claiming one name are refused (no silent shadowing). |
| `os` | **yes (in practice)** | `windows` \| `linux` \| `darwin`. A real `deploy` **refuses** when the host OS doesn't match — rehearse a cross-machine deploy with `--root <dir>` instead. |
| `targets` | **yes** | Which tool adapters emit on this box. Every entry must be a known target (`claude-code`, `gemini`, `claude-ai`, `agents-md`, `hermes`, `claude-desktop`); an unknown one aborts compile. |
| `paths` | **yes** | Map of named locations the targets write to (see the key list below). Values use **forward slashes** even on Windows — an unescaped `\` shows up as a control character and is rejected with a pointed error. |
| `example` | no | `true` marks a shipped *template* profile (skipped by compile once a real machine exists, refused by a real deploy). Must be a bool if present. Your own profiles omit it. |
| `sync` | no | How `mitos sync` reaches the overlay hub. Git-only: `sync.git.hub` is required whenever the block exists; `remote`, `branch`, `ssh_key` are optional. The compiler validates only its *shape* — it never imports the sync code (the deterministic verbs stay offline). |

**Common `paths` keys** (only the ones a machine's `targets` need have to be present):

| Path key | Used by | Points at |
|---|---|---|
| `projects_root` | all | Base directory that relative project `local_path` entries resolve under. |
| `agentic_context_root` | claude-code (Hermes machines) | Root of the Agentic Context tree (graph-derived `AGENTS.md` roster + `Projects/<slug>/` indexes). Used only on **Hermes machines** (`agents-md` in `targets`). On pure workstation machines (without `agents-md`), project AGENTS.md files deploy directly to each project's `local_path` instead — `agentic_context_root` is not required. |
| `gemini_config` | gemini | Gemini CLI / Antigravity config dir (`mcp_config.json` + `config.json`). |
| `antigravity_skills` | gemini | Antigravity's native skill dir (`~/.gemini/skills/`). Skills and prompts targeting `gemini` deploy here. |
| `claude_desktop_config` | claude-desktop | Full path to `claude_desktop_config.json`. Set to enable Desktop MCP wiring. Windows default: `%APPDATA%/Claude/claude_desktop_config.json`. |
| `claude_ai_staging` | claude-ai | Where skill `.zip` bundles are staged for **manual** upload to claude.ai. |
| `hermes_home`, `hermes_config` | hermes | Hermes home and its `config.yaml` (surgically merged, never overwritten). |
| `assistant_root` | hermes | Where Hermes's deployed context lands. |
| `<server>_env` | deploy (connections lane) | Destination for a merged MCP env file, e.g. `gws_env: ".local/gws.env"`. Secrets are merged in here at deploy time, never committed. |

#### Workstation vs Hermes: two claude-code deploy modes

The `claude-code` target behaves differently depending on whether `agents-md` is also in the machine's `targets`:

| Machine type | `targets` includes | Project AGENTS.md lands at | Repo clones into |
|---|---|---|---|
| **Workstation** | `claude-code` (no `agents-md`) | `<local_path>/AGENTS.md` — full doc context inline, no companion details file | `<local_path>/<repo_basename>/` |
| **Hermes** | `claude-code` + `agents-md` | `<agentic_context_root>/Projects/<slug>/AGENTS.md` — lightweight title index, full details in `AGENTS_DETAILS.md` | `<agentic_context_root>/Projects/<slug>/<repo_basename>/` |

On a **workstation machine**, for each project that has a knowledge graph (`registry/local/graph/<slug>.jsonld`) and a `local_path` on that machine, deploy writes two files into the project's directory:

- **`<local_path>/AGENTS.md`** — the project's context prose (from `context.assistant` in the manifest, resolved under the `agents-md` audience) followed by the full document index: document IDs, links, modified dates, descriptions, and tags, all inline. The prose section is `protect`-policy (hand-edits drift-capture to inbox); the generated doc block is silently regenerated every deploy.
- **`<local_path>/CLAUDE.md`** — a thin `@AGENTS.md` stub so Claude Code auto-loads the full context above.

A workstation machine does **not** need `agentic_context_root`. The `local_path` in the project manifest is what activates this for each project.

The context partial's `audience` does **not** need to include `claude-code` — the workstation deploy reads the partial under the `agents-md` audience (the same one Hermes uses), so a partial with `audience: [hermes, agents-md]` is visible in both places without any frontmatter change.

### MCP server definitions — `connections/servers.yaml`

Servers are the moat's **tools**, not registry content, so they live in `connections/` on their own
deploy lane — but the overlay can still override or add servers via
`registry/local/connections/servers.yaml` (per-server last-layer-wins), which is why this file
appears in the overlay map above. The canonical contract for each server's env/credentials/transport
is its **upstream repo** (the `repo:` field) — consult that upstream README before adding keys; don't
invent them.

```yaml
servers:
  gws:                                   # the server key — referenced by a project's document_store
    description: Google Workspace suite — source of truth for user data.
    repo: https://github.com/taylorwilsdon/google_workspace_mcp   # upstream config contract
    setup_docs: docs/connectors/google-workspace.md
    transport: streamable-http
    url: http://localhost:8000/mcp       # default endpoint
    urls:                                # optional per-machine overrides (e.g. reach it over the LAN)
      linux-box: http://192.168.1.20:8000/mcp
    hosted_on: [linux-box]               # machines that actually run this server (must exist)
    env_template: connections/env/gws.env.example   # tracked template
    env_local: .local/gws.env            # merged real values (gitignored)
    graph_enum:                          # optional: lets the generic `mcp` connector enumerate docs
      list_tool: search_drive_files      # required when graph_enum is present
      query_arg: query                   # the tool arg that carries a folder/name scope
      fields:                            # map the tool's fields → the lean graph shape
        id: id                           # `id` and `name` are required
        name: name
        dateModified: modifiedTime
        webUrl: webViewLink
    tools:                               # categorized inventory of the server's MCP tools
      drive: [search_drive_files, get_drive_file_content, …]
```

| Field | Required | What it does / how it's validated |
|---|---|---|
| *(server key)* | **yes** | The map key (e.g. `gws`) is the server's name — what a project's `document_store` points at. |
| `repo` | recommended | Upstream project that **defines the config contract**. The source of truth for which env vars and credential files exist. |
| `setup_docs` | recommended | Path to the connector's setup guide under `docs/connectors/`. |
| `transport`, `url` | recommended | How the server speaks and its default endpoint. |
| `urls` | no | Per-machine URL overrides — keys must be known machines. Lets one host reach a server running on another (e.g. over the LAN). |
| `hosted_on` | no | Machines that run the server — must be known machines. |
| `env_template` / `env_local` | no | The tracked `*.env.example` and the gitignored merged target. Only the template is committed (invariant #6). |
| `graph_enum` | no | Teaches the backend-agnostic `mcp` connector how to enumerate this store for knowledge-graph init. When present, `list_tool` is required and `fields` **must** map both `id` and `name`. A store *without* `graph_enum` falls back to a dedicated backend connector (e.g. `gws` OAuth). |
| `tools` | no | Categorized inventory of the server's MCP tools — documentation/reference for what the server exposes. |

## Everything here is optional

You commit **only what you personalize.** `mitos init` pre-creates the `identity/`, `projects/`,
`graph/`, `skills/`, and `agents/` trees, but they can sit empty until you fill them. A perfectly
valid minimal overlay is just:

```
registry/local/
├── identity/who-i-am.md         ← your name + form of address
└── machines/<this-host>.yaml    ← this box's profile + sync block
```

Anything you don't override falls through to the public core defaults.

## What is *not* in this repo

The overlay repo is intentionally narrow — three things stay out of it:

- **The public core.** `registry/identity/`, `registry/skills/`, … (the neutral defaults and the
  compiler) live in the **main Mitos repo**, which you update with a plain `git pull`. The overlay
  repo carries *only* `registry/local/`.
- **Secrets.** Real credentials and env values live in `.local/` (gitignored, per-machine) and are
  merged in at deploy time — **never** committed, never synced (invariant #6). Only
  `connections/env/*.env.example` *templates* are tracked, and those are in the public core, not
  here.
- **The inbox.** Proposals captured by your tools land in `inbox/` (inside the overlay), which travels directly with your overlay repository.

So the worst case if this repo leaked is your overlay prose and machine layout — no keys, no tokens.

## Getting your overlay onto a machine

`python build/mitos.py init` sets up `registry/local/` and offers three paths — and **none of them
ever overwrite a file you already have**, so it's safe to run over existing data:

| You have… | Pick | What happens |
|---|---|---|
| Nothing yet | **[1] Scaffold a fresh one** | Seeds a starter overlay from your name + an org template. If some files already exist, only the *missing* pieces are added. |
| An overlay on a **hub** (another machine's `mitos-local`) | **[2] Pull from a git hub** | Clones your real files into `registry/local/` (wraps `sync clone`), installs the auto-deploy hook, and captures this machine's sync config. **Your existing files come down as-is — nothing is generated.** |
| Custom files **already in `registry/local/`** | **[3] Use them as-is** | Finishes the install around your files untouched, and optionally publishes them to a hub (wraps `sync init`). |

So a returning machine pulls your established overlay rather than starting from a blank skeleton,
and a machine where you've hand-placed files keeps every one of them.

## Updating your overlay after init

There is **no single `mitos update` command** — by design. The overlay is a plain, git-tracked
folder of files, so "updating" it means one of a few things depending on *what* you're changing.
Nothing here is a black box: most updates are just edits to the files mapped in
[Config-file reference](#config-file-reference) above, schema-validated on the next `compile`.

**Re-run `mitos init` — it's safe and idempotent.** Running it again over an existing overlay
**never overwrites a file you already have**; it only fills in *missing* pieces. Use it to pick up a
scaffold tree you skipped the first time, or to add an org template you didn't seed. It is the one
"update" path that's a guided prompt rather than a file edit.

**Dedicated verbs for the structured additions:**

| Want to… | Command |
|---|---|
| Add a new project manifest (Stage 1 of graph init) | `python build/mitos.py project add <slug> [--name … --document-store …]` |
| Bind a document store / build the knowledge graph | `python build/mitos.py connect --project <slug>` |
| Pull or push the overlay across machines | `python build/mitos.py sync --machine <name> [init \| clone \| pull \| push]` |
| List the available workspace connectors | `python build/mitos.py connectors` |

**Everything else is a direct file edit.** There is intentionally no CLI for editing an identity
persona, adding a skill or agent, tweaking a machine profile, or overriding a core project — you
edit the file under `registry/local/` and recompile. To **override** a core file, place a file with
the same logical name (same partial path / skill name / agent name / project slug / machine name);
last-layer-wins replaces the core entry. To **add** something new, use a new name. Then:

```bash
python build/compile.py compile                          # schema-validates your edits (fails loudly)
python build/compile.py deploy --machine <name> --dry-run  # read the plan before deploying for real
```

**The `review` console is the other update surface.** `python build/compile.py review` accepts
inbox candidates into the registry and edits the knowledge graph through a localhost UI — it writes
to the working tree (never commits), so your overlay edits land as ordinary file changes you then
sync.

## How a machine carries it across hosts

`machines/` is **shared** — every peer holds every machine's profile — but a given box deploys only
its own (`deploy --machine <its-name>`). The one file a peer genuinely *owns* is its own
`machines/<name>.yaml`; everything else is common. That is why conflicts are rare: peers edit
different files.

Setup, day-to-day sync, and the auto-deploy hook are all covered in
[`lan-sync.md`](../docs/lan-sync.md). In short: `mitos sync --machine <host> init --hub <url>` turns
`registry/local/` into this repo on your first machine, and `… clone --hub <url>` onboards the
rest.
