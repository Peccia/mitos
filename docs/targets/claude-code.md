# Target: Claude Code

## What it officially supports

| Surface | Support | Mechanism |
|---|---|---|
| Context | ✅ | `CLAUDE.md` per project or at repo root |
| Skills | ✅ | `.claude/skills/<name>/SKILL.md` (project) or `~/.claude/skills/<name>/SKILL.md` (personal/global) — see [Skill scope](#skill-scope-global-vs-project) below |
| Agents (subagents) | ✅ | `.claude/agents/<name>.md` — wired and deployed today |
| Prompts (slash-commands) | ✅ **confirmed** | `.claude/commands/<name>.md` — per-project; `~/.claude/commands/` — global (user-level) |
| MCP config | project `.mcp.json` | Not currently wired in Mitos (no project opts in) |

## Skill scope: global vs. project

Claude Code reads skills from the same two levels it reads slash-commands from
([confirmed](https://code.claude.com/docs/en/skills)):
- **Personal (global):** `~/.claude/skills/<name>/SKILL.md` — available in every project
- **Project:** `<project-root>/.claude/skills/<name>/SKILL.md` — available only there

A skill's `scope:` frontmatter key picks which one Mitos deploys to (mirrors the identical
`gemini` target surface — `~/.agents/skills/` global vs. `<project>/.agents/skills/`):

- **`scope: global`** (default, or omitted): deploys once to the machine's
  `claude_code_skills` path (`~/.claude/skills/`) — every project on that machine sees it,
  no manifest binding needed.
- **`scope: project`**: deploys ONLY to the projects that name this skill in their manifest's
  `skills:` list (`registry/projects/<slug>.yaml`), at `<project-root>/.claude/skills/`. Never
  appears in the personal directory.

`hermes` and `claude-app` have no project-scoped skill surface at all — they ignore `scope`
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

## Deployment path for Mitos

Prompts targeting `claude-code` should deploy to **per-project `.claude/commands/`** (consistent with how skills and agents deploy per-project today) and/or optionally to a **user-level global** directory.

A project-scoped prompt would appear only in that project's Claude Code sessions. A user-scoped prompt appears everywhere — more like a skill than a project-specific tool.

**Recommended approach (Phase 3):**

- Add a `prompts:` block to `targets/claude-code.yaml`, deploying to `.claude/commands/{name}.md` within each project that lists the prompt in its manifest (mirroring the `skills:` binding pattern)
- Add a `global_prompts_dir` path key to machine profiles for user-level commands (optional; omit if not needed)
- Frontmatter rendered: `name` and `description` only (matching Agent Skills standard)

## Research sources

- Claude Code documentation (`.claude/` directory layout)
- Confirmed by codebase inference from existing `.claude/skills/` and `.claude/agents/` patterns

## Verdict

- [x] **First-class target** — `.claude/commands/` is a confirmed, documented prompt slot

## Phase 3A — What was implemented

A `prompts:` block in `targets/claude-code.yaml` deploying to `.claude/commands/{name}.md` per project.

**Binding model:** identical to `skills:` and `agents:` — the project manifest's `prompts:` list controls which prompts deploy to which project's checkout. A bound prompt must exist in `registry/prompts/` AND list `claude-code` in its `targets:`. Console-only prompts cannot be bound.

**Rendered format:** `description:` frontmatter (for the slash-command picker) + prompt body. No `allowed-tools:` (not in the Mitos prompt schema yet — add to the prompt's `targets:` extension if needed in a later phase).

**Global (user-scoped) prompts** — `~/.claude/commands/` — are deferred. Per-project binding is the right default for now; a `global_commands_dir` machine path key can be added in a later phase once there's a concrete use case.
