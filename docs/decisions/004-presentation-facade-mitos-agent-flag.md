# ADR-004 — Gate Mitos Agent as a presentation facade, not a compiler switch

- **Status:** Accepted
- **Date:** 2026-09-17
- **Numbering:** follows the milestone plan that commissioned it
  (`docs/implementation/mitos-agent-feature-flag-technical-project-manager-milestones.md`).
  It is the first decision recorded under `docs/decisions/`.

## Context

Mitos does two things that a reader cannot easily tell apart. It compiles one canonical body
of context into the native formats of third-party coding harnesses — Claude Code, Antigravity,
Claude Desktop — which works today and is the reason to use Mitos. It also ships `mitos-agent`,
a target for a first-party planning harness that is an incubating work in progress.

Both were visible at once. The operator console offered org-domain skills, a `mitos-agent`
target chip and an effort `Org domain` field; `mitos init` listed the planning harness as one
of two equal choices; the README gave it a row in the target table. A new user could not tell
which half of the product was finished.

The obvious fix — retire the target, the org skills and the example machine that uses them —
was rejected. `machines/example-linux.yaml` carries the compiler's only regression coverage for
mitos-agent planning output, and anyone already running the harness would lose it.

## Decision

Gate the harness at the **presentation layer only**, behind one boolean in the user's
configuration: `mitos_agent` in `registry/user.yaml` (default `false`), overridable in the
gitignored `registry/local/user.yaml`.

1. **The compiler never reads the flag.** `planner.deploys_org_content()`,
   `hosts_assistant_tree()` and `deploys_assistant_skills()` stay keyed to a machine's declared
   `targets:`. A machine that names `mitos-agent` compiles and deploys byte-for-byte the same
   whatever the flag says. This is the load-bearing invariant: it is what makes the change safe
   to ship without a migration.
2. **Nothing is retired.** `targets/mitos-agent.yaml`, `machines/example-linux.yaml` and the
   `org-*` skills stay in core. The harness returns as a documented feature when it ships; until
   then it is unadvertised, not removed. `mitos init` still honours a typed `2`.
3. **The loader enforces the type.** `mitos_agent` joins `KNOWN_USER_KEYS` under a new
   `_USER_BOOL_KEYS` group, validated with `isinstance(v, bool)`. `"true"` and `1` are rejected
   at load rather than read as truthy — a typo that silently revealed the harness would be worse
   than one that failed.
4. **It is deliberately absent from `_USER_TOKENS`.** A feature flag is not a placeholder;
   `{{user_mitos_agent}}` must never be a thing.
5. **The client gates on static predicates.** `build/review_ui/app.js` decides visibility from
   properties every item already carries in `/api/state`:

   ```javascript
   const hasMitosAgent = () => !!STATE.mitos_agent;
   const isTargetVisible = (t) => t !== "agents-md" && (hasMitosAgent() || t !== "mitos-agent");
   const isSkillVisible = (s) => hasMitosAgent() || !s.org_domain;
   ```

## Alternatives considered

**Join against `/api/org` to decide which skills are org skills.** Rejected. That response is
fetched asynchronously and may be skipped or fail; the join then comes back empty and every org
skill renders. A predicate that fails open is not a gate.

**Test the `org-` name prefix or a `mitos-agent` target.** Rejected after first ship (621be4a).
Both have false positives in the real registry: an overlay skill named `org-software-…` is an
ordinary coding-harness skill, and the `delivers:` skills and `gws` list `mitos-agent` alongside
the coding harnesses. `review.state()` instead carries `org_domain` as a read-only sibling of
`frontmatter`, and `isSkillVisible` reads only that.

**Expose `org_domain` through `_SKILL_META_WHITELIST`.** Rejected. That whitelist defines
which frontmatter fields the console's metadata editor lets you *edit*, and a domain's identity
is fixed by `propose_new_org_domain`. Widening it to answer a display question would make the
domain editable as a side effect.

**Return HTTP 403 from `/api/org` when the flag is off.** Rejected. The review server binds to
`127.0.0.1` for a single maintainer, with no sessions and no tenants. Hiding the button is the
request; authorization is machinery with no threat to answer. The client simply skips the fetch.

**Drop `mitos-agent` from `machines/example-linux.yaml` so a fresh clone carries no trace.**
Rejected — it would change `dist/` and delete the compiler's regression coverage for the target.
The facade hides the chip instead.

## Consequences

- A fresh clone still has `mitos-agent` in `STATE.machine_targets`, and `isTargetVisible` filters
  it out of the chips. `machine_targets` and `mitos_agent` are independent signals and must stay
  that way.
- `curl http://localhost:<port>/api/org` still returns domain metadata. Accepted: single-user
  loopback, no secrets in that response.
- The flag has no settings dialog. It is set once, if ever, by editing `registry/local/user.yaml`;
  the overlay README says so.
- `app.js` has no bundler, so a syntax slip in the gated code would take the whole console down.
  `test_review.py` runs `node --check` where Node exists and warns where it does not, and asserts
  each gated affordance as a source invariant.
