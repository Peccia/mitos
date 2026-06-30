# Connectors & document stores

A **document store** is the system that holds a project's real documents (a local directory,
Google Workspace, Notion, etc.). Mitos never copies those documents — it keeps a lean
knowledge-graph *index* of where each one lives. A **connector** is what reads a store to build
that index.

Three built-in connector backends:
- **`local`** — local filesystem (the default; no credentials needed). Used automatically when no
  `document_store` is set.
- **`mcp`** — any MCP server that declares a `graph_enum:` block in `connections/servers.yaml`;
  Mitos reuses the server you already run, no second OAuth.
- **`mock`** — in-process demo for tests and dry runs.

## Binding a store (optional for local-file users)

If your documents live on a local disk, you don't need to set anything — `mitos connect` will use
the local-file connector by default, scoped to whatever folder you pass.

To use an MCP-backed store, define it in
[`../../connections/servers.yaml`](../../connections/servers.yaml) and point the project at it:

```yaml
# registry/local/projects/<slug>.yaml
document_store: gws        # ← the server name from connections/servers.yaml
```

Without this line (or with `document_store: none`), `mitos connect` defaults to the
local-file connector.

## The three stages (each separate, each optional)

1. **Create the project and bind the store** — `python build/mitos.py project add <slug> --document-store <server>`
   (or add the `document_store:` line to an existing manifest). Offline, no network.
2. **Set up the document MCP server** — separately, on its own. It may already be running and may
   be authless. Per-store guides live in this folder (e.g.
   [Google Workspace](google-workspace.md)).
3. **Map the documents** — `python build/mitos.py connect [--project <slug>]`. The connector is
   resolved from the project's `document_store`; it enumerates a scoped folder and proposes a
   `kind: graph` candidate you accept in the operator console (`python build/compile.py review`).
   `--project` is **optional** — see *Staging without assigning to a project* below.

## How a store is enumerated

**Local-file connector (the default):** Mitos walks a local directory with `os.walk`, emitting
one graph record per file: a SHA-1 id (URL-safe, satisfies the IRI invariant), the filename,
mtime as ISO date, and a `file://` URL. `--recursive` includes nested subdirectories.

**MCP connector:** For a store with a `graph_enum:` block in `connections/servers.yaml`, Mitos
calls the server's `list_tool` and maps the returned fields onto the lean graph shape
(`id`, `name`, `dateModified`, `webUrl`). The `query_syntax: google-drive` flag enables
Drive-specific query construction (folder parents, `mimeType` filter, recursive BFS); without it,
scope is passed verbatim through `query_arg`. The output's `webUrl` is stored as-is in the graph
as a `schema:url` field — no URL is synthesized from an id. (`--backend mock` swaps in an
in-process demo connector for tests and dry runs.)

### Recursive folder scope

By default `--folder-id <id>` maps only that folder's **immediate children**. Add `--recursive`
to include every nested subfolder transitively:

```sh
python build/mitos.py connect --project <slug> --folder-id <id> --recursive          # propose the whole subtree
python build/mitos.py connect --project <slug> --folder-id <id> --recursive --stage  # stage it for curation
```

Mitos resolves the folder's full subtree, queries it in batches, and dedupes files that live
under more than one folder. Any folder you exclude (see below) is removed from the subtree —
exclusion wins over the recursive scope. `--recursive` has no effect without `--folder-id`.

## Staging without assigning to a project

You can sync a store *before* deciding which documents belong to which project:

```sh
python build/mitos.py connect --stage                  # no --project
python build/mitos.py connect --stage --backend mock   # use a specific connector
```

Documents land in `inbox/staging/unassigned.json` — a shared pool. Open the operator console
(`python build/compile.py review`) and navigate to **Knowledge Graph** for any project: if no
project-specific staging file exists, the console shows the unassigned pool instead (labelled
**"Staged documents (Unassigned)"**). Select the documents you want and click **Propose
selected** — the normal acceptance flow then routes them into that project's graph.

Already-mapped documents (ones already in the project's graph) are filtered out of the checklist
automatically, so you cannot accidentally re-propose them.

## Excluding folders from staging

Some folders should never appear in the document picker or staging results — archives, drafts,
personal notes, or anything outside the project's scope. You can exclude them at two levels:

### At the server level (applies to all projects using that store)

Add `exclude_folders:` to the server entry in `connections/servers.yaml`:

```yaml
servers:
  gws:
    exclude_folders:
      - Archive
      - Personal
```

Each entry is a folder **name** or Drive **ID**. For the GWS connector, entire subtrees are
excluded — if `Archive` has sub-folders, their contents are also skipped.

### At the project level (applies only to that project)

Add `exclude_folders:` directly to the project manifest:

```yaml
# registry/local/projects/<slug>.yaml
document_store: gws
exclude_folders:
  - Drafts
  - 1BxyzDriveID   # store IDs also accepted
```

Both lists are **merged** at connect time (project entries are appended to server entries, with
deduplication). The folder picker shown when you run `mitos connect` also omits excluded folders
so they cannot be accidentally chosen as the staging scope.

## Guides

| Store / Connection | Guide |
|---|---|
| Local filesystem (default) | [local-file.md](local-file.md) |
| Google Workspace (Drive/Docs/…) | [google-workspace.md](google-workspace.md) |
| Custom MCP Servers | [custom-servers.md](custom-servers.md) |
