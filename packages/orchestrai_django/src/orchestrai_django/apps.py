# orchestrai_django/apps.py


"""
orchestrai_django.apps
======================

Django integration for OrchestrAI.

Responsibilities
----------------
- Optionally autostart an OrchestrAI application from a project-defined entrypoint.
- Keep startup idempotent and safe during Django app registry finalization.

Settings
--------
- ORCA_AUTOSTART (bool, default True): enable/disable autostart in AppConfig.ready().
- ORCA_ENTRYPOINT (str): import path to the project entrypoint.

  Supported forms:
    - "pkg.module:get_orca"  (callable)
    - "pkg.module:app"       (object)
    - "pkg.module.get_orca"  (callable)

  The callable may return an OrchestrAI instance, or may perform initialization itself.
"""

import importlib
import logging
import os
import threading
from typing import Any

from django.apps import AppConfig
from django.conf import settings as dj_settings

from orchestrai.tracing import service_span_sync

logger = logging.getLogger(__name__)

_startup_lock = threading.RLock()
_started = False


def _import_from_path(path: str) -> Any:
    """Import and return an object from `module:attr` or `module.attr` paths."""
    if ":" in path:
        mod_path, attr = path.split(":", 1)
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr)

    parts = path.split(".")
    for i in range(len(parts), 0, -1):
        mod_path = ".".join(parts[:i])
        try:
            mod = importlib.import_module(mod_path)
        except Exception:
            continue
        obj: Any = mod
        for a in parts[i:]:
            obj = getattr(obj, a)
        return obj

    raise ImportError(f"Could not import ORCA_ENTRYPOINT: {path}")


def _maybe_start(app: Any) -> None:
    """Best-effort start hook for OrchestrAI applications."""

    if hasattr(app, "start") and callable(getattr(app, "start")):
        app.start()
        return

    # Fallbacks for any partially migrated apps
    if hasattr(app, "discover") and callable(getattr(app, "discover")):
        app.discover()
    if hasattr(app, "finalize") and callable(getattr(app, "finalize")):
        app.finalize()


class OrchestrAIDjangoConfig(AppConfig):
    """Django AppConfig for OrchestrAI Django."""

    name = "orchestrai_django"

    def ready(self) -> None:
        global _started

        # Allow opt-out for special cases (tests, one-off management commands, etc.)
        if os.environ.get("DJANGO_SKIP_READY") == "1":
            return

        if not getattr(dj_settings, "ORCA_AUTOSTART", True):
            logger.debug("ORCA_AUTOSTART is False; skipping OrchestrAI autostart")
            return

        entrypoint = getattr(dj_settings, "ORCA_ENTRYPOINT", None) or os.environ.get("ORCA_ENTRYPOINT")
        if not entrypoint:
            logger.debug("ORCA_ENTRYPOINT not set; skipping OrchestrAI autostart")
            return

        with _startup_lock:
            if _started:
                return
            _started = True

        with service_span_sync("orchestrai.django.autostart"):
            target = _import_from_path(entrypoint)

            # If the entrypoint is callable (recommended), call it.
            if callable(target):
                result = target()

                # If the callable returned an app instance, register it as the default.
                if result is not None:
                    try:
                        setattr(dj_settings, "_ORCA_APP", result)
                    except Exception:
                        logger.debug("Failed to set django settings _ORCA_APP", exc_info=True)

                    _maybe_start(result)
                    logger.info("OrchestrAI autostart complete via callable entrypoint")
                    return

                # Callable did initialization itself (no returned instance)
                logger.info("OrchestrAI autostart complete via callable entrypoint (no return value)")
                return

            # If it's an object (e.g. an app instance), register it and try to ready it.
            try:
                setattr(dj_settings, "_ORCA_APP", target)
            except Exception:
                logger.debug("Failed to set django settings _ORCA_APP", exc_info=True)

            _maybe_start(target)
            logger.info("OrchestrAI autostart complete via object entrypoint")
