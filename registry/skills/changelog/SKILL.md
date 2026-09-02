---
name: changelog
description: "After an implementation, add a changelog entry written for the reader rather than the author, then file a return record"
version: 1.0.0
author: Paul Peccia
license: MIT
platforms: [linux, macos, windows]
targets: [claude-code, antigravity, claude-app, mitos-agent]
delivers: changelog
category: devops
mitos_agent:
  tags: [changelog, release, return, sdlc]
---
# Changelog

When an implementation is complete and the effort declares `changelog`, add an entry to the
project's changelog.

## 1. Match the file that is already there

Read the existing changelog first and follow it: its categories, its tense, its level of detail,
its version heading style. Most projects follow [Keep a Changelog](https://keepachangelog.com/)
(`Added` / `Changed` / `Deprecated` / `Removed` / `Fixed` / `Security`) under an `[Unreleased]`
heading — but the file in front of you wins over any convention.

Never invent a version number. New work goes under `Unreleased` unless the owner says otherwise.

## 2. Write for the reader, not the author

The reader wants to know **what is different for them**. They do not care what you did.

- Not: *"Refactored the token validator and added a helper."*
- Yes: *"An expired token is now rejected with 401 instead of 500."*

For anything that changes behaviour, say **what it does now**, and where it is not obvious, **what
it did before**. A `Changed` entry with no before is half an entry.

For a `Fixed` entry, describe the **symptom someone experienced**, not the code that was wrong —
that is how a reader recognises their own bug.

## 3. Breaking changes are the whole point of the file

If anything a user depends on now behaves differently, is gone, or is renamed, say so plainly and
say what to do instead. This is the one entry people actually go looking for. Never soften it.

## 4. No entry is better than a vague one

If the change is genuinely invisible to every reader — an internal rename, a test-only change —
**write nothing** and say so in the record. A changelog padded with "various improvements" is a
changelog people stop reading, and then the breaking change goes unread with it.

## Write the return record

Write to **`{{returns_root}}/<run>/changelog.md`**.

`<run>` is the run folder for this implementation. Use the one the owner gave you; if they gave
none, use `<work-item-key>-<UTC timestamp>` — e.g. `northwind__auth-rework-20260826T141530Z`.
Other skills write their own records into the same folder: **never edit theirs, never merge yours
into a combined document.** Create the folder if it does not exist.

```markdown
---
schema: mitos.return/1
work: <the work item key, from the requirements document you were given>
delivers: changelog
format: markdown
run: <the run folder name>
produced_by: <the harness you are, e.g. claude-code>
---

## Entry

Added under `## [Unreleased]` → `### Fixed` in `CHANGELOG.md`:

- An expired token is now rejected with 401 rather than 500. Previously any malformed
  `Authorization` header reached the handler and failed there.

## Not recorded

- the internal rename of `_check` to `_validate`: invisible to every reader
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
  `<work item key> — changelog`, with this complete record as its content — the `---` header
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
  "http://peccia.net/deliverable": "changelog",
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

Quote the entry you added and say where. If you deliberately wrote nothing, say that and why.
