"""The repo's own AGENTS.md is a build artifact no machine's `deploy` regenerates.

`cmd_compile` rewrites it and CI proves it with `git diff --exit-code`, so this is the
early-warning copy: a test run alone (without a compile) still says so.
"""
from __future__ import annotations

from pathlib import Path

from agentic import selfdoc


def test_repo_agents_md_matches_registry_source():
    assert selfdoc.is_current(), (
        "AGENTS.md is stale — run `python build/compile.py compile` and commit it.")


def test_rewrite_refuses_a_registry_that_isnt_this_repo():
    """The suite compiles throwaway registry copies; none of them may ever rewrite the
    real artifact from a temp fixture's mitos.md."""
    assert selfdoc.rewrite(Path(__file__).parent) is False
