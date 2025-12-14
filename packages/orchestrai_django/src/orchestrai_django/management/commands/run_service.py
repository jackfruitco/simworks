# run_service.py
"""Management command to execute an OrchestrAI service via the new API."""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from orchestrai import get_current_app

logger = logging.getLogger(__name__)


def _import_object(path: str) -> Any:
    if ":" in path:
        module_name, attr = path.split(":", 1)
        module = importlib.import_module(module_name)
        return getattr(module, attr)

    if "." in path:
        module_name, _, attr = path.rpartition(".")
        if not module_name:
            raise ImportError(f"Could not import object from path: {path}")
        module = importlib.import_module(module_name)
        return getattr(module, attr)

    raise ImportError(f"Import path must include a module and attribute: {path!r}")


class Command(BaseCommand):
    help = "Execute an OrchestrAI service via services.start/schedule (and async variants)."

    def add_arguments(self, parser):
        parser.add_argument(
            "service",
            type=str,
            help="Service registry name or import path (module:attr or module.attr).",
        )
        parser.add_argument(
            "-c",
            "--context",
            dest="context",
            type=str,
            default="{}",
            help="JSON-encoded context dict passed to the service (e.g. '{\"simulation_id\": 1}').",
        )
        parser.add_argument(
            "--mode",
            choices=("start", "schedule", "astart", "aschedule"),
            default="start",
            help="Execution method: start/schedule (sync) or astart/aschedule (async).",
        )
        parser.add_argument(
            "--log-level",
            dest="log_level",
            type=str,
            default="INFO",
            help="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL.",
        )

    def handle(self, *args, **options):
        raw_level = options.get("log_level", "INFO").upper()
        level = getattr(logging, raw_level, logging.INFO)
        logging.basicConfig(level=level)

        app = get_current_app()
        if app is None:
            raise CommandError(
                "No OrchestrAI app is active; ensure ORCA_ENTRYPOINT is configured and autostarted."
            )

        context_raw: str = options.get("context", "{}")
        try:
            context: dict[str, Any] = json.loads(context_raw) if context_raw else {}
            if not isinstance(context, dict):
                raise TypeError(f"context must be a JSON object, got {type(context).__name__}")
        except Exception as exc:  # pragma: no cover - defensive parse guard
            raise CommandError(f"Invalid --context JSON: {exc}") from exc

        service_spec: str = options["service"]
        try:
            service_obj = self._resolve_service(app, service_spec)
        except Exception as exc:
            raise CommandError(f"Could not resolve service {service_spec!r}: {exc}") from exc

        mode: str = options.get("mode", "start")
        runner = getattr(app.services, mode)

        try:
            if mode in ("astart", "aschedule"):
                result = asyncio.run(runner(service_obj, **context))
            else:
                result = runner(service_obj, **context)
        except Exception as exc:
            raise CommandError(f"Failed to execute service {service_spec!r} via {mode}: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Service {service_spec!r} executed successfully via app.services.{mode}."
            )
        )

        if result is None:
            return

        try:
            rendered = json.dumps(result, indent=2, default=str)
        except TypeError:
            rendered = repr(result)
        self.stdout.write(rendered)

    def _resolve_service(self, app, spec: str):
        registry = app.services.all()
        if spec in registry:
            return app.services.get(spec)

        # Attempt to import a fully qualified object path.
        return _import_object(spec)