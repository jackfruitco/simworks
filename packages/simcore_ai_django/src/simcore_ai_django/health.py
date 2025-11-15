# simcore_ai_django/health.py
"""
simcore_ai_django.health
========================

Lightweight healthcheck helpers for configured AI clients.

Goals
-----
- Verify at startup that each registered client can reach its provider with the
  *effective* configuration (api key, base_url, model, timeout).
- Keep the checks fast and non-fatal: log INFO on success, WARNING on failure,
  do not block Django boot.
- Remain provider-agnostic, with optional provider-specific checks for richer coverage.

Design
------
- `healthcheck_client(...)` is the main entrypoint. It performs a minimal request
  when a provider-specific check is available; otherwise it falls back to static
  checks (e.g., api key presence).
- `healthcheck_all_registered(...)` iterates over the client registry and runs the
  check for each client, aggregating results for logs.

Provider-defined healthchecks
-----------------------------
Providers implement `BaseProvider.healthcheck()`. The default implementation returns
a simple readiness message; concrete providers should perform a lightweight live call
(e.g., OpenAI Responses with max_output_tokens=1).
"""

import asyncio
import logging
from typing import Dict, Optional, Tuple

from simcore_ai.client.registry import list_clients
from simcore_ai.client.client import AIClient  # type: ignore
from simcore_ai.providers.base import BaseProvider  # type: ignore

logger = logging.getLogger(__name__)


async def _provider_healthcheck_async(provider: BaseProvider, *, timeout_s: Optional[float]) -> Tuple[bool, str]:
    """
    Call the provider's own healthcheck coroutine.

    Providers should implement BaseProvider.healthcheck(). The base implementation
    returns a simple readiness message; concrete providers (e.g., OpenAI) should
    perform a minimal live call.
    """
    try:
        return await provider.healthcheck(timeout=timeout_s)
    except Exception as exc:  # pragma: no cover - network and provider errors vary
        # Let providers record rate limits or details; we just surface the summary.
        return (False, f"{getattr(provider, 'name', type(provider).__name__)} healthcheck error: {exc!s}")


def healthcheck_client(client: AIClient, *, timeout_s: Optional[float] = None) -> Tuple[bool, str]:
    """
    Run a minimal healthcheck for a single AI client.

    Behavior:
        - For OpenAI providers, performs a tiny Responses API call to validate live connectivity.
        - Otherwise, verifies that an API key *likely* exists and returns a best-effort result.

    Args:
        client: Registered AIClient instance.
        timeout_s: Optional per-call timeout override.

    Returns:
        (ok, message): Tuple indicating success and a brief diagnostic message.
    """
    provider = getattr(client, "provider", None)

    if isinstance(provider, BaseProvider):
        try:
            # Prefer a fresh loop; fall back to current loop when already running (tests/ASGI).
            return asyncio.run(_provider_healthcheck_async(provider, timeout_s=timeout_s))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(_provider_healthcheck_async(provider, timeout_s=timeout_s))

    # Fallback: static checks only (non-fatal)
    api_key = getattr(provider, "api_key", None)
    name = getattr(provider, "name", type(provider).__name__)
    if not api_key:
        return False, f"{name}: missing api_key (static check)"
    return True, f"{name}: static check passed"


def healthcheck_all_registered(*, timeout_s: Optional[float] = None) -> Dict[str, Tuple[bool, str]]:
    """
    Run healthchecks for all currently registered AI clients.

    Args:
        timeout_s: Optional per-call timeout override applied to each provider-specific check.

    Returns:
        A mapping of client registry name -> (ok, message).
    """
    results: Dict[str, Tuple[bool, str]] = {}
    clients = list_clients()
    for name, client in clients.items():
        ok, msg = healthcheck_client(client, timeout_s=timeout_s)
        results[name] = (ok, msg)
        # Log per-client at INFO/WARNING level.
        if ok:
            logger.info("AI healthcheck OK: %s — %s", name, msg)
        else:
            logger.warning("AI healthcheck FAIL: %s — %s", name, msg)
    return results