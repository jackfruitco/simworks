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


def _maybe_ensure_ready(app: Any) -> None:
    """Best-effort 'ensure ready' call, preferring Django discovery when available."""
    # If we're running inside Django, prefer Django-native autodiscovery across INSTALLED_APPS.
    try:
        from django.conf import settings as _dj_settings
        from orchestrai_django.integration import django_autodiscover as _django_autodiscover
    except Exception:
        _dj_settings = None
        _django_autodiscover = None

    if _django_autodiscover is not None and callable(_django_autodiscover):
        # 1) Configure providers/clients first (idempotent inside app)
        if hasattr(app, "autoconfigure_orca") and callable(getattr(app, "autoconfigure_orca")):
            app.autoconfigure_orca()
        elif hasattr(app, "ensure_configured") and callable(getattr(app, "ensure_configured")):
            app.ensure_configured()

        # 2) Django-native discovery (preferred in Django deployments)
        module_names = None
        if _dj_settings is not None:
            module_names = getattr(_dj_settings, "ORCA_DISCOVERY_MODULES", None)
        _django_autodiscover(app, module_names=list(module_names) if module_names else None)

        # 3) Prevent core discovery from running again (best-effort; internal flag)
        if hasattr(app, "_discovered"):
            try:
                setattr(app, "_discovered", True)
            except Exception:
                logger.debug("Failed to set app._discovered=True", exc_info=True)

        # 4) Run any remaining readiness logic without re-running discovery
        if hasattr(app, "ensure_ready") and callable(getattr(app, "ensure_ready")):
            app.ensure_ready()
        return

    # Non-Django fallback: use core convenience if present
    if hasattr(app, "ensure_ready") and callable(getattr(app, "ensure_ready")):
        app.ensure_ready()
        return

    # Legacy / transitional fallbacks
    if hasattr(app, "ensure_configured") and callable(getattr(app, "ensure_configured")):
        app.ensure_configured()
    if hasattr(app, "autoconfigure_orca") and callable(getattr(app, "autoconfigure_orca")):
        app.autoconfigure_orca()
    if hasattr(app, "autodiscover_components") and callable(getattr(app, "autodiscover_components")):
        app.autodiscover_components()


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

                    _maybe_ensure_ready(result)
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

            _maybe_ensure_ready(target)
            logger.info("OrchestrAI autostart complete via object entrypoint")
