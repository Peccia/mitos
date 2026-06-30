# Target: Claude app (`claude-app`)

The **`claude-app`** target is the **claude.ai account surface** — one account shared by
the **web app** and the **Desktop app**. Skills and connectors configured on the account
appear in *both*; they are not separate products (verified: the Desktop and web Customize
panels show the same Skills and Connectors). This is the **manual** Claude target;
**`claude-code`** is the automated one (it writes a real `.claude/` filesystem tree).

It merges what used to be two targets (`claude-ai` for skills + `claude-desktop` for MCP).

## What it officially supports

| Surface | Support | Mechanism |
|---|---|---|
| Skills | ✅ (manual upload) | Staged as `.zip` at `claude_skills_staging`; uploaded once at claude.ai → Customize > Skills; syncs to web + Desktop |
| MCP — https servers | ✅ via UI | Add in Customize > Connectors (account-level, syncs everywhere). Not Mitos-deployed. |
| MCP — LAN/HTTP servers | ⚠️ Desktop-only workaround | Connectors UI rejects non-https URLs — **do not use it**. Run `deploy --lane connections`; Mitos writes an `npx mcp-remote` bridge into `claude_desktop_config.json` directly. Restart Desktop and the connector appears automatically. **Requires Node.js/npx.** The HTTP server must be running before Desktop starts. |
| Project custom instructions | ❌ UI-only | Account-side, no filesystem path |
| Prompts | ❌ no native slot | Console Prompt Library = copy-paste |

## MCP config — filesystem path

Claude Desktop reads its MCP server configuration from a JSON file Mitos can write directly:

| Platform / install | Path |
|---|---|
| Windows (classic `.exe`) | `~/AppData/Roaming/Claude/claude_desktop_config.json` |
| Windows (MSIX / Microsoft Store) | `~/AppData/Local/Packages/<PackageFamilyName>/LocalCache/Roaming/Claude/claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

> **MSIX installs virtualize `%APPDATA%`.** The Store build of Claude Desktop redirects
> its `Roaming\Claude` directory into the package's `LocalCache`. Writing to the classic
> `%APPDATA%\Claude` path will *not* be seen by the app. Get the package family name with
> `Get-AppxPackage *Claude* | Select PackageFamilyName`.
>
> **Use the leading `~` form, not `%APPDATA%`.** `io.expand()` resolves `~` (and an
> explicit machine `home`) but does **not** expand environment variables — a literal
> `%APPDATA%` would create a bogus folder by that name.

**This is a connections concern, not a prompts concern** — it wires MCP servers into Desktop exactly as `connections/servers.yaml` + `targets/hermes.yaml` wires them into Hermes. The MCP half of `targets/claude-app.yaml` lives on the `--lane connections` deploy lane (the skills half is on `--lane content`).

> **Do not use "Add custom connector" in the Desktop UI for Mitos-managed servers.**
> The Connectors UI (Desktop menu → Connectors → Add connectors) is for manually adding
> *external* HTTPS servers — it cannot add a LAN/HTTP server (rejects non-https URLs) and
> it has no knowledge of your `servers.yaml`. After running
> `deploy --machine <name> --lane connections`, the server entry is written directly into
> `claude_desktop_config.json` and **appears automatically in the Connectors list after a
> full Desktop restart** (Quit from the tray, then reopen). No UI steps are needed.

**Transport — Desktop is stdio-only; HTTP servers must be bridged.**

`claude_desktop_config.json` only launches **stdio child processes** — it does *not*
consume a remote `{"url": ..., "type": "sse"}` entry (an earlier version of this target
emitted that; it silently failed to register). Anthropic's **Connectors UI** does accept
remote servers by URL, but it **rejects any non-`https` URL** ("URL must start with
'https'"), so a LAN server such as `http://192.168.1.40:8000/mcp` cannot be added there.

The working route for an HTTP/SSE server is the **`npx mcp-remote` stdio↔HTTP bridge**: a
local process Desktop spawns that connects out to the server. `https` is not required for
a local hop — but mcp-remote needs to be *told* to allow plain http (see `--allow-http`
below). **This requires Node.js / `npx` on the machine.**

**Two processes are involved — only one is automatic:**

| Process | Who starts it | When |
|---|---|---|
| `npx mcp-remote` (the bridge) | Claude Desktop — automatic | Spawned on Desktop launch, killed on exit. `npx -y` downloads the package on first run (needs internet once), then uses the local npm cache. No user action needed. |
| The GWS HTTP server (what the bridge connects *to*) | You — manually | Must be running at the configured URL before Desktop connects. If it isn't up, the bridge connects and immediately fails. Start it before launching Desktop. |

Mitos deploys the bridge config; it does not start or manage the GWS server process.

```json
{
  "mcpServers": {
    "gws-mcp-local": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "mcp-remote@0.1.29",
               "http://<ip:port>/mcp", "--transport", "http-only", "--allow-http"]
    }
  }
}
```

