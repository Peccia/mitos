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
├── references/              ← Optional: additional documentation (Hermes convention)
├── templates/               ← Optional: fill-in templates (Hermes convention)
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
  - hermes
category: development        # Optional: organizational category (default: general)
scope: global                # Optional: global (default) | project — see below
---

# Instructions
To draft a changelog, follow these steps...
```

### Skill scope: global vs. project

`claude-code` and `antigravity` both offer two deploy surfaces per skill — a shared/personal
directory available everywhere, and a per-project directory bound through the project
manifest. The `scope:` frontmatter key picks which one:

- **`scope: global`** (default, or omitted): deploys to every shared directory the skill's
  `targets:` declare — `hermes`'s skills dir, `claude-app`'s account-wide zip staging,
  antigravity's `antigravity_skills` (`~/.gemini/config/skills/`), and claude-code's personal
  `claude_code_skills` (`~/.claude/skills/`). No project binding needed.
- **`scope: project`**: deploys ONLY to the projects that list this skill under their
  manifest's `skills:` key, never the shared directory. `hermes` and `claude-app` have no
  project-scoped surface at all, so they ignore `scope` and stay global regardless.

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
