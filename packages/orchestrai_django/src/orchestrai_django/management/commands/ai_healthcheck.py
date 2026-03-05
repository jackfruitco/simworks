# orchestrai_django/management/commands/ai_healthcheck.py


"""
Django management command to run OrchestrAI healthchecks.

Usage:
    python manage.py ai_healthcheck
    python manage.py ai_healthcheck --json           # CI-friendly JSON output (includes http_status)

This command runs after Django setup and triggers
`orchestrai_django.health.healthcheck_orchestrai()` to verify that
OrchestrAI is properly configured and ready. It logs health results and
exits non-zero on failures.

Intended for CI/CD and container boot probes.
"""

import json
import logging
import sys

from django.core.management.base import BaseCommand

from orchestrai import get_current_app
from orchestrai.utils.json import json_default
from orchestrai_django.health import healthcheck_orchestrai

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run OrchestrAI healthchecks and report results."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output results as JSON for CI consumption.",
        )

    def handle(self, *args, **options):
        as_json = bool(options.get("json"))

        if not as_json:
            self.stdout.write("Running OrchestrAI healthcheck...")

        try:
            app = get_current_app()
            if app is not None:
                try:
                    app.start()
                except Exception:
                    logger.debug("OrchestrAI app failed to start before healthcheck", exc_info=True)

            ok, detail = healthcheck_orchestrai()

            if as_json:
                http_status = 200 if ok else 503
                payload = {
                    "ok": ok,
                    "http_status": http_status,
                    "detail": detail,
                }
                self.stdout.write(json.dumps(payload, default=json_default))
                sys.exit(0 if ok else 1)

            if ok:
                line = f"[orchestrai] healthy — {detail}"
                logger.info(line)
                self.stdout.write(self.style.SUCCESS(line))
                self.stdout.write(self.style.SUCCESS("✅ OrchestrAI is healthy."))
                sys.exit(0)
            else:
                line = f"[orchestrai] FAIL — {detail}"
                logger.warning(line)
                self.stdout.write(self.style.WARNING(line))
                self.stdout.write(self.style.ERROR("❌ OrchestrAI healthcheck failed."))
                sys.exit(1)

        except Exception as exc:
            logger.exception("OrchestrAI healthcheck failed unexpectedly: %s", exc)
            if as_json:
                payload = {"ok": False, "http_status": 500, "detail": "", "error": repr(exc)}
                self.stdout.write(json.dumps(payload, default=json_default))
                sys.exit(2)
            self.stdout.write(self.style.ERROR(f"❌ Healthcheck crashed: {exc!r}"))
            sys.exit(2)
