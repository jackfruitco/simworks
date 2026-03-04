"""Ensure removed compatibility shims are not reintroduced."""

from __future__ import annotations

import importlib

import pytest

from orchestrai.fixups import base as fixups_base


def test_orchestrai_shared_module_is_removed():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("orchestrai.shared")


def test_base_fixup_symbol_is_removed():
    assert not hasattr(fixups_base, "BaseFixup")
