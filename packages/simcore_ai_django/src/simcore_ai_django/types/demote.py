from __future__ import annotations

from typing import List, Optional
from collections.abc import Iterable

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

def _demote_messages(messages_rich: Optional[Iterable[DjangoLLMRequestMessage]],
                     fallback: Optional[Iterable[LLMRequestMessage]] = None) -> List[LLMRequestMessage]:
    if messages_rich:
        return [LLMRequestMessage(**m.model_dump(mode="json")) for m in messages_rich]
    return list(fallback or [])


def _demote_response_items(items_rich: Optional[Iterable[DjangoLLMResponseItem]],
                           fallback: Optional[Iterable[LLMResponseItem]] = None) -> List[LLMResponseItem]:
    if items_rich:
        return [LLMResponseItem(**it.model_dump(mode="json")) for it in items_rich]
    return list(fallback or [])


def _demote_usage(usage_rich: Optional[DjangoLLMUsage], fallback: Optional[LLMUsage] = None) -> Optional[LLMUsage]:
    if usage_rich:
        return LLMUsage(**usage_rich.model_dump(mode="json"))
    return fallback


# ---------------------- public API --------------------------------------

def demote_request(dj_req: DjangoLLMRequest) -> LLMRequest:
    """Demote a Django-rich request back to the core LLMRequest.

    Preserves identity fields (namespace, bucket, client_name).
    Strips Django-only overlay fields.
    """
    base = dj_req.model_dump(mode="json")
    # Remove Django-only fields
    for key in (
            "db_pk",
            "created_at",
            "updated_at",
            "simulation_pk",
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
            "simulation_pk",
    ):
        base.pop(key, None)

    base["outputs"] = _demote_response_items(dj_resp.outputs_rich, fallback=dj_resp.outputs)
    base["usage"] = _demote_usage(dj_resp.usage_rich, fallback=dj_resp.usage)
    return LLMResponse(**base)


__all__ = [
    "demote_request",
    "demote_response",
]
