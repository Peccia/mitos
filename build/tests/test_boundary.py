"""Boundary guard: Mitos never depends on Mitos-Agent (architecture invariant — Mitos works
alone, offline, whether or not Mitos-Agent exists). Static analysis only: walks every module
under build/ and fails on a real `import`/`from ... import` of mitos_agent. Identifiers and
string literals that merely name "mitos_agent" as a deploy target are untouched by this check.
"""
from __future__ import annotations

import ast
from pathlib import Path

from conftest import REPO_ROOT

BUILD_ROOT = REPO_ROOT / "build"


def _imports_mitos_agent(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "mitos_agent" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] == "mitos_agent":
                return True
    return False


def test_build_never_imports_mitos_agent():
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in BUILD_ROOT.rglob("*.py")
        if ".venv" not in path.parts and "__pycache__" not in path.parts
        and _imports_mitos_agent(path)
    ]
    assert not offenders, f"build/ must never import mitos_agent; found in: {offenders}"


def test_core_never_names_mitos_agent():
    """TEST-12: scans build/agentic/, targets/, machines/ and registry/
    (excluding registry/local/) for mitos[-_]agent, with an explicit allowlist
    (the pass-through fixture, the M5 golden fixture).
    Also asserts docs/decisions/ does not exist and no doc links to it.
    """
    import re

    pattern = re.compile(r"mitos[-_ ]?agent", re.IGNORECASE)
    # Every tracked file, except the changelog's history and this file, which has to
    # spell the pattern it scans for. Add a legitimate future file here, with a comment.
    exempt = {"CHANGELOG.md", "build/tests/test_boundary.py"}
    import subprocess
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split("\0")

    offenders = []
    for rel in filter(None, tracked):
        if rel in exempt:
            continue
        p = REPO_ROOT / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8-sig", errors="ignore")
        except Exception:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{rel}:{line_no}: {line.strip()}")

    assert not offenders, (
        f"Core Mitos must never name mitos_agent/mitos-agent; found {len(offenders)} occurrence(s):\n"
        + "\n".join(offenders)
    )

    # Asserts docs/decisions/ does not exist
    decisions_dir = REPO_ROOT / "docs" / "decisions"
    assert not decisions_dir.exists(), f"docs/decisions/ must not exist: {decisions_dir}"

    # Asserts no doc links to docs/decisions/ or decisions/
    link_pattern = re.compile(r"(?:docs/)?decisions/", re.IGNORECASE)
    doc_link_offenders = []
    docs_dir = REPO_ROOT / "docs"
    for p in docs_dir.rglob("*.md"):
        text = p.read_text(encoding="utf-8-sig", errors="ignore")
        for line_no, line in enumerate(text.splitlines(), 1):
            if link_pattern.search(line):
                doc_link_offenders.append(f"{p.relative_to(REPO_ROOT)}:{line_no}: {line.strip()}")

    assert not doc_link_offenders, (
        f"Docs must not reference docs/decisions; found {len(doc_link_offenders)} link(s):\n"
        + "\n".join(doc_link_offenders)
    )


def test_loaded_core_modules_bind_no_mitos_agent_name():
    """A name assembled at runtime (e.g. `globals()["a" + "b"] = fn`) is invisible to the
    text scan; this catches it however it is spelled."""
    import importlib
    import pkgutil
    import re

    import agentic

    pattern = re.compile(r"mitos[-_ ]?agent", re.IGNORECASE)
    offenders = []
    for info in pkgutil.walk_packages(agentic.__path__, "agentic."):
        try:
            module = importlib.import_module(info.name)
        except ImportError:
            continue  # optional backend dependency not installed
        offenders += [f"{info.name}.{n}" for n in dir(module) if pattern.search(n)]
    assert not offenders, f"core modules must not bind a Mitos Agent name: {offenders}"


def test_console_source_scan_no_retired_lanes():
    """Console source scan: no flag predicate (e.g. hasMitosAgent, _overlay_has_mitos_agent),
    no + ORG, no deliverables group.
    """
    app_js = REPO_ROOT / "build" / "review_ui" / "app.js"
    assert app_js.exists(), f"app.js missing: {app_js}"
    src = app_js.read_text(encoding="utf-8")

    assert "hasMitosAgent" not in src, "app.js must not contain hasMitosAgent flag predicate"
    assert "+ ORG" not in src, "app.js must not contain + ORG"
    assert "deliverables" not in src.lower(), "app.js must not contain deliverables group"
