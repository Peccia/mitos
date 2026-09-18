# Local-file connector

The local-file connector (`local`) maps files from a local directory into the knowledge graph.
It is the **default connector** — if a project has no `document_store` set, `mitos connect`
uses this backend automatically, so a fresh open-source clone can build a graph from a local
project directory without any MCP server or Google credentials.

## What it produces

For each file it discovers, the connector emits:

| Graph field | Value |
|---|---|
| `id` (schema:identifier) | SHA-1 of the file's absolute POSIX path — URL-safe, satisfies the IRI invariant, stable across renames-in-place |
| `name` | filename |
| `dateModified` | file mtime as ISO date (`YYYY-MM-DD`) |
| `webUrl` (schema:url) | `file://` URI of the absolute path |
| `type` (schema:additionalType) | the file extension, lowercased (`md`, `pdf`, …); omitted for extensionless files |

The connector never reads file content — the graph stores references, not bodies (design rule #3).

## Usage

```bash
# map an entire local folder (non-recursive by default)
python build/mitos.py connect --project <slug> --folder-id /path/to/docs

# include nested subdirectories
python build/mitos.py connect --project <slug> --folder-id /path/to/docs --recursive

# no folder-id: scope defaults to the current directory
python build/mitos.py connect --project <slug>
```

There is no command-line flag for skipping subdirectories. List them under `exclude_folders:` in
the project manifest or in the store's entry in `connections/servers.yaml` — see
[Excluding folders from staging](README.md#excluding-folders-from-staging). This connector
matches each entry against a directory's name (case-insensitive) or its absolute path.

Like every connector, this produces a `kind: graph` candidate in `inbox/` that you accept in the
operator console (`python build/compile.py review`). Nothing is written to the registry directly.

## Identifier stability

The SHA-1 id is derived from the file's **absolute path**. If you move the file to a different
directory or rename it in-place, its absolute path changes, producing a new id and rendering
the previous mapping stale. Re-running `mitos connect` and accepting the new candidate
upserts the corrected mapping.

## No binding required

You do not need a `document_store:` line in the project manifest to use this connector. If the
line is absent or set to `none`, `connector_for_store` returns a `LocalFileConnector` scoped to
the current working directory. To use an MCP-backed store instead, add `document_store: <server>`
and follow the server-specific guide.
