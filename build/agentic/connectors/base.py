"""Workspace connectors (Mitos).

A connector bridges an external document store (Google Workspace today; M365 / Notion /
local FS later) and the knowledge graph. It lives **beside** the compiler, never inside it
(Phase E constraint #1): the deterministic verbs (`compile` / `deploy` / `diff` / `adopt` /
`harvest`) never import this package, and any backend library is lazy-imported *inside* a
method so importing a connector never drags in heavy or optional deps.

A connector NEVER writes the graph. It enumerates a *scoped* folder and hands the documents
to `bootstrap_to_inbox`, which routes them through the one human-gated valve as a
`kind: graph` inbox candidate (constraint #2) — exactly like the Hermes graph-bootstrap
skill. One valve, many producers.
"""
from __future__ import annotations

import abc
import importlib


class ConnectorError(Exception):
    """A connector could not authenticate or fetch — reported, never a silent failure."""


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
        ``[{'id', 'name', 'dateModified', 'webUrl'}]``. Scope is the caller's responsibility —
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


def connector_for_store(reg, store: str, root=None) -> WorkspaceConnector:
    """Build the connector that backs a project's document store (its `document_store` — a
    server name from connections/servers.yaml).

    Every document store is an **MCP server** (Google Workspace is the first official
    offering; more follow). A store declares a `graph_enum` mapping and is enumerated through
    the generic **MCP connector** pointed at the server's `url` — Mitos reuses the server you
    already run rather than holding its own credentials. The in-process `mock` backend remains
    for tests/demos.

    Raises ConnectorError on `none`/unknown stores, or a store with no `graph_enum`, so the
    caller can report cleanly.
    """
    if not store or store == "none":
        raise ConnectorError(
            "this project has no document_store set — add `document_store: <server>` to its "
            "manifest (a server from connections/servers.yaml) before mapping its graph")
    servers = (getattr(reg, "servers", {}) or {}).get("servers") or {}
    server = servers.get(store)
    if server is None:
        raise ConnectorError(
            f"document_store {store!r} is not a known MCP server (connections/servers.yaml)")
    enum = server.get("graph_enum")
    if enum:
        from .mcp import MCPConnector
        return MCPConnector(root=root, endpoint=server.get("url"), enum=enum,
                            server_name=store)
    if store in _REGISTRY:
        return get_connector(store, root=root)
    raise ConnectorError(
        f"document_store {store!r} has no graph_enum mapping — every document store is an MCP "
        f"server; add a graph_enum: block to it in connections/servers.yaml (see the gws "
        f"server for the reference shape)")
