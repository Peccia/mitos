"""Turn a connector's file listing into a `kind: graph` inbox candidate — the one valve.

This is the producer that joins the connector layer to the existing human-gated graph
valve. It calls `review.propose_graph_change`, whose only write is to `inbox/` (invariant
#3); accept upserts the documents into `registry/graph/<slug>.jsonld`. The compiler is
never in this path.
"""
from __future__ import annotations

import datetime as _dt
import json as _json

from .. import loader as _loader
from ..loader import Registry
from .base import WorkspaceConnector

# Reserved slug used when staging without a bound project so the listing can be reviewed
# in the console and then proposed to any project.
_UNASSIGNED = "unassigned"


def files_to_documents(files: list[dict]) -> list[dict]:
    """Map a connector's ``[{'id','name','dateModified','webUrl','type',...}]`` to the
    document shape `review.propose_graph_change` expects. Descriptions default to ``""`` —
    short, human-gated summaries are added later in the console, never scraped (keeps the
    index lean and the prompt small). The connector-provided webUrl and type are carried
    through so the registry stores a store-agnostic link and the tool-selection hint."""
    docs: list[dict] = []
    for f in files:
        fid = str(f.get("id", "")).strip()
        name = str(f.get("name", "")).strip()
        if not fid or not name:
            continue
        docs.append({
            "id": fid,
            "name": name,
            "description": str(f.get("description", "")).strip(),
            "dateModified": str(f.get("dateModified", "")).strip(),
            "webUrl": str(f.get("webUrl", "")).strip(),
            "type": str(f.get("type", "")).strip(),
        })
    return docs


def _staged_documents(files: list[dict]) -> list[dict]:
    """Like files_to_documents, but keeps webUrl for the console's verify link."""
    out = []
    for f in files:
        fid = str(f.get("id", "")).strip()
        name = str(f.get("name", "")).strip()
        if not fid or not name:
            continue
        out.append({
            "id": fid, "name": name,
            "dateModified": str(f.get("dateModified", "")).strip(),
            "webUrl": str(f.get("webUrl", "")).strip(),
            "description": str(f.get("description", "")).strip(),
            "type": str(f.get("type", "")).strip(),
        })
    return out


def stage_listing(reg: Registry, connector: WorkspaceConnector, slug: str,
                  folder_id: str | None = None, query: str | None = None,
                  exclude_folders: list[str] | None = None,
                  recursive: bool = False) -> dict:
    """Enumerate a scoped folder/query and write inbox/staging/<slug>.json for the console
    to curate. Returns {ok, slug, count, path} or {ok: False, error}.

    The special slug ``"unassigned"`` is accepted so callers can stage without binding to a
    project first — the console will surface these documents in the Knowledge Graph tab as a
    shared pool the user manually routes into whichever project they choose.

    For all other slugs, membership in reg.projects is enforced so the written filename is
    registry-controlled — no traversal risk from user input."""
    from .. import io as _io
    if slug != _UNASSIGNED and slug not in reg.projects:
        return {"ok": False, "error": f"unknown project {slug!r}"}
    connector.authenticate()
    docs = _staged_documents(
        connector.list_files(folder_id=folder_id, query=query,
                             exclude_folders=exclude_folders or None, recursive=recursive))
    if not docs:
        return {"ok": False, "error": "connector returned no usable documents in that scope"}
    payload = {
        "slug": slug,
        "staged_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H%MZ"),
        "connector": getattr(connector, "name", "?"),
        "scope": {"folder_id": folder_id, "query": query,
                  "exclude_folders": exclude_folders or []},
        "documents": docs,
    }
    dest = _loader.inbox_dir(reg) / "staging" / f"{slug}.json"
    _io.write_text(dest, _json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return {"ok": True, "slug": slug, "count": len(docs), "path": f"inbox/staging/{slug}.json"}


def bootstrap_to_inbox(reg: Registry, connector: WorkspaceConnector, slug: str,
                       folder_id: str | None = None, query: str | None = None,
                       reason: str = "",
                       exclude_folders: list[str] | None = None,
                       recursive: bool = False) -> dict:
    """Enumerate a project's *scoped* folder via the connector and propose its documents as a
    `kind: graph` candidate, routed through `review.propose_graph_change` (writes only
    `inbox/`). Returns that result: ``{ok, id, registry_path}`` or ``{ok: False, error}``."""
    from .. import review
    connector.authenticate()
    files = connector.list_files(folder_id=folder_id, query=query,
                                 exclude_folders=exclude_folders or None, recursive=recursive)
    documents = files_to_documents(files)
    if not documents:
        return {"ok": False, "error": "connector returned no usable documents"}
    why = reason or (f"bootstrapped from the {connector.name} connector "
                     f"(folder {folder_id or '(scoped)'})")
    return review.propose_graph_change(reg, slug, documents, reason=why)