Two mcp-remote flags are required for this case (confirmed against the mcp-remote README):

- **`--transport http-only`** — gws speaks streamable HTTP, not SSE. mcp-remote's default
  is `http-first` (try HTTP, fall back to SSE on a 404); pinning `http-only` skips the
  spurious SSE attempt. An SSE server would instead get `sse-only`.
- **`--allow-http`** — mcp-remote **refuses a non-`https` URL** unless this flag is set
  (it guards against leaking tokens over plaintext on untrusted networks). The renderer
  adds it only when the url starts with `http://`; an `https://` server omits it.

On **Windows** the command must be wrapped in `cmd /c` — `npx` is a `.cmd` shim that
Electron's `child_process.spawn` cannot resolve directly (bare `"command": "npx"` fails
with `ENOENT` / "Connection closed"). On **macOS/Linux** it is plain `"command": "npx"`.
The renderer is OS-aware (`claude_desktop_mcp_config(..., os_name=...)`, fed the machine
profile's `os:`). A server already described with a native stdio `command:` in
`servers.yaml` is passed through unbridged.

**Security — the bridge package is version-pinned.** `npx` runs whatever `mcp-remote`
resolves to as a child of Claude, so a floating tag (`mcp-remote` / `@latest`) would let a
compromised or typosquatted publish execute on every launch. The renderer emits an exact
pin (`MCP_REMOTE_SPEC = "mcp-remote@<version>"`, a single constant in
`build/agentic/render.py`); every upgrade is a deliberate, reviewable one-line change.
A test asserts the rendered args carry the pinned spec and never the bare package name.
**Maintainer:** confirm the version exists (`npm view mcp-remote versions`) and bump that
constant intentionally — never widen it to a range.

> **No Node?** Then the only alternatives are fronting the server with a real `https`
> endpoint (reverse proxy + TLS) so the Connectors UI accepts it, or doing without GWS
> tools on Desktop. A one-time Node install is the lower-maintenance option.

**Merge, not overwrite:** Claude Desktop keeps its own preferences (theme, layout, account state) in this *same* file, so a whole-file write would erase them. The target uses `kind: json_merge` owning the top-level `mcpServers` key (`owned_keys: [mcpServers]`) — the same mechanism as Hermes `config.yaml` and Gemini `config.json` — splicing the Mitos server block in and leaving every other key untouched.

## Skills

Skills are staged as `.zip` files at the machine's `claude_skills_staging` path (one
`<name>.zip` holding `<name>/SKILL.md`). The **upload is manual** — claude.ai → Customize >
Skills → Upload — after which the account syncs the skill to both web and Desktop. The
lockfile reclassifies a staged zip as `pending` after a registry edit: that's the
re-upload reminder. There is no harvest loop (account-side state is invisible).

## Project custom instructions

UI-only. There is no filesystem path or API for Mitos to deploy project instructions to
Claude. Users set these manually in the app: Projects > [project name] > Custom
instructions.

## How the two targets merged

`claude-app` replaces the former `claude-ai` (skills) and `claude-desktop` (MCP) targets.
They were split on the theory that the web and Desktop apps were different surfaces; in
practice both render the **same** account-level Skills and Connectors, so one target with
two opt-in-by-path-key halves is the honest model:

- **Skills** emit when `claude_skills_staging` is set (content lane).
- **Desktop MCP** emits when `claude_desktop_config` is set (connections lane).

A web-only machine sets only `claude_skills_staging`; a Desktop machine that needs a LAN/HTTP
MCP server sets `claude_desktop_config` too. The precedent for one target spanning two
lanes is `gemini` (MCP config on connections + prompts on content).

**Path key (`claude_desktop_config`), per install:**

```yaml
paths:
  # Windows (classic .exe)
  claude_desktop_config: "~/AppData/Roaming/Claude/claude_desktop_config.json"
  # Windows (MSIX / Microsoft Store) — virtualized under the package LocalCache:
  # claude_desktop_config: "~/AppData/Local/Packages/<PackageFamilyName>/LocalCache/Roaming/Claude/claude_desktop_config.json"
  # macOS
  # claude_desktop_config: "~/Library/Application Support/Claude/claude_desktop_config.json"
```

> Use the `~` form, never `%APPDATA%` — `io.expand()` does not expand environment variables.

**MCP ownership:** `kind: json_merge` owning the top-level `mcpServers` key
(`owned_keys: [mcpServers]`) — the same surgical-merge pattern as Hermes `config.yaml` and
Gemini `config.json`. Claude Desktop stores its own preferences in this *same* file, so a
whole-file write would erase them; owning just `mcpServers` splices the bridge in and
leaves every sibling key intact. A user-added entry *inside* `mcpServers` is replaced on
the next deploy (Mitos owns that whole key) — add servers to `connections/servers.yaml`.
