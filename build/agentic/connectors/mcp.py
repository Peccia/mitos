"""A backend-agnostic connector that enumerates documents from an already-running MCP server.

This is the connector the knowledge-graph pipeline uses to **reuse a document store you set up
separately** (e.g. the Google Workspace MCP server in `connections/servers.yaml`) instead of
doing its own OAuth. It is generic: it knows nothing about a specific store. Each server
describes how to enumerate itself via a `graph_enum` mapping in `connections/servers.yaml`
(which MCP tool lists documents, and how that tool's fields map onto the lean
`{id, name, dateModified, webUrl}` graph shape). The connector calls that tool over the
server's endpoint and maps the result.

Like every connector it lives *beside* the compiler (Phase E constraint #1): the deterministic
verbs never import it, and the HTTP client is lazy-imported inside `_http_call` so importing
this module costs nothing. It NEVER writes the graph — it hands documents to
`bootstrap_to_inbox`, the one human-gated valve.

The HTTP transport is isolated in `_http_call`; the enumerate/map logic is exercised in tests
through an injected `transport` callable, so the mapping is covered without a live server.
Verifying the live `tools/call` round-trip against your own MCP server is a manual step.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Callable

from .base import ConnectorError, WorkspaceConnector


class MCPConnector(WorkspaceConnector):
    """Enumerate documents by calling a running MCP server's list tool.

    `endpoint` is the server's MCP URL (e.g. http://localhost:8000/mcp); `enum` is the
    server's `graph_enum` mapping. `transport(tool_name, arguments) -> list[dict]` is an
    optional injection point for tests — when omitted, `_http_call` performs the real
    streamable-http JSON-RPC call.
    """

    name = "mcp"

    def __init__(self, root=None, *, endpoint: str | None = None,
                 enum: dict | None = None, server_name: str = "mcp",
                 transport: Callable[[str, dict], list[dict]] | None = None):
        self.root = root
        self.endpoint = endpoint
        self.enum = enum or {}
        self.server_name = server_name
        self._transport = transport

    def authenticate(self) -> None:
        """No-op: the MCP server holds its own credentials (and may be authless). We only need
        a reachable endpoint — a missing one fails clearly when we try to enumerate."""
        if not self.endpoint:
            raise ConnectorError(
                f"document store {self.server_name!r} has no MCP url to reach — set `url:` on "
                f"the server in connections/servers.yaml")

    def list_folders(self, exclude_folders: list[str] | None = None) -> list[dict]:
        """Folders for the scope picker. Only available if the server maps a `folder_tool`;
        otherwise return [] and the caller falls back to a free-text scope/query.
        `exclude_folders` filters results by folder name or id before returning."""
        tool = self.enum.get("folder_tool")
        if not tool:
            return []
        rows = self._invoke(tool, {})
        folders = [{"id": str(r.get(self._field("id"), "")),
                    "name": str(r.get(self._field("name"), ""))} for r in rows]
        if exclude_folders:
            excl_ids = set(exclude_folders)
            excl_names = {e.casefold().strip() for e in exclude_folders}
            folders = [f for f in folders
                       if f["id"] not in excl_ids
                       and f["name"].casefold().strip() not in excl_names]
        return folders

    def _get_excluded_folder_ids_recursive(self, exclude_folders: list[str]) -> set[str]:
        """Resolve the folder names/ids in `exclude_folders` to the complete set of Drive
        folder IDs to exclude, including every transitive subfolder.

        Names are matched **case- and whitespace-insensitively**: we ask Drive for folders
        whose name *contains* each entry (Drive's `contains` is case-insensitive), then keep
        only those whose normalized name *equals* a requested entry. That tolerates a folder
        recorded as "Screen Shot" but named "screen shot" on Drive, without over-excluding
        look-alikes like "Old Screen Shots". Entries that already look like a raw Drive ID are
        taken verbatim. Errors are **not** swallowed — a failed resolution raises rather than
        silently disabling the filter (which would leak the excluded folder's files)."""
        if not exclude_folders:
            return set()
        tool = self.enum.get("list_tool")

        excl_ids: set[str] = set()
        name_targets: list[str] = []
        for raw in exclude_folders:
            entry = (raw or "").strip()
            if not entry:
                continue
            if len(entry) > 15 and re.match(r'^[a-zA-Z0-9\-_]+$', entry):
                excl_ids.add(entry)          # already a folder ID — no name lookup needed
            else:
                name_targets.append(entry)

        if not tool:
            return excl_ids

        # Resolve names → IDs, keeping only exact (normalized) name matches.
        if name_targets:
            wanted = {t.casefold() for t in name_targets}
            clauses = [f"name contains '{self._escape(t)}'" for t in name_targets]
            q = ("mimeType = 'application/vnd.google-apps.folder' and ("
                 + " or ".join(clauses) + ")")
            for r in self._invoke_folder_query(tool, q):
                fid = str(r.get(self._field("id")) or r.get("id") or "").strip()
                fname = str(r.get(self._field("name")) or r.get("name") or "").strip()
                if fid and fname.casefold() in wanted:
                    excl_ids.add(fid)

        # Every transitive subfolder of an excluded folder is excluded too.
        return excl_ids | self._descendant_folder_ids(excl_ids)

    def _descendant_folder_ids(self, roots: set[str]) -> set[str]:
        """BFS over child folders to return every transitive descendant folder id of `roots`
        (the roots themselves are NOT included). The parent → child lookups are batched
        (Drive caps query length), and an empty "No files found" result for a childless folder
        is a normal stop, not an error. Shared by both exclusion and recursive listing so the
        walk lives in exactly one place."""
        tool = self.enum.get("list_tool")
        if not tool or not roots:
            return set()
        found: set[str] = set()
        queue = list(roots)
        checked: set[str] = set()
        while queue:
            batch = []
            while queue and len(batch) < 20:
                fid = queue.pop(0)
                if fid not in checked:
                    checked.add(fid)
                    batch.append(fid)
            if not batch:
                continue
            parent_clauses = [f"'{fid}' in parents" for fid in batch]
            child_q = ("mimeType = 'application/vnd.google-apps.folder' and ("
                       + " or ".join(parent_clauses) + ")")
            for r in self._invoke_folder_query(tool, child_q):
                child_id = str(r.get(self._field("id")) or r.get("id") or "").strip()
                if child_id and child_id not in found and child_id not in roots:
                    found.add(child_id)
                    queue.append(child_id)
        return found

    @staticmethod
    def _escape(value: str) -> str:
        """Escape single quotes for a Google Drive query string literal."""
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def _invoke_folder_query(self, tool: str, q: str) -> list[dict]:
        """Run a folder-listing Drive query through the store's list tool, returning dict rows."""
        args: dict = {}
        qarg = self.enum.get("query_arg")
        if qarg:
            args[qarg] = q
        return [r for r in self._invoke(tool, args) if isinstance(r, dict)]

    def list_files(self, folder_id=None, query=None,
                   exclude_folders: list[str] | None = None,
                   recursive: bool = False) -> list[dict]:
        """Enumerate documents via the server's `list_tool`, mapping its fields to the lean
        graph shape per `graph_enum.fields`.

        For the Google Drive store the scope is expressed as a Drive query:
        - `folder_id` restricts to that folder's immediate children;
        - `recursive` (with `folder_id`) widens the scope to the folder and all of its nested
          subfolders, transitively — resolved to a parent-id set via `_descendant_folder_ids`
          and queried in batches (Drive caps query length), with results deduped by id;
        - `exclude_folders` resolves to a set of folder ids (and their subtrees) that are kept
          out of the result. In recursive mode the excluded subtrees are simply removed from
          the positive scope; otherwise they are appended as `not '<id>' in parents` clauses.

        A non-Drive store receives `folder_id`/`query` verbatim through its `query_arg` (it
        decides how to interpret scope); `recursive` is not expressible there and is ignored."""
        tool = self.enum.get("list_tool")
        if not tool:
            raise ConnectorError(
                f"document store {self.server_name!r} has no graph_enum.list_tool — it can't "
                f"be enumerated for the knowledge graph")

        if tool != "search_drive_files":
            scope = folder_id or query
            args: dict = {}
            qarg = self.enum.get("query_arg")
            if qarg:
                args[qarg] = scope if scope is not None else self.enum.get("default_query", "")
            return self._map_rows(self._invoke(tool, args))

        # ── Google Drive query construction ──────────────────────────────────────
        excl_ids: set[str] = set()
        if exclude_folders:
            excl_ids = self._get_excluded_folder_ids_recursive(exclude_folders)
            if not excl_ids:
                # Don't fail open: a requested exclusion that resolves to nothing would
                # otherwise silently return an unfiltered listing (the excluded folder's files
                # leaking through). Make it visible instead.
                print(f"warning: exclude_folders {exclude_folders!r} matched no folders on "
                      f"{self.server_name!r} — nothing will be filtered out. Check the folder "
                      f"name(s) against Drive (matching is case-insensitive but the name must "
                      f"exist).", file=sys.stderr)

        name_clause = [f"name contains '{self._escape(query)}'"] if query else []

        if recursive and folder_id:
            # Positive scope = the folder plus every nested subfolder, minus any excluded
            # subtree (exclusion wins). A file filed under both an included and an excluded
            # folder still surfaces — it genuinely lives in an included folder.
            scope_parents = ({folder_id} | self._descendant_folder_ids({folder_id})) - excl_ids
            if not scope_parents:
                return []  # the entire requested subtree is excluded
            deduped: dict[str, dict] = {}
            for batch in _chunks(sorted(scope_parents), 25):
                parents_clause = "(" + " or ".join(
                    f"'{fid}' in parents" for fid in batch) + ")"
                for doc in self._list_drive_files([parents_clause, *name_clause]):
                    if doc["id"]:
                        deduped.setdefault(doc["id"], doc)
            return list(deduped.values())

        # Non-recursive: single query — folder/query scope plus negative exclusion clauses.
        q_parts: list[str] = []
        if folder_id:
            q_parts.append(f"'{folder_id}' in parents")
        q_parts += name_clause
        q_parts += [f"not '{fid}' in parents" for fid in excl_ids]
        return self._list_drive_files(q_parts)

    def _list_drive_files(self, q_parts: list[str]) -> list[dict]:
        """Run one Google Drive `search_drive_files` query built from `q_parts` (ANDed),
        ensuring a folder-excluding `mimeType` filter is present, and map the rows."""
        if not q_parts:
            drive_q = (self.enum.get("default_query", "")
                       or "mimeType != 'application/vnd.google-apps.folder' and trashed = false")
        else:
            drive_q = " and ".join(q_parts)
            if "mimeType" not in drive_q:
                drive_q = f"mimeType != 'application/vnd.google-apps.folder' and {drive_q}"
        args: dict = {}
        qarg = self.enum.get("query_arg")
        if qarg:
            args[qarg] = drive_q
        return self._map_rows(self._invoke(self.enum["list_tool"], args))

    def _map_rows(self, rows: list) -> list[dict]:
        """Map raw tool rows onto the lean graph shape per `graph_enum.fields`."""
        out: list[dict] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            out.append({
                "id": str(r.get(self._field("id"), "")).strip(),
                "name": str(r.get(self._field("name"), "")).strip(),
                "dateModified": str(r.get(self._field("dateModified"), "") or "")[:10],
                "webUrl": str(r.get(self._field("webUrl"), "") or ""),
            })
        return out

    def get_file_content(self, file_id: str) -> str:
        """Not used by graph init — the graph stores references, not bodies (design rule #3)."""
        raise ConnectorError("the MCP connector does not fetch document bodies; the graph "
                             "stores references and human-gated descriptions only")

    # ── internals ────────────────────────────────────────────────────────────
    def _field(self, logical: str) -> str:
        """The store's raw field name for a logical field, per graph_enum.fields."""
        return (self.enum.get("fields") or {}).get(logical, logical)

    def _invoke(self, tool: str, arguments: dict) -> list[dict]:
        call = self._transport or self._http_call
        rows = call(tool, arguments)
        if not isinstance(rows, list):
            raise ConnectorError(
                f"MCP tool {tool!r} on {self.server_name!r} returned {type(rows).__name__}, "
                f"expected a list of document records")
        return rows

    def _http_call(self, tool: str, arguments: dict) -> list[dict]:
        """One streamable-http MCP `tools/call`: initialize → initialized → call, then pull the
        document list out of the tool result. Lazy-imports `requests`. Best-effort parsing —
        verify against your own server; the field mapping is what tests cover."""
        try:
            import requests
        except ModuleNotFoundError as e:  # pragma: no cover - optional dep
            raise ConnectorError(
                "the MCP connector needs `requests` — `pip install requests`") from e
        if not self.endpoint:
            raise ConnectorError("no MCP endpoint configured")
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        session = requests.Session()

        def rpc(method: str, params: dict | None, want_result: bool):
            body = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                body["params"] = params
            if want_result:
                body["id"] = 1
            resp = session.post(self.endpoint, headers=headers, json=body, timeout=30)
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                headers["Mcp-Session-Id"] = sid
            if not want_result:
                return None
            return _parse_rpc_result(resp)

        page_size_arg = self.enum.get("page_size_arg")
        page_size = self.enum.get("page_size")
        page_token_arg = self.enum.get("page_token_arg")
        token_pattern = self.enum.get("text_next_token")

        call_args = dict(arguments)
        if page_size_arg and page_size is not None:
            call_args[page_size_arg] = page_size

        try:
            rpc("initialize", {"protocolVersion": "2024-11-05",
                               "capabilities": {},
                               "clientInfo": {"name": "mitos", "version": "1"}}, True)
            rpc("notifications/initialized", {}, False)
            all_rows: list[dict] = []
            for _ in range(50):  # hard cap to guard against a token loop
                result = rpc("tools/call", {"name": tool, "arguments": call_args}, True)
                all_rows.extend(_documents_from_tool_result(result, self.enum))
                if not page_token_arg or not token_pattern:
                    break
                token = _extract_next_token(result, token_pattern)
                if not token:
                    break
                call_args = {**call_args, page_token_arg: token}
        except ConnectorError:
            raise
        except Exception as e:  # network/protocol errors → a clear connector failure
            raise ConnectorError(
                f"MCP call to {self.endpoint} failed: {e}") from e
        return all_rows


def _chunks(items: list, size: int):
    """Yield successive `size`-length slices of `items` (used to keep Drive queries short)."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _parse_rpc_result(resp) -> dict:
    """Read a JSON-RPC result from an MCP response (plain JSON or an SSE `data:` line)."""
    text = resp.text or ""
    payload = None
    ctype = resp.headers.get("Content-Type", "")
    if "text/event-stream" in ctype:
        for line in text.splitlines():
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                break
    if payload is None:
        payload = json.loads(text)
    if isinstance(payload, dict) and payload.get("error"):
        raise ConnectorError(f"MCP server error: {payload['error']}")
    return (payload or {}).get("result", {}) if isinstance(payload, dict) else {}


def _extract_next_token(result: dict, pattern: str) -> str | None:
    """Scan an MCP tool result's text content blocks for a pagination continuation token."""
    for block in (result.get("content") or []):
        if isinstance(block, dict) and block.get("type") == "text":
            m = re.search(pattern, block.get("text", ""))
            if m:
                return m.group(1).strip()
    return None


def _parse_text_rows(text: str, text_fields: dict) -> list[dict] | None:
    """Parse a human-readable line-per-item text response (e.g. google_workspace_mcp's
    `search_drive_files` output) using per-field regex patterns from graph_enum.text_fields.
    Returns a list (possibly empty for an empty result such as "Found 0 files" or
    "No files found for ...") when the text looks like a valid item listing, or None if the
    text doesn't match the expected format (caller treats it as an error)."""
    name_pat = text_fields.get("name")
    if not name_pat:
        return None
    has_items = bool(re.search(name_pat, text))
    # An empty-but-valid result. google_workspace_mcp reports zero hits as either
    # "Found 0 files" or "No files found for '<query>'" — both are legitimate empty
    # listings (e.g. a folder with no subfolders during the exclusion BFS), NOT errors.
    has_empty_listing = bool(
        re.search(r"Found\s+0\s+", text, re.IGNORECASE)
        or re.search(r"No\s+files\s+found", text, re.IGNORECASE))
    if not has_items and not has_empty_listing:
        return None  # doesn't look like a file listing — let the caller raise ConnectorError
    rows: list[dict] = []
    for line in text.splitlines():
        if not re.search(name_pat, line):
            continue
        row: dict = {}
        for field, pattern in text_fields.items():
            m = re.search(pattern, line)
            row[field] = m.group(1).strip() if m else ""
        if row.get("id") or row.get("name"):
            rows.append(row)
    return rows


def _documents_from_tool_result(result: dict, enum: dict | None = None) -> list[dict]:
    """Pull a list of document records out of an MCP `tools/call` result.

    Priority: structuredContent → JSON text content → text_fields regex parsing.
    Non-JSON text that can't be parsed via text_fields is raised as ConnectorError (avoids
    silently swallowing auth failures or other server-side errors as empty results). Servers
    that return human-readable text (e.g. google_workspace_mcp) declare graph_enum.text_fields
    with per-field regex patterns so their responses are parsed rather than treated as errors.
    """
    if not isinstance(result, dict):
        return []
    structured = result.get("structuredContent")
    rows = _coerce_rows(structured)
    if rows is not None:
        return rows
    tool_text = None
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            try:
                rows = _coerce_rows(json.loads(text))
            except (ValueError, TypeError):
                rows = None
            if rows is not None:
                return rows
            if text.strip() and tool_text is None:
                tool_text = text.strip()
    if tool_text is None:
        return []
    text_fields = (enum or {}).get("text_fields")
    if text_fields:
        parsed = _parse_text_rows(tool_text, text_fields)
        if parsed is not None:
            return parsed  # may be empty list (valid "Found 0 files" response)
    raise ConnectorError(f"MCP tool error: {tool_text}")


def _coerce_rows(value) -> list[dict] | None:
    """A list of dicts, or a dict wrapping one under a common key (files/documents/results/
    items). None if `value` isn't a recognizable document list."""
    if isinstance(value, list):
        return [r for r in value if isinstance(r, dict)]
    if isinstance(value, dict):
        for key in ("files", "documents", "results", "items"):
            inner = value.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
    return None
