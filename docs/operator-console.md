# Mitos Operator Console Guide

The Mitos **Operator Console** is a local web application that serves as the human steering wheel for your agent organization. 

Run the console to:
1. Review and accept self-improvement proposals or drift from your tools (**Inbox**).
2. Curate and map workspace files into your projects' knowledge graphs (**Knowledge Graph**).
3. Search, compose, and copy-paste registry prompts for one-shot chat sessions (**Prompt Library**).

---

## 🚀 Launching the console

The console runs locally on your loopback interface (`127.0.0.1`) and does not listen on the public network. Launch it from the root of your Mitos repository using the virtual environment's Python interpreter:

```bash
# Linux / macOS
build/.venv/bin/python build/compile.py review

# Windows (PowerShell)
build/.venv/Scripts/python.exe build/compile.py review
```

### Options:
- `--port <number>`: Change the local port (default is `8765`). Useful if another application is binding to the default port.
- `--no-browser`: Start the server in the background without automatically launching your default web browser.

---

## 📥 The Inbox Tab: Drift & Candidate Review

When a self-improving tool (like Hermes) refines its own copy of a skill, or when you edit a deployed file, the changes are captured in your overlay inbox (`registry/local/inbox/`) as **candidates**.

### 🔍 Diffs & Review
- The Inbox lists all pending candidates with their capture timestamps, target tools, and logical paths.
- Selecting a candidate shows a live **Diff View** comparing the proposed changes with the version currently in your registry.
- A **Routing System** determines if the change can be applied automatically:
  - **Acceptable**: Plain Markdown prose edits (e.g. edits to a skill body or identity partial) can be accepted directly. Accepting updates your registry overlay (`registry/local/`) and marks the candidate as resolved.
  - **Unacceptable**: Generated configurations (like `mcp_config.json` or `config.json` permissions) or structural files (like project YAML manifests) must be merged manually in `connections/servers.yaml` or project manifests. The console will display a clear message indicating where the manual change must land.

### 📜 Staleness & Decisions
- **Stale Detection**: If you edit your registry directly while the console is open, it automatically flags inbox candidates as `stale` if they were captured against an older base hash.
- **Procedural Memory**: When you Accept or Reject a candidate, the decision (including an optional text explanation) is appended to `registry/local/inbox/decisions.jsonl`. This log serves as historical procedural metadata for future agent iterations.

---

## 🌐 The Knowledge Graph Tab: Document Curation

The **Knowledge Graph** tab is Stage 3 of mapping your workspace documents into schema.org JSON-LD indexes.

### 📋 Using the Curation Checklist
1. First, stage your document list using the connector CLI (see [Connectors & Document Stores Guide](connectors/README.md)):
   ```bash
   python build/mitos.py connect --project <project-slug> --stage
   ```
2. Open the **Knowledge Graph** tab and select your project from the list.
3. The console lists all staged files (either from the project-scoped staging file or the unassigned staging pool `unassigned.json`). Files that are already mapped are automatically filtered out.
4. Select the checkboxes for the authoritative documents you want to provide to your agents (e.g. project specifications, designs, or logs).
5. Click **Propose selected**. This writes a `kind: graph` candidate into your Inbox.
6. Navigate to the **Inbox** tab, review the candidate's canonical JSON-LD diff, and click **Accept**. This writes or updates `registry/local/graph/<project-slug>.jsonld`, which compiles into the Agentic Context roster on your next deploy.

---

## 📚 The Prompt Library Tab: One-Shot Composition

The **Prompt Library** acts as a scratchpad and library for one-shot chat sessions in tools that Mitos does not deploy directly to (like standard web/desktop chat interfaces).

- **Browse & Search**: Access all authored Skills, Subagents, and Prompts from your registry.
- **Favorites**: Toggle the star icon next to a prompt name to pin it to your favorites list for immediate access.
- **Live Composer**: Select a prompt, edit it or combine it with other content in the live text editor, and copy it to your clipboard.
- **Propose Edit**: If you refine a prompt in the composer and want to save it as a permanent registry asset, type a short reasoning note and click **Propose Edit**. It will land in the **Inbox** tab as a new candidate for review.
