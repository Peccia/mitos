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
