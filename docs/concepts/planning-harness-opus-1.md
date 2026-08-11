# Concept: Metis — the Mitos Planning Harness

> **Status:** concept only. Nothing here is wired, scheduled, or implemented. It proposes a
> second agentic target alongside Hermes and describes what would have to ship for it to be
> real. Read [`README.md`](../../README.md) and [`agents-md-structure.md`](../agents-md-structure.md)
> first — this design reuses their contracts rather than inventing parallel ones.
>
> **Superseded on where it lives by** [`mitos-agent-platform.md`](mitos-agent-platform.md), which
> keeps nearly every mechanism below (phase machine, gates, Ground Ledger, Plan Object, staleness)
> and moves them out of `registry/` into a separate `mitos-agent` repo — one that **replaces the
> `hermes` target** rather than sitting beside it, and treats the Plan Object as one output profile
> among several rather than the output format.

## 1. Premise

Coding harnesses have become good at *executing* a plan and mediocre at *producing* one.
Their planning modes are a courtesy pause inside an execution loop: the same context window,
the same tools, the same incentive to start writing. The plan that falls out is prose — long,
unanchored, restating the codebase back to a reader who can already read it, and stale the
moment the repo moves.

Mitos already solves the hard half of planning: it knows what the projects are, which
documents are authoritative, which org governs which effort, and how to detect when a
materialized artifact has drifted from its source. What it has never had is an agent whose
*only* output is a plan.

**Metis** is that agent. Named for the counsel-goddess (and one vowel from *Mitos*), it is
the deliberative counterpart to Hermes the messenger. Hermes acts. Metis decides what should
be done, proves it against grounded truth, and hands a coding harness a plan tight enough to
execute without rediscovery.

## 2. The defining invariant

> **Metis produces plans and nothing else.** It never edits a repository, never runs a
> mutating command, never deploys, never sends. Its single write surface is
> `registry/local/inbox/` — a `kind: plan` candidate the maintainer accepts or rejects.

This is not a safety veneer bolted on top; it is the reason the design works. An agent that
*cannot* start implementing has no incentive to stop thinking early. Every failure mode of
existing plan modes — premature file edits, plans written to justify a decision already
taken, "I'll figure that out while coding" — is structurally unavailable.

It also lands Metis exactly on invariant #3 (*never write into `registry/` to propose a
change — propose into `registry/local/inbox/`*). The planning harness is a **proposer**, in
a system already built around proposers. Nothing new to trust.

## 3. Relationship to Hermes

| | Hermes | Metis |
|---|---|---|
| Purpose | act on the owner's behalf | produce an executable plan |
| Terminal output | a side effect in the world | a Plan Object |
| Tools | read + write + send | read only, plus one inbox write |
| Context source | the deployed `AGENTS.md` tree | **the same tree**, mounted read-only |
| Persona partials | `who-i-am.md`, `operating-rules.md`, … | shares `security.md`, `comms-style.md`; own `who-i-am-planning.md`, `planning-protocol.md` |
| Session shape | short, task-scoped, `new-session` on pivot | long, one idea per session, phase-gated |
| Failure mode it guards | wrong action taken | wrong plan written confidently |

Metis reads the *identical* deployed context Hermes reads — same operating root, same project
nodes, same generated document maps, same org-domain routing lines. That is the whole point
of sharing Mitos: the planner and the doer cannot disagree about what a project is, because
they are reading one compiled tree. Where they differ is downstream of context, in purpose.

Concretely: `audience: [hermes, agents-md, metis]` on the shared partials; a new
`targets/metis.yaml` whose `context_file.sources` assembles a `COUNSEL.md` system prompt from
the planning-specific identity partials plus the shared security/comms ones.

## 4. What it borrows from existing harnesses — and what it changes

The mandate is *best-of-class*, which means taking the proven mechanics and fixing the part
each one gets wrong for planning specifically.

