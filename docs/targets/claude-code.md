# Target: Claude Code

## What it officially supports

| Surface | Support | Mechanism |
|---|---|---|
| Context | ✅ | `CLAUDE.md` per project or at repo root |
| Skills | ✅ | `.claude/skills/<name>/SKILL.md` (project) or `~/.claude/skills/<name>/SKILL.md` (personal/global) — see [Skill scope](#skill-scope-global-vs-project) below |
| Prompts (slash-commands) | ✅ **confirmed** | `.claude/commands/<name>.md` — per-project; `~/.claude/commands/` — global (user-level) |
| MCP config | project `.mcp.json` | Not currently wired in Mitos (no project opts in) |

## Skill scope: global vs. project

Claude Code reads skills from the same two levels it reads slash-commands from
([confirmed](https://code.claude.com/docs/en/skills)):
- **Personal (global):** `~/.claude/skills/<name>/SKILL.md` — available in every project
- **Project:** `<project-root>/.claude/skills/<name>/SKILL.md` — available only there

A skill's `scope:` frontmatter key picks which one Mitos deploys to (mirrors the identical
`antigravity` target surface — `~/.gemini/config/skills/` global vs. `<project>/.agents/skills/`):

- **`scope: global`** (default, or omitted): deploys once to the machine's
  `claude_code_skills` path (`~/.claude/skills/`) — every project on that machine sees it,
  no manifest binding needed.
- **`scope: project`**: deploys ONLY to the projects that name this skill in their manifest's
  `skills:` list (`registry/projects/<slug>.yaml`), at `<project-root>/.claude/skills/`. Never
  appears in the personal directory.

`mitos-agent` and `claude-app` have no project-scoped skill surface at all — they ignore `scope`
entirely and always deploy globally, regardless of the value set.

Set/edit `scope` via the Operator Console's Skills & Orgs tab (each skill card's **Scope**
section) or directly in the skill's `SKILL.md` frontmatter. Which *projects* bind a
`scope: project` skill is controlled by editing each project's manifest `skills:` list — the
console shows the current bindings read-only but does not write project manifests.

## Slash-command prompts — `.claude/commands/`

Claude Code reads `.md` files from two locations:
- **Project-scoped:** `<project-root>/.claude/commands/<name>.md` — available only in that project
- **User-scoped (global):** `~/.claude/commands/<name>.md` — available in every Claude Code session

Each file becomes a `/name` slash command. The body is injected as the user turn when invoked. The `$ARGUMENTS` placeholder passes any text typed after the command name.

**Supported frontmatter fields:**

```yaml
---
description: "Short description shown in the slash-command picker"
allowed-tools: [Bash, Edit, Read]   # optional: restrict the tool set
---

Prompt body here. Use $ARGUMENTS where the user's input should go.
```

`description:` is displayed in the slash-command palette. `allowed-tools:` is optional and restricts which tools Claude Code may call while handling the command.

## How prompts deploy in Claude Code

Prompts targeting `claude-code` deploy to per-project `.claude/commands/<name>.md` files.

### Binding Prompts to Projects
Like skills, prompts are bound to specific project checkouts through the project manifest (`registry/local/projects/<slug>.yaml`):

```yaml
# registry/local/projects/acme.yaml
prompts:
  - bug-report
```

A bound prompt must exist in `registry/prompts/` (or your overlay `registry/local/prompts/`) and include `claude-code` in its `targets:` frontmatter.

### Rendered Output
When deployed, Mitos writes `<project-root>/.claude/commands/<name>.md` containing the `description:` frontmatter (for Claude Code's slash-command picker) and the prompt body with `$ARGUMENTS` support. Invoking `/name` within that project's checkout executes the command.
