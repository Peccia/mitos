"""Local filesystem connector — the default when no MCP document store is configured.

Enumerates files in a local directory and maps them onto the lean graph shape:
  id          = SHA-1 of the absolute path (URL-safe, stable, satisfies the IRI invariant)
  name        = filename
  dateModified = mtime in ISO-8601 date (YYYY-MM-DD)
  webUrl      = file:// URI of the absolute path

The ``recursive`` flag walks subdirectories via ``os.walk``. ``exclude_folders`` filters by
folder name (case-insensitive) or absolute path. ``folder_id`` and ``query`` are both
treated as path prefixes / name substrings respectively (generic store convention).

This connector holds no credentials and makes no network calls. It is the fallback returned
by ``connector_for_store`` when a project has no ``document_store`` set, so a fresh
open-source clone can build a knowledge graph from a local project directory without any
MCP server or Google credentials.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
from pathlib import Path
from urllib.request import pathname2url

from .base import ConnectorError, WorkspaceConnector


def _file_id(path: Path) -> str:
    """Stable, URL-safe identifier: SHA-1 hex of the absolute POSIX path string."""
    return hashlib.sha1(path.as_posix().encode()).hexdigest()


def _file_url(path: Path) -> str:
    """file:// URI for an absolute path (cross-platform via urllib)."""
    return "file://" + pathname2url(str(path.resolve()))


def _mtime_date(path: Path) -> str:
    """ISO date of the file's last-modified time."""
    ts = path.stat().st_mtime
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime("%Y-%m-%d")


class LocalFileConnector(WorkspaceConnector):
    """Enumerate files in a local directory for knowledge-graph bootstrapping.

    ``root`` is the base directory to enumerate when no ``folder_id`` is supplied.
    It defaults to the current working directory.
    """

    name = "local"

    def __init__(self, root=None, *, base_dir: str | Path | None = None):
        self.root = root
        self._base = Path(base_dir).resolve() if base_dir else Path.cwd()

    def authenticate(self) -> None:
        if not self._base.is_dir():
            raise ConnectorError(
                f"local connector base directory does not exist: {self._base}")

    def list_folders(self, exclude_folders: list[str] | None = None) -> list[dict]:
        """Top-level subdirectories of the base dir as [{id, name}]."""
        excl = _excl_set(exclude_folders)
        folders = []
        try:
            for entry in sorted(self._base.iterdir()):
                if entry.is_dir() and not _is_excluded(entry, excl):
                    folders.append({"id": _file_id(entry), "name": entry.name})
        except PermissionError:
            pass
        return folders

    def list_files(self, folder_id: str | None = None,
                   query: str | None = None,
                   exclude_folders: list[str] | None = None,
                   recursive: bool = False) -> list[dict]:
        """Enumerate files under the base dir (or a scoped subdirectory).

        ``folder_id`` is matched against entry names (since local IDs are SHA-1 hashes,
        a folder_id that looks like a directory name is tried first as a direct name match
        before falling back to the hash-based lookup). ``query`` is a case-insensitive
        substring match on filenames. ``exclude_folders`` filters by name or absolute path.
        """
        scope = self._resolve_scope(folder_id)
        excl = _excl_set(exclude_folders)

        results: list[dict] = []
        if recursive:
            for dirpath, dirnames, filenames in os.walk(scope):
                dirpath_ = Path(dirpath)
                # prune excluded directories in-place so os.walk won't descend into them
                dirnames[:] = [d for d in dirnames
                                if not _is_excluded(dirpath_ / d, excl)]
                for fname in sorted(filenames):
                    fp = dirpath_ / fname
                    if _matches_query(fp, query):
                        results.append(_file_record(fp))
        else:
            try:
                for entry in sorted(scope.iterdir()):
                    if entry.is_file() and _matches_query(entry, query):
                        if not _is_excluded(entry.parent, excl):
                            results.append(_file_record(entry))
            except PermissionError:
                pass

        return results

    def get_file_content(self, file_id: str) -> str:
        raise ConnectorError(
            "the local connector does not fetch document bodies; "
            "the graph stores references, not content (design rule #3)")

    def _resolve_scope(self, folder_id: str | None) -> Path:
        """Resolve a folder_id (name, absolute path, or omitted) to a directory Path."""
        if not folder_id:
            return self._base
        # Try as an absolute path first
        candidate = Path(folder_id)
        if candidate.is_absolute() and candidate.is_dir():
            return candidate
        # Try as a name relative to base
        by_name = self._base / folder_id
        if by_name.is_dir():
            return by_name
        # Fall back: scan for a subdirectory whose SHA-1 id matches
        try:
            for entry in self._base.iterdir():
                if entry.is_dir() and _file_id(entry) == folder_id:
                    return entry
        except PermissionError:
            pass
        return self._base


def _excl_set(exclude_folders: list[str] | None) -> set[str]:
    """Normalised exclusion set: lowercased names and resolved absolute paths."""
    if not exclude_folders:
        return set()
    out: set[str] = set()
    for e in exclude_folders:
        e = e.strip()
        if not e:
            continue
        out.add(e.casefold())
        p = Path(e)
        if p.is_absolute():
            out.add(str(p.resolve()))
    return out


def _is_excluded(path: Path, excl: set[str]) -> bool:
    if not excl:
        return False
    return (path.name.casefold() in excl
            or str(path.resolve()) in excl)


def _matches_query(path: Path, query: str | None) -> bool:
    if not query:
        return True
    return query.casefold() in path.name.casefold()


def _file_record(path: Path) -> dict:
    return {
        "id": _file_id(path),
        "name": path.name,
        "dateModified": _mtime_date(path),
        "webUrl": _file_url(path),
        # the extension is the local store's document kind ("md", "pdf", …); "" for
        # extensionless files keeps the graph field optional (omit-when-absent)
        "type": path.suffix.lstrip(".").lower(),
    }
