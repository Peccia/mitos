# Mitos Agent — Implementation Plan

> **Status:** ready to execute. Nothing in this plan has been applied. It is written to be picked up
> cold, by a person or an agent, without re-deriving anything.
>
> **Design authority:** [`mitos-agent-platform.md`](mitos-agent-platform.md). This document does not
> re-argue design; it says exactly what to change, in what order, and how to know it worked. Where a
> step needs a rationale, it cites the design section rather than repeating it.
>
> **Two parts, independently executable.** **Part A** renames the `hermes` target to `mitos-agent`
> inside this repo. **Part B** builds the `mitos-agent` product in its own repo. Part A is a
> self-contained refactor; Part B does not depend on it until B-Stage 3.
>
> **Verified against the working tree** on 2026-08-09. Every line number, symbol, and count below was
> read from the source, not estimated. Line numbers drift as edits land — treat them as locators, and
> trust the symbol names.

---

## 0. Decisions locked

| # | Decision | Where specified |
|---|---|---|
| 1 | Mitos Agent is a separate, public, open-source repo | design §1, §2 |
| 2 | It replaces the `hermes` target; Mitos then supports exactly two harness classes | design §2.1 |
| 3 | Migration approach: **Option 1, straight rename**, all in one commit series | design §4.2 |
| 4 | **No skill body, prompt, or context partial is rewritten** — only `targets:`/`audience:` strings | design §4.5, and §A6 below |
| 5 | Workspace one-shots are retained; they are skills + MCP, not a port | design §4.5 |
| 6 | A provider port we own, proven with `fake` + Ollama + **Anthropic**; OpenAI/Gemini deferred | design §6.2 |
| 7 | Programmatic before judgment — the model decides content only | design §1.1 |
| 8 | Output format chosen by domain, via pluggable profiles | design §6.4 |
| 9 | Artifact destination: the connection, or a local file | design §6.5 |
| 10 | Chat surface: Telegram, sender-allowlisted, writes always confirmed | design §6.1 |
| 11 | Memory in three tiers; transcripts kept 30 days | design §6.9 |
| 12 | Repo lives at `<mitos project>/mitos-agent/`, moves to its own git home at v0.1.0 | design §4.6 |

---

# PART A — Mitos: the `hermes` → `mitos-agent` rename

## A1. Blast radius, measured

`hermes` (case-insensitive) appears **~480 times**. Verified per-file counts:

**Code — 127 refs**

| File | Refs | Nature |
|---|---|---|
| `build/agentic/planner.py` | 52 | dispatch, `_plan_hermes`, 6 gate sites, comments |
| `build/agentic/loader.py` | 18 | `KNOWN_TARGETS`, exclusivity check, `hermes_settings` validation, comments |
| `build/agentic/render.py` | 18 | `_machine_value`, `render_skill`, `hermes_mcp_block`, the settings block |
| `build/agentic/init.py` | 15 | presets, path keys, `resolve_targets`, comments |
| `build/mitos.py` | 10 | the `init` wizard's role question |
| `build/agentic/graph.py` | 7 | docstrings only |
| `build/agentic/review.py` | 4 | 3 comments + **1 functional** (`propose_new_org_domain`) |
| `build/agentic/commands.py` | 1 | comment |

**Tests — 184 refs:** `test_targets.py` 78, `test_loader.py` 48, `test_review.py` 23,
`test_commands.py` 19, `test_personalization.py` 8, `test_graph.py` 4, `conftest.py` 4.

**Config — 33 refs:** `targets/hermes.yaml` 23, `machines/example-linux.yaml` 9,
`machines/example-windows-secondary.yaml` 1.

**Core prose — 92 refs:** `README.md` 20, `AGENTS.md` 18 *(generated)*,
`registry/context/projects/mitos.md` 18 *(the source of that generated file)*, `registry/README.md` 17,
`docs/managing-state.md` 9, `docs/org-templates.md` 6, `docs/authoring-capabilities.md` 5,
`docs/agents-md-structure.md` 3, `docs/operator-console.md` 3, `docs/targets/claude-app.md` 3,
`targets/agents-md.yaml` 4, `targets/antigravity.yaml` 2, `targets/claude-code.yaml` 2, plus 1 each in
`docs/targets/antigravity.md`, `docs/targets/claude-code.md`, `docs/connectors/google-workspace.md`,
`registry/templates/org/{design,marketing,software}-firm/session-protocol.md`,
and 2 in `registry/templates/org/README.md`.

**Registry frontmatter — 21 refs:** 5 identity partials, 4 core context partials, 7 core skills
(`graph-bootstrap`, `gws`, `new-session`, `org-design`, `org-marketing`, `org-software`,
`project-update`), plus prose mentions inside `graph-bootstrap` (3) and `new-session` (2).

**Overlay (gitignored) — 34 refs:** `registry/local/machines/linux-box.yaml` 10,
`registry/local/skills/plan/SKILL.md` 8, `plan-existing-iteration` 3, `plan-new-idea` 3,
`apdict-ops-logs` 2, `simplified-technical-english` 1, `software-yagni-planner` 1, `ux-design-skill` 1,
and 6 context partials at 1 each.

