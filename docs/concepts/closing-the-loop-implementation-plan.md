# Closing the Loop — implementation plan

**Status:** implemented (2026-08-30) · **Date:** 2026-08-30 · **Spans:** `mitos` + `mitos-agent`

The SDLC loop is open at one end. MitosAgent gathers requirements and exports them; a coding
harness implements them and files return records; MitosAgent harvests those records and reports
per-requirement outcomes. What does not happen: the implementation's own documents never reach the
shared document store, and nothing the loop learns is ever written back as a document the next
planning session can ground on.

```
[MitosAgent: planning & dossier]
        │  export (requirements + forward contract)
        ▼
[Coding harness: Claude Code / Antigravity]
        │  implements, then runs the deliverable skills
        ▼
[Return records: returns_root/<run>/*.md]        ← today: local disk only
        │  harvest → verified / claimed / unchecked / unbuilt
        ▼
[MitosAgent evaluation & graduation]
        │  Implemented Document                   ← today: does not exist
        ▼
[Document store → Mitos Discovery → knowledge graph]
```

This plan closes the two gaps in five batches. It records what was **already true** at the time of
writing, so a reader can tell new work from existing mechanics.

---

## What already exists (do not rebuild)

Establishing this first, because three items on the original roadmap were requests for things the
codebase already does.

| Capability | Where |
|---|---|
| Forward contract in the export | `export.py` renders `## Expected Deliverables` from `Dossier.deliverables` |
| The harness knows where to file returns | every `delivers:` skill says `Write to {{returns_root}}/<run>/<name>.md`, expanded per machine by `render._machine_value` |
| Publishing a document to the wired store | `console/api.py::post_export` → `artifact/writers.py::resolve_store_writer` → `runtime/mcp_client.py::connect_store_writer` |
| Per-requirement outcome buckets | `artifact/harvest.py::harvest` → verified / claimed-only / unverifiable / unresolved / not-addressed / unreported |
| A field for "where this also landed" | `artifact/returns.py::ReturnRecord.locator` — parsed, preserved, and **never written by anything** |
| A document belonging to an effort | `graph.py` — `schema:isPartOf` accepts an effort IRI, validated against the known effort set |
| A published document becoming an inbox record | the staging lane: a watched listing enumerates the store into `inbox/staging/<slug>.json`, which is what Discovery reads |
| Bounded, ranked grounded references | `memory/ledger.py::capped_anchors`, consumed by both the plan's Read First table and the dossier's reference list |

### Superseded

The original roadmap opened with "remove `claude-app` from five skills' targets to clear seven
deploy warnings." That was implemented by the opposite route and is **done**: manual (`mode: zip`)
targets take no curation and never report a scope leak, because staging a zip deploys nothing
(`loader.is_manual_skill_target`, `planner.SCOPE_IGNORING_SKILL_TARGETS`). `windows-main` compiles
at zero warnings with every skill still staged. Re-applying the original action would remove four
working skills from the claude.ai account and is not part of this plan.

---

## Batch 1 — Deliverable skills publish to the connection

**Repo:** `mitos` (skill content) + `mitos-agent` (surfacing only).

An implementation's documents — its runbook, its deploy book, its tests summary — exist only as
files on the machine that ran the harness. They are the artifacts most worth having in the shared
store, and they are the ones that never get there.

`ReturnRecord.locator` was defined for exactly this and has never been written.

### Changes

1. Each of the seven `registry/skills/<name>/SKILL.md` with `delivers:` gains a **Publish to the
   shared connection** step, after the existing "Write the return record" step:
   - The local record at `{{returns_root}}/<run>/<delivers>.md` is written **first and unchanged**.
     It is what `harvest` parses, and it stays the offline source of truth.
   - If this machine has a document store wired, create the document there titled
     `<work> — <delivers>`. Which connection is named by the `## <Name> (\`key\`)` section
     `render.connections_block` already puts in the harness's always-on context — no new
     placeholder token is needed.
   - Record the returned URL in the record's `locator:` header field.
   - With no store wired, print the title and body to add by hand, and say that is what happened.
2. `mitos-agent`: `console/api.py::_evaluation_rows` already reads the record; carry `locator`
   through to the payload and render it as a link in the evaluation panel.

### Why this shape

The local record cannot move to the store. `harvest` is offline, deterministic, and the thing the
whole return lane rests on; making it depend on a network read would trade a guarantee for a
convenience. Writing the document in *addition*, and recording where it went in a field that
already exists, costs one header line and changes no reader.

A skill that cannot publish must say so rather than fail. An unwired store is a normal state on a
fresh machine, and a deliverable skill that errors there would block an implementation over a
document.

