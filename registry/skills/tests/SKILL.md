---
name: tests
description: "After an implementation, write tests that would actually fail without the change, then file a return record naming what is covered and what is not"
version: 1.0.0
author: Paul Peccia
license: MIT
platforms: [linux, macos, windows]
targets: [claude-code, antigravity, claude-app, mitos-agent]
delivers: tests
category: devops
mitos_agent:
  tags: [tests, testing, coverage, return, sdlc]
---
# Tests

When an implementation is complete and the effort declares `tests`, cover the behaviour the change
introduced or altered.

## 1. The bar: would this test fail without the change?

A test that passes against the *old* code is not testing the new code. Before you keep a test, ask
whether it would fail if the change were reverted. If the answer is no, it is coverage theatre —
it will pass forever and catch nothing.

Where a behaviour is load-bearing, check this properly: revert the behaviour mentally (or actually),
confirm the test fails, restore it. Say in the record which tests you verified this way.

## 2. Test behaviour, not lines

Cover what would break for a caller:

- the **contract** — the thing the code promises to do
- the **edges** the change created: empty, absent, duplicated, malformed, too large
- what the code **refuses** to do, and that it refuses for the right reason

That last one matters most for anything guarded. A refusal that is not tested is a refusal that
quietly stops happening the next time someone edits nearby.

## 3. Make a failure diagnosable

The value of a test is what it tells you when it fails at 3am.

- Name it after the behaviour, not the function: `test_an_expired_token_is_rejected`, not
  `test_validate`.
- One reason to fail per test. A test asserting five unrelated things names none of them.
- Put the *why* in the test, briefly — especially for a regression, where the reason is the whole
  point and is otherwise lost.

## 4. Do not

- Do not assert on incidental detail (exact log wording, dict ordering) — it fails on innocent edits.
- Do not write a test whose assertion cannot fail (`assert x or True`). If you are unsure how to
  assert something, say so in the record instead.
- Do not weaken an existing test to make a new one pass. If an existing test now fails, either the
  change is wrong or the test's premise is; decide which, and say so.

## Write the return record

Write to **`{{returns_root}}/<run>/tests.md`**.

`<run>` is the run folder for this implementation. Use the one the owner gave you; if they gave
none, use `<work-item-key>-<UTC timestamp>` — e.g. `northwind__auth-rework-20260826T141530Z`.
Other skills write their own records into the same folder: **never edit theirs, never merge yours
into a combined document.** Create the folder if it does not exist.

```markdown
---
schema: mitos.return/1
work: <the work item key, from the requirements document you were given>
delivers: tests
format: markdown
run: <the run folder name>
produced_by: <the harness you are, e.g. claude-code>
---

## Added

- `tests/test_auth.py::test_an_expired_token_is_rejected` — covers FR-1
- `tests/test_auth.py::test_a_malformed_header_is_refused` — covers the edge FR-1 created

## Verified by reverting

- `test_an_expired_token_is_rejected` fails with the change reverted

## Not covered

- the rate-limit path: needs a clock seam that does not exist yet
```

`schema`, `work`, `delivers` and `format` are required — a record missing any of them is refused.
If you cannot determine the **work item key**, say so and write nothing rather than guessing: the
whole loop joins on that key, and a made-up one joins to nothing.

If the same content also went somewhere else (a wiki page, an issue), add a `locator:` line to the
header naming it. The local record is still written, always — it is the source of truth and the
remote copy is a convenience.

## Publish to the shared connection

The local record is a file on one machine. The owner's planning harness, and anyone reviewing this
work later, read the shared document store — so put a copy there too.

This machine's wired document store is **{{connection}}**. Mitos expands that name at deploy
time from the machine's own configuration, so it is the same store any connection section in
your always-on context would name.

The folder to publish into is **{{returns_container}}**, expanded from that connection at deploy
time. It is the only folder the evaluation lane reads, and it is not a project's own folder — a
record dropped anywhere else in the store is not evaluated, it is ingested as project context,
which is a different thing entirely.