## A2. The naming map

Apply these in order. Everything else is prose and follows the last two rows.

| From | To | Notes |
|---|---|---|
| `targets/hermes.yaml` | `targets/mitos-agent.yaml` | rewritten, not renamed — see A3.1 |
| `"hermes"` *(target string)* | `"mitos-agent"` | hyphen, matching every other target key |
| `hermes_home` *(path key)* | `mitos_agent_home` | |
| `hermes_config` *(path key)* | **deleted** | no third-party config file to merge into |
| `hermes_settings` *(machine key)* | **deleted** | the whole settings lane retires |
| `_plan_hermes` | `_plan_mitos_agent` | |
| `hermes_sk_spec` / `hermes_selected_skills` | `agent_sk_spec` / `agent_selected_skills` | |
| `render.hermes_mcp_block` | `render.mitos_agent_mcp_config` | shape changes — A3.4 |
| `render.hermes_settings_block`, `_HERMES_SETTINGS_LEAVES`, `_HERMES_SETTINGS_WHOLE_KEYS` | **deleted** | |
| `is_hermes` *(local, `mitos.py`)* | `is_agent` | |
| `hermes/` *(dist_rel prefix)* | `mitos-agent/` | |
| `Hermes` *(prose)* | `Mitos Agent` | |
| `hermes` *(prose, lowercase)* | `mitos-agent` | when naming the target |

**Python identifiers use `mitos_agent`; target strings and YAML keys use `mitos-agent`.** A blind
global replace will produce invalid Python — do not run one.

## A3. The commit series

Eight commits. Each is independently reviewable; the suite is green only at the end of A3.8, which is
expected and stated per commit.

### A3.1 — `targets/mitos-agent.yaml` (new), `targets/hermes.yaml` (deleted)

The new spec is the old one minus `settings:`, with the MCP block changed from a `yaml_merge` into a
third party's `config.yaml` to a whole file Mitos owns (design §3.1).

```yaml
# Target: Mitos Agent — the first-party agentic planning harness.
# Replaces the retired `hermes` target. Consumes SOUL.md, a skills tree, mcp.json, and the
# assistant AGENTS.md tree (produced by the agents-md target on the same machine).
#
# Every output here is a WHOLE FILE: Mitos Agent's config belongs to Mitos, so invariant #7
# (surgical merges for tool-owned config) does not apply to this lane.
target: mitos-agent

context_file:
  sources: [identity/who-i-am.md, identity/operating-rules.md, identity/security.md, identity/comms-style.md, identity/session-protocol.md]
  deploy_to_key: mitos_agent_home
  filename: SOUL.md
  drift_policy: protect

skills:
  include_target: mitos-agent
  mode: copy
  deploy_to_key: mitos_agent_home
  subdir: skills/{category}/{name}
  frontmatter: mitos-agent
  drift_policy: harvest

mcp:
  filename: mcp.json
  deploy_to_key: mitos_agent_home
  # No `server_alias:` — the whole-file output carries EVERY store in the machine's
  # `document_store:` list, keyed by server name (A3.3's _agent_servers). A single hard-coded
  # alias would defeat §5.4's resolve(id, store) for a multi-store project.
  render: mitos_agent_mcp_config
  drift_policy: protect
```

Carry over the old file's explanatory comments on skill curation (the `skills: {mitos-agent: {include:}}`
machine-profile block) — they are still accurate and still needed.

*Green?* No. `compile` fails on the unknown target until A3.2.

### A3.2 — `loader.py`