| Borrowed concept | Where it's proven | What Metis changes |
|---|---|---|
| **Plan mode with an approval gate** | Claude Code's plan/exit-plan cycle | The gate is not one modal at the end. Two mandatory gates (intent, plan acceptance) sit at *known* points in a phase machine, and the agent cannot advance past one by asserting it's ready. |
| **Skills as procedure** | Mitos skills, Claude Skills, Antigravity `SKILL.md` | Each planning phase *is* a skill, loaded on entry and dropped on exit — so the whole method never occupies the window at once. |
| **Read-only exploration subagents** | `Explore`-style fan-out agents | Scouts return **anchors and excerpts, never conclusions**. A subagent that returns a narrative has laundered its evidence; Metis requires `path:line` + the quoted lines. |
| **YAGNI / climb-the-ladder planning** | `software-yagni-planner` | The ladder is not advice, it is an *emitted artifact*: the plan records the rung chosen and the rejected rungs with one-line reasons, so a reviewer can argue with the choice instead of reverse-engineering it. |
| **Todo decomposition** | TodoWrite-style step lists | Steps are the deliverable, not scaffolding. Each carries its own verification command; a step without one is a lint failure. |
| **Context compaction** | every long-running harness | Compaction is scheduled at phase boundaries, and what survives is the Ground Ledger (§6) — a structured artifact, not a summary of chat. |
| **Hooks / linting** | Mitos's `lint_node_markdown` | `mitos plan lint` runs the same way: at emit time, failing loudly with the offending step named. |
| **Drift detection** | Mitos's three-way compare | Applied to plans (§8). This is the genuinely new idea. |
| **Org role-play** | `org-software`'s CEO / VP Eng / Assistant | The roles stop being hats worn in one voice and become phases with gates between them; the Assistant role is deleted, because Metis does not execute. |

## 5. Architecture — a phase machine, not a conversation

Eight phases. Each has an entry condition, a bounded token budget, and one artifact it must
produce before the next may start. The agent announces the phase it is entering; the owner
can always say *"skip to plan"* and accept the reduced grounding explicitly.

```
P0 Intake ─ P1 Route ─ P2 Ground ─ P3 Clarify ─╢G1╟─ P4 Shape ─╢G2*╟─ P5 Sequence ─ P6 Adversary ─ P7 Emit ─╢G3╟─→ inbox
```

**P0 Intake.** Capture the idea *verbatim* before interpreting it — the raw ask is quoted at
the top of the Plan Object forever, because every later distortion is measured against it.
Classify: feature / refactor / defect / infrastructure / research. Pick the effort tier
(§10). Nothing is researched yet.

**P1 Route.** Pure Mitos. `cd` the operating root, follow `## Navigation`, land on the
project node, read its `## <Store> (key)` section and the effort's `orgDomain` routing line.
Output: a **draft context manifest** — the ordered list of files, graph document IDs, and
tree nodes this plan will rest on. Routing happens before reading so that reading is cheap
and targeted.

**P2 Ground.** Read-only fan-out over the manifest. Repo anchors via search/read; document
anchors via the knowledge graph, resolved by ID and fetched live (never planned from memory
when a mapped document exists — the VP Engineering rule from `org-software`, promoted to a
hard phase requirement). Read-only commands are permitted and their output is an anchor
(`$ pytest -q → 344 passed`). Output: the **Ground Ledger**.

**P3 Clarify.** Unknown triage and batched questions (§7). Output: zero open unknowns —
each either resolved, defaulted with a stated assumption, or promoted to a deferred decision
in the plan.

**⟨G1⟩ Intent gate.** The owner confirms the restated objective and the definition of done.
This is the cheapest possible place to catch a misread, and it is mandatory: a plan built on
a misunderstood objective is worse than no plan, because it is persuasive.

**P4 Shape.** Build the option ladder — rung 0 (do nothing / it already works), rung 1
(smallest change that satisfies *done*), rung 2, rung 3 (the tempting general solution).
Recommend a rung with reasons. Rejected rungs get one line each; they are kept, not deleted.