- **If a store AND a folder are named above**, create a document in that folder titled
  `<work item key> — tests`, with this complete record as its content — the `---` header
  included, exactly as you wrote it locally —
  and add the URL it returns as a `locator:` line in the local record's header. The header is what
  tells the reader which work item and which run this document belongs to. Publish it even though
  the identity block below repeats it: the two carriers exist because either one can be lost to a
  store's own formatting, and a document that loses both is indistinguishable from any other file
  in the folder and is skipped in silence.
- **If either line shows an unexpanded placeholder** rather than a store name or a folder id,
  this machine has no store wired, or the connection names no evaluation folder. You cannot
  reach one and **must not guess at one — least of all a project folder that happens to be in
  the same store.** Say so, and print the exact title and the full record for the owner to add
  by hand.

Never let this step fail the work. An unwired store is a normal machine, and the local record —
which is what the loop actually parses — is already written by the time you get here.

### Identify the copy you publish

The store copy — and **only** the store copy — ends with an `## Identity` section. It is the
**second carrier of this record's identity, and it is the one that survives**: a store is not a
text file, and a document created by importing markdown loses its `---` header to a horizontal
rule — an element, not characters — which no reader can recover. The identity block is content
rather than markup, so it comes back out of any store intact.

Write it even when you are confident the header survived. Either carrier alone is enough for the
record to be read; neither is enough on its own to be relied on. Append it as the last section,
exactly this shape:

```json
{
  "@context": {"@vocab": "https://schema.org/"},
  "@type": "DigitalDocument",
  "additionalType": "return-record",
  "isPartOf": {"@id": "http://peccia.net/creativework/<effort-id>"},
  "identifier": "<run>",
  "http://peccia.net/deliverable": "tests",
  "http://peccia.net/schema": "mitos.return/1",
  "http://peccia.net/work": "<the work item key>",
  "http://peccia.net/format": "markdown",
  "http://peccia.net/produced_by": "<the harness you are>"
}
```

`<effort-id>` is the part of the work item key after `__` (`northwind__auth-rework` → `auth-rework`)
— the same id Mitos shows in an effort's heading, `### Auth rework (auth-rework)`, as the last
parenthesised group. `<run>` is the run folder name. **Every field above is required** — the block
has to carry enough to rebuild the header on its own, or it is not a carrier.

Two rules, and both matter:

- **Never add this section to the local record.** That file is parsed offline by Mitos and is the
  return lane's source of truth; it is written before you get here and must stay as written.
- **If the work item key has no `__`, omit the `isPartOf` line only** — keep the rest of the
  block. There is no effort to point at, and a mapping to nothing is worse than no mapping; but
  the work key, the run and the deliverable are still exactly what a reader needs, and throwing
  them away to avoid one absent mapping is how a record becomes anonymous.

### Verify the copy actually landed

Read the document back from the store — the same way anyone else would — and check it against
what you meant to publish:

- the first line is `---`, and the header fields are below it as plain text
- the identity block is present, and its JSON is intact

If the store reformatted either one, **say so in your report to the owner**, naming the document.
A store that eats a `---` fence will do it to every record from this harness, and the owner is
the only one who can change how the handoff is made. Do not retry silently and do not paper over
it — a handoff that half-landed is worth more as a reported fact than as a fixed-up document.

**Report the id of every document you created**, as its own line, in the form the store returns
it:

```
published: <deliverable> — <document id or URL>
```

You are the only one who knows where the record landed. The store holds many folders, this step
names none of them, and nothing downstream can find a document by guessing at a title — so an
unreported id is a record the owner has to go looking for. One line per document, and print them
even when everything went perfectly.

## Report back

Say how many tests you added, which ones you verified by reverting, and what you left uncovered and
why. **The uncovered list is not a failure** — it is the honest part, and hiding it is what turns a
green suite into a false one.
