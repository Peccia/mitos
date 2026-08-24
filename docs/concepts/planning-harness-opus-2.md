# Concept: The Mitos Agent — a planning-only harness

> **Status:** concept only. Nothing here is wired, scheduled, or implemented.
>
> **Siblings:** [`planning-harness-gemini-1.md`](planning-harness-gemini-1.md) frames the
> harness as a new target with a "grill loop." [`planning-harness-opus-1.md`](planning-harness-opus-1.md)
> designs the phase machine, the Plan Object schema, and plan-staleness as a reuse of the
> drift compare. **This document does not restate either.** It takes the layered architecture
> as the frame, works out the part neither covers — *grounding against live substrate, not
> just the repo* — and takes explicit positions on three questions the others left open:
> where the plan lives, which machine the planner runs on, and what "good" is measured as.
>
> **Superseded on the boundary question by** [`mitos-agent-platform.md`](mitos-agent-platform.md),
> which keeps §§5, 6, 8, 9 and §11 of this doc but rejects §3 (the read-only guarantee as a
> per-harness permission profile), §4's persona table on two partials, and §7 (the artifact of
> record belongs in the connection, not the repo) — and moves the planner into its own repo as a
> product with a native tree-traversal engine — one that **replaces the `hermes` target**, which also
> makes §9 ("put the planner on the workstation, not the Hermes box") moot.
>
> Read [`README.md`](../../README.md) and [`agents-md-structure.md`](../agents-md-structure.md)
> first. Everything below reuses existing Mitos contracts; where it can't, that is called out
> as a contract change with a cost attached.

---

## 1. The stack

The design is three layers with a strict rule about which direction each kind of information
flows. Nothing here is novel on its own; the value is in refusing to let the layers blur.

