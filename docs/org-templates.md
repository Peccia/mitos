# Mitos Organization Templates Guide

Mitos uses a hierarchical agent delegation model to structure collaboration between specialized agent roles. Instead of using a single monolithic assistant, Mitos structures your agents like a virtual team.

When you run the setup wizard (`python build/mitos.py init`), Mitos asks you to select one of its pre-seeded **Organization Templates**. This wizard copies starter files directly into your private overlay (`registry/local/`), which you can then customize.

---

## 📂 Seeded files

Each template seeds two critical files in your private overlay:

1. **`registry/local/identity/org-hierarchy.md`**
   - **Type**: Always-on Identity Persona.
   - **What it does**: Describes the team structure, specialized agent roles, and how work is delegated between them (e.g. from the CEO to the VP of Engineering). It flows into your tool's system context (like Hermes's `SOUL.md` or Gemini's `AGENTS.md`) automatically.
2. **`registry/local/skills/org/SKILL.md`**
   - **Type**: On-demand Playbook Skill.
   - **What it does**: Provides instructions and playbooks teaching the agents *how* to execute tasks according to their roles. Edits are marked as `harvest`, so improvements the agents discover on disk can be pulled back.

---

## 🏢 Available template archetypes

Mitos ships with three default templates tailored for different workflows:

### 1. Solo Assistant (`solo-assistant`)
A flat, direct delegation model optimized for individuals.
- **Roles**: General Assistant.
- **Best for**: Standard task automation, email drafting, calendar management, and general research where a complex team structure would add unnecessary overhead.
- **Workflow**: Simple, direct prompt-to-agent interactions.

### 2. Software Firm (`software-firm`)
A comprehensive team structure modeled after a modern agile software team.
- **Roles**:
  - **CEO**: Aligns project goals and oversees execution.
  - **Product Manager (PM)**: Drafts specifications, features, and roadmaps.
  - **VP of Engineering / Lead Dev**: Decides on system architecture and code design.
  - **QA Engineer**: Validates builds, reviews logs, and drafts tests.
  - **Technical Writer**: Drafts developer guides, API references, and release notes.
- **Best for**: Programming tasks, feature development, system architecture design, and writing tests.

### 3. Design Firm (`design-firm`)
A creative agency team structure focused on brand, layout, and content generation.
- **Roles**:
  - **Creative Director**: Establishes vision and approves designs.
  - **UX/UI Designer**: Details user flows, wireframes, and design system tokens.
  - **Copywriter**: Drafts marketing copy, landing pages, and newsletters.
  - **Project Manager**: Manages delivery timelines and client specs.
- **Best for**: Creating web layouts, writing copy, managing digital design assets, and marketing campaigns.

---

## 🔧 Customizing your organization

The template only seeds the initial files. Once copied, **you own the files completely**. You can edit them directly to refine your organizational structure:

- **Adding a Role**: Edit `registry/local/identity/org-hierarchy.md` to define a new role (e.g. `Security Auditor` or `Data Scientist`) and detail who they report to.
- **Tuning Playbooks**: Edit `registry/local/skills/org/SKILL.md` to refine instructions on how code reviews or PM handoffs occur.
- **Applying Changes**: Recompile and deploy:
  ```bash
  python build/compile.py compile
  python build/compile.py deploy --machine <machine-name>
  ```

---

## 🤝 Contributing new templates

To contribute a new organizational template back to the Mitos public core:
1. Create a new folder under `registry/templates/org/<template-slug>/`.
2. Author both `org-hierarchy.md` (defining the delegation structure) and `org-skill.md` (defining the playbooks).
3. Submit a Pull Request. Keep the template generic and neutral; personal details (such as your actual name or company) should remain in your private `registry/local/` overlay.
