---
name: migration-notes
description: "After an implementation, write what changed for existing data and consumers and what they must do about it, as a return record"
version: 1.0.0
author: Paul Peccia
license: MIT
platforms: [linux, macos, windows]
targets: [claude-code, antigravity, claude-app, mitos-agent]
delivers: migration-notes
category: devops
mitos_agent:
  tags: [migration, breaking-change, upgrade, return, sdlc]
---
# Migration Notes

When an implementation is complete and the effort declares `migration-notes`, write what this
change means for **data and consumers that already exist**.

This one is addressed to **someone else** — another team, an integrator, a future upgrader. That is
what makes it different from a changelog (which announces) and a deploy book (which ships).

## 1. Lead with whether they have to do anything

The first line answers the only question they have: **do I need to act, and by when?**

- *"No action required. Existing clients keep working unchanged."*
- *"Action required before 1 October: every client sending `user_id` must switch to `subject_id`."*

Do not bury this under context. If they need to act and read only one line, that line must say so.

## 2. Separate breaking from non-breaking, plainly

Say which of these is true and do not hedge:

- **Breaking** — something that works today stops working. Name exactly what, and what to do.
- **Behaviour change** — it still works but does something different. Name the before and after.
- **Additive** — new capability, nothing existing affected.

If you are unsure whether something is breaking for a consumer you cannot see, **say it is** and
explain the case. A false alarm costs someone an hour; a missed break costs them an outage.

## 3. Data already in the system

Existing rows do not migrate themselves. Be specific:

- What happens to data written before this change? Is it converted, defaulted, or left alone?
- Is there a **backfill**? Is it automatic or manual, and how long does it take?
- Is there a period where **both shapes exist**? What reads them during that window?
- Is any of it **irreversible**? Say so plainly and say what is lost.

## 4. Give them the actual change to make

Not a description of the change — the change:

```
- client.send(user_id=u.id)
+ client.send(subject_id=u.id)
```

A before/after they can copy is worth three paragraphs explaining it. Include the version or date
the old form stops working, if there is one.

## 5. Compatibility window

If old and new are both accepted for a while, say **exactly how long** and what happens at the end.
"Deprecated" with no date is ignored, every time.

## Write the return record

Write to **`{{returns_root}}/<run>/migration-notes.md`**.

`<run>` is the run folder for this implementation. Use the one the owner gave you; if they gave
none, use `<work-item-key>-<UTC timestamp>` — e.g. `northwind__auth-rework-20260826T141530Z`.
Other skills write their own records into the same folder: **never edit theirs, never merge yours
into a combined document.** Create the folder if it does not exist.

```markdown
---
schema: mitos.return/1
work: <the work item key, from the requirements document you were given>
delivers: migration-notes
format: markdown
run: <the run folder name>
produced_by: <the harness you are, e.g. claude-code>
---

## Action required

**Before 1 October 2026.** Clients sending `user_id` must switch to `subject_id`.

## Breaking

- `POST /events` no longer accepts `user_id`. Requests carrying it get 400 after 1 October;
  until then they are accepted with a deprecation header.

```
- client.send(user_id=u.id)
+ client.send(subject_id=u.id)
```

## Existing data

- Rows written before this change are backfilled automatically on first read. No action.
- The backfill is one-way: `user_id` is not retained after conversion.

## Not affected

- `GET /events` is unchanged in both shape and behaviour.
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
  `<work item key> — migration-notes`, with this complete record as its content — the `---` header
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
  "http://peccia.net/deliverable": "migration-notes",
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

Lead with whether action is required and by when. Then say what you classified as breaking, and
anything you flagged as irreversible.