1. **L14** — `KNOWN_TARGETS = {"mitos-agent", "claude-code", "antigravity", "agents-md", "claude-app"}`
2. **L785–797** — **keep** the machine-role exclusivity block; `mitos-agent` inherits Hermes's slot in
   the coding-clash set. Change `if "hermes" in targets:` → `if "mitos-agent" in targets:`, the
   `_CODING_TARGETS` set is unchanged, and the error message names the assistant target. Do **not**
   delete it (design §4.4, reversed from an earlier revision): nothing in the programme needs a
   both-classes machine, the planner's role checks and the `is_hermes_machine` branch assume one class
   per machine, and deleting a guard to enable an unused configuration is unmotivated (invariant #10).
   `plan_machine`'s output-path collision check stays the second, mechanical guard beneath it.
3. **L859–881** — **delete** the whole `hermes_settings` validation block.
4. Comments at **L19, L21, L43, L137, L139, L550, L698** — prose rename.

> **Check while here:** machine validation rejects unknown *targets* (L782) but does not appear to
> reject unknown *top-level machine keys*. If that holds, a leftover `hermes_settings:` in a profile
> is silently ignored rather than erroring — which is why A3.7 removes it explicitly rather than
> relying on a validation failure to catch it. Confirm before relying on either behaviour.

*Green?* No. `planner` still references the old names.

### A3.3 — `planner.py`

**The dispatch (L65–74):**
```python
elif target == "mitos-agent":
    outputs += _plan_mitos_agent(reg, machine_name, spec, paths)
```

**The three questions become three helpers** (design §4.1). Add near the top of the module:

```python
# The single assistant-harness target. These three predicates all test it today, but they ask
# genuinely different questions and must not be collapsed into one — see docs/concepts/
# mitos-agent-platform.md §4.1.
ASSISTANT_TARGET = "mitos-agent"

def deploys_org_content(machine) -> bool:
    """Question A — do org skills actually land on this machine? Gates the org-domain table
    and every per-effort routing line. A machine can reach the tree without deploying org
    skills, and must then render `orgDomain` as inert metadata."""
    return ASSISTANT_TARGET in machine.get("targets", [])

def hosts_assistant_tree(machine) -> bool:
    """Question B — does this machine already host the operating tree at its root, with a
    SOUL.md carrying the persona? Nothing to do with orgs."""
    return ASSISTANT_TARGET in machine.get("targets", [])

def deploys_assistant_skills(reg, machine) -> bool:
    """Question C — does this machine deploy the assistant's skill set? Needs the target spec,
    not just a boolean."""
    return bool(ASSISTANT_TARGET in machine.get("targets", [])
                and (reg.targets.get(ASSISTANT_TARGET) or {}).get("skills"))

# NOTE: a FOURTH gate lives at L1193 — `is_hermes_machine = "agents-md" in targets` — and is NOT
# one of these three. It keys off `agents-md`, not the assistant target, and decides graph-AGENTS.md
# vs CLAUDE.md-stub. The rename fixes only its Hermes-flavoured NAME (→ `is_assistant_tree_machine`
# or similar); it stays keyed on "agents-md". Do not fold it into hosts_assistant_tree().
```

**Call sites:**

| Line | Was | Becomes |
|---|---|---|
| 418 (`_plan_graph_tree`) | `org_routing = "hermes" in …` | `org_routing = deploys_org_content(machine)` |
| 772 (`_plan_agentic_tree_mounts`) | `if "hermes" in …: return []` | `if hosts_assistant_tree(machine): return []` |
| 805 (`_emit_tree`) | `org_routing = "hermes" in …` | `org_routing = deploys_org_content(machine)` |
| 1015–1018 (`_plan_agents_md`) | `hermes_sk_spec` / `hermes_selected_skills` | `agent_sk_spec` / `agent_selected_skills`, gated on `deploys_assistant_skills(reg, machine)` |
| 1022 (`_plan_agents_md`) | `org_routing = "hermes" in …` | `org_routing = deploys_org_content(machine)` |
| 1045 (`_plan_agents_md`) | `if "hermes" in …:` drop identity sources | `if hosts_assistant_tree(machine):` |
| 1193, 1197, 1206, 1257 (`_plan_claude_code`) | `is_hermes_machine = "agents-md" in …` (the **fourth gate**) | rename the local to `is_assistant_tree_machine`; **keep it keyed on `"agents-md"`** — not the assistant target. Name-only change; behaviour identical. |

**`_plan_hermes` → `_plan_mitos_agent`** (L1120+). Within it:
`paths.get("hermes_home")` → `mitos_agent_home`; every `target="hermes"` → `"mitos-agent"`; every
`dist_rel=f"hermes/…"` → `f"mitos-agent/…"`; `_sections(reg, cf["sources"], "hermes")` →
`"mitos-agent"`; `render.render_skill(skill, "hermes", …)` → `"mitos-agent"`;
`_skill_resource_outputs(…, "hermes", …)` → `"mitos-agent"`.

**Replace the MCP merge** with a whole-file JSON output that carries **every wired store, not just
`gws`** (design §3.1). `_gws` resolves exactly one hard-coded server; the new output loops the
machine's `document_store:` list (via `loader.document_stores`, the same normalizer the graph lane
uses) and resolves each server's per-machine URL the way `_gws` does for one. This is what makes
§5.4's `resolve(id, store)` implementable for a multi-store project.

```python
mcp = spec["mcp"]
servers = _agent_servers(reg, machine_name)   # {alias: resolved-server-dict} over document_stores()
                                              # — generalizes _gws; None/empty → no mcp.json
if home and servers:
    deploy_path = f"{home.rstrip('/')}/{mcp['filename']}"
    outputs.append(Output(
        target="mitos-agent", kind="json", deploy_path=deploy_path,
        dist_rel=f"mitos-agent/{safe_rel(deploy_path)}",
        content=_json(render.mitos_agent_mcp_config(servers)),
        drift_policy=mcp.get("drift_policy", "protect"), lane="connections",
        sources=["connections/servers.yaml"],
    ))
```

Add `_agent_servers(reg, machine_name)` beside `_gws`: iterate `document_stores(machine["document_store"])`,
skip `none`, look each up in `reg.servers["servers"]`, apply its per-machine `urls:` override, and key
the result by the server name (its stable alias everywhere else). A one-store machine yields
`{"gws": …}` — identical in effect to today. Because the target spec now names no single alias, drop
`server_alias:` from `targets/mitos-agent.yaml`'s `mcp:` block (A3.1).

