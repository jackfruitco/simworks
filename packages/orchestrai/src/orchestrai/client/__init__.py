from .client import OrcaClient
from .registry import (
    create_client, create_client_from_dict,
    get_ai_client, list_clients,
    set_default_client, get_default_client
)


__all__ = [
    "OrcaClient",
    # Preferred high-level helper
    "get_client",

    # Registry-level (lower‑level) APIs
    "create_client",
    "create_client_from_dict",
    "get_ai_client",
    "get_default_client",
    "list_clients",
    "set_default_client",
]

def get_client(name: Optional[str] = None):
    """
    Lazy wrapper around orchestrai.client.factory.get_client to avoid
    circular imports during settings/bootstrap initialization.

    Importing `orchestrai.client` no longer imports the factory module
    immediately; the import happens only when this function is called.
    """
    from .factory import get_client as _get_client

    return _get_client(name)