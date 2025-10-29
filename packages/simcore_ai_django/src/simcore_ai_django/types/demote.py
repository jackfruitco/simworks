from __future__ import annotations

"""
Demotion helpers (Django → core DTOs).

These functions convert Django-rich DTOs back into the core, framework-agnostic
`simcore_ai.types` models. They preserve identity (`namespace`, `kind`, `name`),
provider/client metadata, correlation fields, and timestamps like `received_at`
on responses, while stripping Django-only overlay fields.

This module mirrors `types/promote.py` (promotion flow) and keeps all logic
pure (no ORM). Order of items/messages is preserved where applicable.
"""

from typing import Optional
from collections.abc import Sequence

from simcore_ai.types import (
    LLMRequest,
    LLMRequestMessage,
    LLMResponse,
    LLMResponseItem,
    LLMUsage,
)
from .django_dtos import (
    DjangoLLMRequest,
    DjangoLLMRequestMessage,
    DjangoLLMResponse,
    DjangoLLMResponseItem,
    DjangoLLMUsage,
)


# ---------------------- helpers -----------------------------------------

def _demote_messages(
        messages_rich: Optional[Sequence[DjangoLLMRequestMessage]],
        fallback: Optional[Sequence[LLMRequestMessage]] = None,
) -> list[LLMRequestMessage]:
    """Best-effort demotion of rich request messages to core messages.

    Prefers `messages_rich` (order-preserving); falls back to `fallback` if absent.
    """
    if messages_rich:
        return [LLMRequestMessage(**m.model_dump(mode="json")) for m in messages_rich]
    return list(fallback or [])


def _demote_response_items(
        items_rich: Optional[Sequence[DjangoLLMResponseItem]],
        fallback: Optional[Sequence[LLMResponseItem]] = None,
) -> list[LLMResponseItem]:
    """Demote rich response items to core response items, preserving order."""
    if items_rich:
        return [LLMResponseItem(**it.model_dump(mode="json")) for it in items_rich]
    return list(fallback or [])


def _demote_usage(usage_rich: Optional[DjangoLLMUsage], fallback: Optional[LLMUsage] = None) -> Optional[LLMUsage]:
    """Demote rich usage to core usage when present; otherwise return fallback."""
    if usage_rich:
        return LLMUsage(**usage_rich.model_dump(mode="json"))
    return fallback


# ---------------------- public API --------------------------------------

def demote_request(dj_req: DjangoLLMRequest) -> LLMRequest:
    """Demote a Django-rich request back to the core LLMRequest.

    Preserves identity fields (namespace, kind, client_name).
    Strips Django-only overlay fields.
    Order of messages is preserved.
    """
    base = dj_req.model_dump(mode="json")
    # Remove Django-only fields
    for key in (
            "db_pk",
            "created_at",
            "updated_at",
            "object_db_pk",
            "messages_rich",
            "prompt_meta",
    ):
        base.pop(key, None)

    # Rebuild messages from rich list if available
    base["messages"] = _demote_messages(dj_req.messages_rich, fallback=dj_req.messages)
    return LLMRequest(**base)


def demote_response(dj_resp: DjangoLLMResponse) -> LLMResponse:
    """Demote a Django-rich response back to the core LLMResponse.

    Preserves identity and provider/client name fields and received_at.
    Strips Django-only overlay fields.
    Order of outputs is preserved. The response's `received_at` timestamp is retained if present.
    """
    base = dj_resp.model_dump(mode="json")
    for key in (
            "db_pk",
            "created_at",
            "updated_at",
            "outputs_rich",
            "usage_rich",
            "request_db_pk",
            "response_db_pk",
            "object_db_pk",
    ):
        base.pop(key, None)

    base["outputs"] = _demote_response_items(dj_resp.outputs_rich, fallback=dj_resp.outputs)
    base["usage"] = _demote_usage(dj_resp.usage_rich, fallback=dj_resp.usage)
    return LLMResponse(**base)


__all__ = [
    "demote_request",
    "demote_response",
]
