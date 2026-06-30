"""Canonical stdlib test runner — no pytest required.

`python build/tests/test_compiler.py` runs the whole compiler suite: it discovers every
sibling `test_*.py` module, runs each `test_*` function, and reports pass/fail with a final
count (exit 1 on any failure). pytest also works (`pip install -e .[dev]` then
`pytest build/tests/`) via [tool.pytest.ini_options], but it is optional — this runner keeps
the suite runnable from a bare `requirements.txt` install.
"""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))          # so conftest + the test modules import by name
sys.path.insert(0, str(HERE.parent))   # build/ — for the `agentic` package

import conftest  # noqa: E402  (sets up the agentic import path and loads the shared registry)


def _modules() -> list[str]:
    """Every test_*.py beside this file, except this runner itself."""
    return sorted(p.stem for p in HERE.glob("test_*.py") if p.stem != "test_compiler")


def main() -> int:
    total = failed = 0
    for mod_name in _modules():
        mod = importlib.import_module(mod_name)
        for name in sorted(dir(mod)):
            fn = getattr(mod, name)
            if not (name.startswith("test_") and callable(fn)):
                continue
            total += 1
            try:
                fn()
            except AssertionError as e:
                failed += 1
                print(f"FAIL  {mod_name}.{name}: {e}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"ERROR {mod_name}.{name}: {type(e).__name__}: {e}")
                traceback.print_exc()
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
