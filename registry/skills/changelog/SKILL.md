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
hermes:
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

## Report back

Quote the entry you added and say where. If you deliberately wrote nothing, say that and why.
