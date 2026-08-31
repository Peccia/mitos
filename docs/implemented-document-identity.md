# The Implemented Document's identity fragment

**The contract.** When Mitos-Agent graduates a Work item, it publishes an Implemented Document —
the evaluated record of what was actually built — into the project's watched store folder. That
document carries a small, fenced JSON-LD block naming which Work item it reports on, in the same
vocabulary Mitos's own knowledge graph validates (`build/agentic/graph.py`). Mitos never imports
Mitos-Agent and Mitos-Agent never imports Mitos (see each repo's boundary test,
`build/tests/test_boundary.py` here and `tests/test_boundary.py` there) — this document is the
contract both sides conform to instead of sharing code.

**This file is the source of truth for the fragment's shape.** Mitos-Agent's renderer
(`mitos-agent/src/mitos_agent/artifact/evaluation.py::identity_fragment`) implements it; Mitos's
console (`build/agentic/review.py`) reads it. If the two ever disagree, this document decides —
update it first, then bring both implementations into line.

## Shape

A fenced ` ```json ` block under a `## Identity` heading, appended as the LAST section of the
rendered Markdown document:

```json
{
  "@context": {"@vocab": "https://schema.org/"},
  "@type": "DigitalDocument",
  "additionalType": "implemented-requirements",
  "isPartOf": {"@id": "http://peccia.net/creativework/<effort-id>"},
  "identifier": "<run>"
}
```

There are **two** `additionalType` values, and they are a closed set:

| `additionalType` | The document | Written by |
|---|---|---|
| `implemented-requirements` | the Implemented Document, one per graduation | Mitos-Agent (`evaluation.py::identity_fragment`) |
| `return-record` | one deliverable's return record, published to the store beside its local copy | the coding harness, following a `delivers:` skill |

An unrecognized value is ignored exactly like a malformed block — the reader degrades to the
manual flow rather than guessing what a type it has never heard of means.

- `isPartOf` — the Work item's IRI, in Mitos's own `CREATIVE_WORK_NS` form
  (`http://peccia.net/creativework/` + the effort id — no hyphen in "creativework"). `<effort-id>`
  is the SAME id Mitos renders into the effort's tree heading (`### Auth rework (auth-rework)`,
  the last parenthesised group — see graph.py's `effort_heading`) and the same id Mitos-Agent's
  requirements dossier keys itself on (`memory/requirements.py::dossier_key`). It always matches
  `graph.py`'s `_EFFORT_ID_RE` (`^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`), because Mitos only ever mints
  ids in that shape.
- `additionalType` — always the literal string `"implemented-requirements"`, so a reader (or a
  future second consumer) can tell an identity fragment from any other JSON-LD a document might
  carry.
- `identifier` — the run's identifying string (`Evaluation.run`), the same value the document's
  own summary line already shows the reader (`` _Run `<run>` · score …_ ``). Not a Drive id — this
  document has none yet at render time.
- No `@id` on the `DigitalDocument` node itself. The fragment is written before the document is
  uploaded to any store, so it has no Drive id to carry; Mitos assigns the real
  `http://peccia.net/document/<drive-id>` IRI itself, from the real id, once the document lands in
  the graph.

Omitted entirely — no `## Identity` section at all — when the dossier carries no effort id (a
per-project record, or a tree deployed before Mitos started rendering effort ids into headings).
There is nothing to point at, so nothing is asserted.

## The `return-record` variant

A return record published to the shared store carries the same block with one extra key:

```json
{
  "@context": {"@vocab": "https://schema.org/"},
  "@type": "DigitalDocument",
  "additionalType": "return-record",
  "isPartOf": {"@id": "http://peccia.net/creativework/<effort-id>"},
  "identifier": "<run>",
  "http://peccia.net/deliverable": "<delivers>"
}
```

- `http://peccia.net/deliverable` — the deliverable this record answers for, written as the FULL
  predicate IRI because that is exactly how Mitos serializes it on the effort itself
  (`graph.DELIVERABLE_PRED`; see any `registry/graph/<slug>.jsonld`, where an effort's forward
  contract appears as `"http://peccia.net/deliverable": [...]` under the same bare
  `{"@vocab": "https://schema.org/"}` context). One vocabulary in both directions: the effort
  declares `tests` as expected, and the record answers with `tests`. Its value is a member of
  `graph.KNOWN_DELIVERABLES`.
- `identifier` — the run, the same string the record's own `run:` header field carries. It is what
  groups the several records of one run back together once they are flat documents in a store.
- `isPartOf` and `@type` are unchanged, and carry the same meaning.

**Where it goes, and where it must not.** The fragment belongs ONLY in the copy published to the
store. The local record at `{{returns_root}}/<run>/<delivers>.md` is written first and left exactly
as `artifact/returns.py` expects — that parser is the offline source of truth for the whole return
lane, and an identity block is for Mitos's Discovery view, which never reads the local file. A
harness that cannot publish therefore writes no fragment anywhere, which is correct: there is no
store document for it to identify.

**Why a return record wants one at all.** Without it, a published `<work> — tests` document reaches
Discovery as an anonymous file, and the operator reconstructs by hand a mapping the harness knew
when it wrote the thing. That is the same waste the Implemented Document's fragment already
removes; there is no reason the other six deliverables should pay it.

## How each side uses it

**Mitos-Agent** renders the fragment purely from the dossier and the run — same inputs, same
bytes, forever (pinned by a snapshot test, `tests/test_evaluation.py`). It has no opinion about
whether the effort id names anything real; that is Mitos's graph to know, not this repo's.

**Mitos** treats the fragment strictly as a hint, never an authority. When an operator opens the
"map to effort" flow for a Discovery document (the Knowledge Graph tab's Tweak & map), the console
scans the staged document's content for this block. If it parses, and the named effort id exists
in that project's current graph, the effort dropdown is prefilled with the suggestion — the
operator still confirms or changes it before Propose. A block that fails to parse, or names an id
the project's graph doesn't have, degrades silently to today's manual flow: nothing errors, no
candidate is created, no invisible write happens. The accepted candidate goes through the exact
same `propose_graph_change` → `kind: graph` inbox path every mapped document already uses, so it
passes `graph.py`'s own `isPartOf` validation unchanged — this fragment never bypasses that gate,
it only saves the operator from retyping what Mitos-Agent already knew.
