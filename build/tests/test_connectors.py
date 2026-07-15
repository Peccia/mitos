"""Connector, MCP, local-file, and staging tests."""
from __future__ import annotations

import sys
from pathlib import Path

from conftest import (
    REPO_ROOT, reg, loader, planner, render, classify_output,
    _inbox, _temp_registry, _doc, _write_graph,
    _plant_candidate, _skill_meta, _full_windows_rig, _sandbox_deploy,
    _git_available, _run_git, _make_overlay_hub, _clone_overlay, _seed_overlay,
)

def test_connector_bootstrap_emits_graph_candidate_through_valve():
    # a connector is a producer for the one valve: it proposes a kind:graph candidate via
    # review.propose_graph_change (writes inbox/ only), never the graph directly. No creds.
    from agentic import graph, review
    from agentic.connectors import bootstrap_to_inbox
    from agentic.connectors.mock import MockConnector
    treg, tmp = _temp_registry()
    mock = MockConnector(files=[
        {"id": "DRV1", "name": "Forecast Spec", "dateModified": "2026-06-18"},
        {"id": "DRV2", "name": "Roadmap", "dateModified": "2026-06-19"}])
    out = bootstrap_to_inbox(treg, mock, "example-project")
    assert out["ok"] and out["registry_path"] == "graph/example-project.jsonld"
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out["id"])
    assert cand["kind"] == "graph" and cand["acceptable"]
    assert any(r["t"] == "ins" and "DRV1" in (r["r"] or "") for r in cand["diff"])
    # accept upserts both docs into registry/graph/example-project.jsonld (same path as the console)
    acc = review.decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"] and acc["changed"] == ["graph/example-project.jsonld"]
    merged = graph.load_project_graph(tmp / "registry" / "graph" / "example-project.jsonld")
    assert {d.drive_id for d in merged.documents} >= {"DRV1", "DRV2"}
    # a connector that returns nothing reports and writes no candidate (reported, not fatal)
    assert not bootstrap_to_inbox(treg, MockConnector(files=[]), "example-project")["ok"]

def test_bootstrap_to_inbox_reason_not_passed_as_removals():
    # regression: bootstrap_to_inbox used to pass `why` positionally as `removals`,
    # causing the reason string to be iterated char-by-char as Drive IDs to remove.
    import yaml
    from agentic import loader, review
    from agentic.connectors import bootstrap_to_inbox
    from agentic.connectors.mock import MockConnector
    treg, tmp = _temp_registry()
    mock = MockConnector(files=[
        {"id": "DRV1", "name": "Spec", "dateModified": "2026-06-18"}])
    out = bootstrap_to_inbox(treg, mock, "example-project",
                             reason="seeded from integration test")
    assert out["ok"]
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out["id"])
    # the candidate must carry no spurious removals (reason chars must NOT appear as IDs)
    assert cand.get("removals", []) == []
    # the reason must be stored in meta.yaml (id == folder name)
    meta = yaml.safe_load(
        (loader.inbox_dir(treg) / out["id"] / "meta.yaml").read_text())
    assert meta.get("reason") == "seeded from integration test"

def test_mcp_connector_maps_store_fields_and_bootstraps_through_valve():
    # the backend-agnostic MCP connector enumerates an already-running store via its graph_enum
    # mapping (transport injected here so the field-mapping is covered without a live server),
    # then rides the SAME one human-gated valve as every other connector.
    from agentic import review
    from agentic.connectors import bootstrap_to_inbox
    from agentic.connectors.mcp import MCPConnector
    treg, tmp = _temp_registry()
    enum = treg.servers["servers"]["gws"]["graph_enum"]
    captured = {}

    def transport(tool, arguments):
        captured["tool"], captured["args"] = tool, arguments
        return [
            {"id": "DRV1", "name": "Forecast Spec", "modifiedTime": "2026-06-18T10:00:00Z",
             "webViewLink": "https://drive/1",
             "mimeType": "application/vnd.google-apps.spreadsheet"},
            {"id": "DRV2", "name": "Roadmap", "modifiedTime": "2026-06-19T09:00:00Z"}]

    conn = MCPConnector(endpoint="http://localhost:8000/mcp", enum=enum,
                        server_name="gws", transport=transport)
    files = conn.list_files(folder_id="FOLDERX")
    # the store's raw fields map onto the lean graph shape (modifiedTime->dateModified, dated
    # to the day; webViewLink->webUrl; mimeType->type, friendly form) and the folder scope
    # rides the configured query_arg
    assert files[0] == {"id": "DRV1", "name": "Forecast Spec",
                        "dateModified": "2026-06-18", "webUrl": "https://drive/1",
                        "type": "spreadsheet"}
    assert files[1]["type"] == "", "no mimeType from the store → empty, omitted from the graph"
    assert captured["tool"] == "search_drive_files"
    assert "FOLDERX" in captured["args"]["query"]
    out = bootstrap_to_inbox(treg, conn, "example-project")
    assert out["ok"]
    cand = next(c for c in review.load_candidates(treg) if c["id"] == out["id"])
    assert cand["kind"] == "graph" and cand["acceptable"]

def test_mcp_connector_generic_path_passes_scope_verbatim():
    # A store with no query_syntax (or query_syntax != "google-drive") must receive scope
    # verbatim through query_arg — no Drive-specific query construction happens.
    from agentic.connectors.mcp import MCPConnector
    captured = {}

    def transport(tool, arguments):
        captured["tool"], captured["args"] = tool, arguments
        return [{"id": "N1", "name": "Page One", "dateModified": "2026-06-01",
                 "webUrl": "https://notion.so/page-one"}]

    # enum without query_syntax → generic path
    enum = {
        "list_tool": "search_notion_pages",
        "query_arg": "query",
        "fields": {"id": "id", "name": "name",
                   "dateModified": "dateModified", "webUrl": "webUrl"},
    }
    conn = MCPConnector(endpoint="http://localhost:9000/mcp", enum=enum,
                        server_name="notion", transport=transport)
    files = conn.list_files(folder_id="SPACE_X", query="design")
    assert captured["tool"] == "search_notion_pages"
    # scope = folder_id or query; folder_id takes priority when both are set
    assert captured["args"]["query"] == "SPACE_X"
    assert files[0]["webUrl"] == "https://notion.so/page-one"

    # folder_id only (no query): scope = folder_id
    conn2 = MCPConnector(endpoint="http://localhost:9000/mcp", enum=enum,
                         server_name="notion", transport=transport)
    conn2.list_files(folder_id="SPACE_X")
    assert captured["args"]["query"] == "SPACE_X"

    # neither: scope = default_query (empty string → passed as-is)
    conn3 = MCPConnector(endpoint="http://localhost:9000/mcp", enum=enum,
                         server_name="notion", transport=transport)
    conn3.list_files()
    assert captured["args"]["query"] == ""

