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
mitos_agent:
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

This machine's wired document store is **{{connection}}**. Mitos expands that name at deploy
time from the machine's own configuration, so it is the same store any connection section in
your always-on context would name.

- **If a store is named above**, create a document there titled `<work item key> — documentation`, with this
  record's body as its content, and add the URL it returns as a `locator:` line in the local
  record's header.
- **If no store is named above** — the line shows an unexpanded placeholder rather than a store
  name — this machine has no store wired. You cannot reach one and must not guess at one. Say
  so, and print the exact title and the body for the owner to add by hand.

Never let this step fail the work. An unwired store is a normal machine, and the local record —
which is what the loop actually parses — is already written by the time you get here.

### Identify the copy you publish

The store copy — and **only** the store copy — ends with an `## Identity` section, so the document
arrives in Mitos knowing which Work item it belongs to instead of as an anonymous file someone has
to map by hand. Append it as the last section, exactly this shape:

```json
{
  "@context": {"@vocab": "https://schema.org/"},
  "@type": "DigitalDocument",
  "additionalType": "return-record",
  "isPartOf": {"@id": "http://peccia.net/creativework/<effort-id>"},
  "identifier": "<run>",
  "http://peccia.net/deliverable": "documentation"
}
```

`<effort-id>` is the part of the work item key after `__` (`northwind__auth-rework` → `auth-rework`)
— the same id Mitos shows in an effort's heading, `### Auth rework (auth-rework)`, as the last
parenthesised group. `<run>` is the run folder name.

Two rules, and both matter:

- **Never add this section to the local record.** That file is parsed offline by Mitos and is the
  return lane's source of truth; it is written before you get here and must stay as written.
- **If the work item key has no `__`, omit the section entirely.** There is no effort to point at,
  and a mapping to nothing is worse than no mapping. Publish the document without it.

## Report back

Tell the owner what you corrected, what you added, and — separately — anything you found wrong that
you did **not** fix. That last list is the one they need.
