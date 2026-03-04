from __future__ import annotations

from orchestrai import OrchestrAI

__all__ = ["OrchestrAI", "orca"]


def __getattr__(name: str):
    if name == "orca":
        from orchestrai_django.decorators import orca
        return orca
    raise AttributeError(f"module 'orchestrai_django' has no attribute {name!r}")
