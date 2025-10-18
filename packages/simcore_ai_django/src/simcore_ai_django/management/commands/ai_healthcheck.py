# simcore_ai_django/management/commands/ai_healthcheck.py
from __future__ import annotations

"""
Django management command to run AI client/provider healthchecks.

Usage:
    python manage.py ai_healthcheck
    python manage.py ai_healthcheck --json           # CI-friendly JSON output (includes http_status)
    python manage.py ai_healthcheck --flat           # Return a flat list (by client); default groups by provider

This command runs after Django setup and triggers
`simcore_ai_django.health.healthcheck_all_registered()` to verify that
configured AI clients/providers respond successfully to minimal, provider-defined
healthchecks (e.g., OpenAI Responses ping). It logs per-client health results and
exits non-zero on failures.

Intended for CI/CD and container boot probes.
"""

import json
import logging
import sys
from django.core.management.base import BaseCommand
from simcore_ai_django.health import healthcheck_all_registered
from simcore_ai.client.registry import list_clients

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run AI provider/client healthchecks and report results."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output results as JSON for CI consumption.",
        )
        parser.add_argument(
            "--by-provider",
            action="store_true",
            help="(Deprecated) Group results by provider. Now the default; use --flat to get client-level list.",
        )
        parser.add_argument(
            "--flat",
            action="store_true",
            help="Return a flat client-level list instead of grouping by provider.",
        )

    def handle(self, *args, **options):
        as_json = bool(options.get("json"))
        flat = bool(options.get("flat"))
        by_provider_flag = bool(options.get("by_provider"))
        # New default: group by provider unless --flat is set
        by_provider = not flat
        # Back-compat: if --by-provider explicitly passed, force grouping
        if by_provider_flag:
            by_provider = True
        if not as_json:
            self.stdout.write("Running AI healthcheck...")

        try:
            results = healthcheck_all_registered()
            provider_map = {}
            if by_provider:
                try:
                    for cname, client in list_clients().items():
                        # Map client registry name to its provider's display name
                        prov = getattr(client, "provider", None)
                        prov_name = getattr(prov, "name", type(prov).__name__)
                        provider_map[cname] = prov_name
                except Exception:
                    provider_map = {}

            all_ok = True
            if by_provider:
                # report structure: { provider_name: { "ok": bool, "clients": {client_name: {"ok": bool, "detail": str}} } }
                report: dict[str, dict[str, object]] = {}
            else:
                # report structure: { client_name: {"ok": bool, "detail": str} }
                report: dict[str, dict[str, object]] = {}

            for name, (ok, detail) in results.items():
                if by_provider:
                    prov_name = provider_map.get(name, "unknown")
                    bucket = report.setdefault(prov_name, {"ok": True, "clients": {}})
                    bucket["clients"][name] = {"ok": bool(ok), "detail": str(detail)}
                    # provider bucket is ok only if all its clients are ok
                    bucket["ok"] = bool(bucket["ok"] and ok)
                else:
                    report[name] = {"ok": bool(ok), "detail": str(detail)}

                # Human-readable output (only when not JSON)
                if not as_json:
                    if by_provider:
                        line = f"[{prov_name}::{name}] {'healthy' if ok else 'FAIL'} — {detail}"
                    else:
                        line = f"[{name}] {'healthy' if ok else 'FAIL'} — {detail}"
                    if ok:
                        logger.info(line)
                        self.stdout.write(self.style.SUCCESS(line))
                    else:
                        all_ok = False
                        logger.warning(line)
                        self.stdout.write(self.style.WARNING(line))

                # Track overall status
                if not ok:
                    all_ok = False

            if as_json:
                http_status = 200 if all_ok else 503
                payload = {"ok": all_ok, "http_status": http_status, "results": report}
                self.stdout.write(json.dumps(payload))
                sys.exit(0 if all_ok else 1)

            if all_ok:
                self.stdout.write(self.style.SUCCESS("✅ All AI clients/providers are healthy."))
                sys.exit(0)
            else:
                self.stdout.write(self.style.ERROR("❌ One or more AI clients/providers failed healthcheck."))
                sys.exit(1)

        except Exception as exc:
            logger.exception("AI healthcheck failed unexpectedly: %s", exc)
            if as_json:
                payload = {"ok": False, "http_status": 500, "results": {}, "error": repr(exc)}
                self.stdout.write(json.dumps(payload))
                sys.exit(2)
            self.stdout.write(self.style.ERROR(f"❌ Healthcheck crashed: {exc!r}"))
            sys.exit(2)