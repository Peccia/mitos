# Managing your moat's state — deploy, drift & reconciliation

This is the core of Mitos. Your **registry** (`registry/` + your `registry/local/` overlay) is the
single source of truth for everything an agent reads. **Deploy** materializes that truth into each
tool's native files on a machine. Between deploys, those deployed files can change — a tool edits
its own copy, you tweak something by hand, or a machine already had files before Mitos arrived.
This page explains exactly how Mitos tracks that, every state it can report, and how you reconcile
each one.

> **One rule underpins all of it:** the registry wins. Tools and hand-edits *propose*; nothing is
> adopted into the registry except by you. Deploy never silently throws away a change — anything it
> is about to overwrite is captured first.

## Contents
- [The mental model](#the-mental-model)
- [The lockfile: how drift is detected](#the-lockfile-how-drift-is-detected)
- [Reading a deploy plan: every state](#reading-a-deploy-plan-every-state)
- [Drift policies: protect, harvest, generated](#drift-policies-protect-harvest-generated)
- [Worked example: a first deploy onto a populated machine](#worked-example-a-first-deploy-onto-a-populated-machine)
- [The scenarios you'll actually hit](#the-scenarios-youll-actually-hit)
- [The reconciliation toolbox](#the-reconciliation-toolbox)
- [Safety rails](#safety-rails)
- [State across machines](#state-across-machines)

---

## The mental model

```
registry/ (+ local/ overlay)        ← source of truth, the moat
        │  compile
        ▼
   dist/<machine>/                   ← rendered artifacts (disposable)
        │  deploy --machine <name>
        ▼
   live files on the machine         ← what tools actually read
        ▲
        │  the lockfile records what was deployed + its hashes
   .deploy-lock.json                 ← per-machine, gitignored "ETag"
```

- **`compile`** validates the registry and renders every machine's targets into `dist/`. It writes
  nothing outside `dist/`. Schema validation is your first test — it fails loudly on a missing
  partial or bad field.
- **`deploy`** compares three things for every output and acts on the difference. It is the only
  verb that writes to live paths, and it records what it did in the lockfile.

## The lockfile: how drift is detected

`.deploy-lock.json` lives at the repo root (or your `--root` sandbox), is **per-machine**, and is
**gitignored** — it is local bookkeeping, not shared content. For every file it deployed it stores:

| field | meaning |
|---|---|
| `source_hash` | hash of what the registry rendered at deploy time |
| `deployed_hash` | hash of the bytes written to disk (identical to `source_hash` at deploy) |
| `drift_policy` | `protect` \| `harvest` \| `generated` (see below) |
| `sources` | the registry partial(s) the file was built from |
| `sections` | for multi-source documents, the per-section base (so an edit can be routed back to the right partial with no markers in the file) |

Drift detection is a **three-way comparison** — like an optimistic-concurrency ETag:

- **fresh render vs `source_hash`** → if different, *the registry changed* since deploy → **pending**.
- **live file vs `deployed_hash`** → if different, *the file was edited in place* → **drift**.
- both different → **conflict**. Neither → **unchanged**.

If there's **no lock entry** for a file but a file is already on disk, it's an **untracked existing
file**: Mitos compares the live bytes to what it would write — equal means `unchanged` (it just
records it), different means `conflict`.

## Reading a deploy plan: every state

Each line of a `deploy`/`diff` plan is `[state]  <path> — <detail>  <flag>`. The states:

| `[state]` | What it means | What deploy does |
|---|---|---|
| `create` | No file there yet. | Writes it; records it in the lock. |
| `unchanged` | Live bytes already equal the render (tracked, or an untracked file that happens to match). | Nothing to write; ensures the lock matches. |
| `pending` | Registry changed since deploy; the file wasn't touched. | Overwrites with the new render (registry wins). |
| `drift` | File was edited in place; registry unchanged. | Depends on **policy** (below): capture+overwrite, or block. |
| `conflict` | Either edited-in-place **and** registry-changed, **or** an untracked existing file that differs. | Depends on **policy**: capture+overwrite, or block. |
| `resolved` | Live already matches the registry but the lock was stale (e.g. right after `adopt`). | Re-locks; **never** needs `--force`. |
| `merge` | A tool-owned config file (Gemini `config.json`, Hermes `config.yaml`). | Splices only Mitos-owned keys in; never a whole-file overwrite. |
| `orphan` | Previously deployed by Mitos, no longer in the plan (a deselected skill, a retired project). | Kept on disk until you `--prune`. |
| `clone` | A project repo to clone into the Agentic Context tree. | Clones if absent; never touches an existing checkout. |

The two flags you'll see on `drift`/`conflict` lines:

- `<-- protected, blocked` — a `protect`-policy file drifted; deploy will **refuse** (see below).
- `<-- will capture to inbox/, then overwrite` — the in-place edit will be snapshotted into
  `inbox/` as a review candidate **before** it's overwritten, so the proposal survives.

## Drift policies: protect, harvest, generated

Every emitted file carries a **drift policy** (set in its target spec) that decides what happens
when its deployed copy drifts:

- **`protect`** — the safe default for authored prose (SOUL.md, AGENTS.md, the Gemini prompt files,
  staged skill zips). If it drifts, **deploy refuses the whole run** (exit 1) and tells you to
  resolve it. Nothing is overwritten until you decide. Override for one run with `--force` (which
  still captures the drift to `inbox/` first, unless the file is exempt — see below).
- **`harvest`** — for files a self-improving tool is *expected* to edit (e.g. a skill Hermes tunes).
  On drift, deploy **captures the edit to `inbox/` and then overwrites** (registry wins), so the
  proposal is preserved for you to accept later, and the machine still converges on the registry.
- **`generated`** — knowledge-graph-derived files with no human prose: the Agentic Context
  **roster** (`AGENTS.md` at the tree root) and, on the agents-md/Hermes side, each project's
  `AGENTS_DETAILS.md`. Regenerated from `registry/graph/` on every deploy; in-place edits are
  **overwritten silently** and are **non-adoptable** (there's no registry partial to route an edit
  back to — edit `registry/graph/<slug>.jsonld` instead).

  A project's **`AGENTS.md`** is a special case: it is the project's prose (a registry partial,
  **`protect`**) followed by a generated document block. The two are split in the lockfile, not by
  any in-file marker (invariant #5): only the **prose** is protected and adoptable, while the
  generated block regenerates every deploy — a hand-edit of the block never blocks a deploy and is
  silently overwritten, exactly as a `generated` file would be. So one file carries both policies,
  section by section.

**Capture exemptions:** `env` files (the intake queue must never hold secrets — their canonical
source is your `.local/` overlay), staged `.zip` skills (binary build artifacts), and
`generated` files (no partial to route to) are never snapshotted to `inbox/`.

**Skill supporting files.** A skill's `examples/` and `scripts/` files deploy alongside
`SKILL.md` as their own separately-tracked outputs, each carrying the skill's own drift
policy (`harvest` on hermes/claude-code) — an edited script drifts, captures, and
adopts/harvests **back to its own file**, never to `SKILL.md`. Deploy also sets the executable
bit on files under `scripts/` when the target machine isn't Windows.

## Worked example: a first deploy onto a populated machine

This is the exact plan from a first real deploy where the machine already had Gemini/Hermes files:

```
deploy plan for windows-laptop (apply):
  [conflict ] ~/.gemini/config/mcp_config.json — untracked existing file  <-- protected, blocked
  [merge    ] ~/.gemini/config/config.json — exists
  [unchanged] ~/.gemini/prompts/marketing.md — untracked existing file
  [conflict ] ~/.gemini/prompts/idea-revision.md — untracked existing file  <-- will capture to inbox/, then overwrite
  [conflict ] ~/ClaudeSkills/gws.zip — untracked existing file  <-- protected, blocked
  [create   ] C:/Projects/MyAssistant/AGENTS.md
  [create   ] C:/Projects/MyAssistant/Projects/apdict/AGENTS.md
  ...
  [clone    ] C:/Projects/MyAssistant/Projects/mitos/mitos — absent -> will clone

refusing to deploy: 2 protected file(s) drifted. Resolve with `adopt` / `harvest`, or pass --force.
```

Line by line:

- **`mcp_config.json` — conflict, protected, blocked.** A file is already there, differs from what
  Mitos would write, and its policy is `protect`. This single file (and `gws.zip`) is why the whole
  run is **refused** — nothing was written.
- **`config.json` — merge.** Tool-owned; Mitos will splice only its MCP entries in and leave the
  rest of your Gemini config alone. (A merge never blocks.)
- **`dept-*.md` — unchanged (untracked).** Those files already match what Mitos would deploy, so
  there's nothing to do; they'll just be recorded in the lock.
- **`idea-revision.md` — conflict, will capture+overwrite.** Differs, but its policy is `harvest`,
  so on a real run it would be snapshotted to `inbox/` and then overwritten — *not* a blocker.
- **`gws.zip` — conflict, protected, blocked.** The second protected file. (Note: zips are exempt
  from capture, so `--force` would overwrite it without an `inbox/` snapshot.)
- **`create` / `clone` lines** — new files and a project checkout; harmless.

**Why this is the expected first-deploy experience.** Mitos found pre-existing files it never wrote.
For the two `protect` ones it stops and asks you, rather than clobbering work it didn't author. You
now choose, per file, who is right — see the next two sections. This one-time **baseline** is the
intended cutover ritual; after it, the lock tracks everything and deploys are quiet.

## The scenarios you'll actually hit

**1. Baseline / cutover (the example above).** Pre-existing `protect` files block the first deploy.
For each blocked file decide:
- *The file on disk is the version you want* → `adopt <path>` to pull it into the registry, then
  re-deploy (it becomes `resolved` → relocked, no force).
- *The registry is the version you want* → `deploy --force` once (captures non-exempt drift to
  `inbox/`, then overwrites). After that, deploys are clean.
- *Neither is fully right* → reconcile by hand in the registry, then deploy.

**2. Routine update (`pending`).** You edited the registry and recompiled. Deploy shows `pending`
and overwrites the deployed copies. Nothing to think about — registry wins.

**3. A tool improved its own copy (`drift`, `harvest`).** A self-improving tool edited a
`harvest`-policy file. `diff` shows it; deploy captures it to `inbox/` and re-converges. Review the
candidate in the console and `adopt` it to keep the improvement, or just let the registry win.

**4. You edited a deployed file by hand (`drift`).** Same machinery. If it's a `protect` file the
deploy blocks until you `adopt` it (keep your edit) or `--force` (discard it). `adopt` routes the
edit back to the exact partial it came from — and if that partial is overridden by your overlay, the
write lands in `registry/local/` (your private moat), not the public core.

**5. Both sides changed (`conflict`).** You edited the file *and* the registry moved. Treat it like
#4: `adopt` to take the disk version, `--force` to take the registry version, or merge by hand.

**6. Retiring something (`orphan` → `--prune`).** Deselect a skill or remove a project and its
deployed files become orphans — **kept** on every deploy (and reported) until you run
`deploy --prune`, which deletes them (capturing any drifted ones to `inbox/` first). Deletion is
never a silent side effect.

**7. Tool-owned configs (`merge`).** Gemini `config.json` and Hermes `config.yaml` are never
overwritten — Mitos owns only specific keys and splices them in, preserving everything else you have
in those files. Ownership can be a whole top-level key (the MCP server entries) or, for a handful of
Hermes runtime knobs (`terminal.cwd`, `memory.memory_enabled`), a single dotted LEAF path inside an
otherwise Hermes/user-owned block — so sibling settings in that same block (`terminal.timeout`,
`agent.max_turns`, ...) are never touched. Several merge blocks may target the same file (Hermes's
`config.yaml` carries both); compile refuses if their owned keys ever overlap.

## The reconciliation toolbox

| Command | Use it to… |
|---|---|
| `compile [--target T]` | Validate + render. Always safe; writes only `dist/`. |
| `deploy --machine M --dry-run` | **Preview** the plan and write nothing. Do this first, always. |
| `diff --machine M [--lane L] [--target T]` | A three-way drift report without deploying — see what's `pending`/`drift`/`conflict`. |
| `deploy --machine M` | Apply. Blocks on `protect` drift; captures `harvest` drift; converges everything else. |
| `adopt <path>` | Pull an in-place edit on a live file **back into the registry** (overlay-aware routing). The "keep the disk version" verb. |
| `harvest --machine M [--adopt-all]` | List `harvest`-policy drift across a machine; `--adopt-all` pulls every one into the registry. |
| `review` | The operator console (localhost): accept/reject every `inbox/` candidate against a live diff, edit the knowledge graph, browse prompts. A skill candidate's Supporting Files panel proposes the **full replacement set** for `examples/`/`scripts/` — omitted (untouched candidate) leaves existing files alone, an explicit empty set deletes them all on accept. Edits the working tree, never commits. |
| `deploy --machine M --force` | Let the registry win over `protect` drift (captures non-exempt drift first). |
| `deploy --machine M --prune` | Delete orphans (capturing drifted ones first). |

`adopt` only works on **text** files. It refuses, with the right instruction, on: `env` files (edit
`.local/` or the `connections/env/` template), staged `.zip` skills (edit the skill and recompile),
`generated` graph-tree files (edit `registry/graph/<slug>.jsonld`), and JSON/YAML configs (edit
`connections/servers.yaml`).

## Safety rails

- **Dry-run by default in your head.** `--dry-run` prints the full plan and writes nothing. The plan
  is the contract — read it before applying.
- **OS guard.** Deploy refuses when the machine profile's `os:` doesn't match the host (it won't
  write a Linux machine's paths onto Windows). Rehearse cross-machine with `--root <dir>`.
- **`--root <dir>` sandbox.** Redirects every write — files, the lockfile, and `inbox/` captures
  (to `<root>/registry/local/inbox/`) — into a throwaway tree. The way to rehearse any deploy
  safely.
- **Example-machine guard.** The shipped `machines/example-*.yaml` are templates (`example: true`).
  A real deploy of one is refused; copy it into `registry/local/machines/`, rename it, drop
  `example: true`, and deploy that. Once you have a real machine, `compile` skips the examples.
- **Example-project guard.** The shipped `registry/projects/example-project.yaml` is a sample
  (`example: true`). It renders on a fresh clone (so the quick-start shows a worked example), but
  steps aside automatically as soon as you add your own projects under `registry/local/projects/`
  — so a configured fleet's roster and assistant tree never list the sample. Same spirit as the
  machine guard, but keyed off "you have overlay projects" rather than a per-deploy refusal.
- **Lanes.** `--lane content` touches only prose; `--lane connections` touches only MCP wiring +
  env files; default `all` does both. Orphans are always computed against the **full** plan, so a
  lane/target-filtered deploy never falsely reports or deletes the other lane's files.
- **`--target T`.** Restrict a deploy/diff to one adapter's outputs.

## State across machines

The lockfile is **local and gitignored** — each machine keeps its own; it is never shared. What
*does* travel is your registry overlay (`registry/local/`) — which now includes `inbox/` inside
it, so drift candidates and staged document listings move to your review PC via a single
`mitos sync push` / `mitos sync pull`. See [`lan-sync.md`](lan-sync.md) for the sync setup.

> Capture → review → accept → commit → sync → deploy elsewhere. That loop — drift surfaced on any
> machine, gated by you, folded back into the one source of truth — *is* the project.
