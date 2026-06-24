# Connecting Custom MCP Servers & Document Stores

This guide describes how to connect arbitrary **Model Context Protocol (MCP)** servers to Mitos, wire their connections and permissions automatically, and configure them as **Document Stores** to feed your projects' knowledge graphs.

By default, Mitos ships with the `gws` (Google Workspace) server definition. You can add or override servers in your private overlay at `registry/local/connections/servers.yaml` (last-layer-wins).

---

## 🛠️ Registering a custom MCP server

To register a new server, add it to your local connection overrides file (`registry/local/connections/servers.yaml`):

```yaml
servers:
  notion-mcp:
    description: Notion workspace document reader.
    repo: https://github.com/example/notion_mcp
    transport: sse
    url: http://localhost:9000/mcp           # Default endpoint
    urls:
      linux-box: http://192.168.1.10:9000/mcp # Per-machine URL override
    hosted_on:
      - linux-box                             # Machines running this server
    env_template: connections/env/notion.env.example # Tracked template
    env_local: .local/notion.env              # Merged real credentials (gitignored)
    tools:                                    # Inventory of exposed tools
      database: [list_databases, query_database]
      pages: [get_page_content, update_page]
```

### Key Fields:
- `transport`: `sse` (Server-Sent Events HTTP stream) or `stdio` (standard input/output subprocess).
- `url` / `urls`: The default endpoint, plus a map of per-machine overrides (e.g. if one host reaches the server over your LAN).
- `env_template` / `env_local`: The tracked variable template and the gitignored file holding real secrets (merged at deploy time — secrets never enter git).
- `hosted_on`: An allowlist of machine names that host this server.

---

## 🔌 Configuring Stage 3 Document Enumeration (`graph_enum`)

If your MCP server is a document store and you want to use it with the `mitos connect` CLI to populate your project knowledge graphs, you must teach Mitos how to list its documents by adding a **`graph_enum`** block.

The generic `mcp` connector uses this configuration to call the server's listing tool over its `url` (reusing its active OAuth token/credentials) and maps the results into the unified graph schema.

### JSON-Based Mapping Example
If your server's listing tool returns structured JSON objects:

```yaml
    graph_enum:
      list_tool: query_database
      query_arg: database_id                  # The argument carrying the search/folder scope
      default_query: "db_12345"               # The default scope if none is passed
      fields:
        id: page_id                           # Maps Mitos standard 'id' to Notion 'page_id'
        name: properties.title.title[0].plain_text # Maps standard 'name' (supports nested paths)
        dateModified: last_edited_time        # Maps standard 'dateModified'
        webUrl: url                           # Maps standard 'webUrl'
        type: object_type                     # OPTIONAL: the store's document kind / MIME type —
                                              # normalized to a friendly form ("spreadsheet",
                                              # "pdf") and stored as schema:additionalType
```

### Text-Based Mapping Example
Some MCP servers return file listings as plain text lists or formatted Markdown strings instead of structured JSON arrays. In this case, use **`text_fields`** to supply a Python regular expression (containing exactly one capture group) to extract each field from a line:

```yaml
    graph_enum:
      list_tool: search_drive_files
      query_arg: query
      fields:
        id: id
        name: name
        dateModified: modifiedTime
        webUrl: webViewLink
        type: mimeType
      # Regex patterns to parse text output line by line:
      text_fields:
        id: 'ID: ([^\s,)]+)'
        name: 'Name: "([^"]+)"'
        modifiedTime: 'Modified: ([^,)]+)'
        webViewLink: 'Link: (\S+)'
        mimeType: 'Type: ([^\s,)]+)'
```

---

## 📄 Configuring Pagination

If your document store contains hundreds of files, you should configure pagination inside the `graph_enum` block so the Mitos connector can iterate pages without hitting timeouts or capping results:

```yaml
    graph_enum:
      ...
      page_size_arg: page_size                 # Tool argument for page limit
      page_size: 100                           # Maximum items per page request
      page_token_arg: start_cursor             # Tool argument for the continuation token
      text_next_token: 'nextCursor: (\S+)'    # (Text only) Regex to extract next token
```

---

## 🔄 Applying and Deploying

Once your custom server is registered in `registry/local/connections/servers.yaml`:
1. Run `python build/compile.py compile` to validate your YAML schema.
2. Bind the new server to a project manifest (`registry/local/projects/<slug>.yaml`):
   ```yaml
   document_store: notion-mcp
   ```
3. Deploy the configurations:
   ```bash
   python build/compile.py deploy --machine <machine-name> --lane connections
   ```
   This will surgically merge the new server's configuration and allowlist permissions into your AI tool configs (like Claude Desktop or Gemini's `config.json`).
