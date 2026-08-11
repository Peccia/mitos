# Mitos Planning Harness: Concept Document

> A specialized agentic harness designed to be the "Architect", leveraging the deep organizational context of Mitos (`AGENTS.md` and `SOUL.md`) to produce grounded, token-efficient, and unambiguous execution plans for downstream coding harnesses.

> **Superseded on where it lives by** [`mitos-agent-platform.md`](mitos-agent-platform.md), which keeps
> §4's delta-only plan output and the skill-curation idea, but makes the harness shell of §5.4 the
> product itself — in its own repo — rather than a wrapper added last.

## 1. Vision & Purpose

Current coding harnesses (Antigravity, Claude Code, Cursor, Cline) are exceptional at execution but often drift when faced with ambiguous requirements or when they lack deep organizational context. 

The **Mitos Planning Harness** is a proposed new target/harness in the Mitos ecosystem. Instead of writing code, its *sole purpose* is to act as a Staff Engineer / Architect. It takes an idea, iteratively resolves ambiguity through conversation, grounds the solution in the Mitos knowledge graph (domain playbooks, org routing, existing project context), and outputs a pristine, execution-ready plan.

**Key Objectives:**
- **Zero-Execution:** The agent has no ability to write code or modify project files. It only reads, thinks, and writes plans.
- **Iterative Clarity:** Employs an aggressive "Grill / Alignment" loop to eliminate underspecified requirements before any code is written.
- **Contextual Grounding:** Inherits the rich `agents-md` context (the same deep context as the Hermes assistant) so the plan inherently respects the org's existing architecture, skills (e.g., `frontend-design`), and constraints.
- **Harness-Agnostic Output:** Produces plans optimized for specific downstream execution harnesses.

---

## 2. Architecture & Mitos Integration

In Mitos, this harness would be defined as a new target, sitting alongside `hermes`, `claude-code`, and `antigravity`.

### 2.1 Context Assembly
- **Identity (`SOUL.md`):** Uses a specialized persona (e.g., `registry/identity/who-i-am-planner.md`) with `audience: [mitos-planner]`. The identity emphasizes architectural rigor, Systems Thinking, and ASD-STE100 Simplified Technical English.
- **Knowledge Graph:** Receives the full `AGENTS.md` tree. Because it operates at the "Architect" level, it needs the org-routing and domain playbooks (`org-software`, `org-design`) that typical coding harnesses often omit to save tokens.
- **Tooling:** Read-only access to the file system, web search, and MCP tools (like `gws` for reading PRDs or Jira tickets). *No write tools except for writing the final plan artifact.*

### 2.2 Skill Curation
The planner receives a curated subset of Mitos skills:
- **Included:** `ux-design`, `frontend-design`, `simplified-technical-english`, `system-architecture`.
- **Excluded:** `git-auto-commit`, `git-auto-release`, or any deployment scripts.

---

## 3. The "Iterate to Clarity" Workflow

The harness operates in a strict, phased lifecycle:

> [!TIP]
> **The Grill Loop**
> The core of the planner is the interactive interview. It refuses to write the final plan until it can confidently answer: *What are the edge cases? What is the rollback strategy? How does this impact existing state?*

1. **Intake & Discovery:** 
   - User provides a raw idea or a link to a spec.
   - The Planner reads the relevant `Projects/AGENTS.md` sections to understand the current state.
2. **Alignment (The Interview):**
   - The Planner cross-references the idea against Mitos constraints. 
   - It outputs targeted, multiple-choice or short-answer questions to the user to resolve ambiguity (e.g., *"Does this new microservice need to support the legacy auth token? Yes/No"*).
3. **Drafting & Grounding:**
   - Synthesizes the constraints into a draft architecture.
   - Verifies the draft against specific Mitos skills (e.g., ensuring the UI draft adheres to the `frontend-design` aesthetics rule).
4. **Final Synthesis (The Output):**
   - Renders the final `implementation_plan.md`.

---

## 4. The Output: Token-Efficient Execution Plans

The primary deliverable is a plan optimized for machine reading (by the downstream coding harness). 

**Characteristics of the Output Plan:**
- **Markdown / XML Hybrid:** Uses structured tags (e.g., `<file_changes>`, `<verification_steps>`) that downstream LLMs can parse natively.
- **Omit Redundancy:** The plan does *not* repeat the Mitos context, because the downstream execution harness (like `claude-code`) will already have its own `CLAUDE.md`. It only contains the *delta*.
- **Constraint Boundaries:** Explicitly lists what the execution agent should *not* do (anti-goals) to prevent scope creep.

### Example Output Structure
```markdown
# Implementation Plan: [Feature Name]

## 1. Context & Goal
[Concise summary of what is being built in Simplified Technical English]

## 2. Anti-Goals / Out of Scope
> [!WARNING]
> DO NOT modify the legacy `v1/auth` endpoints during this migration.

## 3. Step-by-Step Execution
### Phase 1: Foundation
#### [NEW] `src/services/new_auth.ts`
- Implement `AuthService` class.
- **Requirement:** Must use the `CryptoProvider` defined in `src/utils/crypto.ts`.

#### [MODIFY] `src/middleware/auth.ts`
- Inject `AuthService`.
- **Constraint:** Maintain backwards compatibility for `Bearer` tokens.

## 4. Verification
- Run `npm run test:auth`.
- Expected behavior: Old tokens return 401, new tokens return 200.
```

---

## 5. Implementation Path within Mitos

To build this inside Mitos today, you would:
1. **Create Target:** Add `targets/mitos-planner.yaml`.
2. **Draft Persona:** Add `registry/identity/who-i-am-planner.md` (and ensure it's selected by the target).
3. **Configure Compile Rules:** Ensure `compile.py` routes the full `agents-md` context to this new target, while keeping the output file named something the planner CLI expects (e.g., `.planner/CONTEXT.md`).
4. **Harness Shell:** Create a thin CLI wrapper (similar to the Antigravity or Claude CLI) that restricts the available MCP tools to read-only, forces the "Grill" loop, and outputs the final artifact.