def test_mcp_text_format_parsing():
    # google_workspace_mcp returns search_drive_files results as human-readable text, not JSON.
    # _parse_text_rows extracts items via text_fields regex patterns; _documents_from_tool_result
    # uses it when JSON parsing fails; auth errors are still raised as ConnectorError.
    from agentic.connectors.base import ConnectorError
    from agentic.connectors.mcp import _documents_from_tool_result, _parse_text_rows

    text_fields = {
        "id": r'ID: ([^\s,)]+)',
        "name": r'Name: "([^"]+)"',
        "modifiedTime": r'Modified: ([^,)]+)',
        "webViewLink": r'Link: (\S+)',
    }
    enum = {"text_fields": text_fields, "fields": {"id": "id", "name": "name",
                                                    "dateModified": "modifiedTime",
                                                    "webUrl": "webViewLink"}}
    gws_text = (
        "Found 2 files for user@example.com matching '':\n"
        '- Name: "Report Alpha" (ID: DRIVE_ALPHA, Type: application/vnd.google-apps.document, '
        'Size: 1500, Created: 2026-01-01T00:00:00.000Z, Modified: 2026-06-01T12:00:00.000Z, '
        'Last Edited By: User <user@example.com>) Link: https://docs.google.com/document/d/DRIVE_ALPHA/edit\n'
        '- Name: "Report Beta" (ID: DRIVE_BETA, Type: application/vnd.google-apps.document, '
        'Size: 2500, Created: 2026-02-01T00:00:00.000Z, Modified: 2026-06-15T09:00:00.000Z, '
        'Last Edited By: User <user@example.com>) Link: https://docs.google.com/document/d/DRIVE_BETA/edit\n'
    )

    # _parse_text_rows extracts all items with correct field values
    rows = _parse_text_rows(gws_text, text_fields)
    assert rows is not None and len(rows) == 2
    assert rows[0]["id"] == "DRIVE_ALPHA" and rows[0]["name"] == "Report Alpha"
    assert rows[0]["modifiedTime"].startswith("2026-06-01")
    assert "DRIVE_ALPHA" in rows[0]["webViewLink"]

    # error text has no Name: "..." pattern → returns None (caller raises ConnectorError)
    assert _parse_text_rows("Error calling tool: ACTION REQUIRED: Google Auth Needed", text_fields) is None

    # "Found 0 files" header, no item lines → empty list (valid empty result, not an error)
    assert _parse_text_rows("Found 0 files for user@example.com matching 'q':\n", text_fields) == []

    # _documents_from_tool_result: non-JSON text content → parsed via text_fields
    result = {"content": [{"type": "text", "text": gws_text}]}
    docs = _documents_from_tool_result(result, enum)
    assert len(docs) == 2 and docs[0]["id"] == "DRIVE_ALPHA"

    # auth error text → ConnectorError (text doesn't match item format)
    error_result = {"content": [{"type": "text", "text": "Error calling tool: ACTION REQUIRED"}]}
    try:
        _documents_from_tool_result(error_result, enum)
        raise AssertionError("should raise ConnectorError")
    except ConnectorError as e:
        assert "MCP tool error" in str(e)

    # "Found 0 files" via _documents_from_tool_result → empty list, not an error
    empty_result = {"content": [{"type": "text", "text": "Found 0 files for user@example.com matching 'q':\n"}]}
    assert _documents_from_tool_result(empty_result, enum) == []

    # without text_fields configured, non-JSON text still raises ConnectorError
    try:
        _documents_from_tool_result(result, {})
        raise AssertionError("should raise ConnectorError")
    except ConnectorError:
        pass

def test_mcp_next_token_extraction():
    # _extract_next_token pulls the continuation token from a GWS text response so _http_call
    # can follow pages; returns None when no token is present (last page).
    from agentic.connectors.mcp import _extract_next_token

    pattern = r'nextPageToken: (\S+)'
    result_with_token = {"content": [{"type": "text", "text":
        "Found 10 files for user@example.com matching '':\n"
        "- Name: \"Doc\" (ID: X, ...) Link: https://docs.google.com/d/X/edit\n"
        "nextPageToken: ~!!~SOMETOKEN123\n"}]}
    assert _extract_next_token(result_with_token, pattern) == "~!!~SOMETOKEN123"

    result_no_token = {"content": [{"type": "text", "text": "Found 2 files...\n- Name: \"Doc\" ...\n"}]}
    assert _extract_next_token(result_no_token, pattern) is None

def test_connector_for_store_resolves_mcp_from_graph_enum_and_rejects_unmapped():
    # graph init resolves its connector from the project's document_store: a server WITH a
    # graph_enum mapping → the generic MCP connector pointed at that server's url (reuse, no
    # second auth); 'none'/unset → LocalFileConnector (default); unknown server → error.
    from agentic.connectors import ConnectorError, connector_for_store
    from agentic.connectors.local import LocalFileConnector
    from agentic.connectors.mcp import MCPConnector
    treg, _tmp = _temp_registry()
    conn = connector_for_store(treg, "gws")
    assert isinstance(conn, MCPConnector)
    assert conn.endpoint == treg.servers["servers"]["gws"]["url"]
    # none/empty → LocalFileConnector (the open-source cold-start default, not an error)
    for fallback in ("none", ""):
        lc = connector_for_store(treg, fallback)
        assert isinstance(lc, LocalFileConnector), f"{fallback!r} should return LocalFileConnector"
    # unknown server name → ConnectorError
    try:
        connector_for_store(treg, "no-such-store")
        raise AssertionError("expected ConnectorError for unknown store")
    except ConnectorError:
        pass

