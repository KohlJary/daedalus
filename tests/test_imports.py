"""Every module must import on every platform (fcntl, for one, is Unix-only)."""

import importlib
import pkgutil

import pytest

import daedalus


def all_modules():
    for info in pkgutil.walk_packages(daedalus.__path__, prefix="daedalus."):
        yield info.name


@pytest.mark.parametrize("name", list(all_modules()))
def test_module_imports(name):
    try:
        importlib.import_module(name)
    except ImportError as e:
        # Optional extras (e.g. the 'sdk' extra) may be missing; a stdlib module never should be
        if e.name and e.name.split(".")[0] in {"claude_agent_sdk"}:
            pytest.skip(f"optional dependency {e.name} not installed")
        raise
