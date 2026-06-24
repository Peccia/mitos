"""Shared error for the git sync flow."""
from __future__ import annotations


class SyncError(Exception):
    """A sync operation failed — reported, never silent."""