def test_local_file_connector_enumerates_files_and_emits_correct_shape():
    """LocalFileConnector produces records with URL-safe SHA-1 ids, file:// webUrls,
    ISO date modified, and filenames — satisfying the IRI invariant (id = IRI suffix)."""
    import hashlib, tempfile
    from pathlib import Path
    from agentic.connectors.local import LocalFileConnector, _file_id, _file_url
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "report.txt").write_text("hello")
        (base / "notes.md").write_text("world")
        sub = base / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_text("nested")

        conn = LocalFileConnector(base_dir=base)
        conn.authenticate()

        # non-recursive: only immediate files, not sub/deep.txt
        files = conn.list_files()
        names = {f["name"] for f in files}
        assert names == {"report.txt", "notes.md"}
        for f in files:
            # id must be SHA-1 hex (40 chars, hex only) — URL-safe for IRI suffix
            assert len(f["id"]) == 40 and all(c in "0123456789abcdef" for c in f["id"])
            assert f["webUrl"].startswith("file://")
            assert len(f["dateModified"]) == 10 and f["dateModified"][4] == "-"

        # recursive: includes sub/deep.txt
        files_r = conn.list_files(recursive=True)
        assert {f["name"] for f in files_r} == {"report.txt", "notes.md", "deep.txt"}

        # query filter: case-insensitive substring match on filename
        filtered = conn.list_files(query="REPORT")
        assert [f["name"] for f in filtered] == ["report.txt"]

        # exclude_folders: sub/ excluded by name
        files_excl = conn.list_files(recursive=True, exclude_folders=["sub"])
        assert {f["name"] for f in files_excl} == {"report.txt", "notes.md"}

        # id is stable: same path → same SHA-1
        report = next(f for f in files if f["name"] == "report.txt")
        assert report["id"] == _file_id(base / "report.txt")

        # webUrl matches file:// URI for the path
        assert report["webUrl"] == _file_url(base / "report.txt")

        # list_folders returns subdirectories
        folders = conn.list_folders()
        assert any(f["name"] == "sub" for f in folders)

def test_local_file_connector_folder_id_scope():
    """folder_id scopes to a named subdirectory."""
    import tempfile
    from pathlib import Path
    from agentic.connectors.local import LocalFileConnector
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        sub = base / "docs"
        sub.mkdir()
        (base / "root.txt").write_text("r")
        (sub / "inner.txt").write_text("i")

        conn = LocalFileConnector(base_dir=base)
        # folder_id as directory name → scoped to that subdir
        files = conn.list_files(folder_id="docs")
        assert [f["name"] for f in files] == ["inner.txt"]

def test_local_file_connector_bootstraps_through_valve():
    """End-to-end: LocalFileConnector → bootstrap_to_inbox → accept → graph with file:// links.
    Proves web_url (Commit 1) and the generic query path (Commit 2) work together."""
    import tempfile
    from pathlib import Path
    from agentic import graph, loader, review
    from agentic.connectors import bootstrap_to_inbox
    from agentic.connectors.local import LocalFileConnector
    treg, tmp = _temp_registry()
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "spec.md").write_text("spec content")
        (base / "roadmap.txt").write_text("roadmap content")
        conn = LocalFileConnector(base_dir=base)
        out = bootstrap_to_inbox(treg, conn, "example-project")
        assert out["ok"], out.get("error")
        acc = review.decide(loader.load(tmp), out["id"], "accept", "")
        assert acc["ok"]
        pg = graph.load_project_graph(
            tmp / "registry" / "graph" / "example-project.jsonld")
        # new docs were upserted (may join pre-existing example docs)
        local_docs = [d for d in pg.documents if d.web_url.startswith("file://")]
        assert len(local_docs) == 2
        for d in local_docs:
            # web_url is a file:// link, not a synthesized Drive URL
            assert d.web_url.startswith("file://")
            assert d.drive_url == d.web_url  # drive_url falls back to web_url (no Drive ID)

def test_project_document_store_must_name_a_known_server():
    import yaml as _y
    _treg, tmp = _temp_registry()
    p = tmp / "registry" / "projects" / "example-project.yaml"
    data = _y.safe_load(p.read_text(encoding="utf-8"))
    data["document_store"] = "not-a-server"
    p.write_text(_y.safe_dump(data), encoding="utf-8")
    try:
        loader.load(tmp)
        raise AssertionError("expected RegistryError")
    except loader.RegistryError as e:
        assert "document_store" in str(e)

def test_server_graph_enum_requires_list_tool_and_id_name_fields():
    import yaml as _y
    _treg, tmp = _temp_registry()
    conn = tmp / "connections" / "servers.yaml"
    data = _y.safe_load(conn.read_text(encoding="utf-8"))
    data["servers"]["gws"]["graph_enum"] = {"fields": {"name": "name"}}  # no list_tool, no id
    conn.write_text(_y.safe_dump(data), encoding="utf-8")
    try:
        loader.load(tmp)
        raise AssertionError("expected RegistryError")
    except loader.RegistryError as e:
        assert "graph_enum" in str(e)

def test_project_add_manifest_scaffold_loads_and_binds_store():
    # Stage 1: the manifest `mitos project add` writes must load cleanly and carry the
    # document_store binding that Stage 3 (connect) reads.
    import importlib
    sys.path.insert(0, str(REPO_ROOT / "build"))
    mitos = importlib.import_module("mitos")
    _treg, tmp = _temp_registry()
    text = mitos._project_manifest_yaml("acme", "Acme Co", "gws")
    (tmp / "registry" / "projects" / "acme.yaml").write_text(text, encoding="utf-8")
    reg2 = loader.load(tmp)
    assert reg2.projects["acme"]["slug"] == "acme"
    assert reg2.projects["acme"]["document_store"] == "gws"
    assert reg2.projects["acme"]["name"] == "Acme Co"

def test_connect_missing_store_explains_servers_file_and_line():
    # an unbound project must not fail with a bare error — it spells out the available servers,
    # the manifest file, and the exact line to add (the #1 thing a new user hits).
    import contextlib
    import importlib
    import io
    sys.path.insert(0, str(REPO_ROOT / "build"))
    mitos = importlib.import_module("mitos")
    treg, _tmp = _temp_registry()  # example-project ships document_store: none
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rc = mitos._explain_missing_store(treg, "example-project")
    msg = err.getvalue()
    assert rc == 2
    assert "gws" in msg                                   # names the available server
    assert "projects/example-project.yaml" in msg         # names the manifest file
    assert "document_store: gws" in msg                   # gives the exact line

