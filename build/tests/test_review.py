"""Tests for the operator console backend (build/agentic/review.py)."""
from __future__ import annotations

import copy

from conftest import reg, _temp_registry


def test_graph_index_lists_local_projects_regardless_of_drive_key():
    """graph_index must list every local project — presence or absence of 'drive' is irrelevant.

    Regression guard for the bug where `drive: {}` (falsy dict) hid a project from the
    Knowledge Graph sidebar even when its staging file existed."""
    from agentic.review import graph_index

    rig = copy.deepcopy(reg)
    # project with no drive key at all — must appear
    rig.projects["proj-no-drive"] = {
        "name": "No Drive", "slug": "proj-no-drive", "_is_local": True,
        "local_path": {}, "agents": [], "context": {},
        "document_store": "gws",
    }
    # project with empty drive dict — the original bug trigger
    rig.projects["proj-empty-drive"] = {
        "name": "Empty Drive", "slug": "proj-empty-drive", "_is_local": True,
        "local_path": {}, "agents": [], "context": {},
        "document_store": "gws",
        "drive": {},
    }
    # project with a populated drive block — must continue to appear
    rig.projects["proj-full-drive"] = {
        "name": "Full Drive", "slug": "proj-full-drive", "_is_local": True,
        "local_path": {}, "agents": [], "context": {},
        "document_store": "gws",
        "drive": {"root_folder": "1abc"},
    }

    result = graph_index(rig)
    slugs = {r["slug"] for r in result}

    assert "proj-no-drive" in slugs, "project with no drive key must appear in graph_index"
    assert "proj-empty-drive" in slugs, "project with drive: {} must appear in graph_index"
    assert "proj-full-drive" in slugs, "project with populated drive block must appear in graph_index"


def test_graph_index_core_projects_step_aside_when_local_overlay_present():
    """When any local project exists the core (non-local) projects are hidden — same convention
    as the example-machine guard in commands.py."""
    from agentic.review import graph_index

    rig = copy.deepcopy(reg)
    # inject exactly one local project
    rig.projects["my-local"] = {
        "name": "My Local", "slug": "my-local", "_is_local": True,
        "local_path": {}, "agents": [], "context": {},
    }

    result = graph_index(rig)
    slugs = {r["slug"] for r in result}

    assert "my-local" in slugs
    # core projects (no _is_local flag) must not appear
    for slug, proj in rig.projects.items():
        if not proj.get("_is_local"):
            assert slug not in slugs, f"core project {slug!r} must step aside when local overlay present"


def test_graph_index_shows_all_when_no_local_overlay():
    """Without any local projects every project appears."""
    from agentic.review import graph_index

    # load a fresh registry with ignore_local=True (conftest.reg does this already)
    result = graph_index(reg)
    slugs = {r["slug"] for r in result}
    # at minimum the core mitos project must be visible
    assert "mitos" in slugs
