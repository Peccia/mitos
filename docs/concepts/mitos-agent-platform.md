# Concept: Mitos Agent — the Mitos-native planning harness

> **Status:** concept only. Nothing here is wired, scheduled, or implemented. This is the design
> document a final implementation plan will be written from.
>
> **Siblings:** [`planning-harness-gemini-1.md`](planning-harness-gemini-1.md),
> [`planning-harness-opus-1.md`](planning-harness-opus-1.md), and
> [`planning-harness-opus-2.md`](planning-harness-opus-2.md) each design a planner *inside* Mitos.
> §13 is the accept/reject ledger; nothing above it restates them.
>
> **What this is.** Mitos Agent is a public, open-source product that **replaces the `hermes` target**
> as the agentic harness this registry feeds. It captures ideas, refines them, and turns them into a
> documented artifact whose format is chosen by the work's domain — written to the user's document
> store or to a file. It traverses the deployed `AGENTS.md` tree natively rather than being prompted
> to, runs on any model provider including local ones, uses the user's workspace through the same MCP
> connection Mitos wires, does not write code, and does not talk to coding harnesses.
>
> **Scope of the Mitos-side change: the target, and nothing else.** No skill body, prompt, or context
> partial is rewritten. The `plan`, `plan-new-idea`, `plan-existing-iteration`, and `gws` skills are
> untouched (§4.5). The only registry edits are target-name strings in `targets:` and `audience:`
> lists.
>
> **It lives at `<mitos project>/mitos-agent/`** — a second repo inside the existing Mitos project,
> registered in that project's manifest (§4.6).

---

## 1. The position

**1. Mitos is not a harness and must not grow one.** Its README is unambiguous: *a registry and
compiler* whose value is that "execution engines are rented — when a better tool ships, you write one
adapter, not a migration." A planning harness living in `registry/` and `build/agentic/` is an
execution engine wearing the moat's clothes. The first time it needs a session store, a provider
client, or a retry policy, the compiler grows a runtime, and the property that makes Mitos worth
having — boring, offline, deterministic, outliving every tool it feeds — is gone.

**2. But the harness Mitos feeds should stop being rented.** The mismatch shows in the registry
itself: `targets/hermes.yaml` surgically merges eleven owned keys into a third party's `config.yaml`,
and the overlay's own `plan` skill spends its first step teaching a model to `cd` into a tree and read
`AGENTS.md` files in order. Both are workarounds for a runtime that does not know what Mitos is.

**3. A prompted harness cannot execute the Mitos tree.** The deployed tree is a *contract*: one H1,
reserved `## Navigation` / `## Workflows` / `## Tools` / `## Skills` in fixed order, connection
sections headed ``## <Name> (`key`)``, document lines carrying a resolvable store ID — all
lint-enforced by `planner.lint_node_markdown`. Mitos enforces that on *emit*; on *read* it can only
ask. §5 closes the gap with a parser.

**4. Agnostic to Mitos, dependent on its outputs.** Mitos Agent never imports Mitos, never reads
`registry/`, and never asks what version produced a tree. It depends on the *artifact shape* — an
`AGENTS.md` hierarchy, a system prompt, skills, MCP wiring — and detects capability by parsing what is
there. Mitos is the best producer of those artifacts; a hand-written tree also works.

**5. Programmatic before judgment.** §1.1.

### 1.1 The law: programmatic before judgment

> Every decision that can be made by code is made by code. The model is asked only for the thing no
> mechanism can produce — the content of the plan.

**It is what makes the harness model-agnostic.** A design that leans on judgment for routing, format
selection, or freshness works on a frontier model and degrades unpredictably on a smaller or local
one. A design that leans on code behaves *identically* on both, and the only thing that varies with
model strength is prose quality — the honest place for it to vary.

**It is what makes prompts simple.** Every rule you don't have to write into a prompt is a rule that
cannot be misread, ignored, or eaten by compaction. Prompts stay short, imperative, and free of
vendor-specific tricks.

| Decision | Mechanism | Model involved |
|---|---|---|
| Which branch / project a message concerns | slug + name match against the parsed tree | only when ambiguous → one `small` call → else ask |
| Which files to load | the route's node chain | never |
| Which document to fetch | graph ID → server → `graph_enum` tool | never |
| Which output profile applies | `orgDomain` → project default → built-in | never |
| Whether the artifact is well-formed | profile lint | never |
| Whether an anchor is stale | content hash | never |
| Whether the session may advance | gate state; the owner answers | never |
| **What the plan should say** | — | **always. This is the only one.** |

```
┌─ mitos (this repo) ──────────────────────────────────────────────────────────┐
│   Connections → Knowledge Graph ← Personalized Context                       │
│   Skills · agents-md tree · SOUL          →  build/compile.py  →  deployed   │
└──────────┬──────────────────────────────────────────────┬────────────────────┘
           │  the same deployed artifacts, read two ways  │
           ▼                                              ▼
┌─ mitos-agent (new repo, public) ─────────┐    ┌─ coding harnesses ───────────┐
│   Message → Request Type                 │    │  Claude Code, Antigravity    │
│      ├── Assistant → idea refinement     │    │  (no interface between them) │
│      └── Project   → planning            │    └──────────────▲───────────────┘
│   native traversal · any provider        │                   │ the user carries it
└──────────┬───────────────────────────────┘                   │
           │  documented artifact, format by domain            │
           ▼                                                   │
   the Connection (document store)  ─── or ───  a local file ──┘
           │
           └─▶ `mitos propose --kind graph` ─▶ inbox ─▶ accept ─▶ back into context
```

---

## 2. What each side owns