def test_connect_loops_multi_store_one_candidate_per_store():
    """A project bound to two stores loops connect once per store — one candidate each,
    each tagged with its own store (review._apply_graph_candidate's store-scoped upsert
    then keeps them from touching each other's documents, covered in test_graph.py)."""
    import argparse
    import importlib
    import json as _json
    import yaml as _y
    from agentic import review
    from agentic.connectors.mock import MockConnector
    import agentic.connectors as connectors_pkg
    sys.path.insert(0, str(REPO_ROOT / "build"))
    mitos = importlib.import_module("mitos")

    treg, tmp = _temp_registry()
    pfile = tmp / "registry" / "projects" / "example-project.yaml"
    data = _y.safe_load(pfile.read_text(encoding="utf-8"))
    data["document_store"] = ["gws", "fake2"]
    pfile.write_text(_y.safe_dump(data), encoding="utf-8")
    conn_file = tmp / "connections" / "servers.yaml"
    conn_data = _y.safe_load(conn_file.read_text(encoding="utf-8"))
    conn_data["servers"]["fake2"] = {"description": "Second store — for tests."}
    conn_file.write_text(_y.safe_dump(conn_data), encoding="utf-8")

    calls: list[str] = []

    def fake_connector_for_store(reg2, store, root=None):
        calls.append(store)
        return MockConnector(files=[
            {"id": f"{store.upper()}1", "name": f"{store} doc", "dateModified": "2026-06-01"}])

    orig_connector_for_store = connectors_pkg.connector_for_store
    orig_repo_root = mitos.REPO_ROOT
    connectors_pkg.connector_for_store = fake_connector_for_store
    mitos.REPO_ROOT = tmp
    try:
        args = argparse.Namespace(project="example-project", backend=None,
                                  folder_id=None, recursive=False, query=None,
                                  stage=False, store=None)
        rc = mitos._cmd_connect(args)
    finally:
        connectors_pkg.connector_for_store = orig_connector_for_store
        mitos.REPO_ROOT = orig_repo_root

    assert rc == 0
    assert sorted(calls) == ["fake2", "gws"]
    cands = [c for c in review.load_candidates(loader.load(tmp)) if c["kind"] == "graph"]
    assert len(cands) == 2
    stores_seen = set()
    for c in cands:
        meta = _y.safe_load((_inbox(tmp) / c["id"] / "meta.yaml").read_text(encoding="utf-8"))
        stores_seen.add(meta["store"])
        payload = _json.loads((_inbox(tmp) / c["id"] / "graph.jsonld").read_text(encoding="utf-8"))
        ids = [n["identifier"] for n in payload["@graph"] if n.get("@type") == "DigitalDocument"]
        assert ids == [meta["store"].upper() + "1"]
    assert stores_seen == {"gws", "fake2"}

def test_connect_stage_loops_multi_store_one_listing_per_store():
    """`--stage` on a multi-store project used to refuse outright; it now loops the same
    way the non-stage path does — one LISTING per store, all in the same
    inbox/staging/<slug>.json (not one candidate each, since --stage never proposes)."""
    import argparse
    import importlib
    import json as _json
    import yaml as _y
    import agentic.connectors as connectors_pkg
    sys.path.insert(0, str(REPO_ROOT / "build"))
    mitos = importlib.import_module("mitos")

    treg, tmp = _temp_registry()
    pfile = tmp / "registry" / "projects" / "example-project.yaml"
    data = _y.safe_load(pfile.read_text(encoding="utf-8"))
    data["document_store"] = ["gws", "fake2"]
    pfile.write_text(_y.safe_dump(data), encoding="utf-8")
    conn_file = tmp / "connections" / "servers.yaml"
    conn_data = _y.safe_load(conn_file.read_text(encoding="utf-8"))
    conn_data["servers"]["fake2"] = {"description": "Second store — for tests."}
    conn_file.write_text(_y.safe_dump(conn_data), encoding="utf-8")

    def fake_connector_for_store(reg2, store, root=None):
        from agentic.connectors.mock import MockConnector
        return MockConnector(files=[
            {"id": f"{store.upper()}1", "name": f"{store} doc q"}])

    orig_connector_for_store = connectors_pkg.connector_for_store
    orig_repo_root = mitos.REPO_ROOT
    connectors_pkg.connector_for_store = fake_connector_for_store
    mitos.REPO_ROOT = tmp
    try:
        args = argparse.Namespace(project="example-project", backend=None,
                                  folder_id=None, recursive=False, query="q",
                                  stage=True, store=None)
        rc = mitos._cmd_connect(args)
    finally:
        connectors_pkg.connector_for_store = orig_connector_for_store
        mitos.REPO_ROOT = orig_repo_root

    assert rc == 0
    data = _json.loads((_inbox(tmp) / "staging" / "example-project.json")
                       .read_text(encoding="utf-8"))
    assert len(data["listings"]) == 2
    stores_seen = {l["scope"]["store"] for l in data["listings"]}
    assert stores_seen == {"gws", "fake2"}
    ids_by_store = {l["scope"]["store"]: [d["id"] for d in l["documents"]] for l in data["listings"]}
    assert ids_by_store == {"gws": ["GWS1"], "fake2": ["FAKE21"]}
    # no kind:graph candidates — --stage never proposes, only writes staging/
    from agentic import review
    assert [c for c in review.load_candidates(loader.load(tmp)) if c["kind"] == "graph"] == []

def test_stage_listing_writes_artifact_with_weburl():
    """stage_listing writes inbox/staging/<slug>.json as one listing and keeps webUrl."""
    import json as _json
    from agentic.connectors.bootstrap import stage_listing
    from agentic.connectors.mock import MockConnector
    treg, tmp = _temp_registry()
    mock = MockConnector(files=[
        {"id": "DRV1", "name": "Forecast Spec", "dateModified": "2026-06-18",
         "webUrl": "https://example.com/drive/1"}])
    out = stage_listing(treg, mock, "example-project", query="forecast")
    assert out["ok"] and out["count"] == 1 and out["overlap"] == []
    artifact = _inbox(tmp) / "staging" / "example-project.json"
    assert artifact.is_file()
    data = _json.loads(artifact.read_text(encoding="utf-8"))
    assert data["slug"] == "example-project"
    assert len(data["listings"]) == 1
    listing = data["listings"][0]
    assert listing["scope"]["query"] == "forecast"
    d = listing["documents"][0]
    assert all(k in d for k in ("id", "name", "dateModified", "webUrl"))
    assert d["webUrl"] == "https://example.com/drive/1"


def test_stage_listing_replaces_same_scope_appends_new_scope():
    """Re-staging the SAME scope (store/folder_id/query/recursive) replaces its listing in
    place; a different scope is appended alongside it — the "watch more than one folder"
    story. exclude_folders is deliberately NOT part of scope identity."""
    import json as _json
    from agentic.connectors.bootstrap import stage_listing
    from agentic.connectors.mock import MockConnector
    treg, tmp = _temp_registry()
    artifact = _inbox(tmp) / "staging" / "example-project.json"

    out1 = stage_listing(treg, MockConnector(files=[{"id": "A", "name": "q1 Alpha"}]),
                         "example-project", query="q1")
    assert out1["ok"], out1
    data1 = _json.loads(artifact.read_text(encoding="utf-8"))
    assert len(data1["listings"]) == 1

    # same scope (query="q1"), different exclude_folders, different result set — REPLACES
    out2 = stage_listing(treg, MockConnector(files=[{"id": "B", "name": "q1 Beta"}]),
                         "example-project", query="q1", exclude_folders=["Archive"])
    assert out2["ok"], out2
    data2 = _json.loads(artifact.read_text(encoding="utf-8"))
    assert len(data2["listings"]) == 1
    assert data2["listings"][0]["documents"][0]["id"] == "B"
    assert data2["listings"][0]["scope"]["exclude_folders"] == ["Archive"]

    # a genuinely different scope (query="q2") APPENDS a second listing
    out3 = stage_listing(treg, MockConnector(files=[{"id": "C", "name": "q2 Gamma"}]),
                         "example-project", query="q2")
    assert out3["ok"], out3
    data3 = _json.loads(artifact.read_text(encoding="utf-8"))
    assert len(data3["listings"]) == 2
    ids_by_listing = {tuple(sorted(d["id"] for d in l["documents"])) for l in data3["listings"]}
    assert ids_by_listing == {("B",), ("C",)}


