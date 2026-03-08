"""Django integration package for OrchestrAI.

Keep package import side-effect free so Django can safely resolve AppConfig
during `INSTALLED_APPS` loading.
"""

from __future__ import annotations


def __getattr__(name: str):
    if name == "orca":
        from orchestrai_django.decorators import orca

        return orca
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__: list[str] = ["orca"]
