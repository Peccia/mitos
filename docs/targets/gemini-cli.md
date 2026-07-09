# Gemini CLI (superseded)

Gemini CLI retires 2026-06-18, replaced by Antigravity CLI. Mitos no longer has a separate
`gemini` target — everything that used to deploy here (MCP config, tool permissions, skills,
prompts) now lives under the **`antigravity`** target, which covers Antigravity IDE + CLI and,
until the retirement date, the classic Gemini CLI too (they currently share
`~/.gemini/config/mcp_config.json`).

See **[docs/targets/antigravity.md](antigravity.md)** for current configuration, the support
matrix, and the open caveat on the `config.json` permissions file's exact schema.

Antigravity CLI can import an existing `~/.gemini/` setup (`agy plugin import gemini`) — MCP
servers, allowlists, keybindings, theme — into its own `~/.gemini/antigravity-cli/settings.json`,
a separate migration not yet wired into Mitos.
