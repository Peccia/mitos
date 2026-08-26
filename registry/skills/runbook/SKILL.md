---
name: runbook
description: "After an implementation, write how to operate and troubleshoot the result once it is running, as a return record"
version: 1.0.0
author: Paul Peccia
license: MIT
platforms: [linux, macos, windows]
targets: [claude-code, antigravity, claude-app, mitos-agent]
delivers: runbook
category: devops
hermes:
  tags: [runbook, operations, oncall, return, sdlc]
---
# Runbook

When an implementation is complete and the effort declares `runbook`, write how to **operate**
what you built once it is running. This outlives the release. Shipping *this change* is a
`deploy-book`; this is everything after.

## 1. Write for 3am

Your reader is on call, did not build this, and is under pressure. That single constraint decides
the whole shape:

- **Symptom first.** They arrive with a symptom, not a cause. Organise by what they can see.
- **Answers, not architecture.** No design rationale, no history. What is wrong, and what to do.
- **Concrete commands.** Copy-pasteable, with the expected output beside them.

If a section would not help someone with no context at 3am, it does not belong here.

## 2. Structure it by symptom

For each failure worth writing down:

| | |
|---|---|
| **Symptom** | What they will actually observe — an alert name, an error string, a graph shape |
| **Likely cause** | Most common first, not most interesting |
| **Check** | The command that confirms or rules it out, and what the answer means |
| **Fix** | What to do, including whether it is safe to just retry |
| **If that fails** | The next thing, or who to wake |

Write the failures you know are possible because you built it — the ones nobody else can predict.
Exhaustiveness is not the goal; **the three most likely failures written well beat twenty written
thinly.**

## 3. Cover the routine operations too

Not only failure:

- how to tell it is healthy right now (the one command)
- how to start, stop, and restart it safely
- what its normal load and normal error rate look like — **a number, not "low"**, because a reader
  cannot judge "elevated" without a baseline
- where the logs are, and what a normal log line looks like

## 4. Say what NOT to do

The most valuable section and the one always missing. Every system has an action that looks
obviously right at 3am and makes things much worse: the restart that loses the queue, the cache
clear that stampedes the database, the retry that duplicates the charge.

Write those down. **If you know of one, it goes in this runbook**, phrased as a warning with the
consequence attached.

## Write the return record

Write to **`{{returns_root}}/<run>/runbook.md`**.

`<run>` is the run folder for this implementation. Use the one the owner gave you; if they gave
none, use `<work-item-key>-<UTC timestamp>` — e.g. `northwind__auth-rework-20260826T141530Z`.
Other skills write their own records into the same folder: **never edit theirs, never merge yours
into a combined document.** Create the folder if it does not exist.

```markdown
---
schema: mitos.return/1
work: <the work item key, from the requirements document you were given>
delivers: runbook
format: markdown
run: <the run folder name>
produced_by: <the harness you are, e.g. claude-code>
---

## Health

- `curl -s localhost:8080/healthz` → `{"status":"ok","queue":<n>}`
- Normal: queue depth under 500, error rate under 0.2%

## Symptoms

### Queue depth climbing, no errors
- **Likely cause**: a stuck consumer holding a lease.
- **Check**: `app leases --stale` — any lease older than 5 minutes is stuck.
- **Fix**: `app leases --release <id>`. Safe to repeat.
- **If that fails**: restart the consumer (below), then page the owner.

## Do NOT

- Do **not** clear the cache to fix slow reads. Every instance refills at once and the
  database becomes the outage. Scale reads first.

## Restarting safely

1. `app drain` — wait for in-flight to reach 0 (up to 30s)
2. `systemctl restart app`
```

`schema`, `work`, `delivers` and `format` are required — a record missing any of them is refused.
If you cannot determine the **work item key**, say so and write nothing rather than guessing: the
whole loop joins on that key, and a made-up one joins to nothing.

If the same content also went somewhere else (a wiki page, an issue), add a `locator:` line to the
header naming it. The local record is still written, always — it is the source of truth and the
remote copy is a convenience.

## Report back

Say where you wrote the runbook, which symptoms you covered, and — explicitly — every "do NOT" you
recorded. Those are the ones worth the owner reading now rather than at 3am.
