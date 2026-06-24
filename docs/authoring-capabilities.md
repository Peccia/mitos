# Authoring Custom Capabilities Guide

Mitos allows you to extend your agent organization by authoring three kinds of reusable text assets: **Skills**, **Subagents**, and **Prompts**. You write these assets once in your private overlay (`registry/local/`), and Mitos handles compiling and deploying them to your active AI tools.

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
└── references/              ← Optional: additional documentation
```

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
---

# Instructions
To draft a changelog, follow these steps...
```

### Binding to Projects (Claude Code only)
For Claude Code, skills deploy *per-project* into `<project-root>/.claude/skills/`. To bind a skill:
1. List the skill under the `skills` key in your project manifest (`registry/local/projects/<project-slug>.yaml`):
   ```yaml
   skills:
     - changelog
   ```
2. The skill's `SKILL.md` **must** list `claude-code` in its `targets:` frontmatter list. If a project manifest binds a skill that is incompatible, the compiler will fail loudly.

---

## 🤖 2. Authoring Subagents

A **Subagent** is a specialized agent persona (like a Database Debugger or Code Reviewer) that Claude Code can spawn in the background to handle off-thread sub-tasks.

### File Location
Subagents live at the top level of the agents folder:
```
registry/local/agents/<name>.md
```

### Frontmatter Schema
Each agent Markdown file must specify a `name` and `description` in its frontmatter:

```yaml
---
name: code-reviewer
description: "Reviews git diffs for style and safety guidelines"
# optional fields supported by Claude Code:
# tools: [Read, Edit, Bash]
# model: gemini-3.5-flash
---

You are the Code Reviewer subagent. Your role is to examine the provided code changes...
```

### Binding to Projects
To deploy a subagent to a project's Claude Code environment:
1. List the agent in the project manifest's `agents:` list:
   ```yaml
   agents:
     - code-reviewer
   ```
2. The file will deploy to `<project-root>/.claude/agents/<name>.md`.

---

## 💬 3. Authoring Prompts (Slash-Commands)

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
Prompts are bound to Claude Code checkouts identically to skills and agents. List the prompt under `prompts:` in your project's manifest:

```yaml
# registry/local/projects/acme.yaml
prompts:
  - bug-report
```
The prompt compiles to `<project-root>/.claude/commands/bug-report.md`.

---

## 🔄 The Authoring daily loop

1. **Write the asset**: Create the skill folder, agent file, or prompt file in `registry/local/`.
2. **Bind to a project**: Edit the target project's manifest under `registry/local/projects/<slug>.yaml`.
3. **Validate**: Run `python build/compile.py compile` to run schema checks.
4. **Deploy**: Run `python build/compile.py deploy --machine <name>` to materialize the files into your project checkouts or global config directories.