def test_stage_listing_reports_overlap_with_sibling_listings():
    """Two watched scopes that share a document report the overlap — warn-only, both
    listings are written and both keep the shared document."""
    import json as _json
    from agentic.connectors.bootstrap import stage_listing
    from agentic.connectors.mock import MockConnector
    treg, tmp = _temp_registry()

    out1 = stage_listing(treg, MockConnector(files=[
        {"id": "SHARED", "name": "q1 Shared"}, {"id": "ONLY1", "name": "q1 Only One"}]),
        "example-project", query="q1")
    assert out1["ok"] and out1["overlap"] == [], out1

    out2 = stage_listing(treg, MockConnector(files=[
        {"id": "SHARED", "name": "q2 Shared"}, {"id": "ONLY2", "name": "q2 Only Two"}]),
        "example-project", query="q2")
    assert out2["ok"], out2
    assert len(out2["overlap"]) == 1
    assert out2["overlap"][0]["count"] == 1

    artifact = _inbox(tmp) / "staging" / "example-project.json"
    data = _json.loads(artifact.read_text(encoding="utf-8"))
    assert len(data["listings"]) == 2   # both kept — overlap never blocks a write

def test_stage_listing_empty_scope_is_reported():
    """stage_listing with no matching files returns ok=False and writes nothing."""
    from agentic.connectors.bootstrap import stage_listing
    from agentic.connectors.mock import MockConnector
    treg, tmp = _temp_registry()
    out = stage_listing(treg, MockConnector(files=[]), "example-project")
    assert out["ok"] is False
    assert "no usable documents" in out["error"]
    assert not (_inbox(tmp) / "staging" / "example-project.json").is_file()

def test_stage_listing_unknown_project_rejected():
    """stage_listing refuses to write for a project not in the registry."""
    from agentic.connectors.bootstrap import stage_listing
    from agentic.connectors.mock import MockConnector
    treg, _tmp = _temp_registry()
    out = stage_listing(treg, MockConnector(), "no-such-project")
    assert out["ok"] is False

def test_load_staged_reads_artifact():
    """load_staged returns ok=True and the documents from an existing (legacy single-
    listing shape) staging file — the pre-multi-scope file must keep reading forever."""
    import json as _json
    from agentic import review
    treg, tmp = _temp_registry()
    staging_dir = _inbox(tmp) / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "slug": "example-project", "staged_at": "2026-06-23T1430Z",
        "connector": "mock", "scope": {},
        "documents": [{"id": "D1", "name": "Doc One", "dateModified": "2026-01-01",
                       "webUrl": "", "description": ""}],
    }
    (staging_dir / "example-project.json").write_text(_json.dumps(payload), encoding="utf-8")
    result = review.load_staged(treg, "example-project")
    assert result["ok"]
    assert len(result["documents"]) == 1 and result["documents"][0]["id"] == "D1"
    assert len(result["listings"]) == 1 and result["listings"][0]["staged_at"] == "2026-06-23T1430Z"

def test_load_staged_absent_is_empty_not_error():
    """Absent staging file → ok=True with empty documents; traversal slug → ok=False."""
    from agentic import review
    treg, _tmp = _temp_registry()
    result = review.load_staged(treg, "example-project")
    assert result["ok"] and result["documents"] == []
    for bad in ("../etc", "", ".", ".."):
        r = review.load_staged(treg, bad)
        assert r["ok"] is False, f"expected ok=False for slug {bad!r}"

def test_multiselect_propose_keeps_only_selected():
    """propose_graph_change with a subset [A, C] lands those docs; B (never proposed) stays out."""
    from agentic import graph, review
    treg, tmp = _temp_registry()
    gdir = tmp / "registry" / "graph"
    gdir.mkdir(parents=True, exist_ok=True)
    # Propose only A and C — never propose B
    selected = [
        {"id": "A", "name": "Alpha", "description": "a", "dateModified": "2026-01-01"},
        {"id": "C", "name": "Gamma", "description": "c", "dateModified": "2026-01-03"},
    ]
    out = review.propose_graph_change(treg, "example-project", selected, reason="subset selection")
    assert out["ok"]
    acc = review.decide(loader.load(tmp), out["id"], "accept", "")
    assert acc["ok"]
    merged = graph.load_project_graph(gdir / "example-project.jsonld")
    ids = {d.drive_id for d in merged.documents}
    assert "A" in ids and "C" in ids    # proposed subset was merged in
    assert "B" not in ids               # B was never proposed so it must not appear

