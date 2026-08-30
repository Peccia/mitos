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

Look at your always-on context for a connection section headed ``## <Name> (`key`)``. That names
the document store this machine has wired.

- **If one is named**, create a document there titled `<work item key> — tests`, with this
  record's body as its content, and add the URL it returns as a `locator:` line in the local
  record's header.
- **If none is named**, you cannot reach a store and must not guess at one. Say so, and print the
  exact title and the body for the owner to add by hand.

Never let this step fail the work. An unwired store is a normal machine, and the local record —
which is what the loop actually parses — is already written by the time you get here.

## Report back

Say how many tests you added, which ones you verified by reverting, and what you left uncovered and
why. **The uncovered list is not a failure** — it is the honest part, and hiding it is what turns a
green suite into a false one.
