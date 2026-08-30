---
name: requirements-receipt
description: "After an implementation is complete, report per-requirement outcomes against the requirements document that was handed over, as a return record Mitos can read"
version: 1.1.0
author: Paul Peccia
license: MIT
platforms: [linux, macos, windows]
targets: [claude-code, antigravity, claude-app, mitos-agent]
delivers: requirements-receipt
category: devops
hermes:
  tags: [requirements, return, receipt, handoff, sdlc]
---
# Requirements Receipt

When an implementation is finished and the work was driven by an exported requirements
document, write a **return record** saying what happened to each requirement.

This is not a summary. A summary is prose nobody can check. This is a structured answer
to a document that named its requirements by id, and Mitos reads it by parsing, not by
interpreting — so the shape below is the whole contract. **If you cannot follow it, write
nothing rather than something close.** A malformed record is refused; a missing one is a
visible "no return filed". Both are honest. A record that half-parses is not.

## 1. Find the requirements document you built against

It is the export the owner handed you. **Read its header, do not read its prose.** An
export opens with a `---` block naming everything you need as fields:

```yaml
---
schema: mitos.export/1
work: northwind__narrative-pipeline
template: systems-design
digest: sha256:9f2c1a...
requirements: [FR-1, FR-2, NFR-1]
---
```

Take three things from it, verbatim:

- `work` — the work item key. Copy it exactly; do not reconstruct it from a heading.
- `requirements` — every id you must report on. This is the list you are accountable
  for, and it is authoritative even if the document's body appears to hold more or fewer.
- `digest` — copy it into your record's `export_digest` field. It is how the owner is told
  their requirements moved on after this document was handed to you.

**Older exports carry no header.** If the `---` block is absent, fall back to the title
(`# Requirements: <key>`) for the work item key and to the bracketed ids in the body
(`- [FR-1] …`) for the list, and omit `export_digest`. Do not guess a digest.

If you cannot find that document at all, **stop and say so.** Do not invent ids: the whole
loop closes on identifiers Mitos minted, and an id you made up joins to nothing.

## 2. Decide one outcome per requirement

Use exactly these words. Nothing else is accepted:

| Outcome | Use when |
|---|---|
| `satisfied` | Done. |
| `partial` | Some of it. Say which part in a `claim:`. |
| `not-addressed` | Not attempted. |
| `blocked` | Attempted and prevented. Give the reason in a `claim:`. |
| `contested` | **You believe the requirement itself is wrong or cannot hold.** |

`contested` is important and under-used. You are often the first to discover that a
requirement cannot hold — it contradicts another one, or it cannot be met without breaking
something the owner cares about. Say so. **You cannot withdraw a requirement** (only the
owner can), but a contest is put in front of them at their next review with your reason
attached, which is the whole point of having the word.

## 3. Separate evidence from claims

Two different lines, and the difference is not stylistic:

- **`evidence:`** — a pointer someone else can follow. A test id, a file path, a commit.
- **`claim:`** — anything you are asserting without a pointer.

Write `evidence:` **only** when the thing you name actually exists and actually
demonstrates the requirement. A test path that does not exist, or that tests something
else, is worse than no evidence at all: it is the line a reviewer will trust and not check.
When in doubt, it is a `claim:`.

A requirement may carry both — evidence for the part that is proven, a claim for the part
that is not.

## 4. Write the record

Write to **`{{returns_root}}/<run>/requirements-receipt.md`**.

`<run>` is the run folder name. Use the one the owner gave you; if they gave none, use
`<work-item-key>-<UTC timestamp>` in the form `northwind__narrative-pipeline-20260826T141530Z`.
Create the folder if it does not exist. Other skills write their own records into the same
folder — never edit theirs, and never merge yours into one combined document.

The exact shape:

```markdown
---
schema: mitos.return/1
work: northwind__narrative-pipeline
delivers: requirements-receipt
format: markdown
run: northwind__narrative-pipeline-20260826T141530Z
produced_by: claude-code
export_digest: sha256:9f2c1a...
---

## Requirements

- [FR-1] satisfied
  evidence: tests/test_auth.py::test_expired_token_401
- [NFR-1] partial
  evidence: bench/latency.json
  claim: p99 is 180 ms locally; not measured under production load
- [FR-2] not-addressed
- [FR-3] contested
  claim: the gateway cannot log every rejection without also logging tokens

## Unrequested

- Added a token-refresh path. Nothing in the export asked for it.
```

Rules the reader enforces, so getting these wrong means the record is refused:

- The `---` header comes first, and `schema`, `work`, `delivers`, `format` are all required.
- `produced_by` is the harness you are (`claude-code`, `antigravity`, …). Optional but useful.
- `export_digest` is the `digest` you copied from the export's header, verbatim. Optional, and
  **omit it rather than guess** — a wrong digest reports the owner's requirements as having moved
  on when they have not, and a warning that cries wolf is one nobody reads.
- Ids are **bracketed**: `[FR-1]`, not `FR-1`. This is why `NFR-1` is never read as `FR-1`.
- One bullet per requirement, and **never the same id twice** — two verdicts for one id is
  refused rather than resolved by line order.
- `evidence:` / `claim:` go on their own indented lines under their bullet.
- Report **every** requirement the document listed. A requirement you omit is not neutral;
  it is a gap in the answer.

## 5. The Unrequested section

List anything you built that no requirement asked for. Be honest and specific here — this
is frequently the most valuable part of the record, because it is where the requirement
nobody wrote down shows up. If there was nothing, omit the section.

## 6. The `locator:` field

`locator:` names where this record ALSO landed — the shared connection (next section), or an issue
tracker or wiki if you filed it there too:

```
locator: https://example.atlassian.net/browse/PROJ-412
```

The local record is still written, always. It is the source of truth; the remote copy is a
convenience. Mitos never makes a network call to find out what you did.

## 7. Publish to the shared connection

The local record is a file on one machine. The owner's planning harness, and anyone reviewing this
work later, read the shared document store — so put a copy there too.

Look at your always-on context for a connection section headed ``## <Name> (`key`)``. That names
the document store this machine has wired.

- **If one is named**, create a document there titled `<work item key> — requirements-receipt`,
  with this record's body as its content, and add the URL it returns as the `locator:` line above.
- **If none is named**, you cannot reach a store and must not guess at one. Say so, and print the
  exact title and the body for the owner to add by hand.

Never let this step fail the work. An unwired store is a normal machine, and the local record —
which is what the loop actually parses — is already written by the time you get here.

## 8. Report back

Tell the owner, in one or two lines: the run folder you wrote, how many requirements you
reported, and — separately and explicitly — anything you marked `contested` or `blocked`.
Those two are the ones they need to act on.
