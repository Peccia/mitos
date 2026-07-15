"""Pure, offline helpers for the inbox/staging/<slug>.json multi-listing shape.

A project can watch more than one scope (folder/query/store) at once — each stage run
either updates the listing matching its scope or appends a new one. No connector,
network, or OAuth imports live here: this module is safe for BOTH review.py (the
console, invariant #11 — no network code) and connectors/bootstrap.py (the CLI writer)
to import, so the scope-key/merge/overlap logic is defined exactly once rather than
duplicated across that boundary.

File shape (current):
    {"slug": "...", "listings": [
        {"scope_key": "...", "label": "", "staged_at": "...", "connector": "...",
         "scope": {"store": "", "folder_id": None, "query": None, "recursive": False,
                   "exclude_folders": []},
         "documents": [...]},
        ...
    ]}

File shape (legacy, pre-multi-scope — read-only, never written again once re-staged):
    {"slug": "...", "staged_at": "...", "connector": "...", "scope": {...},
     "documents": [...]}
"""
from __future__ import annotations

import hashlib
import json

# The four fields that make two scopes "the same watch" — re-staging one of these
# replaces its listing in place rather than appending a duplicate. exclude_folders is
# deliberately NOT part of identity: it's a filter, not what's being watched, so editing
# a server's exclude list in servers.yaml refreshes the existing watch on next stage
# instead of silently forking a second one.
_IDENTITY_FIELDS = ("store", "folder_id", "query", "recursive")

# A label is cosmetic — the operator's name for a watch, never part of its identity. It is
# stored on the listing rather than derived, so renaming one watch can't disturb another
# and a refresh keeps the name (bootstrap.stage_listing carries it across a re-stage).
LABEL_MAX = 60


def scope_key(scope: dict) -> str:
    """Deterministic identity for a staging scope, from _IDENTITY_FIELDS only."""
    canonical = {
        "store": scope.get("store") or "",
        "folder_id": scope.get("folder_id") or None,
        "query": scope.get("query") or None,
        "recursive": bool(scope.get("recursive")),
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def is_full_scope(scope: dict) -> bool:
    """True when a listing has no folder/query narrowing — a full enumeration of the
    store, the only kind that can prove a document's absence on its own (a scoped
    listing's silence about a document outside its scope means nothing)."""
    return not (scope.get("folder_id") or scope.get("query"))


def scope_label(scope: dict) -> str:
    """Short human label for a scope — used in overlap notes and as the fallback name for
    an unlabelled watch. Not persisted; derived fresh from the scope dict each time."""
    if scope.get("folder_id"):
        return f"folder {scope['folder_id']}" + (" (recursive)" if scope.get("recursive") else "")
    if scope.get("query"):
        return f'query "{scope["query"]}"'
    return "unscoped"


def clean_label(raw: object) -> str:
    """Normalize an operator-supplied watch name: a single trimmed line, capped at
    LABEL_MAX. Empty (or anything unstringy) means "no label" — the caller falls back to
    scope_label, so clearing the field restores the derived name rather than blanking it."""
    if not isinstance(raw, str):
        return ""
    return " ".join(raw.split())[:LABEL_MAX]


def listing_label(listing: dict) -> str:
    """What to call a watch: the operator's name when set, else the derived scope label."""
    return listing.get("label") or scope_label(listing.get("scope") or {})


def _normalize_listing(listing: dict) -> dict:
    docs = listing.get("documents")
    scope = listing.get("scope") if isinstance(listing.get("scope"), dict) else {}
    return {
        "scope_key": listing.get("scope_key") or scope_key(scope),
        "label": clean_label(listing.get("label")),
        "staged_at": listing.get("staged_at", ""),
        "connector": listing.get("connector", ""),
        "scope": scope,
        "documents": docs if isinstance(docs, list) else [],
    }


def normalize_staging(data: dict) -> list[dict]:
    """Parse a staging/<slug>.json payload into its listings, wrapping the legacy
    single-listing shape (no "listings" key) as one listing with a computed scope_key.
    Never mutates `data`. Malformed entries are dropped rather than raising — staging
    data is best-effort curation state, not a source of truth."""
    listings = data.get("listings")
    if isinstance(listings, list):
        return [_normalize_listing(entry) for entry in listings if isinstance(entry, dict)]
    docs = data.get("documents")
    if not isinstance(docs, list):
        return []
    scope = data.get("scope") if isinstance(data.get("scope"), dict) else {}
    return [_normalize_listing({
        "staged_at": data.get("staged_at", ""),
        "connector": data.get("connector", ""),
        "scope": scope,
        "documents": docs,
    })]


def merge_documents(listings: list[dict]) -> list[dict]:
    """Union of every listing's documents, deduped by id. A document present in more
    than one listing carries every scope_key that produced it (`scope_keys`) — this is
    what both the console's overlap chips and the absence-provenance check in review.py
    key off of. First-seen wins for the document's own fields (name/dateModified/etc.);
    only scope_keys accumulates across listings."""
    merged: dict[str, dict] = {}
    for listing in listings:
        key = listing["scope_key"]
        for doc in listing["documents"]:
            did = str(doc.get("id") or "").strip()
            if not did:
                continue
            if did not in merged:
                merged[did] = dict(doc)
                merged[did]["scope_keys"] = [key]
            elif key not in merged[did]["scope_keys"]:
                merged[did]["scope_keys"].append(key)
    return list(merged.values())


def overlapping_listings(new_scope_key: str, new_doc_ids: set[str],
                         other_listings: list[dict]) -> list[dict]:
    """Listings (other than `new_scope_key`) that share at least one document id with the
    just-(re)staged listing — the "note: N documents also appear in watch X" warning.
    Warn-only: nothing is blocked here, refreshing either listing keeps the shared
    documents visible either way (see merge_documents's present-in-any-listing union)."""
    out = []
    for listing in other_listings:
        if listing["scope_key"] == new_scope_key:
            continue
        ids = {str(d.get("id")) for d in listing["documents"] if d.get("id")}
        shared = new_doc_ids & ids
        if shared:
            out.append({"scope_key": listing["scope_key"], "scope": listing["scope"],
                       "label": listing_label(listing), "count": len(shared)})
    return out
