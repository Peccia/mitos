---
name: documentation
description: "After an implementation, update the documentation the change made wrong and add what it made necessary, then file a return record"
version: 1.0.0
author: Paul Peccia
license: MIT
platforms: [linux, macos, windows]
targets: [claude-code, antigravity, claude-app, mitos-agent]
delivers: documentation
category: devops
hermes:
  tags: [documentation, docs, return, sdlc]
---
# Documentation

When an implementation is complete and the effort declares `documentation`, bring the docs back
in line with the code.

## 1. Fix what the change made false, before writing anything new

This is the step that gets skipped, and skipping it is how a codebase ends up with confident,
detailed, wrong documentation. **Stale documentation is worse than missing documentation**, because
a reader trusts it and does not check.

Search the docs for every claim the change invalidated:

- names you renamed, flags you removed, defaults you altered
- counts, limits, and examples that no longer hold
- a described behaviour that now behaves differently
- setup or install steps that changed

Fix each one. If a document is now wrong end to end, say so in the record rather than quietly
half-fixing it.

## 2. Then document what is genuinely new

Only what a reader cannot get from the code itself:

- **What it is for**, in one or two plain sentences, before any mechanism.
- **How to use it** — the smallest real example, one that would actually run.
- **What it refuses to do**, and why. This is usually the most valuable paragraph and the one most
  often missing.

Write it where the surrounding docs already live, matching their voice and depth. Do not create a
new document for something that belongs in an existing one.

## 3. What NOT to write

- Do not narrate the implementation. Nobody reads docs to learn what you did.
- Do not restate what the code plainly says. A parameter list is not documentation.
- Do not document intentions. If it is not built, it does not go in the docs.

## Write the return record

Write to **`{{returns_root}}/<run>/documentation.md`**.

`<run>` is the run folder for this implementation. Use the one the owner gave you; if they gave
none, use `<work-item-key>-<UTC timestamp>` — e.g. `northwind__auth-rework-20260826T141530Z`.
Other skills write their own records into the same folder: **never edit theirs, never merge yours
into a combined document.** Create the folder if it does not exist.

```markdown
---
schema: mitos.return/1
work: <the work item key, from the requirements document you were given>
delivers: documentation
format: markdown
run: <the run folder name>
produced_by: <the harness you are, e.g. claude-code>
---

## Updated

- `docs/cli.md` — corrected the default for `--include`, which the change made false
- `README.md` — removed the removed `--legacy` flag

## Added

- `docs/returns.md` — new, covers the return lane end to end

## Still wrong

- `docs/architecture.md` describes the old two-store model throughout; needs a rewrite, not a patch
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

- **If one is named**, create a document there titled `<work item key> — documentation`, with this
  record's body as its content, and add the URL it returns as a `locator:` line in the local
  record's header.
- **If none is named**, you cannot reach a store and must not guess at one. Say so, and print the
  exact title and the body for the owner to add by hand.

Never let this step fail the work. An unwired store is a normal machine, and the local record —
which is what the loop actually parses — is already written by the time you get here.

## Report back

Tell the owner what you corrected, what you added, and — separately — anything you found wrong that
you did **not** fix. That last list is the one they need.
