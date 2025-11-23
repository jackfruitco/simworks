"""
DTO promotion helpers (core -> Django overlays).

This module performs **pure, lossless** transformations of core simcore_ai DTOs
(`Request`, `Response`, etc.) into Django-rich DTOs (`DjangoLLM*`).
It does **no identity normalization** or resolver logic and intentionally
contains **no tracing**. Service‑aware enrichment (identity/provider/client,
spans) belongs in `simcore_ai_django.services.promote` / `...demote`.

Behavior:
- Empty/None inputs produce empty rich lists.
- Sequence order is preserved via `sequence_index`.
- All extra fields are passed via `**overlay` verbatim.
"""



from typing import Any, List, Optional, Sequence
from uuid import UUID

from simcore_ai.types import (
    Request,
    LLMRequestMessage,
    Response,
    LLMResponseItem,
    LLMUsage,
)
from .django_dtos import (
    DjangoRequest,
    DjangoLLMRequestMessage,
    DjangoResponse,
    DjangoLLMResponseItem,
    DjangoLLMUsage,
)

__all__ = [
    "promote_request",
    "promote_response",
]

# ---------------------- helpers -----------------------------------------

def _promote_messages(
        messages: Optional[Sequence[LLMRequestMessage]], *, request_db_pk: int | UUID | None = None,
        request_correlation_id: UUID | None = None
) -> List[DjangoLLMRequestMessage]:
    """
    Promote a sequence of LLMRequestMessage core DTOs into DjangoLLMRequestMessage DTOs.

    Parameters:
    - messages: Optional sequence of LLMRequestMessage to promote.
    - request_db_pk: Optional database primary key to associate with each message.
    - request_correlation_id: Optional correlation UUID to associate with each message.

    Returns:
    - List of DjangoLLMRequestMessage with sequence_index preserving order.
    - Returns empty list if input is None or empty.
    """
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
        items: Optional[Sequence[LLMResponseItem]], *, response_db_pk: int | UUID | None = None,
        request_db_pk: int | UUID | None = None,
        request_correlation_id: UUID | None = None,
        response_correlation_id: UUID | None = None,
) -> List[DjangoLLMResponseItem]:
    """
    Promote a sequence of LLMResponseItem core DTOs into DjangoLLMResponseItem DTOs.

    Parameters:
    - items: Optional sequence of LLMResponseItem to promote.
    - response_db_pk: Optional database primary key for the response.
    - request_db_pk: Optional database primary key for the request.
    - request_correlation_id: Optional correlation UUID for the request.
    - response_correlation_id: Optional correlation UUID for the response.

    Returns:
    - List of DjangoLLMResponseItem with sequence_index preserving order.
    - Returns empty list if input is None or empty.
    """
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
    """
    Promote an optional LLMUsage core DTO into DjangoLLMUsage DTO.

    Passes through usage fields and stamps correlation and database keys.

    Parameters:
    - usage: Optional LLMUsage to promote.
    - response_db_pk: Optional database primary key for the response.
    - request_correlation_id: Optional correlation UUID for the request.
    - response_correlation_id: Optional correlation UUID for the response.

    Returns:
    - DjangoLLMUsage instance or None if usage is None.
    """
    if not usage:
        return None
    data = usage.model_dump(mode="json")
    return DjangoLLMUsage(**data, response_db_pk=response_db_pk,
                          request_correlation_id=request_correlation_id,
                          response_correlation_id=response_correlation_id)


# ---------------------- public API --------------------------------------

def promote_request(req: Request, **overlay: Any) -> DjangoRequest:
    """Promote a core Request to a Django-rich DjangoRequest.

    Identity and correlation fields from overlay are copied verbatim.
    No normalization or resolution logic is performed here.

    Any keyword args in **overlay are merged in and can include identity fields such as namespace, kind, name,
    object_db_pk, correlation identifiers, etc. If you already know the request audit pk,
    pass it via overlay as `db_pk` to stamp onto the DTO.
    """
    data = req.model_dump(mode="json")
    dj = DjangoRequest(**data, **overlay)

    # Build rich messages for convenience (sequence-indexed), if base messages exist
    dj.messages_rich = _promote_messages(req.messages, request_db_pk=dj.db_pk,
                                         request_correlation_id=getattr(dj, "correlation_id", None))
    return dj


def promote_response(resp: Response, **overlay: Any) -> DjangoResponse:
    """Promote a core Response to a Django-rich DjangoResponse.

    Identity and correlation fields from overlay are copied verbatim.
    No normalization or resolution logic is performed here.

    The overlay may include identity and correlation link fields such as request_db_pk, request_correlation_id, response_correlation_id, object_db_pk, namespace, etc.
    """
    data = resp.model_dump(mode="json")
    dj = DjangoResponse(**data, **overlay)

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

