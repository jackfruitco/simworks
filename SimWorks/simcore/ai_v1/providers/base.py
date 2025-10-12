# simcore/ai_v1/providers/base.py
from __future__ import annotations

import importlib
import inspect
import logging
import re
import types
from abc import ABC, abstractmethod
from typing import AsyncIterator, Any, Iterable, Optional, Protocol, get_origin, get_args, ClassVar, Annotated, Union
from weakref import WeakKeyDictionary

from pydantic import TypeAdapter, Field, create_model

# Slim, LLM-facing projections
from simcore.ai_v1.schemas.output_types import (
    OutputMessageItem,
    OutputMetafieldItem,
    FullOutputMetafieldItem,
)
# DTOs (single source of truth)
from simcore.ai_v1.schemas.types import (
    LLMRequest,
    LLMResponse,
    StreamChunk,
    MessageItem,
    MetafieldItem,
    AttachmentItem, ToolItem,
)

logger = logging.getLogger(__name__)


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
    _override_index_cache: ClassVar[dict[str, dict[str, dict]]] = {}

    @classmethod
    def clear_schema_cache(cls, provider_namespace: str | None = None) -> None:
        """Clear the specialized schema cache.

        If `provider_namespace` is provided, it can be either the full namespace
        (e.g., 'simcore.ai_v1.providers.openai') or just the label (e.g., 'openai').
        """
        if provider_namespace:
            # Accept both "openai" and "simcore.ai_v1.providers.openai"
            if "." not in provider_namespace:  # looks like just a label
                provider_namespace = f"simcore.ai_v1.providers.{provider_namespace}"
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
        Return a stable provider namespace like 'simcore.ai_v1.providers.<label>'
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
        slim_metadata = TypeAdapter(list[FullOutputMetafieldItem]).validate_python(
            raw_metadata if isinstance(raw_metadata, list) else []
        )

        # 5) Promote to DTOs (domain)
        messages = TypeAdapter(list[MessageItem]).validate_python(
            [m.model_dump() for m in slim_messages]
        )
        metadata = TypeAdapter(list[MetafieldItem]).validate_python(
            [m.model_dump() for m in slim_metadata]
        )

        # TODO: remove if keeping slim DTO validation first
        # messages = TypeAdapter(list[MessageItem]).validate_python(
        #     raw_messages if isinstance(raw_messages, list) else []
        # )
        # metadata = TypeAdapter(list[MetafieldItem]).validate_python(
        #     raw_metadata if isinstance(raw_metadata, list) else []
        # )

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

    def apply_schema_overrides(self, schema_cls: type | None) -> type | None:
        if schema_cls is None:
            return None

        mod = None
        for modname in (
                f"{self._provider_namespace_key()}.schema_overrides",
                f"{self._provider_namespace_key()}.type_overrides",
                f"{self._provider_namespace_key()}.schema",
                f"{self._provider_namespace_key()}.overrides",
                f"{self._provider_namespace_key()}.types",
                f"{self._provider_namespace_key()}.base",
                f"{self._provider_namespace_key()}",
        ):
            try:
                mod = importlib.import_module(modname)
                break
            except Exception:
                continue
        if mod is None:
            logger.warning(
                f"provider '{self.name}'::  failed to import overrides module -- skipping"
            )
            return schema_cls

        logger.debug(f"provider '{self.name}':: using {mod.__name__} to discover overrides")

        model_fields = getattr(schema_cls, "model_fields", None)
        if not model_fields:
            return schema_cls

        # helper: get a type name token for override lookup
        def _inner_token_from(field_name: str, ann_obj) -> str | None:
            # prefer real inner class name
            origin = get_origin(ann_obj)
            args = get_args(ann_obj)
            if origin is list and args:
                inner = args[0]
                # unwrap Annotated
                if get_origin(inner) is Annotated:
                    inner = get_args(inner)[0]
                name = getattr(inner, "__name__", None)
                if name:
                    logger.debug(f"found inner token '{name}' for `{field_name}`")
                    if name != "Union": return name
            # fallback to string annotation slice if available
            logger.debug(f"no inner token found for `{field_name}` or found 'Union' - trying string annotation slice")
            try:
                ann_str = schema_cls.__annotations__[field_name]
                m = re.search(r"\[([\w\.]+)\]", ann_str)
                if m:
                    name = m.group(1)
                    logger.debug(f"found inner token {name} for {field_name}` using string annotation slice")
                    return name
            except Exception:
                logger.warning(f"failed to find inner token for {field_name}`")
            return None

        overrides: dict[str, tuple[object, Field]] = {}

        for fname, field in model_fields.items():
            ann = getattr(field, "annotation", None)
            if ann is None:
                continue

            origin = get_origin(ann)
            args = get_args(ann)
            new_ann = None

            # case: list[T]
            if origin is list and args:
                token = _inner_token_from(fname, ann)  # e.g., "OutputMetafieldItem"
                if token:
                    override_name = f"{token}Override"
                    override_cls = getattr(mod, override_name, None)
                    if isinstance(override_cls, type):
                        new_ann = list[override_cls]  # keep array shape, avoid oneOf

            # case: direct T (rare in your schemas, but supported)
            else:
                # unwrap Annotated
                direct = ann
                if get_origin(direct) is Annotated:
                    direct = get_args(direct)[0]
                token = getattr(direct, "__name__", None)
                if not token:
                    # fallback to string type name if present (no [] in this shape)
                    token = schema_cls.__annotations__.get(fname, None)
                if token:
                    override_name = f"{token}Override" if isinstance(token, str) else f"{token}Override"
                    override_cls = getattr(mod, override_name, None)
                    if isinstance(override_cls, type):
                        new_ann = override_cls

            if new_ann is not None:
                default = Field(...) if bool(getattr(field, "is_required", False)) else Field(
                    getattr(field, "default", None))
                overrides[fname] = (new_ann, default)

        if not overrides:
            logger.debug(f"client found no overrides for {schema_cls.__name__} in {self.name}`")
            return schema_cls

        logger.debug(f"client found overrides for {schema_cls.__name__} in {self.name}`: {overrides}")
        Specialized = create_model(
            schema_cls.__name__ + "ProviderOverride",
            __base__=schema_cls,
            **overrides,
        )
        logger.debug(f"client built new schema with override(s) for {schema_cls.__name__} in {self.name}`: {repr(Specialized)}")
        return Specialized


        # cache = self._schema_cache.setdefault(provider_key, WeakKeyDictionary())
        # cached = cache.get(schema_cls)
        # if cached is not None:
        #     logger.debug(f"client found cached override for {schema_cls.__name__} in {provider_key}`")
        #     return cached
        # override = self._schema_to_provider(schema_cls)
        # logger.debug(f"client built override for {schema_cls.__name__} in {provider_key}`")
        # cache[schema_cls] = override
        # logger.debug(f"client cached override for {schema_cls.__name__} in {provider_key}`")
        return override

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
        Uses a precomputed override index for efficiency.
        """
        try:
            model_fields = getattr(schema_cls, "model_fields", None)
            if not model_fields:
                return schema_cls

            idx = self._get_override_index()
            type_overrides = idx["type_overrides"]
            union_override_map = idx["union_override_map"]

            overrides: dict[str, tuple[Any, Any]] = {}

            for fname, field in model_fields.items():
                ann = getattr(field, "annotation", None)
                if ann is None:
                    continue
                new_ann = None
                origin = get_origin(ann)
                args = get_args(ann)

                # Handle list[T] and list[Union[...]]
                if origin is list and args:
                    inner = args[0]
                    # Unwrap Annotated if present
                    inner_ann = inner
                    if get_origin(inner_ann) is Annotated:
                        inner_ann = get_args(inner_ann)[0]
                    inner_origin = get_origin(inner_ann)
                    inner_args = get_args(inner_ann)
                    # If inner is a Union (including | syntax)
                    if inner_origin in (Union, types.UnionType):
                        members = [m for m in inner_args]
                        # Unwrap Annotated from each member
                        member_types = []
                        for m in members:
                            mt = m
                            if get_origin(mt) is Annotated:
                                mt = get_args(mt)[0]
                            if isinstance(mt, type):
                                member_types.append(mt)
                        # --- REPLACE union_override_map lookup with best-match logic ---
                        if member_types:
                            key = frozenset(member_types)
                            # Try exact match first
                            override = union_override_map.get(key)
                            # Fallback: try superset/subset best-effort match
                            if override is None:
                                for k, ov in union_override_map.items():
                                    if key.issubset(k) or k.issubset(key):
                                        override = ov
                                        break
                            if override is not None:
                                new_ann = list[override]
                                if logger.isEnabledFor(logging.DEBUG):
                                    logger.debug(
                                        "schema override: field '%s' union members matched %s -> %s",
                                        fname, {t.__name__ for t in member_types}, override.__name__,
                                    )
                            elif logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    "schema override: no union match for field '%s' with members %s",
                                    fname, [getattr(t, '__name__', str(t)) for t in member_types],
                                )
                        # --- END PATCH ---
                    elif isinstance(inner_ann, type) and inner_ann in type_overrides:
                        new_ann = list[type_overrides[inner_ann]]
                else:
                    # Handle direct type T (unwrap Annotated)
                    direct = ann
                    if get_origin(direct) is Annotated:
                        direct = get_args(direct)[0]
                    if isinstance(direct, type) and direct in type_overrides:
                        new_ann = type_overrides[direct]

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

    def _iter_provider_modules_for_overrides(self):
        """
        Yield imported modules to search for override classes, in provider-specific order.
        """
        import sys
        from importlib import import_module
        provider_root = self._provider_namespace_key()
        modnames = [
            provider_root,
            f"{provider_root}.schema_overrides",
            f"{provider_root}.overrides",
            f"{provider_root}.type_overrides",
            f"{provider_root}.types",
            f"{provider_root}.base",
        ]
        legacy = f"simcore.ai_v1.providers.{self.name}"
        if legacy != provider_root:
            modnames.append(legacy)
        for modname in modnames:
            mod = sys.modules.get(modname)
            if mod is None:
                try:
                    mod = import_module(modname)
                except Exception:
                    continue
            if mod is not None:
                yield mod

    def _get_override_index(self):
        """
        Returns a dict with 'type_overrides' and 'union_override_map' for this provider root.
        """
        provider_root = self._provider_namespace_key()
        cache = self._override_index_cache
        if provider_root in cache:
            return cache[provider_root]
        # Build index
        override_classes = []
        for mod in self._iter_provider_modules_for_overrides():
            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if name.endswith("Override"):
                    override_classes.append(obj)
        # Build type_overrides
        type_overrides = {}
        try:
            from simcore.ai_v1.schemas import output_types as outputs
        except Exception:
            outputs = None
        for override_cls in override_classes:
            base_name = override_cls.__name__[:-8]
            base = getattr(outputs, base_name, None) if outputs else None
            if isinstance(base, type):
                type_overrides[base] = override_cls
        # Build union_override_map
        union_override_map = {}
        for override_cls in override_classes:
            model_fields = getattr(override_cls, "model_fields", None)
            if not model_fields:
                continue
            inner_types = set()
            for field in model_fields.values():
                ann = getattr(field, "annotation", None)
                origin = get_origin(ann)
                args = get_args(ann)
                if origin is list and args:
                    inner = args[0]
                    # Unwrap Annotated if present
                    if get_origin(inner) is Annotated:
                        inner = get_args(inner)[0]
                    if isinstance(inner, type):
                        inner_types.add(inner)
            if inner_types:
                union_override_map[frozenset(inner_types)] = override_cls
        idx = {"type_overrides": type_overrides, "union_override_map": union_override_map}
        cache[provider_root] = idx
        return idx

    def _find_override_type(self, typ: Any) -> type | None:
        """
        Given an original type, attempt to resolve a provider override class named
        '<TypeName>Override'. Search order:
          1) Provider module (e.g. simcore.ai_v1.providers.openai)
          2) Provider module's 'schema_overrides' submodule
          3) Provider module's 'base' submodule
          4) Legacy flat path (simcore.ai_v1.providers.{self.name}) if different from provider module
        Returns the override type if found, else None.
        """
        import sys
        from importlib import import_module
        logger.debug(f"client checking for override for {typ} in provider {self.name}")
        try:
            type_name = getattr(typ, "__name__", None)
            if not type_name:
                return None
            override_name = f"{type_name}Override"
            logger.debug(f"...looking for cls for {override_name}")

            provider_root = self._provider_namespace_key()
            search_modules = [
                provider_root,
                f"{provider_root}.schema_overrides",
                f"{provider_root}.type_overrides",
                f"{provider_root}.overrides",
                f"{provider_root}.types",
                f"{provider_root}.base",
            ]
            legacy_mod = f"simcore.ai_v1.providers.{self.name}"
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
                    logger.debug(f"...found override for {typ} in {modname}: {cand}")
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
