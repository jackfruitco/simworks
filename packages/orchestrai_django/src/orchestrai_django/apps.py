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
import sys
from typing import Any

from django.apps import AppConfig
from django.conf import settings as dj_settings

from orchestrai._state import set_current_app
from orchestrai.tracing import service_span_sync

from orchestrai_django.integration import DjangoAdapter

logger = logging.getLogger(__name__)

_startup_lock = threading.RLock()
_started = False

DEFAULT_SKIP_READY_COMMANDS = {"migrate", "makemigrations", "collectstatic", "shell"}


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return default
    return bool(value)


def _active_management_command(argv: list[str]) -> str | None:
    if len(argv) < 2:
        return None
    runner = argv[0]
    if not runner.endswith("manage.py") and "django-admin" not in runner:
        return None
    command = argv[1]
    if command.startswith("-"):
        return None
    return command


def _commands_to_skip() -> set[str]:
    configured = getattr(dj_settings, "ORCHESTRAI_SKIP_READY_COMMANDS", None)
    if configured is None:
        configured = getattr(dj_settings, "ORCA_SKIP_READY_COMMANDS", None)
    if configured is None:
        configured = os.environ.get("ORCHESTRAI_SKIP_READY_COMMANDS")
    if configured is None:
        configured = os.environ.get("ORCA_SKIP_READY_COMMANDS")

    if configured is None:
        return set(DEFAULT_SKIP_READY_COMMANDS)

    if isinstance(configured, str):
        configured = [p.strip() for p in configured.split(",") if p.strip()]
    if isinstance(configured, (list, tuple, set)):
        return {str(item) for item in configured if str(item)}
    return set(DEFAULT_SKIP_READY_COMMANDS)


def _autostart_enabled() -> bool:
    if os.environ.get("DJANGO_SKIP_READY") == "1":
        return False

    env_override = os.environ.get("ORCHESTRAI_AUTOSTART") or os.environ.get("ORCA_AUTOSTART")
    if env_override is not None:
        return _coerce_bool(env_override)

    return _coerce_bool(getattr(dj_settings, "ORCA_AUTOSTART", True))


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
    """Start an OrchestrAI application using the current lifecycle."""

    if not hasattr(app, "ensure_ready") or not callable(getattr(app, "ensure_ready")):
        raise TypeError("ORCA_ENTRYPOINT must resolve to an OrchestrAI instance with .ensure_ready()")

    adapter = DjangoAdapter(app)
    adapter.configure()
    adapter.ensure_ready()


def _register_current_app(app: Any) -> None:
    """Persist the resolved app on settings and the context var."""

    try:
        setattr(dj_settings, "_ORCA_APP", app)
        setattr(dj_settings, "_ORCHESTRAI_APP", app)
    except Exception:
        logger.debug("Failed to set django settings _ORCA_APP", exc_info=True)

    try:
        set_current_app(app)
    except Exception:
        logger.debug("Failed to set current OrchestrAI app", exc_info=True)


class OrchestrAIDjangoConfig(AppConfig):
    """Django AppConfig for OrchestrAI Django."""

    name = "orchestrai_django"

    def ready(self) -> None:
        global _started

        # Allow opt-out for special cases (tests, one-off management commands, etc.)
        if not _autostart_enabled():
            return

        command = _active_management_command(sys.argv)
        if command and command in _commands_to_skip():
            logger.debug("Skipping OrchestrAI autostart for management command %s", command)
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
                    _register_current_app(result)
                    _maybe_start(result)
                    logger.info("OrchestrAI autostart complete via callable entrypoint")
                    return

                # Callable did initialization itself (no returned instance)
                logger.info("OrchestrAI autostart complete via callable entrypoint (no return value)")
                return

            # If it's an object (e.g. an app instance), register it and try to ready it.
            _register_current_app(target)
            _maybe_start(target)
            logger.info("OrchestrAI autostart complete via object entrypoint")
