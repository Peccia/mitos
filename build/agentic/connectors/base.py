"""Workspace connectors (Mitos).

A connector bridges a document store and the knowledge graph. Three built-in backends:
  - ``local``  — local filesystem (the default; no credentials needed)
  - ``mcp``    — any MCP server with a ``graph_enum:`` block in connections/servers.yaml
  - ``mock``   — in-process demo for tests and dry runs

A connector lives **beside** the compiler, never inside it (Phase E constraint #1): the
deterministic verbs (`compile` / `deploy` / `diff` / `adopt` / `harvest`) never import this
package, and any backend library is lazy-imported *inside* a method so importing a connector
never drags in heavy or optional deps.

A connector NEVER writes the graph. It enumerates a *scoped* folder and hands the documents
to `bootstrap_to_inbox`, which routes them through the one human-gated valve as a
`kind: graph` inbox candidate (constraint #2). One valve, many producers.
"""
from __future__ import annotations

import abc
import importlib


class ConnectorError(Exception):
    """A connector could not authenticate or fetch — reported, never a silent failure."""


# Friendly names for the store MIME types the fleet actually meets. Anything else falls
# back to the subtype tail ("text/markdown" → "markdown", "vnd.google-apps.drawing" →
# "drawing") so no store type is ever silently dropped.
_MIME_FRIENDLY = {
    "application/vnd.google-apps.document": "document",
    "application/vnd.google-apps.spreadsheet": "spreadsheet",
    "application/vnd.google-apps.presentation": "presentation",
    "application/vnd.google-apps.form": "form",
    "application/vnd.google-apps.folder": "folder",
    "application/pdf": "pdf",
}


def friendly_doc_type(raw: str) -> str:
    """A short, agent-facing document kind from a store's raw MIME type. Already-short
    values (a file extension from the local connector) pass through unchanged; empty
    stays empty — the graph field is optional (omit-when-absent)."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw in _MIME_FRIENDLY:
        return _MIME_FRIENDLY[raw]
    if "/" in raw:
        return raw.rsplit("/", 1)[-1].rsplit(".", 1)[-1] or raw
    return raw


class WorkspaceConnector(abc.ABC):
    """The minimal contract every backend implements. Keep it small: the graph is a lean
    index, so a connector only needs to list folders/files and (optionally) read a body."""

    name: str = "base"

    @abc.abstractmethod
    def authenticate(self) -> None:
        """Establish credentials. Raises ConnectorError on failure (missing creds, denied)."""

    @abc.abstractmethod
    def list_folders(self, exclude_folders: list[str] | None = None) -> list[dict]:
        """Top-level folders as ``[{'id', 'name'}]`` — the folder-mapping picker's source.
        Entries matching an id or name in `exclude_folders` are omitted."""

    @abc.abstractmethod
    def list_files(self, folder_id: str | None = None,
                   query: str | None = None,
                   exclude_folders: list[str] | None = None,
                   recursive: bool = False) -> list[dict]:
        """Files in a scoped folder (or matching a query) as
        ``[{'id', 'name', 'dateModified', 'webUrl', 'type'}]`` (``type`` optional/"" —
        the friendly document kind). Scope is the caller's responsibility —
        never enumerate the whole store. Entries whose parent folder id or name matches any
        element in `exclude_folders` (including recursively nested subfolders) are omitted.

        When `recursive` is true and a `folder_id` is given, files in all nested subfolders of
        that folder are included transitively (not just its immediate children)."""

    @abc.abstractmethod
    def get_file_content(self, file_id: str) -> str:
        """A document's text. Optional in practice — the graph stores references, not bodies;
        descriptions are human-gated, never scraped (design rule #3)."""


# Connector registry — name -> "module:ClassName" (relative to agentic.connectors). The
# backend module is imported lazily in get_connector, so registering a backend with heavy
# deps costs nothing until it's actually selected.
_REGISTRY: dict[str, str] = {
    "local": "local:LocalFileConnector",
    "mock": "mock:MockConnector",
    "mcp": "mcp:MCPConnector",
}


def available() -> list[str]:
    return sorted(_REGISTRY)


def get_connector(name: str, root=None) -> WorkspaceConnector:
    """Instantiate a connector by name. The backend module is imported here, lazily, so the
    deterministic compiler (which never calls this) never imports connector deps."""
    if name not in _REGISTRY:
        raise ConnectorError(f"unknown connector {name!r}; available: {available()}")
    mod_name, cls_name = _REGISTRY[name].split(":")
    mod = importlib.import_module(f"{__package__}.{mod_name}")
    return getattr(mod, cls_name)(root=root)


def _active_machine(root) -> str | None:
    if root is None:
        return None
    try:
        import subprocess
        from pathlib import Path
        overlay_dir = Path(root) / "registry" / "local"
        if overlay_dir.is_dir():
            res = subprocess.run(["git", "-C", str(overlay_dir), "config", "mitos.machine"],
                                 capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return res.stdout.strip() or None
    except Exception:
        pass
    return None


def connector_for_store(reg, store: str, root=None) -> WorkspaceConnector:
    """Build the connector that backs a project's document store (its `document_store` — a
    server name from connections/servers.yaml, or ``"none"``/unset).

    Resolution order:
    1. ``none``/unset → **LocalFileConnector** (the default; no MCP server required).
    2. A server with a ``graph_enum`` block → **MCPConnector** reusing the running server.
    3. A name already in the connector registry (e.g. ``mock``) → that connector directly.
    4. A server without ``graph_enum`` → ConnectorError with actionable guidance.

    The local fallback means a fresh clone with no Google credentials can still bootstrap
    a knowledge graph from a local project directory.
    """
    if not store or store == "none":
        from .local import LocalFileConnector
        return LocalFileConnector(root=root)
    servers = (getattr(reg, "servers", {}) or {}).get("servers") or {}
    server = servers.get(store)
    if server is None:
        raise ConnectorError(
            f"document_store {store!r} is not a known MCP server (connections/servers.yaml)")
    enum = server.get("graph_enum")
    if enum:
        from .mcp import MCPConnector
        url = server.get("url")
        machine_name = _active_machine(root)
        if machine_name:
            url = (server.get("urls") or {}).get(machine_name, url)
        return MCPConnector(root=root, endpoint=url, enum=enum,
                            server_name=store)
    if store in _REGISTRY:
        return get_connector(store, root=root)
    raise ConnectorError(
        f"document_store {store!r} has no graph_enum mapping — add a graph_enum: block to "
        f"it in connections/servers.yaml (see the gws server for the reference shape)")
