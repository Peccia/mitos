# Authoring Custom Capabilities Guide

Mitos allows you to extend your agent organization by authoring two kinds of reusable text assets: **Skills** and **Prompts**. You write these assets once in your private overlay (`registry/local/`), and Mitos handles compiling and deploying them to your active AI tools.

---

## 💡 1. Authoring Skills

A **Skill** is an on-demand playbook or capability that teaches your agents how to perform specific tasks (e.g. running migrations, drafting changelogs, or auditing security).

### Folder Structure
Each skill lives in its own subdirectory:
```
registry/local/skills/<name>/
├── SKILL.md                 ← Required: metadata + markdown instructions
├── scripts/                 ← Optional: helper scripts (Python, Bash, etc.)
├── examples/                ← Optional: reference inputs/outputs
├── references/              ← Optional: additional documentation (Mitos Agent convention)
├── templates/               ← Optional: fill-in templates (Mitos Agent convention)
└── resources/               ← Optional: other supporting assets (Antigravity convention)
```

All five supporting subdirectories are deployed alongside `SKILL.md` (and bundled into
claude-app zips); anything outside them is ignored. UTF-8 text only — a binary file
fails the load loudly.

### `SKILL.md` Schema
The `SKILL.md` file must start with a YAML frontmatter block containing metadata:

```yaml
---
name: changelog              # Unique logical name of the skill
description: "Drafts a release changelog from git logs" # Shown in rosters/commands
targets:                     # List of compatible tools
  - claude-code
  - mitos-agent
category: development        # Optional: organizational category (default: general)
scope: global                # Optional: global (default) | project — see below
requires_server: gws         # Optional: only deploy where this connection exists — see below
delivers: deploy-book        # Optional: the expected deliverable this skill produces — see below
---

# Instructions
To draft a changelog, follow these steps...
```

### Skill scope: global vs. project

`claude-code` and `antigravity` both offer two deploy surfaces per skill — a shared/personal
directory available everywhere, and a per-project directory bound through the project
manifest. The `scope:` frontmatter key picks which one:

- **`scope: global`** (default, or omitted): deploys to every shared directory the skill's
  `targets:` declare — `mitos-agent`'s skills dir, `claude-app`'s account-wide zip staging,
  antigravity's `antigravity_skills` (`~/.gemini/config/skills/`), and claude-code's personal
  `claude_code_skills` (`~/.claude/skills/`). No project binding needed.
- **`scope: project`**: deploys ONLY to the projects that list this skill under their
  manifest's `skills:` key, never the shared directory. `mitos-agent` and `claude-app` have no
  project-scoped surface at all, so they ignore `scope` and stay global regardless.

**`claude-app` is the exception worth understanding**, because it is the one target that
*deploys nothing*. `deploy` writes a zip to the machine's `claude_skills_staging` path and
stops; a human uploads it in Customize > Skills. So a `scope: project` skill staged there has
not leaked anywhere — it is a file on disk until someone chooses it. That has two consequences:

- **Manual targets take no curation.** `skills: {claude-app: {include:/exclude:}}` on a machine
  profile is refused at load. The staged set is a *menu*, and the choice already happens at
  upload time; filtering the menu only removes options you would then need a registry edit and
  a redeploy to reach. Automated targets (`mitos-agent`, `claude-code`, `antigravity`) still
  curate normally.
- **`requires_server:` still applies.** Which MCP connections a machine has is a fact about the
  machine, not a preference — a skill that is nothing but instructions for a server you never
  wired is a dangling instruction whether a human uploaded it or the compiler wrote it.

`mitos-agent` is therefore the only target `skill_deploy_warnings` reports a scope leak for: it
writes the file itself, automatically, machine-wide.

### Deliverable-producing skills: `delivers:`

An effort in the knowledge graph declares its **expected deliverables** — the artifacts every
implementation under it must yield. That declaration compiles into every harness's context as a
line asking for them. `delivers:` names which of those terms a skill actually produces:

```yaml
delivers: deploy-book        # one term from the controlled deliverables vocabulary
```

This makes the pair checkable. `deploy --dry-run` warns when an effort declares a deliverable that
**no skill on that machine knows how to produce** — otherwise an effort can ask for a deploy book,
every harness can read the request, no skill anywhere describes how to write one, and the gap only
surfaces months later as a missing deploy book.

**One skill per deliverable**, never one skill for all of them. The vocabulary is meant to grow, so
adding a deliverable should be an *addition* — a new file — rather than another edit to a file that
keeps getting longer. Independent skills also mean a bad one produces a weak artifact instead of
breaking the others.