**Delete the entire `settings` block** (the `st = spec.get("settings")` clause).

*Green?* No — `render` still lacks `mitos_agent_mcp_config`.

### A3.4 — `render.py`

1. **`_machine_value` (L139–155)** — `paths.get("hermes_home")` → `paths.get("mitos_agent_home")`;
   update the docstring's tree names.

   > **Consequence to expect, not a bug:** `{{skills_root}}` expands to `<mitos_agent_home>/skills`,
   > so deployed prose changes from `~/.hermes/skills/…` to `~/.mitos-agent/skills/…`. Four partials
   > carry that token — `registry/context/projects-index.md`, its overlay copy, and the three
   > `registry/templates/org/*/session-protocol.md`. The first deploy after the rename will show them
   > as `pending`. That is correct. `reverse_expand_placeholders` folds the new value back on adopt.

2. **`render_skill` (L502–513)** — `if target == "hermes":` → `"mitos-agent"`. For the tag block:

   ```python
   # The per-skill tag block is still authored under the legacy `hermes:` key in registry
   # SKILL.md frontmatter — inert metadata (tags), not a target reference — so the rename
   # deliberately left those 13 files alone (decision 4). Emitted under the current name.
   # Rename the authored key when Mitos Agent defines its own skill frontmatter (B-Stage 5).
   tag_meta = fm.get("mitos_agent") or fm.get("hermes")
   if tag_meta:
       meta["metadata"] = {"mitos_agent": tag_meta}
   ```

3. **Replace `hermes_mcp_block` (L562)** with a version that takes the resolved server MAP (A3.3's
   `_agent_servers`) and emits one entry per store — not a single `(server, alias)` pair:

   ```python
   def mitos_agent_mcp_config(servers: dict[str, dict]) -> dict:
       """The whole mcp.json Mitos Agent reads: one entry per wired store (keyed by server
       name), each carrying its transport, the URL as seen from this machine, and the flat
       tool list. A one-store machine yields a single entry — same shape Hermes had."""
       return {"mcpServers": {alias: {
           "url": server["url"],
           "transport": server.get("transport", "streamable-http"),
           "tools": flat_tools(server),
       } for alias, server in servers.items()}}
   ```

4. **Delete `_HERMES_SETTINGS_LEAVES`, `_HERMES_SETTINGS_WHOLE_KEYS`, and `hermes_settings_block`**
   (L567–615).
5. **`skills_block` docstring (L448)** — prose rename.

*Green?* No — `init`/`mitos.py` still offer the old preset, and tests still assert old names.

### A3.5 — `init.py` and `mitos.py`

**`init.py`:**
- `MACHINE_USE_CASES`: `"hermes": ["hermes", "agents-md"]` → `"mitos-agent": ["mitos-agent", "agents-md"]`
- `_TARGET_PATH_KEYS`: `"hermes": ("hermes_home", "hermes_config", "assistant_root")` →
  `"mitos-agent": ("mitos_agent_home", "assistant_root")`
- `_PATH_ORDER`: replace `"hermes_home", "hermes_config"` with `"mitos_agent_home"`
- `_PATH_VALUES`: drop `hermes_config`; `"mitos_agent_home": "~/.mitos-agent"`
- `resolve_targets` (L233–256): `mitos-agent` pulls in `agents-md`; **keep the coding-clash refusal**
  and rename `hermes` → `mitos-agent` inside it. It mirrors the loader check A3.2 keeps, so the two
  must stay in lockstep — deleting it here would let the wizard write a profile the loader then
  rejects, the exact split-brain the mirror exists to prevent
- The scaffolded overlay partial (L182): `audience: [mitos-agent, claude-code, antigravity, agents-md]`
- Comments L26–37, L223

**`mitos.py`** (L102–177): rename `is_hermes` → `is_agent`; `use_case = "mitos-agent"`; reword the
role question — option 2 becomes *"Mitos Agent — the planning harness (SOUL.md, the operating tree,
org routing)"* rather than *"Full agentic assistant (Hermes)"*. The org-routing question stays gated
on the same answer.

*Green?* No — tests.

### A3.6 — `graph.py`, `commands.py`, `review.py`

Docstring-only in `graph.py` (L513, 528–531, 622, 686–687) and `commands.py` (L446).

`review.py` has **one functional change** among three comments: **L1310**, inside
`propose_new_org_domain`, hard-codes `"targets": ["hermes"]` for a newly proposed org skill. It must
become `["mitos-agent"]`, or the console will propose skills that deploy nowhere. Comments at L1003,
L1475, L2167.

### A3.7 — Machines

**`machines/example-linux.yaml`** (9 refs) — `targets: [mitos-agent, agents-md]`; `paths:` drops
`hermes_home`/`hermes_config` for `mitos_agent_home: "~/.mitos-agent"`; **delete the
`hermes_settings:` block**; update the header comment.

**`machines/example-windows-secondary.yaml`** (1) — comment only.

