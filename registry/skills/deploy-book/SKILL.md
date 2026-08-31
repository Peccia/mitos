---
name: deploy-book
description: "After an implementation, write the ordered, verifiable steps to ship this change and the rollback for each, as a return record"
version: 1.0.0
author: Paul Peccia
license: MIT
platforms: [linux, macos, windows]
targets: [claude-code, antigravity, claude-app, mitos-agent]
delivers: deploy-book
category: devops
mitos_agent:
  tags: [deploy, release, rollback, return, sdlc]
---
# Deploy Book

When an implementation is complete and the effort declares `deploy-book`, write how to ship
**this change**. Scope is one release. How to *operate* the result afterward is a `runbook`; what
existing data and consumers must do is `migration-notes`.

## 1. Write for someone who was not here

They do not know what you know. Assume they are shipping this at the end of a long day and have
never seen the code. Every step is a command they can run or a specific action they can take —
never "update the config" without saying which key, to what, where.

## 2. Every step needs a way to tell whether it worked

This is what separates a deploy book from a list. For each step:

1. **Do** — the exact command or action.
2. **Expect** — what a successful result looks like. A specific output, a status, a value.
3. **If not** — what to do when it does not.

A step whose success is not checkable is a step that silently half-applies and is discovered three
hours later.

## 3. Order matters, and say why

State the order and, where it is not obvious, **why that order** — which step depends on which. A
book whose steps look interchangeable will be run out of order eventually.

Call out explicitly:

- anything that must happen **before** the code goes out (a migration, a flag, a key)
- anything that must happen **after**, and how long the gap can safely be
- anything that causes downtime, and how much

## 4. Write the rollback before you need it

For each step that changes state, write how to undo it — **now**, while the change is fresh.
Rollback written under pressure is rollback written wrong.

Be honest about what **cannot** be rolled back. A deleted column, a sent notification, a consumed
token. Naming a one-way door is far more useful than pretending everything reverses.

## 5. Preconditions and the stop rule

Open with what must be true before starting: access, backups taken, a healthy baseline. End with
the rule for **when to stop and roll back** rather than push forward — the decision nobody makes
well while it is going wrong.

## Write the return record

Write to **`{{returns_root}}/<run>/deploy-book.md`**.

`<run>` is the run folder for this implementation. Use the one the owner gave you; if they gave
none, use `<work-item-key>-<UTC timestamp>` — e.g. `northwind__auth-rework-20260826T141530Z`.
Other skills write their own records into the same folder: **never edit theirs, never merge yours
into a combined document.** Create the folder if it does not exist.

```markdown
---
schema: mitos.return/1
work: <the work item key, from the requirements document you were given>
delivers: deploy-book
format: markdown
run: <the run folder name>
produced_by: <the harness you are, e.g. claude-code>
---

## Preconditions

- database backup taken within the last hour
- deploy access to production
- current error rate at baseline

## Steps

1. **Apply the migration.** `alembic upgrade head`
   - Expect: `Running upgrade a1b2 -> c3d4`, exit 0
   - If not: stop. Do not deploy the code — it reads the new column.
   - Rollback: `alembic downgrade a1b2`

2. **Deploy the service.** `./deploy.sh --env prod`
   - Expect: health check green within 90s
   - If not: rollback below, then investigate
   - Rollback: `./deploy.sh --env prod --ref <previous-sha>`

## One-way doors

- The migration backfills `last_seen` from the audit log. Downgrading drops the column;
  the backfilled values are not recoverable.

## Stop rule

Roll back if the error rate is above baseline five minutes after step 2.
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

- **If a store is named above**, create a document there titled `<work item key> — deploy-book`, with this
  record's body as its content, and add the URL it returns as a `locator:` line in the local
  record's header.
- **If no store is named above** — the line shows an unexpanded placeholder rather than a store
  name — this machine has no store wired. You cannot reach one and must not guess at one. Say
  so, and print the exact title and the body for the owner to add by hand.

Never let this step fail the work. An unwired store is a normal machine, and the local record —
which is what the loop actually parses — is already written by the time you get here.

## Report back

Say where you wrote the book, how many steps it has, and — explicitly — anything you identified as
**not rollbackable**. That last one is what the owner needs before they schedule this.
