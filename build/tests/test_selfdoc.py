"""The repo's own AGENTS.md is a build artifact no machine's `deploy` regenerates.

`cmd_compile` rewrites it and CI proves it with `git diff --exit-code`, so this is the
early-warning copy: a test run alone (without a compile) still says so.
"""
from __future__ import annotations

import re
from pathlib import Path

from agentic import selfdoc

REPO_ROOT = Path(__file__).resolve().parents[2]
# Verbs build/mitos.py owns. The shims route everything else to build/compile.py, so this
# is the ONE list that has to stay in sync; a new interactive verb must be added to both.
_VERB_LINE = {
    "mitos": re.compile(r'^MITOS_INTERACTIVE_VERBS="([^"]*)"', re.M),
    "mitos.cmd": re.compile(r'^set "MITOS_INTERACTIVE_VERBS=([^"]*)"', re.M),
}


def test_repo_agents_md_matches_registry_source():
    assert selfdoc.is_current(), (
        "AGENTS.md is stale — run `python build/compile.py compile` and commit it.")


def test_rewrite_refuses_a_registry_that_isnt_this_repo():
    """The suite compiles throwaway registry copies; none of them may ever rewrite the
    real artifact from a temp fixture's mitos.md."""
    assert selfdoc.rewrite(Path(__file__).parent) is False


def _interactive_verbs(shim: str) -> list[str]:
    text = (REPO_ROOT / shim).read_text(encoding="utf-8")
    match = _VERB_LINE[shim].search(text)
    assert match, f"{shim}: MITOS_INTERACTIVE_VERBS line not found"
    return sorted(match.group(1).split())


def test_cli_shim_verbs_match_mitos_py():
    """A verb added to build/mitos.py but not the shims would silently route to
    build/compile.py, which answers `invalid choice` instead of running it."""
    source = (REPO_ROOT / "build" / "mitos.py").read_text(encoding="utf-8")
    registered = sorted(set(re.findall(r'sub\.add_parser\(\s*"([a-z-]+)"', source)))
    assert registered, "no subparsers found in build/mitos.py"
    for shim in _VERB_LINE:
        assert _interactive_verbs(shim) == registered, (
            f"{shim} routes {_interactive_verbs(shim)} to build/mitos.py, "
            f"but it registers {registered}")


def test_cli_shims_agree_with_each_other():
    assert _interactive_verbs("mitos") == _interactive_verbs("mitos.cmd")