**`registry/local/machines/linux-box.yaml`** (10, gitignored) — same shape. Its `hermes_settings:`
block is the largest single deletion in the rename: `memory_enabled`, `user_profile_enabled`,
`max_turns`, `restart_drain_timeout`, `disabled_toolsets`, the platform toolsets, and the
`fallback_providers`/`fallback_model`/`custom_providers` chain. **Keep only the provider-fallback keys
(`fallback_providers`, `fallback_model`, `custom_providers`) as a Part B reference** — they are
evidence Mitos Agent should offer provider fallback and name the local Ollama endpoint (§6.2).
**Discard the rest:** the ~20 disabled third-party toolsets describe Hermes's tool surface, which
Mitos Agent replaces with the seven-tool surface of §6.3 — importing them as a requirements source
would smuggle Hermes's shape into a design that rejects it. (The overlay is already git-synced, so no
separate "save it first" step is needed; this is about what to *carry forward as reference*, not
backup.)

### A3.8 — Tests (184 refs)

Mechanical for most, but five are semantic:

| Test | Action |
|---|---|
| `test_targets.py::test_hermes_mcp_flat_tool_count` | Rewrite as `test_mitos_agent_mcp_config_shape` — the output is now whole-file JSON keyed by server name, not a merge block. Keep the flat-tool-count assertion, and **add a two-store fixture** asserting `mcp.json` carries one `mcpServers` entry per store (the multi-store regression for §5.4). |
| `test_targets.py::test_non_hermes_machine_coproduces_agents_md` | Rename; assertions unchanged. |
| `test_targets.py::test_project_agents_md_drops_identity_on_hermes_machines` | Rename to `…_on_assistant_machines`; update the `hermes_home` fixture path. |
| `test_loader.py::test_agents_md_without_hermes_never_leaks_org_routing` | Rename to `…_without_assistant_target_…`. **Assertions must not change** — this is the regression that protects Question A. |
| the exclusivity tests (`loader` + `init`) | **Keep, rename only.** `test_machine_role_exclusivity_hermes_vs_coding` → `…_assistant_vs_coding`, and the `["hermes","claude-code"]` loader case at ~L474 → `["mitos-agent","claude-code"]`, **assertions unchanged** (must still raise). Do **not** add `test_mitos_agent_coexists_with_coding_targets` — it asserts the opposite of the kept rule (design §4.4). |

Also: any `hermes_settings` tests are deleted with the feature; `test_targets.py:49`'s lint fixture
path `"x/.hermes/SOUL.md"` becomes `"x/.mitos-agent/SOUL.md"`; `conftest.py`'s fixture machines
change target and path keys.

*Green?* **Yes — this is the first commit where the suite passes.**

## A4. Registry prose and docs (one commit, or split by area)

**Frontmatter — 21 core + 12 overlay refs.** `audience:`/`targets:` lists: `hermes` → `mitos-agent`,
position preserved — **except the three `plan-*` skills, which subtract `hermes` and add nothing**
(design §4.5). The runtime is the router, so listing them on `mitos-agent` would deploy a prose tree
walk redoing `route()`'s job.

- Identity (5): `comms-style`, `operating-rules`, `security`, `session-protocol`, `who-i-am` — rename
- Core context (4): `agentic-root`, `assistant`, `projects-index`, `projects/example-project` — rename
- Core skills (7): `graph-bootstrap`, `gws`, `new-session`, `org-design`, `org-marketing`,
  `org-software`, `project-update` — rename
- Org templates (3 + README) — rename
- Overlay context partials (6) — rename
- **Overlay skills (7): `plan`, `plan-new-idea`, `plan-existing-iteration` DROP `hermes` (no
  replacement); the other 4 rename `hermes` → `mitos-agent`**

**The `plan-*` body prose fix lands here, not in B-Stage 5.** The three skill bodies carry **14
now-false references to Hermes** (*"Action (Hermes): transfer execution to…"*, *"target Hermes
only"*, *"Note for Hermes users"*). After the rename they name a harness on no machine and instruct a
coding harness to hand off to nothing. This is a fast find-and-replace in three files — *"Hermes"* →
*"the assistant harness"* (or delete the sentence where it only described a hand-off that no longer
exists) — and it is in scope for A4 as a prose fix, **not** decision 4's frozen-body rule (that rule
protects *logic*; a dead harness name is a factual error, not logic). Doing it now keeps A6's "nothing
false ships" honest.

**Prose:** `README.md` (the role table in *Choosing your setup* is the substantive edit — it must now
describe the two harness classes of design §2.1), `registry/README.md`, `docs/managing-state.md`,
`docs/org-templates.md`, `docs/authoring-capabilities.md`, `docs/agents-md-structure.md`,
`docs/operator-console.md`, the three `docs/targets/*.md` mentions, `docs/connectors/google-workspace.md`,
and the three non-hermes `targets/*.yaml` comment mentions.

**`registry/context/projects/mitos.md` (18 refs)** — the builder context, and the highest-value edit
in Part A because it is what every future agent reads. Three rows need real rewriting, not renaming:

