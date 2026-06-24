"""An in-memory connector for tests and demos — no credentials, no network.

`mitos connect --backend mock` exercises the whole bootstrap → inbox path offline, and the
test suite uses it to prove a connector emits a `kind: graph` candidate through the valve
without live Google credentials.

Each file entry may carry an optional ``parents`` list (folder IDs) so that exclude_folders
filtering can be exercised in tests without a live Drive.
"""
from __future__ import annotations

from .base import WorkspaceConnector

_DEFAULT_FILES = [
    {"id": "MOCKDOC1", "name": "Quarterly Plan", "dateModified": "2026-06-18",
     "webUrl": "https://example.com/1", "parents": ["FOLDER1"]},
    {"id": "MOCKDOC2", "name": "Roadmap", "dateModified": "2026-06-19",
     "webUrl": "https://example.com/2", "parents": ["FOLDER1"]},
    {"id": "MOCKDOC3", "name": "Archive Doc", "dateModified": "2026-06-01",
     "webUrl": "https://example.com/3", "parents": ["FOLDER2"]},
]
_DEFAULT_FOLDERS = [
    {"id": "FOLDER1", "name": "Project Docs"},
    {"id": "FOLDER2", "name": "Archive"},
]


class MockConnector(WorkspaceConnector):
    name = "mock"

    def __init__(self, root=None, files=None, folders=None):
        self.root = root
        self._files = list(files) if files is not None else list(_DEFAULT_FILES)
        self._folders = list(folders) if folders is not None else list(_DEFAULT_FOLDERS)

    def authenticate(self) -> None:
        return None

    def list_folders(self, exclude_folders: list[str] | None = None) -> list[dict]:
        folders = list(self._folders)
        if exclude_folders:
            excl = set(exclude_folders)
            folders = [f for f in folders
                       if f.get("id") not in excl and f.get("name") not in excl]
        return folders

    def _descendant_folder_ids(self, root: str) -> set[str]:
        """Transitive subfolder ids of `root`, walking the folders' optional ``parents``."""
        found: set[str] = set()
        queue = [root]
        while queue:
            cur = queue.pop()
            for f in self._folders:
                fid = f.get("id", "")
                if fid and fid not in found and cur in (f.get("parents") or []):
                    found.add(fid)
                    queue.append(fid)
        return found

    def list_files(self, folder_id=None, query=None,
                   exclude_folders: list[str] | None = None,
                   recursive: bool = False) -> list[dict]:
        files = self._files
        if query:
            files = [f for f in files if query.lower() in str(f.get("name", "")).lower()]
        if folder_id:
            scope = {folder_id}
            if recursive:
                scope |= self._descendant_folder_ids(folder_id)
            files = [f for f in files if scope & set(f.get("parents") or [])]
        if exclude_folders:
            # Collect all folder IDs and names that are excluded; walk parent trees.
            excl_names = set(exclude_folders)
            # Build id→name and child→parent maps from the folder list
            id_to_name = {f["id"]: f.get("name", "") for f in self._folders}
            # Seed with folders matching by name or id
            excl_ids: set[str] = set()
            for f in self._folders:
                if f.get("id") in excl_names or f.get("name") in excl_names:
                    excl_ids.add(f["id"])
            # Expand recursively: any folder whose parent is excluded is also excluded
            changed = True
            while changed:
                changed = False
                for doc in self._files:
                    pass  # files don't have sub-folders in mock; folders are flat
                # For full child-of-child coverage, check folders whose parents are excluded
                for f in self._folders:
                    fid = f.get("id", "")
                    if fid not in excl_ids:
                        for par in (f.get("parents") or []):
                            if par in excl_ids:
                                excl_ids.add(fid)
                                changed = True
                                break
            files = [f for f in files
                     if not (set(f.get("parents") or []) & excl_ids)]
        return list(files)

    def get_file_content(self, file_id: str) -> str:
        return f"(mock body for {file_id})"