**⟨G2⟩ Rung gate — conditional.** Fires only when the recommendation is not the lowest rung
that satisfies *done*. Climbing costs the owner's approval, staying low is free. That
asymmetry is the whole YAGNI enforcement mechanism, and it is cheaper than a lecture.

**P5 Sequence.** Decompose the chosen rung into ordered steps. The constraint that does the
work: **every step is independently verifiable** — it names what it touches, what changes,
and the command or observation that proves it. A step that cannot state its verification is
not a step; it is an unresolved unknown that escaped P3, and it goes back.

**P6 Adversary.** A dedicated critic pass with a hostile brief: find the step that will fail,
the anchor that has gone stale, the assumption that only holds on the maintainer's machine,
the ordering that breaks under partial completion. It must produce findings **or** an
explicit "no findings; here is what I checked" list. Silence is not a pass.

**P7 Emit.** Compress to the Plan Object schema (§9), run `plan lint`, write the candidate to
`registry/local/inbox/`. Compression is a distinct step because the plan's audience is a
machine with a finite window, and prose written for a human reader is roughly twice the
tokens it needs to be.

**⟨G3⟩ Acceptance gate.** The maintainer accepts in the operator console, exactly like any
other inbox candidate. Accept writes `PLAN.md` into the target project. Nothing else does.

## 6. The grounding contract

> **No assertion without an anchor.** Every factual claim in a plan resolves to a repo
> location, a graph document ID, or a captured command output.

The **Ground Ledger** is the structured record P2 produces and every later phase cites:

| Kind | Anchor form | Freshness key |
|---|---|---|
| Repo fact | `build/agentic/planner.py:412-430` | content hash of those lines |
| Document fact | graph doc ID + `dateModified` | the store's `dateModified` |
| Observed behaviour | the read-only command + its output | re-runnable |
| Owner decision | gate + timestamp | — |
| **Assumption** | explicitly typed as unproven | must appear in the plan's Assumptions section |

The fifth row is the honest one. Some things genuinely cannot be verified before
implementation starts; the failure is not making an assumption, it is laundering one into
the plan as a fact. Typed assumptions surface in their own section where the executing
harness can check them cheaply and bail early.

## 7. The clarity loop, with a stopping rule

Iterating "until complete clarity" fails in one of two directions: the agent asks nothing and
guesses, or it interrogates the owner about things it could have read. Metis triages every
unknown into exactly one bucket:

| Bucket | Handling |
|---|---|
| **Readable** — the repo, the graph, or a doc answers it | resolve it silently. *Never ask what you can read.* |
| **Observable** — a read-only command answers it | run it; the output becomes an anchor |
| **Judgment** — only the owner can decide (priority, tradeoff, taste, external constraint) | ask |
| **Deferrable** — the answer doesn't change the plan's shape | record as a deferred decision inside the plan, at the step where it bites |

Questions go out in **batched rounds** (≤4 per round), each with a recommended default, so
silence is a valid answer and the owner is never blocked on a question the agent could have
answered for itself. Rounds are capped — typically two. If the third round would fire, that
is itself the finding: the idea is not yet well-formed enough to plan, and Metis says so and
stops rather than laundering confusion into a confident document.

**Stopping condition:** every unknown is Readable-resolved, Observable-resolved,
Judgment-answered, or Deferred-and-recorded. That is a checkable state, not a feeling.

## 8. Plan staleness — the drift compare, applied to plans

This is where Metis earns its place inside Mitos specifically rather than being a generic
planning bot.

Mitos already runs a three-way compare on every deployed file: rendered source vs. lockfile
`source_hash` vs. on-disk `deployed_hash`. **A plan has exactly the same shape.** It is an
artifact materialized from sources (the anchors) that keep moving after materialization.

A Plan Object records the content hash of every anchor it rests on. Then:

```bash
mitos plan status PLAN.md
```

| State | Meaning | Action |
|---|---|---|
| `fresh` | every anchor hashes as recorded | execute it |
| `stale` | an anchor moved, no step depends on the moved region | note it, execute |
| `conflict` | an anchor a step directly depends on has changed | re-ground before executing |
| `landed` | the plan's *done-when* conditions already hold | close it |

A coding harness runs `plan status` before executing, the same way `deploy` refuses to
overwrite drifted protected files. That single check kills the most expensive failure in
agentic development: a confidently executed plan written against a repo that no longer
exists. The machinery is already in `build/agentic/commands.py`; this is a new caller, not a
new mechanism.

## 9. The Plan Object

The plan is an **interface**, and it is versioned like one. Written for a machine reader with
a finite window, not for a person skimming.

```markdown
---
plan: dedupe-connection-render
plan_schema: 1
project: mitos
rung: 1 of 3
base: { registry_sha: a3f9c21, anchors: 9 }
gates: { intent: 2026-08-08, plan: 2026-08-08 }
---
# Collapse the duplicate connection-heading render path

**Asked for (verbatim):** "the connection section renders twice for multi-store projects"

## Done when
- [ ] A two-store project emits exactly one `## <Name> (key)` heading per store
- [ ] `pytest build/tests/` and `python build/tests/test_compiler.py` both green

## Read first
| Anchor | Why |
|---|---|
| `build/agentic/planner.py:388-441` | `_project_doc_block`, the loop being changed |
| `build/agentic/render.py:210-244` | `connection_label`, the heading source |
| `build/tests/test_targets.py:702` | the test that must keep passing |

## Constraints
- Invariant #12: exactly one H1 per file — later stores force level ≥2
- Presentation only; the accept/upsert path is out of scope

## Steps
### 1. Hoist the heading decision out of the per-store loop
**Touch:** `build/agentic/planner.py:401`
**Change:** compute `emit_heading` once from `level`, pass per store
**Verify:** `pytest build/tests/test_targets.py -k multi_store` → passes

### 2. …

## Out of scope
- Single-store rendering (unchanged, and covered by existing tests)

## Assumptions (unproven)
- No third-party consumer parses the duplicate heading

## Deferred decisions
- Whether a keyless-leftover section should warn — decide at step 3 if one appears

