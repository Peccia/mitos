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

- **If a store is named above**, create a document there titled `<work item key> — changelog`, with this
  complete record as its content — the `---` header included, exactly as you wrote it locally —
  and add the URL it returns as a `locator:` line in the local record's header. The header is what
  tells the reader which work item and which run this document belongs to; a store copy published
  without it is indistinguishable from any other file in the folder and is skipped in silence.
- **If no store is named above** — the line shows an unexpanded placeholder rather than a store
  name — this machine has no store wired. You cannot reach one and must not guess at one. Say
  so, and print the exact title and the full record for the owner to add by hand.

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
  "http://peccia.net/deliverable": "changelog"
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

Quote the entry you added and say where. If you deliberately wrote nothing, say that and why.
