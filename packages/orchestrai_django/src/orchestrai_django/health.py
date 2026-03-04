# orchestrai_django/health.py
"""
orchestrai_django.health
========================

Lightweight healthcheck helpers for OrchestrAI services.

Goals
-----
- Verify at startup that OrchestrAI is properly configured
- Keep the checks fast and non-fatal: log INFO on success, WARNING on failure,
  do not block Django boot.

Design
------
- `healthcheck_orchestrai()` is the main entrypoint. It verifies the OrchestrAI app
  is started and services can be instantiated.
- Services use Pydantic AI's Agent abstraction for LLM execution.
"""

import logging

logger = logging.getLogger(__name__)


def healthcheck_orchestrai() -> tuple[bool, str]:
    """
    Run a minimal healthcheck for OrchestrAI.

    Verifies:
        - OrchestrAI app is available and started
        - Services registry is accessible

    Returns:
        (ok, message): Tuple indicating success and a brief diagnostic message.
    """
    try:
        from orchestrai import get_current_app

        app = get_current_app()
        if app is None:
            return False, "OrchestrAI app not configured"

        # Check if app is started
        if not getattr(app, "_started", False):
            try:
                app.start()
            except Exception as e:
                return False, f"OrchestrAI app failed to start: {e}"

        # Check if services registry is accessible
        if hasattr(app, "component_store"):
            services = app.component_store.registry("services")
            if services is not None:
                service_count = len(services.all()) if hasattr(services, "all") else 0
                return True, f"OrchestrAI ready ({service_count} services registered)"

        return True, "OrchestrAI ready"

    except Exception as e:
        logger.warning("OrchestrAI healthcheck failed: %s", e)
        return False, f"OrchestrAI healthcheck error: {e}"
