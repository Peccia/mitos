# Target: Claude Code

## What it officially supports

| Surface | Support | Mechanism |
|---|---|---|
| Context | ✅ | `CLAUDE.md` per project or at repo root |
| Skills | ✅ | `.claude/skills/<name>/SKILL.md` — wired and deployed today |
| Agents (subagents) | ✅ | `.claude/agents/<name>.md` — wired and deployed today |
| Prompts (slash-commands) | ✅ **confirmed** | `.claude/commands/<name>.md` — per-project; `~/.claude/commands/` — global (user-level) |
| MCP config | project `.mcp.json` | Not currently wired in Mitos (no project opts in) |

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
