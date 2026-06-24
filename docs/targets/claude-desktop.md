# Target: Claude Desktop

## What it officially supports

| Surface | Support | Mechanism |
|---|---|---|
| Skills | ✅ | Shared with claude.ai — skill `.zip` uploads sync across web and Desktop (already wired via `claude-ai` target) |
| MCP config | ✅ **confirmed, writable** | `claude_desktop_config.json` at a known filesystem path |
| Project custom instructions | ❌ UI-only | Account-side, no filesystem path — set via Desktop UI > Projects > Custom instructions |
| Prompts | ❌ no native slot | No equivalent to `.claude/commands/` confirmed for Desktop |

## MCP config — filesystem path

Claude Desktop reads its MCP server configuration from a JSON file Mitos can write directly:

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

**This is a connections concern, not a prompts concern** — it wires MCP servers into Desktop exactly as `connections/servers.yaml` + `targets/hermes.yaml` wires them into Hermes. A `targets/claude-desktop.yaml` would live on the `--lane connections` deploy lane.

**JSON schema:**

```json
{
  "mcpServers": {
    "server-name": {
      "url": "http://localhost:8000/mcp",
      "type": "sse"
    }
  }
}
```

HTTP transport uses `"url"` + `"type": "sse"` (or `"streamable-http"`). Command-based servers use `"command"` + `"args"`. The schema mirrors Claude Code's `.mcp.json` closely.

**Drift policy:** `protect` — this is the tool's own config file. A `json_merge` approach (like Hermes `config.yaml` and Gemini `config.json`) owns only Mitos-managed server entries, leaving user-added servers untouched.

## Skills

Skills are **already deployed** via the `claude-ai` target — skill `.zip` files staged for manual upload. The upload syncs to both the web app and the Desktop app through the user's claude.ai account. **No additional wiring is needed for skills on Desktop.**

## Project custom instructions

UI-only. There is no filesystem path or API for Mitos to deploy project instructions to Claude Desktop. Users set these manually in the Desktop app: Projects > [project name] > Custom instructions.

*If Anthropic publishes an API for this in the future, it would be a connections-lane output (like the MCP config), not a prompts-lane output.*

## Verdict

- [x] **First-class target — for MCP config only** — a new `targets/claude-desktop.yaml` on `--lane connections`; skills already covered by `claude-ai`
- [x] Console/copy-paste only — for prompts and project instructions

## Phase 3B — What was implemented

A new `targets/claude-desktop.yaml` (connections lane) that writes `claude_desktop_config.json` as a plain JSON file (kind: `json`, not `json_merge`).

**Why not `json_merge`?** `mcpServers` is a dict, not a list. The `json_merge` mechanism owns a list by prefix; there is no per-key ownership for dicts. The simpler and correct answer is Mitos owns the whole `mcpServers` block — identical to how Gemini's `mcp_config.json` works. Users who want MCP servers add them to `connections/servers.yaml`.

**Opt-in via path key:** the target produces no output unless `claude_desktop_config` is set in the machine profile. Add it to your `registry/local/machines/<name>.yaml`:

```yaml
paths:
  # Windows
  claude_desktop_config: "%APPDATA%/Claude/claude_desktop_config.json"
  # macOS
  # claude_desktop_config: "~/Library/Application Support/Claude/claude_desktop_config.json"
```

**Desktop as standalone target:** yes — it is a separate target from `claude-ai`. The shared account surface (skill zips) is already handled by `claude-ai`. Desktop's MCP config is purely a connections concern, wired independently.
