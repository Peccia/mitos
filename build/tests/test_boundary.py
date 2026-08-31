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
