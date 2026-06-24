"""Mitos workspace connectors — a pluggable, optional layer beside the compiler.

Importing this package is safe and cheap: backend deps (google client libs, etc.) are
lazy-imported inside connector methods, and the deterministic compiler never imports this
package at all (Phase E constraint #1).
"""
from .base import (ConnectorError, WorkspaceConnector, available,
                   connector_for_store, get_connector)
from .bootstrap import bootstrap_to_inbox, files_to_documents, stage_listing

__all__ = ["WorkspaceConnector", "ConnectorError", "available", "get_connector",
           "connector_for_store", "bootstrap_to_inbox", "files_to_documents", "stage_listing"]