```
┌─ LAYER 1 — MITOS (the moat) ─────────────────────────────────────────────────┐
│   Knowledge Graph          Skills + Org              AGENTS.md tree          │
│   what is authoritative    how work is done          what a project is       │
└──────┬───────────────────────────▲───────────────────────┬───────────────────┘
       │ context                   │ skills, org,          │ context
       │ (graph, connections)      │ learned invariants    │ (project nodes)
       ▼                           │                       ▼
┌─ LAYER 2 — AGENTS ───────────────┴───────────────────────────────────────────┐
│                                                                              │
│   MITOS AGENT ─────────── Plan Object ──────────────▶  CODING HARNESS        │
│   plans, never writes     (the interface)              writes, never plans   │
│                                                                              │
└──────▲───────────────────────────────────────────────────────▲───────────────┘
       │ read-only                                             │ read + write
       ▼                                                       ▼
┌─ LAYER 3 — SUBSTRATE ────────────────────────────────────────────────────────┐
│   Source code            MCP servers                 Databases               │
│   what was built         what the world says         what the data is        │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Three flows, and each is one-way:**

| Flow | Direction | Carries |
|---|---|---|
| **Context** | Layer 1 → Layer 2 | The graph, the project nodes, the connection wiring. Both agents read the *same* compiled tree. |
| **Plan** | Planner → Coder | One artifact, versioned, self-contained. The only thing that crosses. |
| **Residue** | Layer 2 → Layer 1 | What planning *learned* that outlives the plan — a new invariant, a document worth mapping, a skill worth writing. Goes through the inbox (invariant #3). Never automatic. |

The layer-3 arrow is the one the sibling docs underweight, and §5 is about it.

**Naming.** The whiteboard calls it the *Mitos Agent*; `planning-harness-opus-1.md` proposes
*Metis*. Either works — this doc uses "the planner" for the role and leaves the product name
to whoever ships it.

---

## 2. Why a separate agent at all

The honest version of the argument, because "planning mode is bad" is not one.

A coding harness in plan mode is an execution agent with a pause bolted on. Three things
follow from that, none of which are fixable by prompting harder:

1. **It plans in the window it will execute in.** Every token spent reasoning about approach
   is a token unavailable for the work. So the plan is short where it should be careful, and
   the exploration gets compacted away exactly when the implementation needs it.
2. **Its context is the repo.** It grounds against the code, which is the record of what *was*
   built. It has no cheap route to the spec that says why, the ticket that says what changed,
   or the database that says what the data actually looks like — the three places where the
   expensive misunderstandings live.
3. **It is rewarded for starting.** Producing a diff reads as progress. Producing a better
   question does not. An agent that *can* write code will, at the margin, stop thinking early.

Mitos already fixes (2) for the assistant: it knows the projects, the authoritative documents,
the org that governs an effort, and it deploys the MCP wiring to reach live systems. What it
has never had is an agent whose only output is a plan, spending a whole window on it.

**The economic claim, stated so it can be falsified:** a defect caught in planning costs one
paragraph. The same defect caught mid-implementation costs a re-plan, a discarded diff, and a
context window. If a planning pass does not measurably reduce false starts in the coding pass,
this harness is not worth building. §8 makes that a test.

---

## 3. The one rule, and where it is enforced

> **The planner produces plans and nothing else.** No file writes in a repo, no mutating
> command, no deploy, no send.

`planning-harness-opus-1.md` argues the *why* of this well and I won't repeat it. The
disagreement is about **where the guarantee comes from.**

That doc reaches for a new target (`targets/metis.yaml`) that emits read-only MCP wiring.
That is a fork-tax: a new adapter, a new render path, a new set of tests, and a new thing to
keep in sync — for a property the harnesses already implement.

**Position: the read-only guarantee is a harness permission config, not a Mitos invention.**
Every modern coding harness has a permission layer with a deny list. The planner is that
harness with `Write`, `Edit`, and mutating Bash denied, plus a system prompt that says so.
Mitos's job is to *supply the context and the connections*, which it already does through
existing targets. Invariant #10 applies: no new mechanism until a concrete pain forces one.

What this buys, concretely: the planner is deployable **today** as a skill plus a permission
profile on an existing target, with zero compiler changes. What it costs: the guarantee is
per-harness rather than structural, so it must be verified per harness rather than proven once.
That is the right trade at concept stage and the wrong one at scale — revisit it when there are
three planners on three harnesses, not before.

---

## 4. Same eyes, different hands

The premise in the request: the planner uses the *existing* `SOUL.md` and `AGENTS.md`
configuration, and differs only in purpose. That is exactly right, and Mitos already has the
mechanism — `audience:` on identity partials, `context_file.sources` on the target.

| Partial | Hermes | Planner | Why |
|---|---|---|---|
| `security.md` | ✅ | ✅ | Same threat model. |
| `comms-style.md` | ✅ | ✅ | Truth over politeness serves planning better than it serves anything else. |
| `session-protocol.md` | ✅ | ✅ | Same tree, same navigation facts. |
| `operating-rules.md` | ✅ | ✅ | Names the tree and the paths — both agents read that tree. |
| `who-i-am.md` | ✅ | ❌ | The personal-assistant framing. Wrong hands. |
| `who-i-am-coding.md` | ❌ | ❌ | A coding agent. Wrong hands the other way. |
| `who-i-am-planning.md` | ❌ | ✅ | **New.** The deliberative framing: your output is a plan, your currency is anchored claims, your failure mode is confident wrongness. |
| `planning-protocol.md` | ❌ | ✅ | **New.** The loop, the stopping rule, the gates. |

Two new partials. Nothing else moves. The shared partials gain the planner in their
`audience:` list, and the split-persona pattern documented in `AGENTS.md` ("the persona itself
is audience-split, not shared") extends by one entry rather than being re-litigated.

**Why sharing the tree matters more than it sounds:** the planner and the coder cannot disagree
about what a project *is*, because they are reading one compiled tree from one registry. The
usual failure of handing a plan to a coding agent — the plan assumes a project layout the
executor doesn't see — is structurally impossible here. That is not a nice property of this
design; it is the entire reason to build the planner inside Mitos rather than as a standalone
tool.

---

## 5. Grounding against three substrates

This is the part the sibling documents don't cover, and it is what the whiteboard's bottom
layer is for.

A plan's claims come from somewhere. A coding harness has one source: the repository. The
planner, because Mitos deploys its connection wiring, has three — and they answer *different
questions*, which is why having all three is not redundancy.

| Substrate | Answers | Reached via | Anchor form | Fails when |
|---|---|---|---|---|
| **Source code** | "What was built, and how?" | file read, search, read-only commands | `path:line` + the quoted lines | The code is the record of a decision, not the decision. It cannot tell you why. |
| **MCP servers** | "What does the world say?" — specs, tickets, docs, the systems of record | the connection sections already in the deployed tree; documents resolved by graph ID | graph doc ID + `dateModified` | The document may be aspirational, stale, or contradicted by the code. |
| **Databases** | "What is the data actually like?" | a read-only query through a wired server | the query + its result, timestamped | Production shape is not the schema's promise. This is where assumptions die. |

**The rule that makes three sources safer than one, rather than three times as confusing:**

> When two substrates disagree, the disagreement **is** the finding. It is reported to the
> owner, not silently resolved by preferring one.

A spec that says "email is unique" and a database that has 4,102 duplicates is not a fact to
be reconciled by the planner picking a winner. It is precisely the problem the whiteboard means
by *tackle the problem before it becomes a problem*, and a plan that quietly picks the spec is
worse than no plan — it will be executed confidently and fail in production.

**The grounding contract, in one line:** *no assertion without an anchor.* Every factual claim
in a plan resolves to one of the three anchor forms above, or is explicitly typed as an
assumption and surfaced in its own section. The failure is never making an assumption; it is
laundering one into the plan as a fact.

**Database access needs a stated boundary, not a vibe.** Read-only credentials, a statement
timeout, no production writes ever, and results recorded as counts and shapes rather than
copied rows — the plan is an artifact that gets committed, and it must not become an
exfiltration path. If a connection cannot be made read-only at the credential level, the
planner does not get it. That is a hard gate, not a preference.

---

## 6. The loop: diverge, ground, converge

"Iterate until complete clarity" fails in two directions — the agent asks nothing and guesses,
or it interrogates the owner about things it could have read. The fix is a triage rule with a
checkable stopping condition.

**Every unknown lands in exactly one bucket:**

| Bucket | Handling |
|---|---|
| **Readable** — code, graph, or a document answers it | Resolve it silently. *Never ask what you can read.* |
| **Observable** — a read-only command or query answers it | Run it. The output becomes an anchor. |
| **Judgment** — only the owner can decide: priority, tradeoff, taste, an external constraint | Ask. |
| **Deferrable** — the answer doesn't change the plan's shape | Record it as a deferred decision, at the step where it bites. |

Questions go out in **batched rounds with a recommended default each**, so silence is a valid
answer. Rounds are capped at two. If a third round would fire, that is itself the finding: the
idea is not well-formed enough to plan, and the planner says so and stops rather than laundering
confusion into a confident document.

**Stopping condition:** every unknown is Readable-resolved, Observable-resolved,
Judgment-answered, or Deferred-and-recorded. That is a state you can check, not a feeling.

The shape of the pass, in three movements:

1. **Diverge** — restate the ask verbatim, route through the tree to the project, enumerate what
   could possibly be relevant across all three substrates. Cheap and wide. Nothing is decided.
2. **Ground** — read only what routing selected. Build the anchor ledger. Surface substrate
   disagreements. This is where the token budget goes.
3. **Converge** — options with the cheapest-that-works recommended, then ordered steps, then
   compress. Compression is a distinct movement because the plan's reader is a machine with a
   finite window, and prose written for a human is roughly twice the tokens it needs to be.

An owner can always say *"skip to the plan"* and accept reduced grounding explicitly. The
planner states what it skipped. Grounding is a dial the owner controls, not a toll it charges.

---

## 7. Where the plan lives

`planning-harness-opus-1.md` leaves this open, correctly identifying the tension: a coding
harness looks in the repo, but content belongs in the registry. It floats registry-authored /
deployed-as-`protect` / harvestable, and calls that "either elegant or one loop too many."

**Position: one loop too many. Plans are not registry content.**

The registry holds things that **compound** — a persona rule, a skill, a project's shape, the
knowledge graph. Their value grows with reuse and they are worth a maintainer's attention on
every change. A plan is the opposite: single-use, disposable within days, and specific to a
repo state that is already moving. Routing every plan through the inbox turns the maintainer
into a bottleneck on their own work and dilutes the inbox — which is valuable precisely because
its queue is short and everything in it deserves a decision.

So:

| Artifact | Home | Lifecycle |
|---|---|---|
| **The plan** | `<repo>/.plans/<slug>.md`, committed with the work | Dies when the work merges. |
| **The residue** | `registry/local/inbox/` as an ordinary candidate | Compounds. Reviewed like anything else. |

**Residue** is the small, valuable thing planning produces that outlives the plan:

- A document the planner had to hunt for → a `kind: graph` candidate.
- A constraint discovered the hard way → a line in the project's context partial.
- A procedure repeated across three plans → a skill.

The inbox stays for what compounds; the repo holds what expires. Invariant #3 is fully
respected — the planner still never writes into `registry/`, and it still proposes rather than
commits. It just doesn't ask permission to write a scratch document into the repo the owner
asked it to plan against.

**A useful consequence:** a plan committed alongside its implementation makes the pair reviewable
together. A reviewer can read what was intended before reading what was written, which is the
cheapest code-review improvement available and needs no tooling at all.

---

## 8. Consistency is the deliverable

The whiteboard's goal line: *a consistent approach to the generation of code through a
consistent planning step.* The operative word is **consistent**, and it is a stronger
requirement than "good."

A planner that produces a brilliant plan on Monday and a mediocre one on Tuesday for the same
class of problem has not solved anything — the variance is the cost. So the acceptance test is
about reproducibility, not quality:

> **The reproducibility test.** Run the same idea through the planner twice, in fresh sessions.
> The two plans must agree on: the anchors read, the option chosen, the step boundaries, and
> the definition of done. Wording may differ. If the *shape* differs, the process is
> underspecified — and the fix is a tighter rule in the protocol, not a better prompt.

This is the metric the harness should be built against, and it is cheap to run. Alongside it,
two more that are worth measuring precisely because they are the ones that justify the build:

| Metric | How | Passes when |
|---|---|---|
| **Rediscovery cost** | Tokens the coding harness spends exploring before its first edit | Materially lower with a plan than without. |
| **False starts** | Diffs written then discarded in the implementation pass | Materially lower. |
| **Shape agreement** | The reproducibility test above | Two runs, same shape. |

If a hand-written plan in the proposed format does not move the first two, the harness around
it is not worth building — and that finding costs three documents and an afternoon, which is
the cheapest possible falsification and should happen before any code is written.

---

## 9. Which machine it runs on

`planning-harness-opus-1.md` proposes carving an exception into the hermes-exclusivity rule so a
planner can co-reside with Hermes. **Position: don't. Put the planner on the workstation.**

The exclusivity rule exists because an agentic actor and a coding actor on one box fight over
the same workspace. But look at where the planner's inputs and outputs actually are:

- Its **substrate** is the source code and the databases — on the workstation.
- Its **consumer** is the coding harness — on the workstation.
- Its **output** lands in the repo — on the workstation.
- Its **context** is the compiled tree, which Mitos deploys to the workstation already
  (`agentic_tree:` mounts the full operating tree inside one project, precisely so a workstation
  harness can operate like an agentic one).

Nothing about the planner wants to be on the Hermes box. Putting it on the workstation means
the exclusivity rule is never touched, no carve-out is written, no test is added, and no
loader change ships. A contract change avoided is worth more than a contract change done well.

The planner is the workstation's architect, sitting between the moat and the coder — exactly
where the whiteboard draws it.

---

## 10. What ships, and in what order

Staged so that each stage can kill the next one cheaply.

| Stage | Ship | Kills the project if |
|---|---|---|
| **0** | The plan format alone. Hand-write three plans against real work; execute them with a coding harness; measure §8. | The metrics don't move. **No code at all.** |
| **1** | `registry/skills/plan-*/` — the loop as ordinary Mitos skills, `targets: [claude-code, antigravity]`. Run it inside an existing harness. | The loop doesn't survive contact with real ideas. |
| **2** | `who-i-am-planning.md` + `planning-protocol.md`; the permission profile that denies write tools; the substrate boundary of §5. | The read-only guarantee can't be made real per-harness. |
| **3** | Substrate grounding beyond the repo — the database read-only path, MCP-served specs resolved by graph ID. | Multi-substrate grounding costs more than the disagreements it catches are worth. |
| **4** | Only if 0–3 all pass: a dedicated target, plan-staleness checking, a console surface. | — |

Stage 0 is the honest test and it needs nothing built. Per the contribution rule, anything from
stage 2 onward lands with its schema validation, its docs section, and its acceptance test — or
not at all.

---

## 11. Deliberate non-goals

- **It does not write code.** Not a scaffold, not a stub, not "just the type signature." The
  moment it can, it will stop thinking early.
- **It does not estimate time.** Unverifiable, and it anchors the reader on the wrong axis.
- **It does not track execution.** The coding harness owns progress. A plan that tracks its own
  execution becomes a second source of truth, and the two will disagree.
- **It does not replace the org skills.** `org-software` still routes and governs the work; the
  planner is the harness that VP Engineering's planning step runs *inside*.
- **It does not need a framework.** Invariant #10: the loop is skills, the gates are questions,
  the ledger is a Markdown table. If any part of this wants an orchestrator, that part is wrong.

---

## 12. Open questions

1. **Does the planner get a live database connection, really?** §5 argues it is where the
   expensive assumptions die, and §5 also puts a hard read-only gate on it. Those may not both
   survive contact with a real credential story. If they can't, the honest answer is that the
   planner grounds against the schema and types the data-shape claims as assumptions — weaker,
   but not dishonest.
2. **What is the plan's format, exactly?** [`planning-harness-opus-1.md` §9](planning-harness-opus-1.md)
   proposes a full Plan Object schema; [`planning-harness-gemini-1.md` §4](planning-harness-gemini-1.md)
   proposes a Markdown/XML hybrid. Stage 0 should test both against the §8 metrics rather than
   arguing about it — this is a question with an experiment attached, which makes it the cheapest
   open question on the list.
3. **Who runs the critic pass?** Self-critique has a known ceiling. A second model reading only
   the finished plan — never the conversation that produced it — is a cleaner test, and it is
   only possible if the plan is genuinely self-contained. Which is a good reason to make it so.
4. **Does the residue loop actually fire?** §7 assumes a planner will propose the durable thing
   it learned. Agents are reliably bad at noticing what was worth keeping. This may need to be a
   mandatory closing step with an explicit "no residue, here is what I considered" answer —
   silence is not a pass.