### Acceptance

- A run on a wired machine leaves both a local record and a store document, and the record's
  `locator:` holds the document's URL.
- A run on an unwired machine leaves the local record exactly as it does today.
- `harvest` produces identical buckets in both cases.

---

## Batch 2 — Planning statistics in the export header

**Repo:** `mitos-agent`. Independent of every other batch.

A receiving harness is handed requirements with no sense of how settled they are. "Gathered over
four sessions across three weeks, eleven requirements agreed, two still draft" is the difference
between a specification and a first draft, and every input already exists.

### Changes

`artifact/export.py::_header` gains a planning-summary block from `planning_stats(d)`:

- Sessions — distinct session ids in the dossier's own `[date] <actor>: <change>` log, excluding
  `console` (the owner editing directly is a real change, but not a planning session).
- The gathering window — `Requirement.first_seen` / `last_changed`.
- Requirement counts by status.

**Sourced from the dossier and nothing else.** The original plan read the session index; that would
have made an export depend on state outside the record, so the same record copied to another
machine would export differently — and "same dossier in, same bytes out, forever" is the property
the whole module rests on. Clarify rounds are dropped for the same reason: they live in the ledger,
which is session-scoped and not part of the record. A number this cannot source honestly is better
left unsaid.

### Two constraints that matter

These fields go in the header and **not** into `digest_over`. The digest is locked to what an
implementation was asked to build; a statistic changing must never make a return already in flight
read as stale. This is the same rule `goal`, `approach`, and `references` already follow.

The window comes from the requirement stamps and **never** from the log's dates. Flagging a
requirement stamps no date on it — precisely so a flagged requirement exports byte-identically to
an unflagged one — but it does append a dated `console:` log line. Reading dates off the log put
that line's date in the header and leaked the owner's private doubt into the document handed to the
coding harness. Caught by an existing test; pinned by a new one.

### Acceptance

- `export_digest` is byte-identical before and after the stats block exists.
- A record with no history exports with the block omitted rather than zeroed — "0 sessions" reads
  as a fact about the work rather than about the record.
- A flagged requirement's export is byte-identical to an unflagged one.

---

## Batch 3 — Curating the grounded reference list

**Repo:** `mitos-agent`. Carries the only schema change in this plan.

`capped_anchors` bounded the reference list at ingest, which fixed volume. It did not give the
operator a say: the top 20 by score is a good default and it is still a guess about which files a
coding harness needs.

### The blocker to handle first

`memory/requirements.py::reconcile` states *"Nothing is ever deleted"*, and the references merge is
a pure union from disk with no `base` comparison. A delete written the way `post_requirements` is
written would see the dropped reference return from disk on the next save. This is a record-format
change before it is a UI change.

### Changes

1. `Reference` gains `pinned: bool`. A pinned reference survives `capped_anchors` regardless of
   score, joining the `PIN_SCORE` set at ingest.
2. Dropping a reference writes a **tombstone** rather than removing the line, so the record still
   round-trips and `reconcile` can tell "dropped here" from "never seen here."
3. `reconcile` learns one exception to its union: a reference present on disk, present in `base`,
   and absent from `mine` stays absent. Everything else unions exactly as it does now.
4. `console/api.py` gains a references write endpoint (TIER-2, loopback only — it changes what a
   coding harness will be handed, which is the definition of a steering write).
5. `console/ui/`: a pin toggle, a drop button, and a `req_id` select per row.

### Association is manual, deliberately

The operator picks which requirement a reference supports. Inferring it would mean a model guessing
that a given file supports FR-3, and a wrong guess becomes an unfalsifiable claim inside a document
the receiving harness treats as ground. Invariant #7 — no assertion without an anchor — applies to
the reference table as much as to a requirement.

### The bug this shape invites

`_REF_RE`'s note group runs to end-of-line, so the `[pinned]` marker appended after it lands INSIDE
the note and is re-rendered beside a fresh one — `[pinned] [pinned]` after two saves, growing by one
every time. Exactly the tail-pattern trap `mitos-agent/CLAUDE.md` records for `_ACCEPT_TAIL_RE`.
`_PIN_TAIL_RE` peels the marker before the note is read. Found by clicking the control in a browser,
not by the round-trip test — which parsed and rendered once and so could never see it.

### Acceptance

- A dropped reference stays dropped across a session that re-grounds the same anchors.
- A pinned low-score reference survives the cap.
- A record written before `pinned` existed round-trips byte-identically.
- Rendering a pinned reference twice is idempotent.

---

