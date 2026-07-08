# Mitos Target Guide: Antigravity IDE

This guide describes how to configure and deploy Mitos registry assets for **Antigravity**, Google's AI-first development environment and IDE. 

Mitos has first-class integration with Antigravity, deploying assistant personas, project builder instructions, custom skills, and reusable prompt libraries directly to the paths consumed by the IDE.

---

## 📊 Support matrix

| Surface | Support | Mechanism / Path |
|---|---|---|
| **Context** | ✅ Full | `AGENTS.md` files written to project/assistant roots (via `agents-md` target) |
| **Skills** | ✅ Full | Markdown files copied to `antigravity_skills` directory |
| **Prompts** | ✅ Full | Markdown files prefixed with `prompt-` copied to `antigravity_skills` directory |
| **MCP Config** | ✅ Shared | Shares connection settings and permissions via the `gemini` target |

> **Note:** Gemini CLI retires 2026-06-18, replaced by Antigravity CLI. Antigravity CLI's
> config contract (`~/.gemini/antigravity-cli/settings.json`) differs from the
> `mcp_config.json` / `config.json` surgical merge this target emits today — that migration
> is tracked separately; the `~/.agents/skills` path above already matches the CLI's
> convention.

---

## ⚙️ Configuration & machine setup

To deploy assets for Antigravity, you need to list both the `gemini` and `agents-md` targets in your machine profile, and define the paths where Antigravity reads them.

Add the following to your machine profile (`registry/local/machines/<name>.yaml`):

```yaml
targets:
  - gemini
  - agents-md

paths:
  # The native directory where Antigravity loads skills and prompts (cross-vendor
  # ~/.agents/skills convention, adopted by Antigravity CLI — Gemini CLI retires
  # 2026-06-18)
  antigravity_skills: "~/.agents/skills"
  
  # The root directory for your personal assistant context tree
  assistant_root: "~/MitosAgent"
  
  # The base directory where your codebase checkouts reside
  projects_root: "~/Projects"
  
  # Shares configuration and MCP connections with Gemini CLI
  gemini_config: "~/.gemini/config"
```

---

## 📂 Deployed surfaces

### 1. Context delivery (`AGENTS.md`)
Antigravity natively reads `AGENTS.md` files to understand identity and project background. Mitos writes context in two places:
- **Assistant tree**: Deployed to `assistant_root` — a root `AGENTS.md` (the operating root: routing + personal-context bridge), an `Assistant/AGENTS.md` branch (one-shot workspace tasks), and a `Projects/AGENTS.md` branch root (roster + org structure) with a `Projects/<project>/AGENTS.md` per project.
- **Code project roots**: Deployed to each active project directory as a unified `AGENTS.md` file combining who you are, operating rules, and project-specific guidelines.

### 2. Custom skills & prompts
Skills and prompts targeting `gemini` deploy to one of two scopes (a skill's `scope:`
frontmatter key — mirrors the identical claude-code surface, see
[docs/targets/claude-code.md](claude-code.md#skill-scope-global-vs-project)):
- **`scope: global`** (default): copied to the shared `antigravity_skills` directory
  (`~/.agents/skills/`) as `{name}.md` — available in every Antigravity session on this machine.
- **`scope: project`**: copied ONLY to the projects that name this skill in their manifest's
  `skills:` list, at `<project-root>/.agents/skills/{name}.md`.
- **Prompts**: always deploy globally, as `prompt-{name}.md` in `antigravity_skills` (prompts
  have no scope concept today).
- **Frontmatter**: Mitos strips YAML frontmatter during deployment, presenting clean markdown instructions directly to the IDE.

---

## 🔄 Drift & reconciliation

- **Context (`protect` policy)**: Context files use the `protect` policy. If you or the IDE edit `AGENTS.md` in place, future deploys will block. Pull those changes back using:
  ```bash
  python build/compile.py adopt /path/to/AGENTS.md
  ```
- **Skills & Prompts (`harvest` policy)**: Skills and prompts are expected to adapt during use. If the IDE refines a skill on disk, Mitos will automatically snapshot the changes to your `inbox/` as proposals during the next deploy, then align the file back to the registry. You can accept these proposals in the Operator Console.
