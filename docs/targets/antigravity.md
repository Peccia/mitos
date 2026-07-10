# Mitos Target Guide: Antigravity

This guide describes how to configure and deploy Mitos registry assets for **Antigravity**,
Google's agentic IDE + CLI (`target: antigravity`) — the successor to Gemini CLI, which retires
2026-06-18. One target key covers both the Antigravity IDE and Antigravity CLI; there is no
separate `gemini` target.

Mitos has first-class integration with Antigravity, deploying assistant personas, project
builder instructions, and custom skills directly to the paths consumed by the IDE/CLI.
Antigravity follows the directory-based **Agent Skills open standard** (the same shape
Claude Code consumes), so Mitos treats it like the other harnesses — one skill folder with
`SKILL.md` plus supporting files, no Antigravity-specific packaging.

---

## 📊 Support matrix

| Surface | Support | Mechanism / Path |
|---|---|---|
| **Context** | ✅ Full | `AGENTS.md` files written to project/assistant roots (via `agents-md` target) |
| **Skills** | ✅ Full | Agent Skills standard folders (`<name>/SKILL.md` + supporting files), global or project scope — see [Skill scope](#skill-scope-global-vs-project) below |
| **Prompts** | ❌ Retired | The flat `prompt-<name>.md` lane was removed — Antigravity's skill discovery only reads `<folder>/SKILL.md`, so those files were never visible to it. Discoverable content belongs in a skill; prompts stay console-only |
| **MCP Config** | ✅ Confirmed | `mcp_config.json` under `antigravity_config` — confirmed shared across Antigravity 2.0/IDE/CLI |
| **Tool Permissions** | ⚠️ Unverified | `config.json` merge — see the caveat below |

> **Permissions file caveat (2026-07-08):** the `config.json` / `userSettings.globalPermissionGrants.allow`
> structure this target emits does not match any documented Gemini CLI or Antigravity CLI schema
> found during research — real Gemini CLI permission keys are `tools.allowed` /
> `mcpServers.<name>.trust` inside `settings.json`, not a separate `config.json`. This block
> predates the antigravity rename and hasn't been re-verified against a real installed
> `config.json`/`settings.json`. Treat `mcp_config.json` as solid; treat the permissions merge as
> unconfirmed until checked against your actual Antigravity CLI install (`agy config --edit` or
> equivalent).
>
> **Gemini CLI retires 2026-06-18.** Antigravity CLI can import an existing `~/.gemini/` setup
> (`agy plugin import gemini`) — MCP servers, allowlists, keybindings, theme — into its own
> `~/.gemini/antigravity-cli/settings.json`, a different file/format than what this target emits
> today. That migration is tracked separately.

---

## ⚙️ Configuration & machine setup

To deploy assets for Antigravity, list both the `antigravity` and `agents-md` targets in your
machine profile, and define the paths where Antigravity reads them.

Add the following to your machine profile (`registry/local/machines/<name>.yaml`):

```yaml
targets:
  - antigravity
  - agents-md

paths:
  # Antigravity's GLOBAL skills directory (all workspaces) — per the official
  # Antigravity 2.0 docs (Customizations > Skills). Workspace-specific skills live at
  # <workspace-root>/.agents/skills/ and are covered by scope: project bindings below.
  antigravity_skills: "~/.gemini/config/skills"

  # The root directory for your personal assistant context tree
  assistant_root: "~/MitosAgent"

  # The base directory where your codebase checkouts reside
  projects_root: "~/Projects"

  # MCP connections + tool permissions — shared with classic Gemini CLI until it retires
  antigravity_config: "~/.gemini/config"
```

---

## 📂 Deployed surfaces

### 1. Context delivery (`AGENTS.md`)
Antigravity natively reads `AGENTS.md` files to understand identity and project background. Mitos writes context in two places:
- **Assistant tree**: Deployed to `assistant_root` — a root `AGENTS.md` (the operating root: routing + personal-context bridge), an `Assistant/AGENTS.md` branch (one-shot workspace tasks), and a `Projects/AGENTS.md` branch root (roster + org structure) with a `Projects/<project>/AGENTS.md` per project.
- **Code project roots**: Deployed to each active project directory as a unified `AGENTS.md` file combining who you are, operating rules, and project-specific guidelines.

### 2. Custom skills

Each skill deploys as an Agent Skills standard folder: `<name>/SKILL.md` with `name` +
`description` frontmatter (the description is what Antigravity's discovery matches against),
plus any supporting files (`examples/`, `scripts/`, `references/`, `templates/`,
`resources/`) alongside it. Extension skills (`extends_skill`) are spliced into the parent's
body at render time, exactly as on hermes/claude-code.

#### Skill scope: global vs. project
Skills targeting `antigravity` deploy to one of two scopes (a skill's `scope:` frontmatter key —
mirrors the identical claude-code surface, see
[docs/targets/claude-code.md](claude-code.md#skill-scope-global-vs-project)). The two
directories map onto Antigravity's documented discovery locations:

- **`scope: global`** (default): copied to the machine's `antigravity_skills` directory
  (`~/.gemini/config/skills/<name>/SKILL.md`) — Antigravity's global location, available in
  every workspace on this machine.
- **`scope: project`**: copied ONLY to the projects that name this skill in their manifest's
  `skills:` list, at `<project-root>/.agents/skills/<name>/SKILL.md` — Antigravity's
  workspace-specific location.

Confirmed working in practice: a skill deployed to `<project>/.agents/skills/<name>/` is
discovered and loaded by Antigravity for that project automatically.

> **Migration note:** earlier Mitos versions deployed flat `{name}.md` files (frontmatter
> stripped) plus `prompt-{name}.md` prompt files. After upgrading, those become **orphans**
> on the next deploy — review the orphan list and remove them with `deploy --prune`.

---

## 🔄 Drift & reconciliation

- **Context (`protect` policy)**: Context files use the `protect` policy. If you or the IDE edit `AGENTS.md` in place, future deploys will block. Pull those changes back using:
  ```bash
  python build/compile.py adopt /path/to/AGENTS.md
  ```
- **Skills (`harvest` policy)**: Skills are expected to adapt during use. If the IDE refines a skill on disk, Mitos will automatically snapshot the changes to your `inbox/` as proposals during the next deploy, then align the file back to the registry. You can accept these proposals in the Operator Console.