## Batch 4 — Evaluation summary and score

**Repo:** `mitos-agent`. Depends on Batch 1 for links, not for correctness.

The evaluation panel reports per-requirement outcomes. What it does not do is tell you, in a
sentence, how the implementation went.

### The recorded decision this touches

`_evaluation_rows` and `mitos-agent/CLAUDE.md` both state: *no score, percentage, or pass/fail
anywhere*, on the grounds that the inputs mix what a harness volunteered about itself with what
could be confirmed offline, and one number over those two is confidence nobody earned.

The owner has decided a score and findings summary are wanted. The design below delivers that while
keeping the property the rule exists to protect.

### Changes

1. `_evaluation_rows` is **untouched** — deterministic, no score, still the panel's primary view.
2. A new summary, rendered beside it and labelled as a summary:
   - The **score is computed in code** from the harvest buckets (verified / claimed-only /
     unchecked / unbuilt / unreported counts) and handed *to* the model. It is reproducible, and
     the prose cannot move it.
   - The **model writes findings prose only** — the repo's "code decides, the model writes" rule,
     applied unchanged.
3. The score renders with its inputs beside it — "N verified · N claimed · N unchecked" — so the
   number never stands alone. Weights: verified 1.0, claimed 0.5, unchecked 0.5, unbuilt /
   contested / unreported 0.0. `unreported` is deliberately in the denominator — leaving it out
   would let an implementation raise its score by staying quiet — and an empty run scores 0, not
   100, because "nothing was asked" and "everything succeeded" are different facts.
4. No provider wired, or a provider failure, degrades to the counts with no prose. A summary is an
   enhancement; the buckets are the product.

### Acceptance

- The same run scores identically on any model.
- The panel still renders with no provider available.
- `harvest`'s buckets are unchanged by anything in this batch.

---

## Batch 5 — The Implemented Document

**Repo:** `mitos-agent`. Depends on Batches 1 and 4.

`post_graduation` currently appends an artifact line and a log line, and writes nothing outward.
Graduation is the moment the loop should close.

### Changes

1. **Compose**, in code: goal, requirements against their outcomes (from the harvest buckets),
   acceptance criteria against what was verified, and the delivered artifacts with the `locator`
   links Batch 1 produces. Batch 4's summary becomes its executive section.
2. **Publish** through `resolve_store_writer` — the same seam `post_export` already uses — and
   `record_artifact("implemented", locator, …)` on the dossier, so the handover is on the record
   like every other artifact.
3. **The inbox record.** Publishing into the **watched** folder puts the document into
   `inbox/staging/<slug>.json` on the next watch refresh, which is the project's inbox record, via
   the staging lane that already exists. Mapping it to the Work item is then one action in
   Discovery, and `schema:isPartOf` already accepts an effort IRI, so the project:work relationship
   is expressible today with no schema change.

### Why MitosAgent does not write Mitos's inbox directly

Two reasons, both already recorded rather than invented here:

- `mitos-agent/CLAUDE.md` invariant #1: never import Mitos, never read `registry/`. The repo
  depends on the *shape* of a deployed tree and has no dependency edge back to the producer.
- `mitos-agent/CLAUDE.md`'s harvest row: *"Ingest deliberately does NOT live in Mitos… Produced
  documents reach the graph through the console's Discovery view — the human maps it."* That was a
  decision to cut cross-repo coupling, not an omission.

Publishing to the watched folder reaches the same end state through the seam both repos already
agree on, and costs zero lines on the Mitos side.

### The one manual step, stated plainly

Discovery needs a refresh before the document appears. Removing that click means a Mitos verb that
re-stages a listing on graduation — a real change to "the human maps it," and a decision that
belongs on its own rather than inside this batch. **Out of scope here.**

### Acceptance

- Graduating a Work item leaves a document in the store and an `implemented` line on the dossier.
- The document names, per requirement, what was verified and what was only claimed.
- With no store wired, graduation still records the artifact and reports that publishing was
  skipped.

---

## Order

**1 → 2 → 3 → 4 → 5.**

Batch 1 first: it is the unbuilt gap the loop is missing, and it feeds 4 and 5. Batch 2 is cheap and
touches nothing else. Batch 3 carries the only schema change and must not block the loop closing.
Batches 4 and 5 land last because each consumes what the earlier ones produce.

## Out of scope

- Auto-mapping a graduated document to its effort without a human step.
- Any Mitos-side ingest verb, or any read of `registry/` from `mitos-agent`.
- Inferring which requirement a grounded reference supports.
- Replacing the deterministic evaluation buckets with a model's reading of them.