1. *"A Hermes config.yaml runtime setting"* — **delete the row**; the lane is gone.
2. *"Whether org content actually renders on a machine"* — rewrite around
   `planner.deploys_org_content`, and keep the warning that it is **not** the same test as
   `agents-md in targets` (and now, that it is **also** not the `is_assistant_tree_machine` fourth
   gate — §4.1's four-way distinction).
3. *"Whether a machine may run an agentic harness alongside coding harnesses"* — **keep "it may
   not"**; only rename `hermes` → `mitos-agent`. The exclusivity check is retained (design §4.4), so
   this row's rule is unchanged — do **not** invert it.

Add one row for the new target and one for `mitos_agent_home`, and — because the whole-file `mcp.json`
now carries every store — a note that its multi-store shape comes from `_agent_servers` looping
`document_stores`. Invariant #7's wording should note it applies to third-party tools only, and that
Mitos Agent's `mcp.json` is the first-party whole-file counterexample (with the merge-residue caveat
of §A8 cross-referenced from `docs/managing-state.md`).

**New file: `docs/targets/mitos-agent.md`**, plus its entry in `docs/README.md`'s target list.

**Document the merge-residue that the rename leaves behind (§A8).** Retiring the two `yaml_merge`
outputs does **not** clean their keys out of `~/.hermes/config.yaml`, and — unlike a deleted
whole-file output — those keys never become reportable orphans (merge outputs are never recorded in
the lockfile; see §A8). A4 must state this in `A7`/`A8` and in `docs/managing-state.md`: after the
rename, `config.yaml` keeps `mcp_servers.gws` and the settings leaves indefinitely, and removing them
is a **manual** step if the box is ever fully retired. This is a documentation item, not a code
change; the code fix (lockfile-track merge outputs so retirement is reportable) is filed separately
per the contribution rule — it is not needed to ship Part A.

**`AGENTS.md` (18 refs) is generated** — never hand-edit. `compile` rewrites it from
`registry/context/projects/mitos.md`; commit the result.

## A5. Verification gates

Run in order. Do not proceed past a red gate.

```bash
python build/compile.py compile
```
```bash
pytest build/tests/
```
```bash
python build/tests/test_compiler.py
```
```bash
python build/compile.py deploy --machine example-linux --dry-run --root /tmp/mitos-rehearse
```