| | **mitos** | **mitos-agent** |
|---|---|---|
| Nature | registry + compiler | planning harness + product |
| Role | authors and materializes context | captures ideas, produces artifacts, uses the workspace in service of both |
| Runs | on demand, offline, deterministic | as a session, with a model, against live substrate |
| State | the registry; a lockfile | ideas, artifacts, sessions (§6.9) |
| Network | only in `build/mitos.py` (invariant #11) | inherently — providers, MCP servers |
| Providers | none | a provider port — `fake` + Ollama (local) + Anthropic first; OpenAI/Gemini deferred (§6.2) |
| Licence | public, open source | public, open source |

**The rule that keeps this honest:** *mitos-agent never reads `registry/` and never imports
`build/agentic/`.* If it needs something the deployed artifacts don't carry, that is a request for
Mitos to emit more — a target-spec change, reviewed like any other. What the rule *permits* is §5: the
deployed tree is a public, lint-enforced format, and parsing it deeply is using the interface as
designed.

### 2.1 Mitos supports exactly two harness classes

A clarification the replacement buys, and worth stating as policy because it decides what future
target requests get accepted:

| Class | Targets | Consumes | Supported |
|---|---|---|---|
| **Agentic planning harness** | `mitos-agent` | `SOUL.md`, the tree, skills, `mcp.json` | first-party, the only one |
| **Coding harnesses** | `claude-code`, `antigravity`, `claude-app` | per-project context, skills, prompts | third-party, several |
| *(context format, not a harness)* | `agents-md` | — | consumed by both classes |

Third-party **agentic** harnesses — Hermes, OpenClaw, and anything of that shape — are no longer
supported. That is not a slight on them; it is the recognition that an agentic harness needs to
execute the tree contract (§5), and a rented one cannot. Coding harnesses stay third-party precisely
because they consume a much simpler surface: a context file and some skills.

---

## 3. The contract

### 3.1 What Mitos emits

The `mitos-agent` target emits into one path key, **`assistant_root`** — the *same* key the `agents-md`
operating tree mounts at, so the harness's own files and the tree it reads share one install root (§7):

| File | Lane | Policy | Corresponds to |
|---|---|---|---|
| `SOUL.md` | content | `protect` | hermes's `SOUL.md`, unchanged in shape |
| `skills/<category>/<name>/SKILL.md` | content | `harvest` | hermes's skills tree, unchanged |
| `mcp.json` | connections | `protect` | hermes's `mcp:` **yaml_merge** into `config.yaml` |

The operating tree is the `agents-md` target's output at `assistant_root` and always was — Mitos Agent
reads the same tree Hermes read, now co-located with its own `SOUL.md`/`skills/`/`mcp.json`. The former
separate `mitos_agent_home` key was collapsed into `assistant_root` once `agents-md` became a hard
requirement on a `mitos-agent` machine (a harness with no tree to traverse is refused at compile).
`bootstrap.json` (§3.2) largely retires with the single root: the only value traversal still can't
recover is where each project's repo checkouts sit on disk.

**Two simplifications follow from owning the runtime.** Mitos writes `mcp.json` whole, because the
config file belongs to Mitos — no surgical merge, no `owned_keys`; invariant #7 stops applying to this
lane. And once Hermes is retired, `targets/hermes.yaml`'s `settings:` block goes with it: eleven owned
keys, the `hermes_settings:` machine block, and `_HERMES_SETTINGS_LEAVES`/`_HERMES_SETTINGS_WHOLE_KEYS`
in `render.py` exist only to reach into a third-party config file.

**And `mcp.json` carries every wired store, not just `gws`.** Hermes's `_gws` hard-codes one server;
the new whole-file output loops the machine's `document_store:` list and emits one `mcpServers` entry
per store — the same list the graph lane already tags documents against. This is what makes §5.4's
`resolve(id, store)` implementable for a multi-store project: the resolver needs the *right* server
for a document's `store` tag, and a single hard-coded entry cannot supply it. A machine with one store
gets one entry, unchanged in effect from today.

### 3.2 `bootstrap.json` — optional acceleration, not a dependency

Because Mitos Agent is *agnostic to Mitos*, it cannot require a file only Mitos produces.

```jsonc
{
  "tree_root": "C:/Projects/MyAssistant",
  "tree_kind": "machine",                  // machine | project
  "content_hash": "a3f9c21…",              // over every file the walk will read
  "propose": ["…/build/.venv/Scripts/python.exe", "…/build/compile.py", "propose"],
  "projects": [
    { "slug": "mitos", "name": "Mitos",
      "node": "Projects/Mitos/AGENTS.md",     // tree path — where its context lives
      "root": "C:/Projects/mitos" }           // local path — where its repos live
  ]
}
```

Each field is something traversal cannot recover — `projects[].root` most of all, since the
`## Navigation` roster emits *relative* dirnames whose base differs by mount kind. Absent the file,
the same values come from Mitos Agent's own `config.toml`, and the root is found by walking up from
`cwd` for an `AGENTS.md` matching the taxonomy signature. **No version handshake:** parse what is
present, report what is missing in actionable terms, degrade rather than refuse.

### 3.3 The proposal valve

Residue goes through the inbox, which invariant #3 already designates as the intake queue for agents.
Mitos Agent must not hand-assemble candidate folders, so Mitos gains **one offline verb**:

```bash
python build/compile.py propose --kind graph --slug mitos --source mitos-agent --payload <file>
```

Deterministic, offline, no network imports; thin, since `review._write_candidate` already does the
work. When no propose command is configured, Mitos Agent writes the artifact and tells the user to
propose it themselves.

### 3.4 What never crosses

- **Mitos Agent never writes into `registry/`.** Invariant #3, unchanged.
- **Mitos never imports, spawns, or knows about Mitos Agent.**
- **Mitos Agent never interfaces with a coding harness.** No MCP server for them, no plugin, no
  `.claude/` writes. Its output is a document or a file; the user carries it (§6.7).

---

## 4. The Mitos-side change

### 4.1 The nine gate sites are three questions, not one

I previously called these "nine sites" and proposed collapsing them behind one helper. Having read
all nine, that was wrong. They test **three different things** that happen to have the same answer
today:

**Question A — "does this machine deploy org content?"** *(3 sites: `planner.py:418`, `:805`, `:1022`,
plus a docstring in `graph.py:622`)*

```python
org_routing = "hermes" in machine.get("targets", [])
```

Gates the org-domain table and every per-effort routing line. Its documented rule: a machine can reach
the tree *without* deploying org skills, and must then render `orgDomain` as inert metadata rather
than a routing line pointing at a skill that was never deployed. Pinned by
`test_agents_md_without_hermes_never_leaks_org_routing`.

**Question B — "does this machine already host the assistant tree at its root?"** *(2 sites:
`planner.py:772`, `:1045`)*

```python
if "hermes" in machine.get("targets", []):
    return []                          # :772 — a project agentic_tree mount would be redundant
    pa_sources = [s for s in pa_sources if not str(s).startswith("identity/")]   # :1045 — SOUL.md
                                       #         already carries the persona
```

Nothing to do with orgs. This asks whether `SOUL.md` and a machine-root tree exist.

**Question C — "does this machine deploy the assistant's skills?"** *(1 site: `planner.py:1018`)*

```python
hermes_sk_spec = (reg.targets.get("hermes") or {}).get("skills") or {}
hermes_selected_skills = (_selected_skills(reg, hermes_sk_spec, machine)
                          if "hermes" in machine.get("targets", []) and hermes_sk_spec else [])
```

Feeds the generated `## Skills` block. It also reads the target spec by name, so it needs the target
*key*, not just a boolean.

**The remaining 2 sites are the exclusivity check** (`loader.py:793`, `init.py:252`), which §4.4
**keeps** and renames only in intent, not behaviour.

**A fourth gate, differently keyed, hides in the same area.** `planner.py:1193`'s
`is_hermes_machine = "agents-md" in machine.get("targets", [])` decides whether every project gets a
graph-bearing `AGENTS.md` or a `CLAUDE.md` stub. It is named after Hermes but keys off `agents-md`,
*not* the assistant target — so it is a genuinely different question from A/B/C, and renaming it to
match them would be wrong. It stays keyed on `agents-md`; the rename only fixes its Hermes-flavoured
*name* (and the three helpers' docstrings note it as the fourth, distinct question so a future reader
does not fold it into Question B).

**So the answer to my own question:** the three assistant-target predicates collapse into **three
named helpers, not one** — and the `agents-md` gate stays separate as a fourth. A single helper works
mechanically today and erases distinctions this repo's `AGENTS.md` explicitly warns are not the same
test — which is exactly the kind of quiet semantic loss that shows up two releases later as a bug
nobody can explain.

### 4.2 Four ways to do it — pick one

**Option 1 — Straight rename.** Find-and-replace `"hermes"` → `"mitos-agent"` across ~450 references
in one change; rename `targets/hermes.yaml`; update every fixture.

```python
org_routing = "mitos-agent" in machine.get("targets", [])
```

*Cost:* one large PR. *Consequence:* **Hermes keeps running on frozen files.** `deploy` deletes
nothing (invariant #9): `~/.hermes/SOUL.md`, the skills tree, and `config.yaml` — including its
`mcp_servers`, fallback providers, and toolset config — all stay on disk exactly as last deployed,
and the `agents-md` tree at `~/MitosAgent` keeps updating (that target is untouched). So Hermes still
answers; it just stops receiving new persona, skill, or MCP edits until Mitos Agent's runtime exists
— realistically Stage 5. The cost is a frozen assistant, not a dead one.

---

**Option 2 — Dual-accept, then delete.** Both names valid during the transition; flip content
gradually; remove `hermes` at the end.

```python
ASSISTANT_TARGETS = {"hermes", "mitos-agent"}          # transitional
def is_assistant_machine(machine) -> bool:
    return bool(ASSISTANT_TARGETS & set(machine.get("targets", [])))
```

*Cost:* four commits, each green. *Consequence:* Hermes works throughout; a transitional constant must
be deleted later, and for a while two names are valid, which a reader has to hold in their head.

---

**Option 3 — Name the three questions first, rename second.** Refactor the six gate sites into
intention-revealing helpers *before* touching any name, so the rename is one line inside each:

```python
def deploys_org_content(machine) -> bool:      # Question A — 3 call sites
    return ASSISTANT_TARGET in machine.get("targets", [])

def hosts_assistant_tree(machine) -> bool:     # Question B — 2 call sites
    return ASSISTANT_TARGET in machine.get("targets", [])

def assistant_target(reg, machine) -> str | None:   # Question C — needs the key, not a bool
    ...
```

*Cost:* one refactor commit with no visible progress, then the rename. *Consequence:* the three
distinctions survive with names and their own tests; future changes to one question can't silently
move the other two.

---

**Option 4 — Add now, subtract later. (Recommended.)** `mitos-agent` is a **new** target added
alongside `hermes`. Nothing about Hermes changes. Skills and identity partials gain `mitos-agent` in
addition to `hermes`, so both deploy. Retirement is later, and it starts as a one-line edit to a
machine profile.

```python
ASSISTANT_TARGETS = {"hermes", "mitos-agent"}   # Options 2 and 4 share this line
```

```yaml
# registry/identity/who-i-am.md
audience: [hermes, mitos-agent, agents-md]      # additive — both harnesses get the persona

# registry/local/machines/linux-box.yaml — the actual retirement, when you're ready
targets: [mitos-agent, agents-md]               # was: [hermes, agents-md]
```

*Cost upfront:* ~150 lines — one target spec, one `KNOWN_TARGETS` entry, the three helpers from
Option 3, the path keys, and tests. *Cost later:* ~150 more to delete `hermes`, the `settings:` lane,
and the extra audience entries. *Consequence:* **zero risk to a running Hermes**, both harnesses
deployable side by side on different machines for direct comparison, and Stage 2 stops blocking on
anything.

---

> ## ▶ DECIDED: **Option 1 — straight rename.**
>
> Rationale accepted from the owner: *"no one is using Mitos but me, so we should just go all-in."*
> The Linux box's assistant *freezes* between the rename and Stage 5 — it runs on its last-deployed
> files (invariant #9 deletes nothing) but receives no new edits — and that is accepted. Option 4's
> analysis is kept below because it documents the three questions (§4.1) that any approach must
> preserve — those still hold, they are just resolved inside one commit series instead of two.
>
> **The executable spec is [`mitos-agent-implementation-plan.md`](mitos-agent-implementation-plan.md).**

**The analysis that produced the alternative: Option 4, with `hermes` deprecated from day one.**
Three facts favoured it:

- **Hermes runs on exactly one machine.** `registry/local/machines/linux-box.yaml` is the only profile
  with `hermes` in `targets:`; `windows-main` is `[antigravity, claude-app, claude-code]`. So a straight
  rename would not touch the workstation at all — and it leaves the Linux box's assistant *frozen*, not
  gone, from Stage 2 until Stage 5 (invariant #9), and that box is where the always-on chat surface
  belongs.
- **Hermes is unsupported going forward** (§2.1), so it should not sit in `KNOWN_TARGETS` as a
  co-equal. The loader emits a deprecation warning on any machine still declaring it — the decision is
  visible from the first commit, not deferred to the deletion.
- **The content is untouched** (§4.5), so the "transition" is only ever two names for one target. There
  is no half-migrated prose to reason about.

Under Option 1 those facts become consequences to accept rather than reasons to hedge: the rename
lands in one series, `hermes` never appears in `KNOWN_TARGETS` again, and the Linux box runs a frozen
assistant (its last-deployed files, unchanged) until Stage 5. The three questions of §4.1 are still
separated — into three named helpers — because the semantic distinction survives the rename even when
the transition does not.

### 4.3 The persona

`who-i-am.md`, `operating-rules.md`, `session-protocol.md`, `security.md`, and `comms-style.md` gain
`mitos-agent` in their `audience:`.

The two tree-navigation partials eventually **shrink** — their prose exists to teach a model to walk
the tree (*"`cd` into each folder and re-read its `AGENTS.md`"*), and Mitos Agent's walk is code (§5),
so the instruction pays tokens to request a job already done. But under Option 4 that trimming waits
until Hermes is retired, because Hermes still needs the full text. The `agents-md` audience keeps it
permanently, since a hand-written tree read by another tool still needs it.

### 4.4 The exclusivity check is kept, not retired

An earlier revision proposed dropping `loader._validate`'s refusal of an agentic target alongside any
coding target, on the theory that Mitos Agent never writes the code workspace so the workspace
contention the rule guards against cannot occur. **That is withdrawn.** Nothing in Part A or Part B
needs a single machine to run both classes, so deleting a guard to enable a configuration no stage
uses is unmotivated (invariant #10: boring beats clever) — and the guard is load-bearing beyond
workspace contention: the planner's role checks and the `is_hermes_machine` branch (§4.1) all assume a
machine is one class or the other. `mitos-agent` therefore *inherits Hermes's slot in the exclusion
set* — the rename swaps the name, not the rule. Keeping it is a four-place hold, not a no-op:

- `loader._validate`'s refusal (was `hermes` in the coding-clash set → now `mitos-agent`);
- `init.resolve_targets`'s mirror of the same refusal (§4.2's Option-1 spec must **not** delete it);
- `test_machine_role_exclusivity_hermes_vs_coding` and the `["hermes","claude-code"]` loader case,
  renamed to the assistant target, **assertions unchanged** — a `[mitos-agent, claude-code]` machine
  must still fail to load;
- no new `test_mitos_agent_coexists_with_coding_targets` — that test asserted the opposite of the
  decision and is not written.

The existing output-path collision check in `plan_machine` stays the second, mechanical guard beneath
this one.

### 4.5 The one-shot prompts and skills are not touched

**Nothing in `registry/` is rewritten.** The only registry edits anywhere in this plan are target-name
strings in `targets:` and `audience:` lists. Bodies, logic, destinations, and the Claude Code fallback
paths stay exactly as written:

| Asset | Change |
|---|---|
| `plan`, `plan-new-idea`, `plan-existing-iteration` | `targets:` **drops `hermes`** and gains **nothing** — see the note below. Their bodies are untouched (decision 4); they keep serving `claude-code`/`antigravity`/`claude-app`. |
| `gws` skill | `targets:` gains `mitos-agent` |
| `who-i-am.md`, `operating-rules.md`, `session-protocol.md`, `security.md`, `comms-style.md` | `audience:` gains `mitos-agent` |
| org skills (`org-software`, `org-design`, `org-marketing`) | `targets:` gains `mitos-agent` |
| every context partial (`agentic-root.md`, `assistant.md`, `projects-index.md`, project partials) | **none** |

**Why the `plan` router is dropped, not ported.** Its Step 1 is a prose tree walk, and Mitos Agent's
walk is code — so listing it on `mitos-agent` would deploy a prompt telling the model to redo the job
`route()` already did, the exact waste §5.1 exists to eliminate. So the three `plan-*` skills **drop
`hermes` from `targets:` and gain no replacement** — the runtime *is* the router. They keep serving
`claude-code`, `antigravity`, and `claude-app` exactly as today, including the "Claude Code behavior"
fallback, which stays correct because coding harnesses remain supported (§2.1). This is not a body
edit (decision 4 holds): only the `targets:` line changes, subtracting one entry. An earlier revision
implied trimming the navigation prose out of `session-protocol.md`; that is withdrawn — the partial is
unchanged, and Mitos Agent simply does not need the part it already did.

The bodies do carry 14 now-false references to Hermes (*"Action (Hermes): transfer execution to…"*,
*"target Hermes only"*). Those are a fast prose fix inside Part A, not deferred debt — they name a
harness that will exist on no machine, and leaving them would instruct a coding harness to hand off to
nothing. The implementation plan schedules them in A4, not B-Stage 5.

**Why the workspace one-shots cost nothing to keep.** They were never Hermes features. They are Mitos
skills (`gws`) calling MCP tools over a wired server; Hermes supplied a loop, and the capability lived
in the registry the whole time. Mitos Agent deploys the same skills and wires the same server, so it
inherits them by construction — no port, no rebuild.

And they are not a detour from planning; they are how a one-shot idea becomes one:

| The user says | What the harness does |
|---|---|
| "This email thread is an idea — capture it" | reads the thread, writes an idea |
| "What did I write about this last month?" | searches the store, resolves by graph ID |
| "Add the plan's first three steps to my task list" | creates tasks from the artifact |
| "Book an hour Thursday to review this plan" | creates the event |

Each is *"a user has an idea and would like to devise a plan, or iterate on a plan"* — the workspace is
the substrate the idea already lives in. What stays out is the general-assistant framing: Mitos Agent
does not exist to run your inbox. It uses your workspace because that is where your thinking is.

The tool-surface consequence is in §6.3: workspace **writes** are permitted under confirmation, and
outbound email gets a harder gate than the rest.

### 4.6 Where the new repo lives

`mitos-agent` is a **second repo inside the existing Mitos project**, not a new project. Mitos already
models this: a manifest's `repo:` accepts a list, each URL clones into its own `<basename>/`
subdirectory, and `repo_notes:` gives each a line in the project node's generated `## Navigation`
roster. The directory `<mitos project>/mitos-agent/` already exists and is empty.

```yaml
# registry/local/projects/mitos.yaml
repo:
  - git@github.com:Peccia/mitos.git
  - git@github.com:Peccia/mitos-agent.git        # new
repo_notes:
  mitos: Open Source public repository of the mitos project (where you will write
    the majority of code).
  mitos-agent: the planning harness that consumes what mitos deploys        # new
```

Three consequences worth knowing:

- **Basenames must be unique within a project.** `mitos` and `mitos-agent` are, so this compiles.
- **The roster is generated, never hand-written.** After this edit, `## Navigation` in the project's
  `AGENTS.md` lists both checkouts with their notes — so every harness learns the two-repo layout from
  the deployed context, without anyone maintaining a list.
- **One prose edit is in scope** (and it is not a prompt): `registry/context/projects/mitos.md` should
  gain a short paragraph naming the split — registry and compiler here, harness there — because the
  roster states *what* the repos are and the project's own prose explains *why*.

> **The subdirectory is scaffolding, not the destination.** `<mitos project>/mitos-agent/` exists only
> to initialize the project; at **v0.1.0** the repo moves to its own git home and is registered in the
> manifest as a second `repo:` entry, cloned back into the same place by `deploy`. Until then it is an
> unregistered working directory, so the `local_path.windows-main: Mitos` + `projects_root: D:/Projects`
> discrepancy (which resolves to a `D:/Projects/Mitos` that does not exist on this box, while the
> checkout is at `C:/Projects/mitos`) blocks nothing — but it must be reconciled before the manifest
> entry is added, or `deploy` will clone to the wrong drive.

---

## 5. The traversal engine

### 5.1 The prior art is already in the overlay

The overlay's `plan` skill opens with: *"Open the Agentic Context tree … Read the roster `AGENTS.md`
in the `Projects/` subfolder … Choose the project … Read the `AGENTS.md` within that project's
subfolder."* That is a tree walk written as prose, executed by a language model, every session, at
full token price and with no guarantee it happens. The same skill then hard-codes a capability split —
*"`plan-new-idea` and `plan-existing-iteration` target Hermes only … Do not attempt to transfer to
those sub-skills here"* — because Claude Code has no `gws` server.

Mitos Agent is the productization of those three skills: the walk becomes a parser, the router becomes
`route()`, and the capability split disappears because one runtime always has the connection.

### 5.2 What the tree already guarantees

| Guarantee | Producer that pins it |
|---|---|
| One H1; `## Navigation` / `## Workflows` / `## Tools` / `## Skills` reserved, in order | `planner.lint_node_markdown` — a violation fails `compile` |
| Connection sections headed exactly ``## <Name> (`key`)`` | `render.connection_label` — stable by design |
| Document lines as ``- **<name>** `<id>` (<date> · <type>) — <desc>`` | `graph._concise_entry`, shared by every surface |
| Repo roster as `` - `<dirname>/` — <note> ``, only inside `## Navigation` | `render.navigation_block` |
| An effort's governing org on its own routing line | `graph._effort_domain_line` |
| Progressive disclosure: lean root → roster → project node → `AGENTS_DETAILS.md` | the `agents-md` target's file layout |

### 5.3 Where a prompted harness falls short

| Failure | Why | What Mitos Agent does |
|---|---|---|
| Starts in the wrong place | opens at `cwd`, reads one context file | resolves `tree_root` before the session opens |
| Loads everything or nothing | no notion of progressive disclosure | walks root → branch → project node only |
| Re-derives the route every turn | the rule lives in prose the model re-reads | routes once, in code |
| Cannot resolve a document ID | `` `13XTaS-…` `` is an opaque string | ID + store key → server in `mcp.json` → its fetch tool |
| Ignores skill frontmatter | reads `SKILL.md` as text | honours `org_domain`, `requires_server`, `scope`, `extends_skill` |
| Drifts from the grammar silently | nothing tells it the taxonomy changed | fixture tests break in CI (§8) |

### 5.4 What ships as code

```
locate()            → tree_root, verified against the taxonomy signature
parse_node(path)    → Node{identity, navigation, workflows, tools, skills,
                           connections[{name, key, efforts[{title, org_domain,
                           goal, documents[{id, name, modified, type, desc}]}]}]}
route(message)      → Route{branch: assistant|project, project?, node_chain[]}
resolve(id, store)  → an MCP call on the right server, from mcp.json
skills(route)       → resolved SKILL.md bodies, frontmatter honoured
pack(route)         → the routed context pack handed to the model
```

Per §1.1, `route()` matches deterministically first — project slugs and names come from the tree, and
the operating root's own question (*does this involve a project or its documents?*) is a genuine
binary. Ambiguity escalates to one cheap call on the `small` model, which may be local. Failing that,
it asks.

### 5.5 The reader's tolerance policy

| Situation | Behaviour |
|---|---|
| Node matches the taxonomy | Parsed into typed sections. Normal path. |
| A needed section is absent | Report it actionably — *"run `mitos deploy`, or point `tree_root` at the mount"* — continue with what parsed. |
| A section is present but malformed | Warn once, skip the structured read, **pass that section's raw markdown into the pack.** |
| Not a Mitos tree node at all | Treat the whole file as prose context. |

**A heading typo must never end a session.** Structured parsing is an optimization over "hand the
model the markdown," and when it fails the fallback is what every other harness does anyway.

### 5.6 The one rule: the model never navigates

> The tree walk completes **before** the first model call. The model receives a routed context pack —
> `SOUL.md`, the resolved route stated rather than re-derived, the branch and project nodes, the
> skills the route pulled in, the connection wiring for that project's stores — and nothing else.

**Tokens:** the window goes to the problem, not to finding files. **Determinism:** two sessions on the
same message read the same files, which is the precondition for §9 and, per §1.1, the reason the
harness behaves the same on a small local model as on a frontier one.

---

## 6. The product

### 6.1 Message → Request Type, and the chat surface

```
Message ─▶ Request Type ─┬─ Assistant ─▶ idea refinement  ─┐
                         └─ Project   ─▶ planning         ─┴─▶ documented artifact
```

| | **Assistant → idea refinement** | **Project → planning** |
|---|---|---|
| Route lands on | `Assistant/AGENTS.md` | `Projects/<name>/AGENTS.md` |
| Inherits | the overlay's `plan-new-idea` shape + the workspace one-shots (§4.5) | `plan-existing-iteration` |
| Grounded against | the idea store, the workspace, prior artifacts | code, documents, data |
| Output | a refined idea document | a plan, in a domain-appropriate format (§6.4) |

```bash
mitos-agent capture "the connection heading renders twice for multi-store projects"
mitos-agent triage                  # short batched session: route, merge, drop
mitos-agent refine <idea-id>        # Assistant branch
mitos-agent plan   <idea-id>        # Project branch
mitos-agent export <artifact> --to <path>
```

Ideas live at `<state_dir>/ideas/<ulid>.md`, one file each, raw text verbatim, four states
(`raw → triaged → planned → dropped`). `<state_dir>` is the runtime state root, **separate from the
Mitos-managed deploy root** — see §7.

**Telegram is the remote surface.** Confirmed: mature bot API, no hosting, works from a phone, and
already in use. It ships as an opt-in surface alongside the CLI (Stage 1) and, later, a localhost web
UI.

One correction to an earlier revision, because I framed the risk wrongly. I proposed narrowing
Telegram to capture-only on injection grounds. That is the wrong control: **prompt injection arrives
in content the agent reads — an email, a shared document — not in the transport it was asked over.**
A capture-only Telegram would not reduce that risk at all, and it would block the exact use you
described: a one-shot message that starts a plan. So the real controls are:

| Control | Rule |
|---|---|
| **Sender allowlist** | A single authorized Telegram user ID. Everything else is dropped, unlogged. |
| **Confirmation on every write** | `write_artifact`, any workspace write, and `propose` require an explicit confirm reply — regardless of surface, and regardless of what any document said. |
| **Message content is data** | A message becomes an idea's text or a session turn. Instructions found inside *fetched content* are quoted to the owner, never executed. |
| **Transport disclosure** | Telegram's servers see message content. Fine for ideas and plans; state it plainly so nobody puts credentials there. |
| **Full capability otherwise** | Capture, triage, refine, and planning all work from chat. Long grounded sessions are simply nicer at a desk. |

### 6.2 Providers: paid, private, and local

**A provider port we own.** Small on purpose (complete a turn, stream, call tools, count tokens),
because it is also the seam that makes the runtime testable offline (§8). A breadth library may sit
*behind* it; it never leaks through. **The port is proven with two adapters, not four:** `fake`
(deterministic, for tests), `ollama` (local, the privacy story), and **one** real cloud provider —
**Anthropic**, chosen because Ollama speaks an OpenAI-shaped API, so Anthropic is the maximally
*different* tool-calling dialect available and therefore the honest test that the seam is a port and
not a wrapper. OpenAI and Gemini adapters are deferred until a concrete need appears (invariant #10);
adding one is a new adapter behind the same port, never a design change.

**Roles, not models:**

| Role | Used for | Sensible default |
|---|---|---|
| `small` | route ambiguity, capture titling, triage | a local model — free, private, offline |
| `main` | the session itself | whatever the user prefers |
| `critic` | the adversary pass (opus-1 P6) | *a different model from `main`, preferably a different provider* |

With only Anthropic and Ollama wired at first, `critic` is thin — a different provider means Ollama, or
it degenerates to a different Anthropic model. That is acceptable at this scope; it strengthens the
moment a third adapter lands, and nothing depends on `critic` being cross-provider to function.

**Prompts are written to §1.1's law:** short, imperative, no vendor-specific tricks, no dependence on
a particular tool-calling dialect, no reliance on very long context. Anything a prompt would have to
police, code polices instead. The test is §9's cross-model eval, not an opinion.

**Key handling, in the order tried:** OS keychain (Windows Credential Manager, macOS Keychain,
libsecret) → environment variables → a gitignored `0600` env file, mirroring Mitos invariant #6. Keys
never enter a transcript, log, artifact, plan, or model context; `mcp.json` holds a *path* to an env
file and no value. Redaction happens at the port, with a test per backend. **`--offline` refuses any
non-local provider.**

### 6.3 The tool surface

No code-writing tool is registered — not denied by policy, absent. No `Write`, no `Edit`, no general
`Bash`. The invariant, stated precisely:

> **Never writes source code. Never writes the registry.** Writes to the user's *own workspace* are
> the deliverable and the assistant surface — permitted, guarded, and confirmed.

| Tool | Surface | Guard |
|---|---|---|
| `read`, `search` | the filesystem | read-only |
| `observe` | an allowlist (`pytest -q`, `git log`, `git diff`, …) | timeout-bounded; output captured as an anchor |
| MCP read tools | from `mcp.json` | always available |
| `write_idea` | `<state_dir>/ideas/` | path guard |
| `write_artifact` | the project's store folder, or a configured output path | folder guard **+ confirmation** |
| **MCP workspace writes** | docs, tasks, calendar, drafts (§4.5) | **confirmation, with the exact call shown** |
| **Outbound email send** | — | **a harder gate: drafts by default; sending needs a separate, explicit confirm naming the recipients** |
| `propose` | shells `mitos propose` | payload shown to the owner first |

Outbound email is singled out because it is the only action that reaches a third party and cannot be
undone. Everything else the owner can delete.

**A declarative preferences table sits above the per-call guards.** The whiteboard drew it —
`Email=False, Drafts=True, Delete Doc=False` — and it is a real feature the guards alone do not
provide: the guards ask *every time*; a preference lets the owner state a standing policy once and
stop being asked, or forbid a surface outright. It is authored, inspectable, and versioned (a
`[preferences]` block in Mitos Agent's own `config.toml`, or a machine-profile field), and it
**composes with** §6.3's guards rather than replacing them — it can only *narrow*:

```toml
[preferences]
email_send      = false   # forbid the surface entirely — never offered, not just confirmed
drafts          = true    # drafting allowed (still shown before it lands)
delete_document = false    # forbid
# a surface with no entry falls through to its default guard (confirm-before-write)
```

Resolution is programmatic (§1.1): a tool call checks the preference first (`false` → refuse and say
so, `true`/absent → fall through to the tool's own guard), so a confirmation prompt only ever appears
for a surface the policy permits. This is deliberately *not* [`planning-harness-opus-2.md`](planning-harness-opus-2.md)'s
per-harness permission profile (rejected in §13, because that could not hold an idea overnight) — it
is a user-authored policy over Mitos Agent's *own* single tool surface, orthogonal to which harness is
running. It ships with the session runtime (Stage 5) and has a refusal test per forbidden surface.

Database access keeps [`planning-harness-opus-2.md` §5](planning-harness-opus-2.md)'s hard gate:
read-only at the credential level or no access; results as counts and shapes, never copied rows.

### 6.4 Output profiles — the differentiator

Mitos Agent conforms to a format chosen by the work's domain or objective — an implementation plan,
Agile stories for a Kanban board, an ADR, a PRD, a design brief. Format, content, and destination are
the product.

```yaml
name: agile-stories
domain: org-software                  # optional — matches an effort's orgDomain
sections:
  - epic:            {required: true, max_words: 60}
  - stories:         {required: true, item: {as_a, i_want, so_that, acceptance_criteria[]}}
  - out_of_scope:    {required: true}
  - anchors:         {required: true}   # no assertion without an anchor
destination: connection                # connection | file
```

**Selection is programmatic (§1.1), and every step is optional except the last:**

```
--profile flag  →  the effort's orgDomain  →  the project's default  →  built-in default
```

**Orgs are an enhancement, never a requirement.** With no orgs, the second step does not match and
selection falls through. The baseline is exactly what §1 claim 4 promises: the `AGENTS.md` tree and
the user's connections, nothing else. A retired org skill behaves the same way — fall through, one
warning naming the orphaned profile, no error.

**Where profiles live.** Mitos Agent ships the defaults. User profiles arrive through a mechanism
Mitos already has: a skill with `targets: [mitos-agent]` whose `templates/` directory holds the
profile — `loader._SKILL_RESOURCE_DIRS` already includes `templates/`. No new lane, no new schema.

The shipped `implementation-plan` profile is
[`planning-harness-opus-1.md` §9](planning-harness-opus-1.md)'s Plan Object, its compression rules
becoming that profile's lint — one profile among several rather than *the* output format.

### 6.5 Destination: the connection, or a file

The evidence the connection is right is already in this repo's graph — `0.1.3-batch3-fleet-view`,
`0.1.2-Workflow-Expansion`, `0.1.4-Dynamic-Context-Enhancements-Plan` are plans, in the store, indexed,
surfaced to every harness — and in `plan-new-idea`, which files them under a project's
`AssistantCollaboration/` folder.

```
session → artifact written to the store   (write_artifact)
        → `mitos propose --kind graph`    (the new document, mapped)
        → maintainer accepts in the console
        → `deploy` → the artifact appears in every project's AGENTS.md
        → any harness now sees it as authoritative context
```

The first circuit where output re-enters the moat *as context*. **A local file is a first-class
destination**, not a fallback — `document_store: none`, an offline session, or a profile declaring
`destination: file`, which may be inside a repo so a plan is reviewable beside its diff.

### 6.6 Freshness

[`planning-harness-opus-1.md` §8](planning-harness-opus-1.md)'s design: anchors carry content hashes;
`status` reports `fresh` / `stale` / `conflict` / `landed`. Across a repo boundary this is a new
mechanism, not a new caller — about fifty lines of hashing, reimplemented rather than imported.

### 6.7 No interface to coding harnesses

No MCP server for them to call, no plugin, no `.claude/commands/` emission, no execution tracking. The
artifact exists — in the store or as a file — and the user carries it.

### 6.8 Residue — a mandatory closing step

A session does not complete without a residue answer: the graph candidate for the artifact itself
(§6.5, which fires every time), plus either further candidates or an explicit *"nothing else; here is
what I considered."* Silence is not a pass.

### 6.9 Memory — what kind a planning harness actually needs

Memory was never dropped; it was deferred until there was a bar to judge it against. The bar is §1.1
and the moat thesis, and together they give a clear answer.

**The principle:** *long-term memory that compounds belongs in the moat, not in a private blob.*
Anything the harness learns that is worth recalling next month is exactly what invariant #3's inbox is
for — it becomes reviewable, portable, and deployed to **every** tool, not just this one. A private
vector store would be a second source of truth the user cannot inspect, which is the thing Mitos
exists to prevent. So the design question is not "how much memory" but "which tier does each thing
belong in," and two of the three tiers already exist.

| Tier | Holds | Lives in | Status |
|---|---|---|---|
| **Working** — one session | the transcript, the Ground Ledger | RAM, then `<state_dir>` at session end | new |
| **Project** — across sessions on one effort | the persisted Ground Ledger, the session index | `<state_dir>/` | new |
| **Durable** — across everything | ideas, artifacts, learned constraints and preferences | the idea store, the connection, **and the registry via residue** | **already exists** |

Judged individually:

| Candidate | Verdict |
|---|---|
| **Persisted Ground Ledger, per plan** | **Yes — the highest value per byte.** Bounded, hash-validated, and it lets a resumed session skip re-grounding instead of re-reading everything. This is the one genuinely new piece of memory the design needs. |
| **Session index** — one line per session: date, idea, project, route, profile, artifact ID, decisions taken | **Yes.** Small, greppable, no embeddings. It is what makes *"what did we decide about X?"* answerable, and it composes with the graph rather than duplicating it. |
| **Raw transcripts** | **Keep locally for 30 days, gitignored, never uploaded**, with `--keep` to pin one and `purge` to drop them early. They are debugging and eval material (§8), not a recall mechanism. Highest value to keep, highest risk to store — so they expire by default and live where the user can delete them. |
| **Learned constraints and preferences** | **Yes, but as residue** (§6.8) — into the registry, where they become context every harness reads. Never a private store. This is the tier Hermes's memory was doing badly. |
| **Semantic / vector recall over past conversations** | **Not first.** Fuzzy, unauditable, and largely duplicative once artifacts are graph-indexed and sessions are indexed. If the session index proves insufficient, add embeddings **over the idea store and session index only**, computed by a local model, never over raw transcripts. |

The shape of the answer is the same as everywhere else in this design: prefer the mechanism you can
inspect, keep the fuzzy thing out until something concrete demands it, and let what compounds flow
back into the moat.

---

## 7. Repo shape and runtime

```
mitos-agent/
  AGENTS.md            # the repo's own agent-facing context — Mitos deploys it here
  src/mitos_agent/
    tree/         # §5 — locate, parse_node, route, resolve, skills, pack
    providers/    # §6.2 — the port + fake | ollama | anthropic (openai/gemini deferred)
    secrets/      # keychain → env → 0600 file; redaction at the port
    capture/      # the idea store and its four states
    memory/       # §6.9 — ground ledger persistence, session index, retention
    planning/     # the phase machine, gates
    profiles/     # §6.4 — schema, selection, lint, built-ins
    artifact/     # destinations: connection | file; anchors and freshness
    runtime/      # session loop, tool surface, write guards, message surfaces
    cli.py
  docs/                # §8.2 — one contract page per boundary
  tests/
    fixtures/tree/     # real emitted Mitos trees, checked in
```

**Python 3.11+**, matching Mitos. **No single-vendor agent SDK** — §6.2 decides it. The session loop
is ours, kept small and boring, over the provider port.

**One install root; memory is a dot-directory inside it.** Mitos Agent installs into a single root —
`assistant_root` (e.g. `~/MitosAgent`), the SAME directory the `agents-md` operating tree mounts at.
Mitos requires `agents-md` on a `mitos-agent` machine (`loader._validate`) precisely so this holds: the
harness's own files and the tree it traverses are one folder.

```
~/MitosAgent/                # assistant_root — the one install root
  SOUL.md  mcp.json  skills/ # the mitos-agent target's files (Mitos deploy)
  AGENTS.md  Assistant/  Projects/   # the agents-md operating tree (Mitos deploy)
  .local-memory/             # the harness's RUNTIME state (the runtime writes; Mitos never does)
```

The two writers stay cleanly separated by **one rule: the traversal engine ignores dot-directories.**
`.local-memory/` therefore never enters a pack, a roster, or Mitos's own walk — and because Mitos only
tracks what it *plans*, a runtime dir can never become an orphan or be pruned. That rule is the whole
guard; state-vs-context is a `.`-prefix, not a second root to reason about.

| Holds | Written by | Location |
|---|---|---|
| `SOUL.md`, `skills/`, `mcp.json`, the tree (§3.1) | Mitos `deploy` | `assistant_root` |
| ideas, ground ledgers, session index, transcripts (§6.9) | the runtime only | `<assistant_root>/.local-memory/` |

`MITOS_AGENT_STATE` overrides the memory location (default `<assistant_root>/.local-memory/`) for the
cases that need it — a read-only or synced install root, memory on a different disk, two harness
instances against one tree. It gets a contract page (§8.2). **Two lookalike paths remain, one dot
apart:** `~/MitosAgent` (the install root) and `~/MitosAgent/.local-memory` (its runtime state) — name
them explicitly wherever they appear. The earlier design used a *separate* `~/.mitos-agent` deploy root
and an OS-specific `<state_dir>`; both were collapsed into this single root once `agents-md` became a
hard requirement.

---

## 8. Test-driven development and documentation

### 8.1 Tests first, in five layers

**A verb, a profile, or a schema field lands together with its validation, its contract page, and its
acceptance test — or not at all.** Tests precede implementation; every layer below runs offline.

| Layer | Covers | Rule |
|---|---|---|
| **Contract** | `tests/fixtures/tree/` — real emitted Mitos trees, checked in, parsed and asserted | A change to Mitos's rendered grammar breaks CI **loudly**. Includes malformed nodes pinning §5.5. |
| **Unit** | `route`, profile selection, anchor hashing, section lint, retention | No network, no model, no filesystem beyond `tmp_path`. |
| **Runtime** | the session loop against the port's **`fake` adapter** | The whole agent is testable with no provider. This is why the port must be ours. |
| **Guard** | one refusal test per write surface, per secret backend, per forbidden preference (§6.3), for the Telegram allowlist, and for the email-send gate | Security-relevant, therefore never skipped. |
| **Eval** | `mitos-agent eval` — §9, **across model tiers** | Marked `live`, excluded from the default run, required on release. |

CI runs layers 1–4 with no network available — enforced, not assumed. Coverage gates apply to `tree/`,
`profiles/`, and the guards; a global percentage is theatre.

### 8.2 Documentation for two readers

- **One contract page per boundary** — the tree grammar and its tolerance policy, the profile schema,
  the provider port, the write guards, the preferences schema (§6.3), the `<state_dir>` resolver (§7),
  `bootstrap.json`, the memory tiers and their retention.
- **Every example is a fixture.** The example in a contract page is the file the tests parse, so prose
  and code cannot diverge quietly. A stale example fails CI.
- **The repo's own `AGENTS.md` is agent-facing context**, authored in Mitos and deployed here — the
  product eats its own output.
- **Simplified Technical English** for procedures and contract pages; the overlay already carries the
  skill.
- **Mitos-side reciprocity:** a second public repo parsing the taxonomy promotes
  [`agents-md-structure.md`](../agents-md-structure.md) from internal note to published contract.

---

## 9. Consistency is the deliverable — measured across models

| Axis | Test | Passes when |
|---|---|---|
| **Run-to-run** | the same idea, twice, same model, fresh sessions | Same shape. Wording may differ. |
| **Model-to-model** | the same idea on a `small`-tier local model and a frontier model | **Same anchors read, same profile selected, same section structure.** Only prose quality may differ. |

The second axis is the direct test of §1.1. If a smaller model reads different files or emits a
different structure, something that should be code is still living in a prompt — and the fix is to
move it, not to write a better prompt. That makes the eval suite a design-conformance check.

---

## 10. Build order

A format experiment sits *before* Stage 1 as an unnumbered prerequisite, not a kill gate: write the
two profile specs (`implementation-plan`, `agile-stories`) as plain Markdown, hand-write three
artifacts against real Mitos work, execute them with a coding harness, and see whether the formats
help. It is cheap and worth doing, but it exercises none of §1.1 (no routing, no traversal, no pack),
so it cannot be the gate that decides the programme — it feeds Stage 5's profile work.

| Stage | Ship | Repo | Killed if | Gate |
|---|---|---|---|---|
| **1** | `git init` at `<project>/mitos-agent/`; register it in the project manifest and fix the path discrepancy (§4.6). Then the **traversal engine** (§5) as a CLI printing the routed pack, against checked-in fixtures, with §5.5's tolerance policy. **No model.** | agent | The tree can't be parsed reliably, or the pack isn't materially leaner than the tree. | **routing is deterministic** — the same message routes identically across runs, and the pack is materially leaner than the tree. No model, because `route()` is deterministic-first. |
| **2** | **Option 1** (§4.2): the whole `hermes` → `mitos-agent` rename in one commit series — target spec, the three helpers, the `agents-md` fourth gate renamed-not-rekeyed, the exclusivity check kept (§4.4), the `settings:` lane deleted, machines, prose frontmatter, docs, tests. Hermes freezes on its last-deployed files here. | mitos | The three questions can't be separated cleanly. | Part A's verification gates (implementation plan A5). |
| **3** | The provider port + secrets (§6.2): `fake`, `ollama`, and **Anthropic** — OpenAI/Gemini deferred. | agent | Multi-provider costs more than the local-model privacy story is worth. | **cross-model conformance** — the *same* routes and the same profile selected on a `small` local model and a frontier one (§9 axis 2). This is the direct §1.1 check and needs the port. |
| **4** | `capture` + idea store + `triage`, CLI only. Standalone value with no planning. | agent | Ideas captured, never triaged — the store is a graveyard. | capture is sub-second and offline; triage routes against the real tree; duplicates merge. |
| **5a** | Session runtime core: the phase machine and gates, the tool surface with its guards, the **preferences table** (§6.3), and `write_artifact`. | agent | The loop doesn't survive contact with real ideas. | one full session ends with an artifact; a passing refusal test per write surface **and** per forbidden preference. |
| **5b** | Profiles (schema, selection, lint, built-ins), the three memory tiers with 30-day transcript retention (§6.9), and the workspace one-shots. | agent | Profiles/memory don't earn their complexity. | the **full §9 eval** — run-to-run *and* model-to-model structure conformance — passes on a real plan session. |
| **6** | Telegram (§6.1), with its allowlist and confirmation guards. | agent | — | a non-allowlisted sender is dropped, unlogged; no write without a confirm reply. |
| **7** | Grounding past the repo — documents by graph ID, then the read-only DB path. | agent | The disagreements it catches cost less than the access does. | — |
| **8** | `deploy --prune` retires the frozen Hermes artifacts; `mitos-agent` moves to its own git remote and gains its manifest `repo:` entry (§4.6) — after reconciling the `D:`/`C:` path. | mitos | — | — |

**The gate moves to where the thesis lives.** Stage 1 tests determinism with no model, because if the
tree can't be parsed the premise of §1 claim 3 is wrong — worth knowing in week one. Stage 3's gate is
the model-to-model check, because that is §1.1's actual bet and it needs the port; the `fake` adapter
cannot stand in for it (it is deterministic by construction). Stage 5 splits so the one stage that can
truly fail has an interior checkpoint: **5a** proves the loop and its guards, **5b** proves profiles
and memory against the full §9 eval. **Stage 3 before Stage 5** stands — the port is what makes the
runtime testable, so it precedes the thing it tests. **The accepted cost:** Hermes runs frozen from
Stage 2 until 5a, then is pruned at Stage 8. Stage 2 can be deferred until Stage 1 has proven the
parser — no reason to freeze the assistant before its replacement is shown to work at all.

---

## 11. Non-goals

- **It does not write code.** Not a scaffold, not a stub, not a type signature.
- **It does not interface with coding harnesses** (§6.7).
- **It does not exist to run your inbox.** It uses the workspace in service of ideas and plans (§4.5);
  general assistant duty is not the product.
- **It does not estimate time** or **track execution**.
- **It does not become a second Mitos.** No registry, no compiler, no drift engine.
- **It does not keep memory the user cannot inspect** (§6.9).
- **It does not fork the tree format.** A new field is a Mitos change, never a private extension.
- **It does not require a framework.** Invariant #10 holds.

---

## 12. Naming

Repo `mitos-agent`, CLI `mitos-agent`, product **Mitos Agent**. *Metis* (opus-1) is a better name in
isolation and a worse one here: two Greek-named products in one thread doubles the explaining.

---

## 13. The ledger

| From | Accepted | Rejected, and why |
|---|---|---|
| **gemini-1** | Plans carry the delta only. Skill curation. | "A thin CLI wrapper" as the last step. The wrapper is the product. |
| **opus-1** | The phase machine, gates, effort tiers, Ground Ledger, the Plan Object, its lint, the staleness states. | Its home — all of it moves to the new repo. Its **primacy**: the Plan Object is one profile among several (§6.4). "A new caller, not a new mechanism" is false across a repo boundary (§6.6). |
| **opus-2** | Three-substrate grounding and the disagreement rule. Unknown triage and the stopping condition. The reproducibility metric, now two-axis (§9). The *idea* of a declarative permission policy — reshaped in §6.3 into a user-authored preferences table over Mitos Agent's own single tool surface (the whiteboard's `Email=False, Drafts=True`), composing with the per-call guards. | **§3's form** — a *per-harness* permission profile can't hold an idea overnight (§6.3); the preferences table keeps the intent without the per-harness framing. **§7** — the artifact of record belongs in the connection (§6.5). **§9** — "the workstation, not the Hermes box" is moot: it *takes over from* Hermes. |
| **whiteboard 1** | Three layers, one-way arrows, never writes code. | — |
| **whiteboard 2** | Message → Request Type onto the tree's Assistant/Project split. Capture as first-class. The artifact landing in the connection. | — |
| **the overlay's `plan-*` skills** | The router, the New Idea / Existing Project fork, the `AssistantCollaboration/` destination, and the `gws` workspace capability — prior art, validated in use (§4.5, §5.1). | The prompted tree walk and the per-harness capability split, both artefacts of a rented runtime. |

---

## 14. Remaining questions

**Effectively closed; two design surfaces remain to be pinned down in their contract pages, neither
blocking.** The long-settled decisions still hold: public licensing; no schema handshake;
deterministic-then-cheap routing; the critic as a config role (now *a different model, preferably a
different provider* — §6.2); destination by profile; no coding-harness interface; the one-shot prompts
dropped-not-ported (§4.5); orgs optional (§6.4); model-agnosticism as a law (§1.1); Telegram (§6.1);
memory in three tiers with a 30-day transcript window (§6.9); two supported harness classes (§2.1);
the repo's home and its v0.1.0 move (§4.6); and the migration approach — **Option 1, straight rename**
(§4.2), with Hermes *frozen* not killed at Stage 2 and the exclusivity check **kept** (§4.4).

Two things gained shape during this revision and get pinned when their contract pages are written
(§8.2), not before:

- **The preferences schema** (§6.3) — the exact `[preferences]` keys and their fall-through semantics.
- **The `<state_dir>` resolver** (§7) — the env var, the per-OS defaults, and the retention verbs that
  key off it.

This document is the design. The executable spec, with the exact per-file edits, commit sequence,
test changes, and verification gates, is
**[`mitos-agent-implementation-plan.md`](mitos-agent-implementation-plan.md)**.

Two things remain worth *doing* rather than deciding, both cheap and both scheduled in that plan:

- **The format experiment is worth running early** — hand-write three artifacts in the two profiles
  and note whether they reduce rediscovery. It is a *prerequisite that feeds Stage 5b's profiles*, not
  the kill gate and not a §9 test (§9 needs the traversal engine, which is Stage 1); do not let a
  passing format experiment read as validation of §1.1.
- **Reconcile the `D:` / `C:` project path** before the manifest gains its second `repo:` entry
  (§4.6). It blocks nothing today.
