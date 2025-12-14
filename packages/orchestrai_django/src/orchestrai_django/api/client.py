# orchestrai_django/client.py
"""
orchestrai_django.api
=====================

Thin, Django-facing facades for interacting with configured AI clients.

Why this module?
----------------
SimWorks apps should avoid importing core `orchestrai` internals directly to keep a
clean boundary. Instead, they call into these helpers which delegate to the core
client registry.

Primary helpers:
- `get_default_client()` — return the default `OrcaClient`.
- `get_client(name)`     — return a named `OrcaClient` by registry key.
- `call_default(request)`— convenience: call the default client with an `Request`.

These helpers are intentionally minimal and stable; richer flows should continue
to use the core `OrcaClient` methods once a client instance is obtained.
"""

from typing import Optional

from orchestrai.client.registry import get_ai_client, get_default_client as _get_default_client
from orchestrai.client.client import OrcaClient  # type: ignore
from orchestrai.types import Request, Response


def get_default_client() -> OrcaClient:
    """
    Return the default AI client.

    Default selection is orchestrated during Django startup in
    `orchestrai_django.setup.configure_ai_clients()` based on the
    `orchestrai["CLIENTS"]` configuration.
    """
    return _get_default_client()


def get_client(name: str) -> OrcaClient:
    """
    Return a named AI client by registry key.

    Args:
        name: The registry name from `orchestrai["CLIENTS"]` (e.g., "openai:prod-gpt-4o-mini").

    Raises:
        RegistryLookupError: if no client with `name` is registered.
    """
    if not name or not isinstance(name, str):
        raise ValueError("client name must be a non-empty string")
    return get_ai_client(name=name)


def call_default(request: Request, *, timeout: Optional[float] = None) -> Response:
    """
    Convenience helper to call the default client with an `Request`.

    Args:
        request: The normalized request to send to the default AI client.
        timeout: Optional per-call timeout in seconds.

    Returns:
        Response produced by the backend.
    """
    client = get_default_client()
    # The OrcaClient.call is async or sync depending on your implementation.
    # If it's async-only, the caller should use their async runtime.
    # Here we assume a synchronous facade that forwards through the client's `.call`.
    return client.send_request(request, timeout=timeout)  # type: ignore[call-arg]
