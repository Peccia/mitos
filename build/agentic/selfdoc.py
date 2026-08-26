"""Keep the repo's own `AGENTS.md` in sync with the registry partial it is compiled from.

`AGENTS.md` is this project's build artifact like any other, but unlike every other one it
belongs to the REPO rather than to a machine: a contributor's checkout lives wherever they
cloned it, so no machine profile's `local_path` reliably points at it and `deploy` can never
be what keeps it fresh. `cmd_compile` calls `rewrite()` instead — compile is step 1 of
Verifying changes and the first thing CI runs, so the artifact cannot silently rot. CI
proves it with `git diff --exit-code -- AGENTS.md` after compiling: a stale commit fails
because compile CHANGED the file, which no amount of forgetting can fool.

The source is `context/projects/mitos-repo.md`, NOT the `mitos` project's node partial
(`context/projects/mitos.md`). They were one file until the node — deployed to the project
folder that HOLDS this checkout — ended up repeating all 57KB of builder prose that this
artifact already carries, so both loaded on every session started inside the repo. The node
now answers "which checkout, and what is this project for"; this file answers "how do I
change code in here". Nothing else consumes `mitos-repo.md`: no manifest binds it, so the
loader parses it as a partial and deploys it nowhere.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "registry" / "context" / "projects" / "mitos-repo.md"
ARTIFACT = REPO_ROOT / "AGENTS.md"
MARKER = "# Mitos — Builder Context"


def _rendered() -> str | None:
    """The artifact as it should be: whatever the deployed persona header put above the
    marker, then the registry partial's body. None when either file is missing or the
    marker isn't there (a fresh clone mid-edit — never a reason to crash a compile)."""
    if not (SOURCE.is_file() and ARTIFACT.is_file()):
        return None
    live = ARTIFACT.read_text(encoding="utf-8")
    idx = live.find(MARKER)
    if idx == -1:
        return None
    src = SOURCE.read_text(encoding="utf-8")
    m = re.match(r"^---\n.*?\n---\n?(.*)", src, re.DOTALL)
    return live[:idx] + (m.group(1) if m else src).strip() + "\n"


def is_current() -> bool:
    """Does the committed artifact already match the registry source?"""
    new = _rendered()
    return new is None or new == ARTIFACT.read_text(encoding="utf-8")


def rewrite(reg_root: Path | None = None) -> bool:
    """Regenerate the artifact; True when it changed.

    `reg_root` is the registry being compiled — a no-op unless it IS this repo, so the
    test suite compiling a throwaway registry copy can never rewrite the real artifact
    from a temp fixture's `mitos.md`.
    """
    if reg_root is not None and Path(reg_root).resolve() != REPO_ROOT:
        return False
    new = _rendered()
    if new is None or new == ARTIFACT.read_text(encoding="utf-8"):
        return False
    ARTIFACT.write_text(new, encoding="utf-8", newline="\n")
    return True