## Anchors
planner.py:388-441 @ 4c1a…  render.py:210-244 @ 9e02…  test_targets.py:702 @ b71f…
```

**Compression rules, enforced by lint:**

- Anchors, never quoted code. The executing harness can open the file; it cannot recover
  tokens you spent showing it what it already has.
- Imperative deltas ("hoist X out of the loop"), never narration ("we should consider…").
- No time estimates. They are unverifiable and they anchor the reader on the wrong axis.
- No restatement of the codebase, the request, or the plan's own structure.
- One outcome per step; if a step needs "and", it is two steps.

`mitos plan lint` checks the mechanical half: every anchor resolves, every step has a
verification, `done-when` conditions are observable, no step depends on a deferred decision
that fires later than the step itself, the schema version is known.

## 10. Effort tiers

Not every idea deserves eight phases. The tier is chosen at P0 and stated out loud.

| Tier | Phases run | For |
|---|---|---|
| **Sketch** | P0, P1, P4, P7 | a one-file change where grounding is a single read |
| **Standard** | all eight, one clarify round | the default |
| **Deep** | all eight, two clarify rounds, adversary fan-out | architecture, migrations, anything touching an invariant |

The tier ratchets *up* freely when P2 surfaces more than it expected, and down only with the
owner's say-so — surprise is evidence the estimate was wrong.

## 11. What ships, in Mitos terms

| Piece | Where it lives |
|---|---|
| The target spec | `targets/metis.yaml` — emits `COUNSEL.md`, a planning-skills tree, read-only MCP wiring |
| Persona | `registry/identity/who-i-am-planning.md`, `planning-protocol.md` (`audience: [metis]`) |
| Shared persona | add `metis` to `security.md` / `comms-style.md` audiences |
| Phase skills | `registry/skills/plan-ground/`, `plan-clarify/`, `plan-shape/`, `plan-adversary/`, `plan-emit/` — `targets: [metis]` |
| Plan schema doc | `docs/plan-object.md` — the versioned handoff contract |
| Candidate kind | `kind: plan` in the inbox, accepted to `<project>/PLAN.md` |
| Verbs | `mitos plan lint`, `mitos plan status` — beside the compiler, offline, no network |
| Console | a **Plans** tab: pending plans, per-plan freshness, accept/reject |

**Two contract changes this forces, and neither should be quiet:**

1. **The hermes-exclusivity rule needs a carve-out.** Today `hermes` in a machine's `targets`
   excludes the coding harnesses, because an agentic actor and a coding actor on one box
   fight over the same workspace. Metis does not act, so the reason does not apply — but the
   loader currently cannot express that. It needs an explicit *planning harnesses may
   co-reside* clause, with its own validation and its own test, not an exception carved by
   omission.
2. **A new drift-policy consumer.** Plans are `protect`-class artifacts with their own
   freshness semantics. `plan status` is a distinct code path from `deploy`'s compare, and
   [`managing-state.md`](../managing-state.md) has to grow a section or it will drift from
   the implementation within one release.

Per the contribution rule, each lands with its schema validation, its README/docs section,
and its acceptance test — or not at all.

## 12. Deliberate non-goals

- **It does not write code.** Not a scaffold, not a stub, not "just the type signature."
- **It does not estimate time.**
- **It does not own execution.** No progress tracking, no step-completion state. The coding
  harness owns that; a plan that tracks its own execution becomes a second source of truth.
- **It does not replace the org skills.** `org-software` still routes and governs; Metis is
  the harness that VP Engineering's planning phase runs *inside*.
- **It does not need a framework.** Invariant #10 holds: phases are skills, gates are
  questions, the ledger is a Markdown table, staleness is the existing hash compare. If any
  part of this needs a graph library or an orchestrator, that part is wrong.

## 13. Build order

| Stage | Ship | Proves |
|---|---|---|
| **0** | The Plan Object schema + `plan lint`, nothing else. Hand-write three plans against real Mitos work and execute them with a coding harness. | Whether the format actually reduces rediscovery. Cheapest possible falsification. |
| **1** | The phase skills as ordinary Mitos skills targeting `hermes`. No new harness. | Whether the phase machine survives contact with real ideas. |
| **2** | `targets/metis.yaml` + the read-only enforcement + the exclusivity carve-out. | The invariant, mechanically. |
| **3** | `plan status` freshness + the console Plans tab. | The drift-compare reuse. |

Stage 0 is the honest test, and it needs no code at all. If a hand-written Plan Object
doesn't measurably cut the tokens and false starts a coding harness burns on the same task,
the harness around it is not worth building — and that's a finding worth having for the price
of three documents.

## 14. Open questions

1. **Does the plan live in the repo or the registry?** `PLAN.md` in the project checkout is
   where a coding harness will look. But plans are content, and content lives in the
   registry. Probably: registry-authored, deployed to the checkout as a `protect` artifact —
   which makes an executed-and-annotated plan a *harvest* candidate. That is either elegant
   or one loop too many.
2. **Is `plan status` the coding harness's job to run, or a hook?** A hook is enforceable; a
   convention is portable.
3. **One plan per effort, or per rung?** Rejecting a rung after implementation starts
   currently means rewriting the plan rather than switching to a sibling.
4. **Should the adversary pass be a different model?** Self-critique has a known ceiling. A
   second model reading only the Plan Object and the Ground Ledger — never the conversation —
   is a cleaner test, and the Plan Object is already designed to be self-contained enough to
   make that possible.
