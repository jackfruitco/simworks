"""Minimal, import-safe OrchestrAI public API."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from ._state import current_app, get_current_app
from .app import OrchestrAI

try:  # pragma: no cover - metadata not available in tests
    __version__ = version("orchestrai")
except PackageNotFoundError:  # pragma: no cover - fallback for editable installs
    __version__ = "0.0.0"

__all__ = ["OrchestrAI", "current_app", "get_current_app", "__version__", "orca"]


def __getattr__(name: str):
    if name == "orca":
        from orchestrai.decorators import orca
        return orca
    raise AttributeError(f"module 'orchestrai' has no attribute {name!r}")
