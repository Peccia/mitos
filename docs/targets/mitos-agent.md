# The `mitos-agent` target

**Mitos Agent** is the first-party agentic planning harness Mitos feeds — the replacement for the
retired `hermes` target. It is one of exactly two harness classes Mitos supports (the other being the
third-party coding harnesses: `claude-code`, `antigravity`, `claude-app`). The harness itself is a
separate, public product; this page documents only what the **`mitos-agent` target emits** into a
machine.

> The full design lives in [`../concepts/mitos-agent-platform.md`](../concepts/mitos-agent-platform.md)
> and the migration in [`../concepts/mitos-agent-implementation-plan.md`](../concepts/mitos-agent-implementation-plan.md).

## What it emits

Everything lands under one path key, **`assistant_root`** (e.g. `~/MitosAgent`):

| File | Lane | Drift policy | Notes |
|---|---|---|---|
| `SOUL.md` | content | `protect` | The system prompt — the identity partials (`who-i-am`, `operating-rules`, `security`, `comms-style`, `session-protocol`), in that order. |
| `skills/<category>/<name>/SKILL.md` (+ supporting files) | content | `harvest` | Every skill whose `targets:` includes `mitos-agent`, curatable per-machine via `skills: {mitos-agent: {include:/exclude:}}`. |
| `mcp.json` | connections | `protect` | A **whole file** Mitos owns — one `mcpServers` entry per wired store. |

The operating **AGENTS.md tree** is *not* emitted by this target — it is the `agents-md` target's
output, which a `mitos-agent` machine always co-deploys (`loader._validate` requires it: the harness
has no tree to traverse without it). Both targets deploy into the **same** `assistant_root`, so a
machine has exactly one install folder:

```
~/MitosAgent/
├── SOUL.md          ← mitos-agent   the system prompt
├── mcp.json         ← mitos-agent   store wiring
├── skills/          ← mitos-agent   skills/<category>/<name>/SKILL.md
├── AGENTS.md        ← agents-md     the operating root (routing starts here)
├── Assistant/       ← agents-md     one-shot workspace tasks
├── Projects/        ← agents-md     the generated project roster + per-project nodes
└── .local-memory/   ← the harness   runtime state; Mitos never writes here
```

The former separate `mitos_agent_home` key was collapsed into `assistant_root`; it is no longer a
recognized path key, and a profile still naming it deploys nothing.

## `mcp.json` — whole file, every store

Unlike the third-party config files (Antigravity/Claude Desktop `config.json`, surgically merged under
invariant #7), Mitos Agent's `mcp.json` belongs to Mitos and is written **entire** (`kind: json`, no
`owned_keys`). It carries one entry per server in the machine's `document_store:` list
(`planner._agent_servers` → `render.mitos_agent_mcp_config`), keyed by server name, each with its
`url` (per-machine resolved), `transport`, and flat tool list — so a multi-store machine's
`resolve(id, store)` can pick the right server. With `document_store:` unset (the default), **no
`mcp.json` is written** — the same connection gate that governs `requires_server:` skills.

```json
{ "mcpServers": { "gws": { "url": "http://localhost:8000/mcp",
                           "transport": "streamable-http",
                           "tools": ["list_calendars", "..."] } } }
```

## Machine profile

```yaml
name: my-agent-box
os: linux
targets: [mitos-agent, agents-md]   # mitos-agent pulls in the agents-md tree
document_store: gws                  # optional — omit and no mcp.json / no gws skills deploy
paths:
  assistant_root: "~/MitosAgent"     # the ONE install root (SOUL.md, skills/, mcp.json, the tree)
```

[`machines/example-linux.yaml`](../../machines/example-linux.yaml) is this profile ready to copy;
`python build/mitos.py init` writes it for you if you pick the planning-harness role.

**Role exclusivity (kept).** `mitos-agent` cannot share a machine with any coding harness
(`antigravity`/`claude-app`/`claude-code`) — rejected at compile by `loader._validate`. An agentic
machine is dedicated to that purpose; for agentic-tree behavior inside one project on a coding
workstation, use a project's `agentic_tree:` instead.

## End to end: from an empty box to a running harness

Mitos and the harness are separate installs with no dependency edge between them — Mitos never
invokes the harness, and the harness never imports Mitos or reads `registry/`. They meet at exactly
one place: **the deployed `assistant_root`**. Mitos writes that folder; the harness reads it.

```bash
# 1. Install the harness (separate repo, zero runtime dependencies, Python ≥3.11)
git clone https://github.com/Peccia/mitos-agent.git
cd mitos-agent && pip install -e .
```

```bash
# 2. Declare an agentic machine — pick the planning-harness role when asked
python build/mitos.py init
```

```bash
# 3. Populate the tree. THIS is what fills ~/MitosAgent — the harness has no populate step of its own
python build/compile.py deploy --machine my-agent-box
```

```bash
# 4. Run it against what Mitos just deployed
cd ~/MitosAgent && mitos-agent plan "your idea here"
```

Step 4 needs no `--root`: the harness walks up from the working directory looking for an `AGENTS.md`
that matches the taxonomy signature plus a `Projects/` sibling, which is exactly the shape step 3
emits. From anywhere else, pass `--root ~/MitosAgent`.

**A fresh harness install is deliberately empty.** `pip install` gives you the engine, not the
context — there is no seed tree, no scaffold command, and no bundled content. If
`mitos-agent plan` reports `no Mitos operating tree found`, the answer is always step 3: you have not
deployed yet, or you are pointed at the wrong root. (The harness also documents a hand-built tree for
users who never adopt Mitos; that path is in the harness's own README, and Mitos is the supported way
to keep one current.)

Re-run step 3 whenever registry content changes — that is the whole update story. The harness reads
the tree fresh on every session, so a `deploy` is picked up by the next run with nothing to restart.

## Retirement note

The `hermes` target it replaced merged eleven owned keys into a third-party `config.yaml` (an
`mcp_servers` merge plus a `hermes_settings:` leaf-path lane). Both are gone — Mitos Agent owns its
config whole. One consequence of that history: a retired `merge` leaves its keys behind in the
third-party file (merges are not lockfile-tracked, so they never become reportable orphans). See the
merge-residue note in [`../managing-state.md`](../managing-state.md).
