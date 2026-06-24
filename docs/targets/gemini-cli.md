# Mitos Target Guide: Gemini CLI

This guide describes how to configure and deploy Mitos registry assets for the **Gemini CLI**. 

The `gemini` target manages connection configurations and global permission grants for the Gemini command-line interface, ensuring it can seamlessly access your registered MCP servers.

---

## 📊 Support matrix

| Surface | Support | Mechanism / Path |
|---|---|---|
| **MCP Config** | ✅ Full | `mcp_config.json` written under `gemini_config` path |
| **Tool Permissions** | ✅ Surgical Merge | `config.json` merged under `gemini_config` path |
| **Context** | ❌ Unmanaged | Gemini CLI reads `GEMINI.md` (unsupported by Mitos; use `AGENTS.md` for Antigravity instead) |
| **Skills / Prompts** | ❌ Unsupported | Gemini CLI uses TOML files under `~/.gemini/commands/` (Mitos Markdown skills/prompts target Antigravity only) |

---

## ⚙️ Configuration & machine setup

To deploy Gemini CLI configurations, you must opt-in by listing `gemini` in your machine profile's targets and providing the configuration directory path.

Add the following to your machine profile (`registry/local/machines/<name>.yaml`):

```yaml
targets:
  - gemini

paths:
  # The directory where Gemini CLI reads mcp_config.json and config.json
  gemini_config: "~/.gemini/config"
```

---

## 📂 Deployed files & mechanics

When you run `python build/compile.py deploy --machine <name>`, Mitos manages two files under your `gemini_config` directory:

### 1. `mcp_config.json` (MCP server connections)
- **Policy**: `protect`
- **What it does**: Registers the MCP servers defined in your `connections/servers.yaml` file so the Gemini CLI knows how to reach them.
- **Example output**:
  ```json
  {
    "mcpServers": {
      "gws-mcp-local": {
        "url": "http://localhost:8000/mcp",
        "type": "sse"
      }
    }
  }
  ```

### 2. `config.json` (Tool execution permissions)
- **Policy**: `protect` (uses `json_merge`)
- **What it does**: Autocompletes tool permission allowlists. This prevents the Gemini CLI from repeatedly prompting you to approve tool executions (e.g. searching or reading files) on every run.
- **Surgical merge details**: Mitos only manages and merges entries matching the pattern `mcp(gws-mcp-local/...)` under the path `userSettings.globalPermissionGrants.allow`. Any other config settings, command-execution permissions, or manually added grants in your `config.json` are preserved.

---

## 🔄 State & drift management

Since both `mcp_config.json` and `config.json` use the **`protect`** drift policy, manually changing these files on disk (or setting tool permissions directly in the CLI) will cause drift and block future deployments.

- **Accepting disk changes**: If you manually authorized tools in the CLI and want to keep those permissions, pull them back into Mitos by running:
  ```bash
  python build/compile.py adopt ~/.gemini/config/config.json
  ```
- **Overwriting disk changes**: To force Mitos to overwrite the files on disk and align them with your registry:
  ```bash
  python build/compile.py deploy --machine <name> --force
  ```
