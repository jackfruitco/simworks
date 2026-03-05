"""
Demotion helpers (Django → core DTOs).

These functions convert Django-rich DTOs back into the core, framework-agnostic
`orchestrai.types` models. They preserve identity (`namespace`, `kind`, `name`),
backend/client metadata, correlation fields, and timestamps like `received_at`
on responses, while stripping Django-only overlay fields.

This module mirrors `types/promote.py` (promotion flow) and keeps all logic
pure (no ORM). Order of items/input is preserved where applicable.
"""

from collections.abc import Sequence

from orchestrai.types import (
    Request,
    Response,
)
from orchestrai.types.messages import InputItem, OutputItem, UsageContent

from .django_dtos import (
    DjangoInputItem,
    DjangoOutputItem,
    DjangoRequest,
    DjangoResponse,
    DjangoUsageContent,
)

__all__ = ("demote_request", "demote_response")


# ---------------------- helpers -----------------------------------------


def _demote_messages(
    messages_rich: Sequence[DjangoInputItem] | None,
    fallback: Sequence[InputItem] | None = None,
) -> list[InputItem]:
    """Best-effort demotion of rich request input to core input.

    Prefers `messages_rich` (order-preserving); falls back to `fallback` if absent.
    """
    if messages_rich:
        return [InputItem(**m.model_dump(mode="json")) for m in messages_rich]
    return list(fallback or [])


def _demote_response_items(
    items_rich: Sequence[DjangoOutputItem] | None,
    fallback: Sequence[OutputItem] | None = None,
) -> list[OutputItem]:
    """Demote rich response items to core response items, preserving order."""
    if items_rich:
        return [OutputItem(**it.model_dump(mode="json")) for it in items_rich]
    return list(fallback or [])


def _demote_usage(
    usage_rich: DjangoUsageContent | None, fallback: UsageContent | None = None
) -> UsageContent | None:
    """Demote rich usage to core usage when present; otherwise return fallback."""
    if usage_rich:
        return UsageContent(**usage_rich.model_dump(mode="json"))
    return fallback


# ---------------------- public API --------------------------------------


def demote_request(dj_req: DjangoRequest) -> Request:
    """Demote a Django-rich request back to the core Request.

    Preserves identity fields (namespace, kind, client_name).
    Strips Django-only overlay fields.
    Order of input is preserved.
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

    # Rebuild input from rich list if available
    base["input"] = _demote_messages(dj_req.messages_rich, fallback=dj_req.input)
    return Request(**base)


def demote_response(dj_resp: DjangoResponse) -> Response:
    """Demote a Django-rich response back to the core Response.

    Preserves identity and backend/client name fields and received_at.
    Strips Django-only overlay fields.
    Order of output is preserved. The response's `received_at` timestamp is retained if present.
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

    base["output"] = _demote_response_items(dj_resp.outputs_rich, fallback=dj_resp.output)
    base["usage"] = _demote_usage(dj_resp.usage_rich, fallback=dj_resp.usage)
    return Response(**base)