Gate 1 is schema validation — the first real test. Gate 3 is the **stdlib runner CI actually uses**;
a green `pytest` is not proof. Gate 4 rehearses the Linux machine's deploy into a sandbox
(invariant #8), and its output should show `SOUL.md`, the skills tree, and `mcp.json` landing under
`~/.mitos-agent/`, with **no** `config.yaml` merge.

Then, and only then, the real machines:

```bash
python build/compile.py deploy --machine windows-main --dry-run
```

Expect `pending` on the four `{{skills_root}}`-bearing files (A3.4) and `orphan` on every deployed
Hermes **whole-file** artifact (`SOUL.md`, the skills tree). **`config.yaml` will NOT appear as an
orphan** — it was a `yaml_merge` output, and merge outputs are never in the lockfile, so the orphan
mechanism can't see it (§A8). That is expected, and it is why the rename leaves residue in that file
rather than cleaning it. **Do not pass `--prune` yet** — the whole-file orphans are the safety net
that lets you walk this back (§A7).

## A6. What is deliberately not changed

| Asset | Why |
|---|---|
| `plan`, `plan-new-idea`, `plan-existing-iteration` **logic/structure** | Decision 4 — the router logic, the New Idea/Existing fork, the destinations stay. Only the `targets:` line (drop `hermes`) and the 14 dead *"Hermes"* name references change (the latter in A4, see below). |
| Every context partial's body | Decision 4. |
| The `hermes:` key in 13 SKILL.md frontmatters | Inert tag metadata, not a target reference (A3.4 §2). Emitted under `metadata.mitos_agent` via the `fm.get("mitos_agent") or fm.get("hermes")` fallback; the *authored* key is renamed once in B-Stage 5. |
| `session-protocol.md` / `operating-rules.md` navigation prose | An earlier design revision proposed trimming it; withdrawn (design §4.5). |

**No prose debt is deferred.** An earlier revision left the three `plan-*` bodies' **14 references to
Hermes** — *"Action (Hermes): transfer execution to…"*, *"target Hermes only"*, *"Note for Hermes
users"* — for B-Stage 5. That is withdrawn: they name a harness on no machine and tell a coding
harness to hand off to nothing, so they are a factual error, not frozen logic. **A4 fixes all 14 as a
prose find-and-replace**, in the same commit that drops `hermes` from those skills' `targets:`. Only
the `hermes:` *frontmatter key* rename remains a B-Stage 5 item, and only because it waits on Mitos
Agent defining its own skill frontmatter.

## A7. Rollback

Part A is a single revert away at every point, with one caveat that matters.

- **Before any real deploy:** `git revert` the series. Nothing outside the repo changed.
- **After a real deploy:** the old Hermes files are **orphans, not deletions** (invariant #9) — still
  on disk, still in the lockfile. Reverting the code and re-deploying restores them. This is the
  reason A5 says not to `--prune`.
- **The point of no return is `deploy --prune`.** Run it only once Mitos Agent is actually serving
  the Linux box (B-Stage 5). A drifted orphan is captured to the inbox first, so even then nothing is
  lost silently.
- **The overlay is separately versioned** — `registry/local/` is its own git repo with a hub
  (`mitos sync`). Commit it before starting so its 34 edits revert independently.

## A8. The `config.yaml` merge residue (there is no destructive prune bug)

An earlier review flagged that `deploy --prune` would delete Hermes's whole `config.yaml`. **It will
not** — verified against `build/agentic/commands.py`:

- Merge outputs (`yaml_merge`/`json_merge`) `continue` in the deploy write loop **before** any
  lockfile entry is built, so `~/.hermes/config.yaml` is never recorded in `.deploy-lock.json` (the
  live lockfile confirms it — no merge target appears). Only Mitos-*owned whole files* are tracked.
- `orphans` is computed as `prior_lockfile_paths − planned_paths`. A path never in the lockfile can
  never be an orphan, so the prune loop — which only iterates `orphans` — cannot reach `config.yaml`.

So the real defect is the **inverse**: retiring the merge leaves `mcp_servers.gws` and the settings
leaves *in* the third-party file, silently, with no orphan report and no drift tracking. Invariant
#9's "deletion is explicit" holds; its companion "orphans are reported on every deploy" does not,
because merges live outside the orphan mechanism entirely.

Two consequences, both already routed above:

1. **Part A documents it** (A4): after the rename, `config.yaml` keeps Mitos's keys; removing them on
   a full retirement is manual. `docs/managing-state.md` gains a line.
2. **A separate Mitos change** (its own commit, test, and `docs/managing-state.md` section, per the
   contribution rule) teaches the lockfile to track merge outputs so a retired merge becomes a
   reportable orphan. It is **not** a prerequisite for Part A and does not gate the rename. The naïve
   "strip `owned_keys` from the orphan" fix is unimplementable as first proposed — the lock entry
   carries no `owned_keys` today; that is exactly what this change would add.

---

# PART B — `mitos-agent`: the product

Location: `<mitos project>/mitos-agent/` — scaffolding only, moving to its own git home at v0.1.0
(design §4.6). The directory exists and is empty.

## B0. Repo bootstrap

`git init`; Python 3.11+; `src/mitos_agent/` layout from design §7; MIT licence; public.
`AGENTS.md` at the repo root is authored *in Mitos* and deployed here — the product reads its own
output (design §8.2). CI from day one: the four test layers of design §8.1, **with no network
available**, enforced rather than assumed.

## B-Stage 0 — Format experiment *(prerequisite, not a kill gate; no code)*

Write two profile specs (`implementation-plan`, `agile-stories`) as plain Markdown. Hand-write three
artifacts against real Mitos work. Execute each with a coding harness; see whether the formats help.
This is cheap and worth doing, but it exercises **none of §1.1** (no routing, no traversal, no pack),
so it does **not** decide the programme — it feeds Stage 5b's profile work. The kill gate is Stage 1.

**Outcome (informational):** rediscovery cost and false starts, noted for the profile design. Not a
stop condition.

## B-Stage 1 — The traversal engine *(no model)* — KILL GATE

`tree/`: `locate`, `parse_node`, `route`, `resolve`, `skills`, `pack` (design §5.4), with §5.5's
tolerance policy. A CLI that prints the routed pack. Fixtures in `tests/fixtures/tree/` are **real
emitted Mitos trees**, checked in, including deliberately malformed nodes.

**Exit:** every fixture parses; **routing is deterministic — the same message routes identically
across runs**; the pack is materially smaller than the whole tree; a heading typo degrades to raw
markdown instead of raising. No model, because `route()` is deterministic-first — if the tree can't be
parsed the premise of design §1 claim 3 is wrong, and that is the thing worth learning first.

## B-Stage 2 — Part A *(Mitos)*

Execute Part A. Deferring it until Stage 1 has proven the parser is deliberate: there is no reason to
freeze the assistant before its replacement is shown to work at all. (Hermes *freezes* on its
last-deployed files here, it does not stop — invariant #9; the actual prune is Stage 8.)

## B-Stage 3 — Provider port and secrets — CROSS-MODEL GATE

`providers/` (port + `fake` + `ollama` + **Anthropic** — OpenAI/Gemini deferred, design §6.2) and
`secrets/` (keychain → env → `0600` file, redaction at the port, `--offline`).

**Exit:** the same scripted session runs identically on `fake` and `ollama`; **the same routes and the
same profile are selected on a `small` local model and a frontier one** (design §9 axis 2 — the direct
§1.1 conformance check, which needs the real port; `fake` is deterministic by construction and cannot
stand in for it); one refusal test per secret backend; `--offline` refuses a cloud provider.

## B-Stage 4 — Capture, idea store, triage *(CLI only)*

Design §6.1. Standalone value with no planning at all. Ideas and all runtime state go to `<state_dir>`
(design §7), **never** the `~/.mitos-agent` deploy root.

**Exit:** capture is sub-second and makes no network call; triage routes against the real tree;
duplicate ideas merge.

## B-Stage 5a — Session runtime core

The phase machine and gates, the tool surface with its guards, the **preferences table** (design §6.3),
and `write_artifact`. Design §6.3, §6.5–6.8.

**Exit:** one full session ends with an artifact in the store and a graph candidate proposed via
`mitos propose`; a passing refusal test **per write surface and per forbidden preference**.

## B-Stage 5b — Profiles and memory

Profiles (schema, selection, lint, built-ins — fed by Stage 0's experiment), the three memory tiers
with 30-day transcript retention (design §6.9), and the workspace one-shots.

Carries from Part A: the provider-fallback keys saved in A3.7 (`fallback_providers`/`fallback_model`/
`custom_providers`) as the reference for Mitos Agent's fallback config; and the `hermes:` frontmatter
key rename, done once as part of defining Mitos Agent's own skill frontmatter. (The `plan-*` prose debt
is **not** here — A4 already fixed it.)

**Exit:** the **full design §9 eval** — run-to-run *and* model-to-model structure conformance — passes
on a real plan session, and `mitos propose` is accepted in the console.

## B-Stage 6 — Telegram

Sender allowlist, confirmation on every write, message-content-is-data. Design §6.1.

**Exit:** a message from any non-allowlisted sender is dropped and unlogged; no write completes
without a confirm reply.

## B-Stage 7 — Grounding beyond the repo

Documents by graph ID, then the read-only database path with its credential-level gate. Design §5, §6.3.

## B-Stage 8 — Prune, and v0.1.0

`deploy --prune` retires the frozen Hermes **whole-file** artifacts (`SOUL.md`, the skills tree). Note
`config.yaml`'s Mitos keys are **not** removed by prune (§A8) — clean them by hand if the box is fully
retired. `mitos-agent` moves to its own git remote and is registered as the Mitos project's second
`repo:` entry with a `repo_notes:` line (design §4.6) — **after** reconciling the `D:` / `C:`
project-path discrepancy.

## B-Cross-cutting — the two rules that hold at every stage

1. **Tests precede implementation**, in the five layers of design §8.1. A verb, profile, or schema
   field lands with its validation, its contract page, and its acceptance test — or not at all.
2. **One contract page per boundary**, and **every example in a contract page is a test fixture**, so
   prose and code cannot diverge quietly (design §8.2).

---

## Appendix — execution checklist

```
PART A
[ ] A3.1  targets/mitos-agent.yaml written (no server_alias); targets/hermes.yaml deleted
[ ] A3.2  loader: KNOWN_TARGETS; exclusivity KEPT (hermes→mitos-agent); hermes_settings DELETED
[ ] A3.3  planner: dispatch; 3 helpers + 4th-gate note; 6 call sites + is_hermes_machine RENAME
          (keep keyed on agents-md); _plan_mitos_agent; _agent_servers (per-store mcp.json); settings DELETED
[ ] A3.4  render: _machine_value; render_skill; mitos_agent_mcp_config (per-store map); settings block DELETED
[ ] A3.5  init.py presets/paths; resolve_targets clash refusal KEPT (renamed); mitos.py wizard
[ ] A3.6  graph/commands docstrings; review.py L1310 targets FUNCTIONAL FIX
[ ] A3.7  example-linux; example-windows-secondary; linux-box (KEEP fallback_* as ref, discard toolsets)
[ ] A3.8  tests: mcp shape+2-store; exclusivity tests KEPT-renamed; 4 renames; mechanical  ← suite green here
[ ] A4    frontmatter (plan-* DROP hermes, rest rename); plan-* 14 Hermes-name prose fix;
          prose; mitos.md 3 rewritten rows; merge-residue doc (managing-state.md);
          docs/targets/mitos-agent.md NEW; docs/README.md entry; commit generated AGENTS.md
[ ] A5    compile → pytest → stdlib runner → --root rehearsal → real --dry-run (NO --prune;
          config.yaml is NOT an orphan, expected)
[ ] A8    document config.yaml merge residue; file the lockfile-tracks-merges change separately

PART B
[ ] B0    format experiment (prerequisite, NOT a gate) — feeds Stage 5b profiles
[ ] B-S1  traversal engine + fixtures; deterministic routing    ← KILL GATE
[ ] B-S2  execute Part A (Hermes freezes, not killed)
[ ] B-S3  provider port + secrets: fake + ollama + Anthropic; cross-model conformance  ← §1.1 GATE
[ ] B-S4  capture / idea store / triage (state → <state_dir>)
[ ] B-S5a session runtime core: phases, gates, tool surface, preferences, write_artifact
[ ] B-S5b profiles + memory tiers + workspace one-shots; full §9 eval  ← eval gate
[ ] B-S6  Telegram
[ ] B-S7  grounding beyond the repo
[ ] B-S8  deploy --prune (whole-file only); move repo to its own remote; manifest entry; v0.1.0
```
