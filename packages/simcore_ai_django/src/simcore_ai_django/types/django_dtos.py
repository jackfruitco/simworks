# simcore_ai_django/types/django_dtos.py
"""
Django-specific rich Data Transfer Objects (DTOs).

These classes extend the core `simcore_ai.types` models with optional Django-facing metadata:
- database primary keys (e.g., `db_pk`, `request_db_pk`, `response_db_pk`)
- audit timestamps (`created_at`, `updated_at`)
- identity echo (`namespace`, `kind`, `name`) for easy filtering
- correlation link fields (`correlation_id`, `request_correlation_id`, `response_correlation_id`)
- provider/client metadata for observability
- optional rich overlays (`messages_rich`, `outputs_rich`, `usage_rich`) promoted by the glue layer

- uses generic `object_db_pk` for domain linkage
- uses `context` for service/app context

They are **not** ORM models and are safe to emit via signals. Persistence remains the responsibility
of codecs and listeners.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import Field

from simcore_ai.types import (
    StrictBaseModel,
    LLMRequest,
    LLMRequestMessage,
    LLMResponse,
    LLMResponseItem,
    LLMUsage,
    LLMToolCall,
    BaseLLMTool,
)


class DjangoDTOBase(StrictBaseModel):
    """Common Django-aware overlay for DTOs.

    Adds optional database primary keys and audit-friendly metadata.
    These are **not** ORM models; they are Pydantic DTOs safe to emit via signals.
    """

    # Optional database primary key for the corresponding persisted record
    db_pk: int | UUID | None = None

    # Optional correlation and identity fields
    correlation_id: UUID | None = None
    namespace: str | None = None  # e.g., "chatlab"
    kind: str | None = None  # e.g., "default"
    name: str | None = None  # concrete leaf name (Identity.name)

    # Provider/client resolution captured at emit-time
    provider_name: str | None = None  # e.g., "openai"
    client_name: str | None = None  # registry name, e.g., "default", "openai-images"

    # Timestamps for auditing
    created_at: datetime | None = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime | None = None


# ---------------------- Request-side (rich) -----------------------------------------
class DjangoLLMRequestMessage(LLMRequestMessage, DjangoDTOBase):
    """Rich request message that can be persisted individually if desired.

    Includes `request_correlation_id` for end-to-end tracing.
    """
    # Optional linkage back to parent persisted request
    request_db_pk: int | UUID | None = None
    request_correlation_id: UUID | None = None
    sequence_index: int | None = None


class DjangoLLMRequest(LLMRequest, DjangoDTOBase):
    """Rich request wrapper for Django integrations.

    Extends the core request with persistence and routing metadata.
    Prefer passing app/service data in the `context` field;
    """

    # Optional object foreign key
    object_db_pk: int | UUID | None = None

    # Context
    context: dict[str, Any] | None = None

    # Optional hints used by glue/persistence layers
    prompt_meta: dict[str, Any] = Field(default_factory=dict)

    # If messages are persisted individually, services may populate this with rich msg DTOs
    messages_rich: list[DjangoLLMRequestMessage] | None = None


# ---------------------- Response-side (rich) ----------------------------------------
class DjangoLLMResponseItem(LLMResponseItem, DjangoDTOBase):
    """Rich response item that can be persisted with ordering and linkage.

    Carries both request/response correlation IDs for traceability.
    """

    response_db_pk: int | UUID | None = None  # parent response PK (if persisted)
    request_db_pk: int | UUID | None = None  # originating request PK
    sequence_index: int | None = None  # item ordering within response
    request_correlation_id: UUID | None = None
    response_correlation_id: UUID | None = None


class DjangoLLMResponseMessage(LLMResponseItem, DjangoDTOBase):
    """Rich response message that can be persisted individually if desired."""


class DjangoLLMUsage(LLMUsage, DjangoDTOBase):
    """Optional persisted usage row.

    Optional persisted usage row tied to a response; includes correlation links.
    """
    response_db_pk: int | UUID | None = None
    request_correlation_id: UUID | None = None
    response_correlation_id: UUID | None = None


class DjangoLLMResponse(LLMResponse, DjangoDTOBase):
    """Rich response wrapper for Django integrations.

    Echoes operation identity and correlation links; includes `received_at`.
    Includes optional `context` snapshot for auditing.
    """

    # Linkage
    request_db_pk: int | UUID | None = None
    object_db_pk: int | UUID | None = None

    # Optional context echo; apps may persist context snapshots alongside responses
    context: dict[str, Any] | None = None

    # Timestamps
    received_at: datetime | None = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Rich items/usage (if promoted by the glue layer)
    outputs_rich: list[DjangoLLMResponseItem] | None = None
    usage_rich: DjangoLLMUsage | None = None

    request_correlation_id: UUID | None = None


# ---------------------- Tooling overlays (optional) ---------------------------------
class DjangoLLMToolCall(LLMToolCall, DjangoDTOBase):
    """Optional persisted tool-call record."""
    response_db_pk: int | UUID | None = None
    request_db_pk: int | UUID | None = None
    request_correlation_id: UUID | None = None
    response_correlation_id: UUID | None = None


class DjangoLLMBaseTool(BaseLLMTool, DjangoDTOBase):
    """Base tool class for Django-aware tooling."""
    pass


# Re-export commonly used core content parts for convenience
__all__ = [
    # Base overlay
    "DjangoDTOBase",
    # Request side
    "DjangoLLMRequestMessage",
    "DjangoLLMRequest",
    # Response side
    "DjangoLLMResponseItem",
    "DjangoLLMUsage",
    "DjangoLLMResponse",
    # Tools
    "DjangoLLMBaseTool",
    "DjangoLLMToolCall",
]
