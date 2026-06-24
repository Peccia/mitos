"""Paths, hashing, and lockfile I/O.

All registry/target/machine data stores POSIX-style forward-slash paths. Native
conversion happens only at the edge, here, when we touch the real filesystem.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path, PurePosixPath


def expand(path_str: str, *, home: str | None = None) -> Path:
    """Resolve a registry path string to a native absolute Path.

    Supports a leading ``~`` (current user, or an explicit machine ``home`` override)
    and normalizes separators. ``home`` lets a deploy target a machine whose home dir
    differs from the box actually running the compiler.
    """
    s = str(path_str).strip()
    if s.startswith("~"):
        rest = s[1:].lstrip("/\\")
        base = Path(home) if home else Path(os.path.expanduser("~"))
        return (base / rest) if rest else base
    return Path(s)


def safe_rel(deploy_path: str) -> PurePosixPath:
    """Turn an absolute/`~` deploy path into a dist-safe relative path.

    Strips leading ``~``, drive letters (``D:``), and leading slashes so the rendered
    artifact can be mirrored under dist/<machine>/ for review.
    """
    s = str(deploy_path).replace("\\", "/").lstrip("~")
    # drop a Windows drive prefix like "D:"
    if len(s) >= 2 and s[1] == ":":
        s = s[2:]
    return PurePosixPath(s.lstrip("/"))


def sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def zip_bytes(member: str, text: str) -> bytes:
    """A single-member zip with a FIXED timestamp: identical content must produce
    identical bytes, or every compile would look like a change to drift detection."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
        info.external_attr = 0o644 << 16
        zf.writestr(info, text)
    return buf.getvalue()


def zip_bytes_multiple(members: dict[str, str]) -> bytes:
    """A deterministic multi-member zip: members written in SORTED order, each with the
    same fixed timestamp as zip_bytes — identical content must produce identical bytes
    regardless of dict iteration order, or every compile would look like a change to
    drift detection. Used for skill zips that bundle examples/scripts alongside SKILL.md."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for member in sorted(members):
            info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            zf.writestr(info, members[member])
    return buf.getvalue()


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(read_text(path))


def dump_json(path: Path, data: dict) -> None:
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
