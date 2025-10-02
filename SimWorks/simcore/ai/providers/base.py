# simcore/ai/providers/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Any, Iterable, Optional, Protocol, get_origin, get_args, ClassVar
from weakref import WeakKeyDictionary

from pydantic import TypeAdapter, Field, create_model

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

    _schema_cache: ClassVar[dict[str, WeakKeyDictionary[type, type]]] = {}

    @classmethod
    def clear_schema_cache(cls, provider_namespace: str | None = None) -> None:
        """Clear the specialized schema cache.

        If `provider_namespace` is provided, it can be either the full namespace
        (e.g., 'simcore.ai.providers.openai') or just the label (e.g., 'openai').
        """
        if provider_namespace:
            # Accept both "openai" and "simcore.ai.providers.openai"
            if "." not in provider_namespace:  # looks like just a label
                provider_namespace = f"simcore.ai.providers.{provider_namespace}"
            cls._schema_cache.pop(provider_namespace, None)
        else:
            cls._schema_cache.clear()

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

    def _provider_namespace_key(self) -> str:
        """
        Return a stable provider namespace like 'simcore.ai.providers.<label>'
        regardless of whether the class lives in ...<label>, ...<label>.base, etc.
        """
        mod = self.__class__.__module__
        parts = mod.split(".")
        try:
            i = parts.index("providers")
            label = parts[i + 1]
            return ".".join(parts[: i + 2])
        except (ValueError, IndexError):
            return mod

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
        # 1) Client is responsible for schema overrides; use given schema_cls as-is
        parsed = None
        text_out = self._extract_text(resp)
        if schema_cls is not None and text_out:
            parsed = self._maybe_parse_to_schema(text_out, schema_cls)

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

        return LLMResponse(
            messages=messages,
            metadata=metadata,
            usage=self._extract_usage(resp),
            provider_meta=self._extract_provider_meta(resp),
            image_requested=getattr(parsed, "image_requested", None) if parsed else None,
        )

    @staticmethod
    def has_schema_overrides() -> bool:
        """Return True if the provider has overridden its schema classes.
        Providers can override this static method to indicate schema overrides.
        """
        return False

    def override_schema(self, schema_cls: type | None) -> type | None:
        if schema_cls is None:
            return None
        provider_key = self._provider_namespace_key()
        cache = self._schema_cache.setdefault(provider_key, WeakKeyDictionary())
        cached = cache.get(schema_cls)
        if cached is not None:
            return cached
        specialized = self._schema_to_provider(schema_cls)
        cache[schema_cls] = specialized
        return specialized

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
        """
        Return a provider-specialized schema where supported inner types are overridden
        by provider-specific `*Override` classes when available.

        Strategy:
        - Walk all pydantic model fields on `schema_cls`.
        - For each field annotation:
            * If it is `list[T]`, try to map `T -> TOverride`
            * If it is a direct type `T`, try to map `T -> TOverride`
        - If any changes are made, return a new create_model(..., __base__=schema_cls)
          that swaps those field types while preserving required/default semantics.
        - If no changes, return the original `schema_cls`.
        """
        try:
            model_fields = getattr(schema_cls, "model_fields", None)
            if not model_fields:
                return schema_cls

            overrides: dict[str, tuple[Any, Any]] = {}

            for fname, field in model_fields.items():
                ann = getattr(field, "annotation", None)
                if ann is None:
                    continue

                new_ann = None
                origin = get_origin(ann)
                args = get_args(ann)

                # Handle list[T]
                if origin is list and args:
                    inner = args[0]
                    override_inner = self._find_override_type(inner)
                    if override_inner is not None:
                        # Rebuild as list[override_inner]
                        new_ann = list[override_inner]  # type: ignore[index]

                else:
                    # Handle direct type T
                    override_type = self._find_override_type(ann)
                    if override_type is not None:
                        new_ann = override_type

                if new_ann is not None:
                    # Preserve required/default semantics
                    is_required = bool(getattr(field, "is_required", False))
                    if is_required:
                        default = Field(...)
                    else:
                        default = Field(getattr(field, "default", None))
                    overrides[fname] = (new_ann, default)

            if overrides:
                Specialized = create_model(
                    schema_cls.__name__ + "ProviderOverride",
                    __base__=schema_cls,
                    **overrides,
                )
                return Specialized

        except Exception:
            # Fall back silently to the original schema class if anything goes wrong
            pass

        return schema_cls

    def _find_override_type(self, typ: Any) -> type | None:
        """
        Given an original type, attempt to resolve a provider override class named
        '<TypeName>Override'. Search order:
          1) Provider module (e.g. simcore.ai.providers.openai)
          2) Provider module's 'schema_overrides' submodule
          3) Provider module's 'base' submodule
          4) Legacy flat path (simcore.ai.providers.{self.name}) if different from provider module
        Returns the override type if found, else None.
        """
        import sys
        from importlib import import_module
        try:
            type_name = getattr(typ, "__name__", None)
            if not type_name:
                return None
            override_name = f"{type_name}Override"

            provider_root = self._provider_namespace_key()
            search_modules = [
                provider_root,
                f"{provider_root}.schema_overrides",
                f"{provider_root}.base",
            ]
            legacy_mod = f"simcore.ai.providers.{self.name}"
            if legacy_mod != provider_root:
                search_modules.append(legacy_mod)

            for modname in search_modules:
                mod = sys.modules.get(modname)
                if mod is None:
                    try:
                        mod = import_module(modname)
                    except Exception:
                        continue
                cand = getattr(mod, override_name, None)
                if isinstance(cand, type):
                    return cand
        except Exception:
            pass
        return None

    def reset_schema_override(self, schema_cls: type) -> type:
        """Provider override to adapt provider schema back to the normalized DTO schema (no-op by default)."""
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