An unknown value fails the compile. A typo here is worse than a missing skill: the skill deploys,
reads correctly, and satisfies nothing.

The vocabulary itself is closed (`graph.KNOWN_DELIVERABLES`): `documentation`, `tests`, `changelog`,
`deploy-book`, `runbook`, `migration-notes`, `requirements-receipt`. Three of those are easy to
confuse, so the boundary is fixed:

| Term | Answers | Lifespan |
|---|---|---|
| `deploy-book` | How do I ship **this change**? Steps, order, verification, rollback | One release |
| `runbook` | How do I **operate and troubleshoot** the result afterward? | Outlives the release |
| `migration-notes` | What changed for **existing data and consumers**, and what must they do? | One release, different audience |

### Connection-bound skills: `requires_server:`

Some skills are nothing but instructions for one MCP server's tools — the shipped `gws`
skill is a page of workflows for the `gws` Google Workspace server. On a machine where
that server was never set up, deploying it is worse than useless: the agent is told to
route every document request through tools it cannot call.

Declare the dependency and the skill self-limits:

```yaml
requires_server: gws         # a server key from connections/servers.yaml
```

It then deploys **only** to machines that declare that server in their profile's
`document_store:` — the same field that decides which connection sections a node may
name. A machine that omits `document_store:` (as every shipped
`machines/example-*.yaml` use-case template does) receives no connection-bound skill at
all, and `deploy` says so:

```
[warn] skill 'gws' targets 'claude-code' but requires the 'gws' connection,
       which machines/dev-box.yaml does not declare (document_store:) — not deployed
```

The gate is **not** a preference: unlike the machine-side `skills: {<target>: {include:}}`
curation, a machine cannot `include:` its way past a connection it doesn't have. Wire the
server first (see `docs/connectors/`), then add `document_store: <name>` to the machine
profile. The same signal gates MCP wiring — a machine with no declared connection gets no
server spliced into its harness config either.

### Binding to Projects (claude-code and antigravity)
A `scope: project` skill (or any skill you want a specific project's checkout to carry,
regardless of scope) is bound the same way for both targets:
1. List the skill under the `skills` key in your project manifest (`registry/local/projects/<project-slug>.yaml`):
   ```yaml
   skills:
     - changelog
   ```
   This deploys to `<project-root>/.claude/skills/changelog/SKILL.md` (if the skill targets
   `claude-code`) and/or `<project-root>/.agents/skills/changelog/SKILL.md` (if it targets
   `antigravity` — the same Agent Skills folder shape on both).
2. The skill's `SKILL.md` **must** list `claude-code` or `antigravity` in its `targets:` frontmatter
   list — one of the two targets with a project-scoped surface. If a project manifest binds a
   skill with neither, the compiler will fail loudly.

---

## 💬 2. Authoring Prompts (Slash-Commands)

A **Prompt** is a harness-agnostic text template. In Claude Code, prompts deploy as custom `/commands` that inject instructions on demand. In other harnesses, they appear in the Operator Console's Prompt Library for copy-pasting.

### File Location
Prompts live at the top level of the prompts folder:
```
registry/local/prompts/<name>.md
```

### Frontmatter Schema
Specify the prompt metadata and targets in the YAML frontmatter:

```yaml
---
description: "Drafts a quick bug report from terminal errors"
targets:
  - claude-code              # Enables deployment as a /bug-report command
category: utility
---

Draft a bug report from the following details. 

Context: $ARGUMENTS
```

### Placeholder Syntax
If a prompt targets `claude-code`, the placeholder `$ARGUMENTS` in the markdown body is replaced by any text you type after the command in the Claude Code terminal (e.g. `/bug-report "Connection timed out"`).

### Binding to Projects
Prompts are bound to Claude Code checkouts identically to skills. List the prompt under `prompts:` in your project's manifest:

```yaml
# registry/local/projects/acme.yaml
prompts:
  - bug-report
```
The prompt compiles to `<project-root>/.claude/commands/bug-report.md`.

---

## 🔄 The Authoring daily loop

1. **Write the asset**: Create the skill folder or prompt file in `registry/local/`.
2. **Bind to a project**: Edit the target project's manifest under `registry/local/projects/<slug>.yaml`.
3. **Validate**: Run `python build/compile.py compile` to run schema checks.
4. **Deploy**: Run `python build/compile.py deploy --machine <name>` to materialize the files into your project checkouts or global config directories.
