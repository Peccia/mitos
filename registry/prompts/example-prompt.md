---
name: example-prompt
description: "Demonstrate the prompts/ frontmatter schema — console-only, not deployed"
version: 1.0.0
category: example
targets: []
---

This is an example harness-agnostic prompt. The body is plain Markdown — no harness
packaging, no frontmatter in the deployed artifact.

**Frontmatter fields:**

- `name` (required) — unique key; must match no other prompt in the registry.
- `description` — one-line summary shown in the Prompt Library.
- `version` — semver string; bump when the prompt substantively changes.
- `category` — groups prompts in the Library (e.g. `engineering`, `planning`, `writing`).
- `targets` — list of harness targets that receive this prompt as a deployed file.
  Omit or set to `[]` for console-only prompts (the Prompt Library is always the
  universal surface regardless of this field).

**Targets currently supporting prompt deployment:**

- `antigravity` — deployed to `antigravity_skills/prompt-<name>.md` (the same directory as
  Antigravity skills, prefixed `prompt-` to avoid name collisions).

Additional targets are added after research confirms their native prompt surface
(see `docs/targets/` for per-harness findings notes and `RC1_PLAN.md` for the roadmap).

**To author your own:**

Copy this file to `registry/local/prompts/<your-name>.md`, fill in the frontmatter,
and write your prompt in the body. Run `python build/compile.py compile` to validate,
then `python build/compile.py deploy --machine <name>` to deploy.