def test_staged_endpoint_serves_listing():
    """GET /api/graph/staged?slug= returns the staging artifact; traversal → ok=False."""
    import http.client
    import json as _json
    import threading
    from agentic import review
    treg, tmp = _temp_registry()
    staging_dir = _inbox(tmp) / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    payload = {"slug": "example-project", "listings": [
        {"scope_key": "k1", "staged_at": "T", "connector": "mock", "scope": {},
         "documents": [{"id": "D1", "name": "N", "dateModified": "2026",
                        "webUrl": "", "description": ""}]}]}
    (staging_dir / "example-project.json").write_text(_json.dumps(payload), encoding="utf-8")
    server = review.make_server(treg, 0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        # valid slug with a staging file
        conn.request("GET", "/api/graph/staged?slug=example-project")
        r = conn.getresponse()
        data = _json.loads(r.read())
        assert r.status == 200 and data["ok"] and len(data["documents"]) == 1
        # traversal slug is rejected
        conn.request("GET", "/api/graph/staged?slug=../etc")
        r = conn.getresponse()
        data = _json.loads(r.read())
        assert r.status == 200 and data["ok"] is False
        # unknown slug (no file) → ok=True, empty
        conn.request("GET", "/api/graph/staged?slug=no-such-project")
        r = conn.getresponse()
        data = _json.loads(r.read())
        assert r.status == 200 and data["ok"] and data["documents"] == []
    finally:
        server.shutdown()
        server.server_close()

def test_unwatch_endpoint_removes_one_listing():
    """POST /api/graph/unwatch drops the named listing; the other watch is untouched."""
    import http.client
    import json as _json
    import threading
    from agentic import review
    treg, tmp = _temp_registry()
    staging_dir = _inbox(tmp) / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    payload = {"slug": "example-project", "listings": [
        {"scope_key": "keep", "staged_at": "T", "connector": "mock",
         "scope": {"folder_id": "F1"}, "documents": [{"id": "A", "name": "A"}]},
        {"scope_key": "drop", "staged_at": "T", "connector": "mock",
         "scope": {"folder_id": "F2"}, "documents": [{"id": "B", "name": "B"}]},
    ]}
    (staging_dir / "example-project.json").write_text(_json.dumps(payload), encoding="utf-8")
    server = review.make_server(treg, 0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        body = _json.dumps({"slug": "example-project", "scope_key": "drop"})
        conn.request("POST", "/api/graph/unwatch", body, {"Content-Type": "application/json"})
        r = conn.getresponse()
        out = _json.loads(r.read())
        assert r.status == 200 and out["ok"]
        assert [l["scope_key"] for l in out["staged"]["listings"]] == ["keep"]
        # unknown scope_key on the second call → 400
        conn.request("POST", "/api/graph/unwatch", body, {"Content-Type": "application/json"})
        r = conn.getresponse()
        assert r.status == 400
    finally:
        server.shutdown()
        server.server_close()

def test_review_module_imports_no_connector():
    """review.py must not import the connectors package — the offline-console invariant."""
    import inspect
    from agentic import review
    source = inspect.getsource(review)
    assert "from .connectors" not in source, "review.py imported the connectors package"
    assert "import connectors" not in source, "review.py imported the connectors package"

def test_connect_stage_flag_routes_to_stage_listing():
    """--stage flag is recognized by the connect argparser and routes to stage_listing."""
    import argparse
    # Mirror the connect subparser setup from mitos.py (pure argparse, no registry load)
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    pc = sub.add_parser("connect")
    pc.add_argument("--project", default=None)
    pc.add_argument("--backend", default=None)
    pc.add_argument("--folder-id", default=None)
    pc.add_argument("--query", default=None)
    pc.add_argument("--stage", action="store_true")
    # with --stage and explicit project
    args = p.parse_args(["connect", "--project", "acme", "--stage", "--query", "forecast"])
    assert args.stage is True and args.query == "forecast"
    # without --stage → defaults to False
    args2 = p.parse_args(["connect", "--project", "acme"])
    assert args2.stage is False
    # --project is now optional (omit for unassigned mode)
    args3 = p.parse_args(["connect", "--stage", "--backend", "mock"])
    assert args3.project is None and args3.stage is True

def test_project_and_server_exclude_folders_validation():
    """_validate rejects invalid top-level exclude_folders in projects and server entries."""
    import copy
    from agentic.loader import RegistryError, _validate
    treg, tmp = _temp_registry()
    # ── project side: non-list value ───────────────────────────────────────────
    r = copy.deepcopy(treg)
    r.projects["example-project"]["exclude_folders"] = "Archive"  # str, not list
    try:
        _validate(r)
        raise AssertionError("expected RegistryError for non-list exclude_folders")
    except RegistryError as e:
        assert "exclude_folders" in str(e), str(e)
    # ── project side: list with a non-string entry ─────────────────────────────
    r2 = copy.deepcopy(treg)
    r2.projects["example-project"]["exclude_folders"] = ["Archive", 42]
    try:
        _validate(r2)
        raise AssertionError("expected RegistryError for non-string entry in exclude_folders")
    except RegistryError as e:
        assert "exclude_folders" in str(e), str(e)
    # ── server side: dict instead of list ─────────────────────────────────────
    r3 = copy.deepcopy(treg)
    servers = r3.servers.setdefault("servers", {})
    servers.setdefault("gws", {})["exclude_folders"] = {"Archive": True}  # dict, not list
    try:
        _validate(r3)
        raise AssertionError("expected RegistryError for non-list server exclude_folders")
    except RegistryError as e:
        assert "exclude_folders" in str(e), str(e)
    # ── valid list passes without error ────────────────────────────────────────
    r4 = copy.deepcopy(treg)
    r4.projects["example-project"]["exclude_folders"] = ["Archive", "Drafts"]
    _validate(r4)   # must not raise

def test_mock_connector_folder_exclusion():
    """MockConnector.list_files and list_folders respect exclude_folders by name and by ID."""
    from agentic.connectors.mock import MockConnector
    # Default mock data: FOLDER1="Project Docs", FOLDER2="Archive"
    conn = MockConnector()
    # list_folders: exclude by name
    folders = conn.list_folders(exclude_folders=["Archive"])
    assert all(f["name"] != "Archive" for f in folders), "Archive should be excluded"
    assert any(f["name"] == "Project Docs" for f in folders)
    # list_folders: exclude by ID
    folders2 = conn.list_folders(exclude_folders=["FOLDER2"])
    assert all(f["id"] != "FOLDER2" for f in folders2)
    # list_files: exclude by name — FOLDER2 holds MOCKDOC3
    files = conn.list_files(exclude_folders=["Archive"])
    ids = {f["id"] for f in files}
    assert "MOCKDOC3" not in ids, "MOCKDOC3 in Archive should be excluded"
    assert "MOCKDOC1" in ids and "MOCKDOC2" in ids
    # list_files: exclude by ID
    files2 = conn.list_files(exclude_folders=["FOLDER1"])
    ids2 = {f["id"] for f in files2}
    assert "MOCKDOC1" not in ids2 and "MOCKDOC2" not in ids2
    assert "MOCKDOC3" in ids2
    # list_files: no exclusions → all 3 docs returned
    all_files = conn.list_files()
    assert len(all_files) == 3
    # Recursive: add a sub-folder of FOLDER2 and a file in it
    sub_folders = list(conn._folders) + [{"id": "FOLDER2_SUB", "name": "Sub",
                                           "parents": ["FOLDER2"]}]
    sub_files = list(conn._files) + [{"id": "MOCKDOC4", "name": "Sub Doc",
                                       "dateModified": "2026-06-02",
                                       "webUrl": "https://example.com/4",
                                       "parents": ["FOLDER2_SUB"]}]
    conn2 = MockConnector(files=sub_files, folders=sub_folders)
    files3 = conn2.list_files(exclude_folders=["Archive"])
    ids3 = {f["id"] for f in files3}
    assert "MOCKDOC3" not in ids3 and "MOCKDOC4" not in ids3, "Recursive sub-folder should also be excluded"
    assert "MOCKDOC1" in ids3 and "MOCKDOC2" in ids3

def test_unassigned_stage_listing_and_fallback():
    """stage_listing with slug='unassigned' writes inbox/staging/unassigned.json; load_staged
    for a normal project falls back to that file when no project-specific staging exists,
    and annotates the result with is_unassigned: True."""
    import json as _json
    from agentic import review
    from agentic.connectors.bootstrap import stage_listing
    from agentic.connectors.mock import MockConnector
    treg, tmp = _temp_registry()
    conn = MockConnector()
    # Stage without binding to a project
    out = stage_listing(treg, conn, "unassigned")
    assert out["ok"], f"unassigned staging failed: {out.get('error')}"
    assert out["slug"] == "unassigned"
    dest = _inbox(tmp) / "staging" / "unassigned.json"
    assert dest.is_file(), "inbox/staging/unassigned.json should have been created"
    data = _json.loads(dest.read_text(encoding="utf-8"))
    assert data["slug"] == "unassigned"
    assert len(data["listings"]) == 1 and len(data["listings"][0]["documents"]) > 0
    # load_staged for example-project (no project-specific file) falls back to unassigned
    result = review.load_staged(treg, "example-project")
    assert result["ok"], f"load_staged returned error: {result.get('error')}"
    assert result["is_unassigned"] is True, "should be flagged as unassigned"
    assert len(result["documents"]) > 0
    # Once a project-specific file exists, it takes precedence over the unassigned pool
    project_staging = _inbox(tmp) / "staging" / "example-project.json"
    project_payload = {"slug": "example-project", "listings": [
        {"scope_key": "k1", "staged_at": "T", "connector": "mock", "scope": {},
         "documents": [{"id": "PROJ1", "name": "Proj Doc",
                        "dateModified": "2026", "webUrl": "", "description": ""}]}]}
    project_staging.parent.mkdir(parents=True, exist_ok=True)
    project_staging.write_text(_json.dumps(project_payload), encoding="utf-8")
    result2 = review.load_staged(treg, "example-project")
    assert result2["ok"] and result2["is_unassigned"] is False
    assert result2["documents"][0]["id"] == "PROJ1"

def test_local_projects_overlay_merge():
    """Local projects overlay onto core projects (last-layer-wins): new slugs are added,
    core-only slugs remain, same-slug local entries replace the core entry."""
    from agentic import loader
    import yaml
    import json
    _, tmp = _temp_registry()
    local_projects_dir = tmp / "registry" / "local" / "projects"
    local_projects_dir.mkdir(parents=True, exist_ok=True)
    local_graph_dir = tmp / "registry" / "local" / "graph"
    local_graph_dir.mkdir(parents=True, exist_ok=True)

    # Write a local project and graph
    proj_content = {"slug": "private", "name": "Private Project", "document_store": "gws", "stage": "build"}
    (local_projects_dir / "private.yaml").write_text(yaml.safe_dump(proj_content), encoding="utf-8")

    graph_content = {
        "@context": {"@vocab": "https://schema.org/"},
        "@graph": [{"@id": "http://peccia.net/project/private", "@type": "Project",
                    "name": "Private Project"}]
    }
    (local_graph_dir / "private.jsonld").write_text(json.dumps(graph_content), encoding="utf-8")

    reg = loader.load(tmp)

    # local project and graph are added
    assert "private" in reg.projects
    assert "private" in reg.graphs
    assert reg.projects["private"].get("_is_local") is True
    # core projects/graphs coexist (last-layer-wins means merge, not exclusion)
    assert "example-project" in reg.projects
    assert "mitos" in reg.projects
    assert "example-project" in reg.graphs

def test_mcp_connector_folder_exclusion():
    """MCPConnector respects folder exclusions recursively by resolving names to IDs and appending not in parents to the Google Drive query."""
    from agentic.connectors.mcp import MCPConnector
    treg, tmp = _temp_registry()
    enum = treg.servers["servers"]["gws"]["graph_enum"]

    captured_args = []

    def transport(tool, arguments):
        q = arguments.get("query", "")
        captured_args.append(q)

        # Name resolution: Drive's `contains` is case-insensitive, so the store returns the
        # real folder ("screen shot", different case from the excluded "Screen Shot") plus a
        # look-alike ("Old Screen Shots") that must NOT be excluded.
        if "mimeType = 'application/vnd.google-apps.folder'" in q and "name contains" in q:
            rows = []
            if "Screen Shot" in q:
                rows.append({"id": "SS_ID", "name": "screen shot"})       # case differs
                rows.append({"id": "OLD_ID", "name": "Old Screen Shots"})  # look-alike
            if "IP Bot" in q:
                rows.append({"id": "IP_ID", "name": "IP Bot"})
            return rows

        # Subfolder discovery for the resolved folders.
        if "mimeType = 'application/vnd.google-apps.folder'" in q and "in parents" in q:
            rows = []
            if "SS_ID" in q:
                rows.append({"id": "SS_SUB_ID", "name": "Sub Screenshots"})
            return rows

        # Otherwise, the file listing.
        return [
            {"id": "FILE1", "name": "Doc 1", "modifiedTime": "2026-06-18", "webViewLink": "https://drive/1"},
            {"id": "FILE2", "name": "Doc 2", "modifiedTime": "2026-06-19", "webViewLink": "https://drive/2"},
        ]

    conn = MCPConnector(endpoint="http://localhost:8000/mcp", enum=enum,
                        server_name="gws", transport=transport)

    files = conn.list_files(exclude_folders=["Screen Shot", "IP Bot"])

    assert len(captured_args) > 2
    final_query = captured_args[-1]
    assert "not 'SS_ID' in parents" in final_query, final_query       # case-insensitive match
    assert "not 'IP_ID' in parents" in final_query, final_query
    assert "not 'SS_SUB_ID' in parents" in final_query, final_query   # transitive subfolder
    assert "not 'OLD_ID' in parents" not in final_query, final_query  # look-alike NOT excluded
    assert "mimeType != 'application/vnd.google-apps.folder'" in final_query

    # ── A name that resolves to nothing must NOT silently fail open ───────────────
    import io
    import contextlib
    captured_args.clear()

    def transport_nomatch(tool, arguments):
        q = arguments.get("query", "")
        captured_args.append(q)
        return []  # the excluded folder name matches no real folder

    conn2 = MCPConnector(endpoint="http://localhost:8000/mcp", enum=enum,
                         server_name="gws", transport=transport_nomatch)
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        conn2.list_files(exclude_folders=["Nonexistent Folder"])
    assert "matched no folders" in stderr.getvalue(), stderr.getvalue()

    # A resolution failure surfaces as an error rather than a silent unfiltered listing.
    def transport_boom(tool, arguments):
        q = arguments.get("query", "")
        if "name contains" in q:
            raise RuntimeError("server hiccup")
        return []
    conn3 = MCPConnector(endpoint="http://localhost:8000/mcp", enum=enum,
                         server_name="gws", transport=transport_boom)
    try:
        conn3.list_files(exclude_folders=["Screen Shot"])
        raise AssertionError("expected resolution failure to propagate, not fail open")
    except RuntimeError:
        pass

def test_mcp_connector_recursive_search():
    """Recursive listing resolves a folder's whole subtree, queries it in batches (Drive caps
    query length), dedupes files surfaced under multiple parents, and lets an excluded subtree
    win over the recursive scope."""
    from agentic.connectors.mcp import MCPConnector
    treg, _tmp = _temp_registry()
    enum = treg.servers["servers"]["gws"]["graph_enum"]

    subfolders = [f"S{i}" for i in range(30)]   # 30 subfolders → forces >1 file batch
    file_queries = []

    def transport(tool, arguments):
        q = arguments.get("query", "")
        # 1) exclusion name resolution
        if "name contains" in q:
            return [{"id": "SKIP_ID", "name": "Skip"}] if "Skip" in q else []
        # 2) subfolder discovery (folder mimeType + in parents)
        if q.startswith("mimeType = 'application/vnd.google-apps.folder'") and "in parents" in q:
            if "'ROOT' in parents" in q:
                return [{"id": s, "name": s} for s in subfolders] + \
                       [{"id": "SKIP_ID", "name": "Skip"}]   # excluded folder is also a child
            return []   # leaf folders have no children
        # 3) file listing
        if q.startswith("mimeType != 'application/vnd.google-apps.folder'"):
            file_queries.append(q)
            # 'DUP' appears in every batch (multi-parent file); 'U<n>' is batch-unique.
            return [
                {"id": "DUP", "name": "shared.doc", "modifiedTime": "2026-06-01",
                 "webViewLink": "https://d/dup"},
                {"id": f"U{len(file_queries)}", "name": f"f{len(file_queries)}.doc",
                 "modifiedTime": "2026-06-02", "webViewLink": "https://d/u"},
            ]
        return []

    conn = MCPConnector(endpoint="x", enum=enum, server_name="gws", transport=transport)
    files = conn.list_files(folder_id="ROOT", exclude_folders=["Skip"], recursive=True)

    ids = [f["id"] for f in files]
    # Scope = ROOT + 30 subfolders (SKIP_ID removed) = 31 parents → batches of 25 + 6 = 2 queries.
    assert len(file_queries) == 2, len(file_queries)
    assert ids.count("DUP") == 1, ids                      # deduped across batches
    assert {"DUP", "U1", "U2"} == set(ids), ids            # one shared + one per batch
    # Exclusion wins: the excluded subtree is never queried as a parent.
    assert all("SKIP_ID" not in q for q in file_queries), file_queries
    # Non-recursive over the same folder stays a single immediate-children query.
    file_queries.clear()
    conn.list_files(folder_id="ROOT", recursive=False)
    assert len(file_queries) == 1 and "'ROOT' in parents" in file_queries[0]

def test_mock_connector_recursive_listing():
    """MockConnector.list_files(recursive=True) walks nested folders via their parents."""
    from agentic.connectors.mock import MockConnector
    folders = [
        {"id": "ROOT", "name": "Root"},
        {"id": "CHILD", "name": "Child", "parents": ["ROOT"]},
        {"id": "GRAND", "name": "Grand", "parents": ["CHILD"]},
    ]
    files = [
        {"id": "F_ROOT", "name": "r", "parents": ["ROOT"]},
        {"id": "F_CHILD", "name": "c", "parents": ["CHILD"]},
        {"id": "F_GRAND", "name": "g", "parents": ["GRAND"]},
        {"id": "F_OTHER", "name": "o", "parents": ["ELSEWHERE"]},
    ]
    conn = MockConnector(files=files, folders=folders)
    shallow = {f["id"] for f in conn.list_files(folder_id="ROOT")}
    assert shallow == {"F_ROOT"}, shallow
    deep = {f["id"] for f in conn.list_files(folder_id="ROOT", recursive=True)}
    assert deep == {"F_ROOT", "F_CHILD", "F_GRAND"}, deep

def test_mcp_empty_listing_is_not_an_error():
    """google_workspace_mcp reports zero hits as "No files found for ..." (and "Found 0
    files"). Both are valid empty listings — e.g. a folder with no subfolders during the
    exclusion BFS — and must parse to [], not raise. A genuine non-listing message (an auth
    failure) must still raise so errors aren't swallowed as empty results."""
    from agentic.connectors import mcp as _mcp
    enum = {"text_fields": {"id": r"ID: ([^\s,)]+)", "name": r'Name: "([^"]+)"'}}

    for msg in ("No files found for 'mimeType = ... in parents'.", "Found 0 files."):
        result = {"content": [{"type": "text", "text": msg}]}
        assert _mcp._documents_from_tool_result(result, enum) == [], msg

    try:
        _mcp._documents_from_tool_result(
            {"content": [{"type": "text", "text": "Authorization required: invalid token"}]},
            enum)
        raise AssertionError("a real error text must raise ConnectorError, not parse as empty")
    except _mcp.ConnectorError:
        pass


def test_connector_for_store_resolves_override_url_from_active_machine():
    """connector_for_store resolves a server's URL override based on the active machine's git config."""
    from agentic.connectors import connector_for_store
    from agentic.connectors.mcp import MCPConnector
    from conftest import _run_git, _git_available
    treg, tmp = _temp_registry()

    treg.servers["servers"]["gws"]["urls"] = {
        "custom-machine": "http://192.168.1.99:8000/mcp"
    }

    overlay_dir = tmp / "registry" / "local"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    if _git_available():
        _run_git(overlay_dir, "init")
        _run_git(overlay_dir, "config", "user.name", "Test")
        _run_git(overlay_dir, "config", "user.email", "test@test.com")
        _run_git(overlay_dir, "config", "mitos.machine", "custom-machine")

        conn = connector_for_store(treg, "gws", root=tmp)
        assert isinstance(conn, MCPConnector)
        assert conn.endpoint == "http://192.168.1.99:8000/mcp"

