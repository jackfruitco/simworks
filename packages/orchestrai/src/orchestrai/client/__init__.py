"""
OrchestrAI Client Module (DEPRECATED).

.. deprecated:: 0.5.0
    This module is deprecated and will be removed in OrchestrAI 1.0.
    Use Pydantic AI directly via :class:`orchestrai.components.services.PydanticAIService`
    or :class:`orchestrai_django.components.services.DjangoPydanticAIService` instead.

Migration Guide:
    Before (using OrcaClient):
        from orchestrai.client import get_client
        client = get_client()
        response = await client.send_request(request)

    After (using Pydantic AI):
        from orchestrai.components.services import PydanticAIService
        from orchestrai.prompts import system_prompt

        class MyService(PydanticAIService):
            model = "openai:gpt-4o"
            response_schema = MySchema

            @system_prompt(weight=100)
            def instructions(self) -> str:
                return "Your instructions..."

        service = MyService(context={...})
        result = await service.arun()
"""
import warnings

warnings.warn(
    "orchestrai.client is deprecated and will be removed in OrchestrAI 1.0. "
    "Use PydanticAIService or DjangoPydanticAIService instead.",
    DeprecationWarning,
    stacklevel=2,
)

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