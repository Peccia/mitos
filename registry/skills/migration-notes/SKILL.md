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
hermes:
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

## Report back

Lead with whether action is required and by when. Then say what you classified as breaking, and
anything you flagged as irreversible.
