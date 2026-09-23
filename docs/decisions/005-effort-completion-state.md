# ADR-005: Effort completion state goes through the Inbox as schema:creativeWorkStatus

- **Status:** Accepted
- **Date:** 2026-09-23
- **Numbering:** follows the milestone plan that commissioned it
  (`docs/implementation/work-item-done-requirements-evaluation-technical-project-manager-milestones.md`).

## Context

When a Work item graduates in Mitos Agent, its Implemented Document is mapped into the project
graph under the effort. Nothing in the graph recorded that the effort itself was finished, so a
completed effort looked the same as an active one in every deployed tree.

The first plan added free-text `status` and `evaluation` fields, a CLI flag that wrote
`registry/graph/` directly, and an automatic server-side trigger keyed on
`Document.doc_type == "implemented-requirements"`. The architecture and QA reviews blocked it for
four reasons:

1. A direct CLI write breaks invariant #3: nothing writes the graph directly.
2. The trigger could never fire. `doc_type` holds a MIME-derived kind (`document`,
   `spreadsheet`). The identity fragment lives in the document body, and only the console's
   identity peek reads it.
3. `propose_graph_change` rebuilt efforts from the incoming dict, so a rename or visibility
   toggle would have silently cleared Done.
4. A free-text status allowed illegal states, and an unchecked evaluation could point at a
   document that doesn't exist.

## Decision

- **Vocabulary.** Status uses the public `schema:creativeWorkStatus` term with a closed
  vocabulary, `KNOWN_STATUSES = ("done",)`. An absent status means active. There are no other
  workflow states. The evaluation is `peccia:evaluation`, an IRI that points to a
  `DigitalDocument` in the same project graph, and it requires status `done`. The loader,
  `propose_graph_change` and accept-time merging all enforce these rules. Both properties are
  left out when absent, so existing graphs serialize to the same bytes as before.
- **Inbox only.** The CLI verb `graph --project P --complete-effort ID [--evaluation-doc DOC]`
  and every console action propose a `kind: graph` Inbox candidate. Only an accept writes the
  graph.
- **Explicit confirmation.** The server never marks an effort Done on its own. When the identity
  peek in Tweak & map finds an Implemented Document fragment, the console shows a checkbox that
  starts unticked. Ticking it adds the effort edit to the same draft, so the mapping and the
  Done change land in one candidate.
- **Keep stored values.** If an effort dict has no `status` or `evaluation` key, the stored value
  is kept. An explicit `""` clears it. Each candidate records `efforts_touched`, and an accept
  merges only those efforts. This way an old candidate can't undo a change that another
  candidate made to a different effort.
- **Cross-repo grammar.** A Done effort renders
  `` _Status: Done · Implemented Document: `<id>`._ `` (or `_Status: Done._`) after its goal
  line. Mitos Agent parses the line with an anchored regex (`Node.effort_statuses`), and golden
  tests in both repos pin the exact strings. Mitos Agent treats the line as information only.
  `Dossier.graduated` still decides whether a session can write.

## Consequences

- Marking an effort Done takes one extra step: someone must accept the candidate. In exchange,
  every Done change appears in the decisions log and lands in the right overlay.
- You can't remove a document that an effort uses as its evaluation unless the same proposal
  clears that evaluation.
- Legacy candidates without `efforts_touched` still merge every effort in their fragment, as
  before.
