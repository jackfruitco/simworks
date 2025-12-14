# orchestrai/apps/bootstrap.py

from typing import Any

from .conf.models import OrcaSettings


def configure_orca(*, app: Any, settings: OrcaSettings) -> None:
    """
    SINGLE ORCA mode bootstrap.

    This function should:
    - configure provider backends / provider instances
    - configure clients that reference provider aliases + profiles/environments
    - populate app.providers / app.clients (or call into your registries)

    This is intentionally framework-agnostic: no Django imports here.
    """
    # Store final settings for runtime access (optional but useful)
    app.settings = settings

    # Minimal, safe defaults:
    app.providers = {}
    app.clients = {}

    # If you have existing factories/registries, wire them here.
    # Keep imports local to avoid import-time cycles.
    #
    # Example (adapt to your real modules):
    #   from orchestrai.providers import build_providers
    #   from orchestrai.clients import build_clients
    #   app.providers = build_providers(settings.PROVIDERS)
    #   app.clients = build_clients(settings.CLIENTS, providers=app.providers)

    if settings.PROVIDERS:
        app.providers_config = settings.PROVIDERS
    if settings.CLIENTS:
        app.clients_config = settings.CLIENTS


def configure_orca_pod(*, app: Any, settings: OrcaSettings) -> None:
    """
    ORCA POD mode bootstrap.

    Pod mode typically means:
    - multiple provider sets / environments
    - multiple named clients
    - routing or selection behavior

    Keep it idempotent and avoid import-time side effects.
    """
    app.settings = settings
    app.providers = {}
    app.clients = {}

    if settings.PROVIDERS:
        app.providers_config = settings.PROVIDERS
    if settings.CLIENTS:
        app.clients_config = settings.CLIENTS

    # Wire in your pod routing here as needed.
