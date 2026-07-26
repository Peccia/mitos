"""Acceptance tests for the stdlib runner's fixture support (`test_compiler.py`).

The suite runs under BOTH `python build/tests/test_compiler.py` (CI, no pytest) and
`pytest build/tests/`. A test authored against a pytest fixture used to pass locally and
fail in CI with `TypeError: ... missing 1 required positional argument`; the runner now
resolves fixture parameters through `conftest.make_fixture`. These tests pin that contract
so the divergence cannot come back silently.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import conftest

HERE = Path(__file__).resolve().parent


def test_every_declared_fixture_in_the_suite_is_supported():
    """Every fixture parameter any test declares must be one the runner can supply —
    this is the check that would have caught the three `monkeypatch` tests at authoring
    time instead of in CI."""
    import importlib
    unsupported: list[str] = []
    for path in sorted(HERE.glob("test_*.py")):
        if path.stem == "test_compiler":
            continue
        mod = importlib.import_module(path.stem)
        for name in dir(mod):
            fn = getattr(mod, name)
            if not (name.startswith("test_") and callable(fn)
                    and getattr(fn, "__module__", "") == mod.__name__):
                continue
            for pname, param in inspect.signature(fn).parameters.items():
                if param.default is not inspect.Parameter.empty:
                    continue          # not a fixture under pytest either
                try:
                    _, teardown = conftest.make_fixture(pname)
                except LookupError:
                    unsupported.append(f"{path.stem}.{name}({pname})")
                else:
                    teardown()
    assert not unsupported, f"unsupported fixtures: {unsupported}"


def test_monkeypatch_shim_sets_and_undoes(monkeypatch):
    """Also proves the runner actually INJECTS the fixture — the test signature itself is
    the assertion under the stdlib runner."""
    import os
    holder = type("H", (), {"value": "orig"})
    mapping = {"keep": 1}

    monkeypatch.setattr(holder, "value", "patched")
    monkeypatch.setitem(mapping, "keep", 2)
    monkeypatch.setitem(mapping, "added", 3)
    monkeypatch.setenv("AE_RUNNER_PROBE", "yes")
    assert holder.value == "patched"
    assert mapping == {"keep": 2, "added": 3}
    assert os.environ["AE_RUNNER_PROBE"] == "yes"

    monkeypatch.undo()
    assert holder.value == "orig"
    assert mapping == {"keep": 1}
    assert "AE_RUNNER_PROBE" not in os.environ


def test_unsupported_fixture_fails_loudly():
    """An unknown fixture name must raise, never hand a test a silent `None`."""
    try:
        conftest.make_fixture("capsys")
    except LookupError as e:
        assert "capsys" in str(e) and "make_fixture" in str(e)
    else:
        raise AssertionError("expected LookupError for an unsupported fixture")
