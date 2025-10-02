# simcore/ai/providers/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Any, Iterable, Optional, Protocol

from pydantic import TypeAdapter

# Slim, LLM-facing projections
from simcore.ai.schemas.output_types import (
    OutputMessageItem,
    OutputMetafieldItem,
)
# DTOs (single source of truth)
from simcore.ai.schemas.types import (
    LLMRequest,
    LLMResponse,
    StreamChunk,
    MessageItem,
    MetafieldItem,
    AttachmentItem, ToolItem,
)


class ProviderError(Exception):
    """Base exception for provider-level errors."""


class ProviderBase(ABC):
    """
    Abstract base class for all AI providers.

    Key ideas:
      - Providers implement `call` (non-stream) and `stream` (streaming) using their SDKs.
      - Providers supply *hook methods* to extract text, outputs, usage, and meta
        from the raw SDK response. The shared `adapt_response` turns those into an
        `LLMResponse` via the Output* → DTO flow.
    """

    name: str
    description: str

    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description
        self._tool_adapter: Optional[ProviderBase.ToolAdapter] = None

    # ---------------------------------------------------------------------
    # Public provider API
    # ---------------------------------------------------------------------
    @abstractmethod
    async def call(self, req: LLMRequest, timeout: float | None = None) -> LLMResponse:
        ...

    @abstractmethod
    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamChunk]:
        ...

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIProvider {self.name}>"

    # ---------------------------------------------------------------------
    # Normalization/adaptation (provider-agnostic core + provider hooks)
    # ---------------------------------------------------------------------
    def adapt_response(self, resp: Any, *, schema_cls: type | None = None) -> LLMResponse:
        """
        Provider-agnostic response construction pipeline.
        Steps:
          1) Parse provider text to declared output schema (if provided)
          2) Validate boundary shapes using slim Output* unions
          3) Promote to DTO unions (MessageItem, MetafieldItem)
          4) Fold in provider-specific attachments (via hooks)
        """
        # 1) Adapt schema class to provider specialized schema
        specialized_schema_cls = self.specialize_output_schema(schema_cls)

        # 2) Parse text into declared output schema (if any)
        parsed = None
        text_out = self._extract_text(resp)
        if specialized_schema_cls is not None and text_out:
            parsed = self._maybe_parse_to_schema(text_out, specialized_schema_cls)

        # 3) Normalize provider-shaped parsed instance back to normalized DTO shape
        if parsed is not None:
            parsed = self.normalize_output_instance(parsed)

        # 4) Boundary validation (slim Output* types)
        raw_messages = getattr(parsed, "messages", []) or []
        raw_metadata = getattr(parsed, "metadata", []) or []

        slim_messages = TypeAdapter(list[OutputMessageItem]).validate_python(
            raw_messages if isinstance(raw_messages, list) else []
        )
        slim_metadata = TypeAdapter(list[OutputMetafieldItem]).validate_python(
            raw_metadata if isinstance(raw_metadata, list) else []
        )

        # 5) Promote to DTOs (domain)
        messages = TypeAdapter(list[MessageItem]).validate_python(
            [m.model_dump() for m in slim_messages]
        )
        metadata = TypeAdapter(list[MetafieldItem]).validate_python(
            [m.model_dump() for m in slim_metadata]
        )

        # 6) Provider attachments (images, etc.) via hooks
        attachments: list[AttachmentItem] = []
        for obj in self._extract_outputs(resp) or []:
            if self._is_image_output(obj):
                att = self._build_attachment(obj)
                if att is not None:
                    attachments.append(att)
        if attachments:
            messages.append(
                MessageItem(
                    role="tool",
                    content="",
                    tool_calls=[
                        {
                            "name": "image_generation",
                            "id": a.provider_meta.get("provider_image_call_id"),
                        }
                        for a in attachments
                    ],
                    attachments=[],
                )
            )

        if specialized_schema_cls is not None:
            import logging
            logging.getLogger(__name__).debug("adapt_response parsed with specialized schema: %s", specialized_schema_cls.__name__)
        return LLMResponse(
            messages=messages,
            metadata=metadata,
            usage=self._extract_usage(resp),
            provider_meta=self._extract_provider_meta(resp),
            image_requested=getattr(parsed, "image_requested", None) if parsed else None,
        )

    def specialize_output_schema(self, schema_cls: type | None) -> type | None:
        """Return a provider-specialized schema class for outbound requests."""
        if schema_cls is None:
            return None
        return self._schema_to_provider(schema_cls)

    def normalize_output_instance(self, model_instance: Any) -> Any:
        """Normalize a provider-shaped parsed model instance back to the provider-agnostic shape.
        Default is a no-op; providers can override.
        """
        return model_instance

    # ---------------------------------------------------------------------
    # Provider-specific Response HOOKS (override in concrete providers)
    # ---------------------------------------------------------------------
    def _extract_text(self, resp: Any) -> Optional[str]:
        """Return the provider's primary text output, if any."""
        ...

    def _extract_outputs(self, resp: Any) -> Iterable[Any]:
        """Yield provider output items (images, tool calls, etc.)."""
        ...

    def _is_image_output(self, item: Any) -> bool:
        """Return True if the output item represents an image generation result."""
        ...

    def _extract_usage(self, resp: Any) -> dict:
        """Return a normalized usage dict (input/output/total tokens, etc.)."""
        ...

    def _extract_provider_meta(self, resp: Any) -> dict:
        """Return provider-specific metadata for diagnostics (model, ids, raw dump)."""
        ...

    def _build_attachment(self, item: Any) -> Optional[AttachmentItem]:
        """Convert an image/tool output item into an AttachmentItem DTO."""
        ...

    # ---------------------------------------------------------------------
    # Provider-specific Schema HOOKS (override in concrete providers)
    # ---------------------------------------------------------------------
    def _schema_to_provider(self, schema_cls: type) -> type:
        """Provider override to adapt the normalized DTO schema to provider schema.

        Default implementation is a no-op.
        """
        return schema_cls

    def _schema_from_provider(self, schema_cls: type) -> type:
        """Provider override to adapt provider schema to the normalized DTO schema.

        Default implementation is a no-op.
        """
        return schema_cls

    # ---------------------------------------------------------------------
    # Tools
    # ---------------------------------------------------------------------
    class ToolAdapter(Protocol):
        def to_provider(self, tool: ToolItem) -> Any: ...

        def from_provider(self, tool: Any) -> ToolItem: ...

    # -- Tool adaptation helpers -------------------------------------------------
    def set_tool_adapter(self, adapter: "ProviderBase.ToolAdapter") -> None:
        """Register a ToolAdapter for this provider.
        Concrete providers can call this in __init__, or the caller can inject one.
        """
        self._tool_adapter = adapter

    def _tools_to_provider(self, tools: Optional[list[ToolItem]]) -> Optional[list[Any]]:
        """Convert our DTO ToolItem list into provider-native tool specs.
        Returns None if no adapter is registered or tools is falsy.
        """
        if not tools or not self._tool_adapter:
            return None
        return [self._tool_adapter.to_provider(t) for t in tools]

    def _tools_from_provider(self, provider_tools: Optional[Iterable[Any]]) -> list[ToolItem]:
        """Convert provider-native tool specs into our ToolItem DTOs.
        Returns an empty list if no adapter is registered or input is falsy.
        """
        if not provider_tools or not self._tool_adapter:
            return []
        return [self._tool_adapter.from_provider(t) for t in provider_tools]

    # ---------------------------------------------------------------------
    # Utilities
    # ---------------------------------------------------------------------
    @staticmethod
    def _maybe_parse_to_schema(text: str, schema_cls: type) -> Any:
        """Best-effort parse of `text` into `schema_cls` via Pydantic v2 API."""
        try:
            # Prefer JSON if schema expects JSON; fall back to plain model_validate
            return schema_cls.model_validate_json(text)
        except Exception:
            try:
                return schema_cls.model_validate(text)
            except Exception:
                return None
