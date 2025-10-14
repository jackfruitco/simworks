from __future__ import annotations
from uuid import UUID

from typing import Any, Iterable, List, Optional

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

def _promote_messages(
        messages: Optional[Iterable[LLMRequestMessage]], *, request_db_pk: int | UUID | None = None,
        request_correlation_id: UUID | None = None
) -> List[DjangoLLMRequestMessage]:
    out: List[DjangoLLMRequestMessage] = []
    if not messages:
        return out
    for idx, msg in enumerate(messages):
        data = msg.model_dump(mode="json")
        out.append(
            DjangoLLMRequestMessage(
                **data,
                request_db_pk=request_db_pk,
                sequence_index=idx,
                request_correlation_id=request_correlation_id,
            )
        )
    return out


def _promote_response_items(
        items: Optional[Iterable[LLMResponseItem]], *, response_db_pk: int | UUID | None = None,
        request_db_pk: int | UUID | None = None,
        request_correlation_id: UUID | None = None,
        response_correlation_id: UUID | None = None,
) -> List[DjangoLLMResponseItem]:
    out: List[DjangoLLMResponseItem] = []
    if not items:
        return out
    for idx, it in enumerate(items):
        data = it.model_dump(mode="json")
        out.append(
            DjangoLLMResponseItem(
                **data,
                response_db_pk=response_db_pk,
                request_db_pk=request_db_pk,
                sequence_index=idx,
                request_correlation_id=request_correlation_id,
                response_correlation_id=response_correlation_id,
            )
        )
    return out


def _promote_usage(
        usage: Optional[LLMUsage], *, response_db_pk: int | UUID | None = None,
        request_correlation_id: UUID | None = None,
        response_correlation_id: UUID | None = None,
) -> Optional[DjangoLLMUsage]:
    if not usage:
        return None
    data = usage.model_dump(mode="json")
    return DjangoLLMUsage(**data, response_db_pk=response_db_pk,
                         request_correlation_id=request_correlation_id,
                         response_correlation_id=response_correlation_id)


# ---------------------- public API --------------------------------------

def promote_request(req: LLMRequest, **overlay: Any) -> DjangoLLMRequest:
    """Promote a core LLMRequest to a Django-rich DjangoLLMRequest.

    Any keyword args in **overlay are merged in and can include identity fields such as namespace, bucket, and name,
    correlation identifiers, etc. If you already know the request audit pk,
    pass it via overlay as `db_pk` to stamp onto the DTO.
    """
    data = req.model_dump(mode="json")
    dj = DjangoLLMRequest(**data, **overlay)

    # Build rich messages for convenience (sequence-indexed), if base messages exist
    dj.messages_rich = _promote_messages(req.messages, request_db_pk=dj.db_pk, request_correlation_id=getattr(dj, "correlation_id", None))
    return dj


def promote_response(resp: LLMResponse, **overlay: Any) -> DjangoLLMResponse:
    """Promote a core LLMResponse to a Django-rich DjangoLLMResponse.

    The overlay may include identity and correlation link fields such as request_db_pk, request_correlation_id, response_correlation_id, simulation_pk, namespace, etc.
    """
    data = resp.model_dump(mode="json")
    dj = DjangoLLMResponse(**data, **overlay)

    req_corr = getattr(dj, "request_correlation_id", None)
    resp_corr = getattr(dj, "correlation_id", None)

    dj.outputs_rich = _promote_response_items(
        resp.outputs,
        response_db_pk=dj.db_pk,
        request_db_pk=getattr(dj, "request_db_pk", None),
        request_correlation_id=req_corr,
        response_correlation_id=resp_corr,
    )
    dj.usage_rich = _promote_usage(resp.usage, response_db_pk=dj.db_pk,
                                   request_correlation_id=req_corr,
                                   response_correlation_id=resp_corr)
    return dj


__all__ = [
    "promote_request",
    "promote_response",
]
