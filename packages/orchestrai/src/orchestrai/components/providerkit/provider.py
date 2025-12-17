# orchestrai/components/providerkit/base.py
import inspect
import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any, AsyncIterator, ClassVar, Optional, Protocol, overload

from pydantic import BaseModel, ConfigDict, Field, field_validator
from slugify import slugify


from .exceptions import ProviderConfigurationError
from ...identity import IdentityMixin
from ...tracing import service_span_sync
from ...types import (
    Request, Response, StreamChunk,
    LLMToolCall, BaseLLMTool,
    OutputItem, UsageContent, ContentRole, OutputTextContent, OutputToolResultContent
)

# NOTE:
#   ALLOWED_PROVIDER_KINDS is an internal allowlist of provider namespaces
#   (e.g. "openai", "azure_openai", "local"). It is used to validate
#   configuration values (ProviderConfig.backend, etc.) without importing
#   contrib modules, avoiding circular imports.
ALLOWED_PROVIDER_KINDS: set[str] = {
    "openai",
    "azure_openai",
    "local",
}

logger = logging.getLogger(__name__)

__all__ = ["BaseProvider", "ProviderConfig"]


class BaseProvider(IdentityMixin, ABC):
    """
    Represents an abstract base class for providers defining core attributes and the
    contract for both non-streaming and streaming operations.

    This class standardizes identity and configuration fields and provides a contract for
    concrete backend implementations. Providers are expected to implement asynchronous
    methods for both standard and streaming operations. Additionally, this class provides
    tools for handling profile variables scoped to the backend's alias.

    Contracts for methods `call` and `stream` are abstract and must be implemented by
    subclasses to integrate backend-specific functionalities.

    :ivar alias: Unique alias for the backend.
    :type alias: str
    :ivar provider: Name of the backend.
    :type provider: str
    :ivar description: Optional description of the backend.
    :type description: str | None
    :ivar slug: Unique slug for the backend, derived or set explicitly.
    :type slug: str
    :ivar environment: Optional profile in which the backend operates.
    :type profile: str | None
    :ivar api_key: Optional API key for authenticating requests to the backend.
    :type api_key: str | None
    """
    # Instance attributes
    alias: str
    provider: str
    description: str | None
    slug: str
    environment: str | None
    api_key: str | None

    # Class-level default
    api_surface: ClassVar[str | None ] = None
    api_version: ClassVar[str | None] = None
    api_key_required: ClassVar[bool] = False

    _tool_adapter: Optional["BaseProvider.ToolAdapter"] = None

    def __init__(
            self,
            *,
            alias: str,
            provider: str,
            api_key_required: bool | None = None,
            api_key: str | None = None,
            description: str | None = None,
            slug: str | None = None,
            profile: str | None = None,
            **_: object,
    ) -> None:
        """
        Common initializer for providers.

        Only standardizes identity/config fields; backend-specific params
        are handled by subclasses.
        """

        # --- alias ---
        if not alias:
            raise ProviderConfigurationError(
                "ALIAS must be provided and non-empty."
            )
        self.alias = alias

        # --- backend ---
        if not provider:
            raise ProviderConfigurationError(
                "PROVIDER must be provided and non-empty."
            )
        self.provider = provider

        # --- api_key_required ---
        if api_key_required is None:
            env_val = self.get_env_for_alias("API_KEY_REQUIRED", default=None)
            if env_val is None:
                api_key_required = self.api_key_required
            else:
                api_key_required = self._coerce_bool(env_val)
        self.api_key_required = api_key_required

        # --- api_key ---
        if api_key is None and self.api_key_required:
            api_key = self.get_env_for_alias("API_KEY")

        if self.api_key_required and not api_key:
            raise ProviderConfigurationError(
                "API_KEY must be provided for this backend. "
                "Did you forget an ENV variable?"
            )

        self.api_key = api_key

        # --- profile ---
        profile = profile or self.get_env_for_alias("ENVIRONMENT", default=None)
        self.environment = profile

        # --- slug ---
        if slug is not None:
            # Use the property setter, which will slugify the provided value.
            self.slug = slug
        else:
            # Trigger default behavior in the setter (identity if present, otherwise alias).
            self.slug = None

        # --- description ---
        if description is None:
            env_label = profile or "<unspecified>"
            description = f"{provider.title()} in {env_label} profile."
        self.description = description

    def _coerce_bool(self, value: str | bool | None) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIProvider {str(self.provider)}>"

    @property
    def slug(self):
        """Get backend slug."""
        return self._slug

    @slug.setter
    def slug(self, value: str | None = None) -> None:
        """Set Provider slug as provided value, or derive from identity/alias."""
        if value:
            base = value.strip()
        else:
            ident = getattr(self, "identity", None)
            if ident is not None:
                base = ident.as_str
            else:
                base = getattr(self, "alias", self.__class__.__name__)
        self._slug = slugify(base)

    @overload
    def get_env_for_alias(self, env_var_name: str) -> str | None:
        ...

    @overload
    def get_env_for_alias(self, env_var_name: str, default: object) -> Any:
        ...

    def get_env_for_alias(self, env_var_name: str, default: object = None) -> Any:
        """Fetches an profile variable value for the given alias.

        Constructs the full key by combining the
        provided alias and the `env_var_name`. If the constructed profile variable is not found, a
        default value is returned. Converts specific string values to boolean where applicable.

        :param env_var_name: The name of the profile variable to retrieve.
        :param default: The default value to return if the profile variable is not found.
        :return: The profile variable value, a boolean if conversion is possible, or the default value otherwise.
        """
        if env_var_name.startswith("_"):
            env_var_name = env_var_name[1:]

        key = f"{self.alias.upper()}_{env_var_name.upper()}"
        value = os.getenv(key, default)
        if value is default:
            logger.debug(f"Env var not found for alias: {key}")

        if str(value).lower() in ("true", "1", "-1", "y", "yes"):
            return True
        elif str(value).lower() in ("false", "0", "n", "no"):
            return False
        return value

    @classmethod
    def from_cfg(cls, cfg: dict) -> BaseProvider:
        """Construct a backend from a configuration dictionary."""
        return cls(**cfg)
    # ---------------------------------------------------------------------
    # Public backend API (async-first contracts)
    # ---------------------------------------------------------------------
    # Providers should implement **async** methods for both non-stream and stream modes.
    # If you have a sync-only SDK, you may still integrate by running the sync call in a thread
    # (the OrcaClient will do this via `asyncio.to_thread` when it detects a sync `call`).
    #
    # Streaming MUST be async: `async def stream(self, req) -> AsyncIterator[StreamChunk]`.
    # Sync streaming is not supported by the client adapter.
    @abstractmethod
    async def call(self, req: Request, timeout: float | None = None) -> Response:
        """Canonical async, non-streaming request.

        Implementations MUST be async when subclassing BaseProvider. If your concrete
        backend relies on a sync-only SDK, consider not subclassing or ensure your
        implementation awaits on an internal `asyncio.to_thread(...)` call to offload
        the blocking work. The `OrcaClient` also provides a safety net when interacting
        with backend-like objects that expose a sync `call(...)` by running them in a
        worker thread to avoid blocking the event loop.
        """
        ...

    @abstractmethod
    async def stream(self, req: Request) -> AsyncIterator[StreamChunk]:
        """Canonical async streaming interface.

        MUST be implemented as an async generator yielding `StreamChunk` items.
        The core client requires an async `stream(...)` and will raise if missing.
        """
        ...

    async def healthcheck(self, *, timeout: float | None = None) -> tuple[bool, str]:
        """
        Default backend healthcheck.

        Returns:
            (ok, detail): ok=True if healthy, detail is a short message.
        """
        # Default behavior (safe no-op): just report the backend is constructed.
        # Concrete providers SHOULD override with a minimal live call.
        try:
            return True, f"{getattr(self, 'name', self.__class__.__name__)} ready"
        except Exception as exc:
            return False, f"init error: {exc!s}"

    def _provider_namespace_key(self) -> str:
        """
        Return a stable backend namespace like 'simcore.ai_v1.providers.<label>'
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
    # Normalization/adaptation (backend-agnostic core + backend hooks)
    # ---------------------------------------------------------------------
    def adapt_response(
            self, resp: Any, *, output_schema_cls: type | None = None
    ) -> Response:
        """
        Provider-agnostic response construction pipeline.

        Steps:
          1) Extract primary assistant text (if any) and add as an OutputItem with OutputTextContent.
          2) Inspect backend-specific output (images/tools) and convert into normalized tool calls and
             OutputToolResultContent input.
          3) Attach usage and provider_meta.

        Args:
            resp: Provider-specific response object
            output_schema_cls: (unused, for call-site compatibility)
        """
        # output_schema_cls is retained for call-site compatibility but is no longer used.
        _ = output_schema_cls
        with service_span_sync(
                "simcore.response.adapt",
                attributes={
                    "simcore.backend.backend": getattr(self, "backend", self.__class__.__name__),
                    "simcore.backend.profile": getattr(self, "profile", None),
                    "simcore.backend.api_family": getattr(self, "api_family", None),
                },
        ) as span:
            messages: list[OutputItem] = []
            tool_calls: list[LLMToolCall] = []

            # 1) Primary assistant text
            text_out = self._extract_text(resp)
            if text_out:
                messages.append(
                    OutputItem(
                        role=ContentRole.ASSISTANT,
                        content=[OutputTextContent(text=text_out)],
                    )
                )

            # 2) Provider output -> tool results / attachments
            from uuid import uuid4
            for obj in self._extract_outputs(resp) or []:
                try:
                    # 3a) Let the backend fully normalize arbitrary tool output (preferred path)
                    pair = self._normalize_tool_output(obj)
                    if pair is not None:
                        call, part = pair
                        tool_calls.append(call)
                        messages.append(
                            OutputItem(
                                role=ContentRole.ASSISTANT,
                                content=[part],
                            )
                        )
                        continue

                    # 3b) Generic fallback: image-like results
                    if self._is_image_output(obj):
                        call_id = getattr(obj, "id", None) or str(uuid4())
                        tool_calls.append(LLMToolCall(call_id=call_id, name="image_generation", arguments={}))
                        b64 = getattr(obj, "result", None) or getattr(obj, "b64", None)
                        mime = getattr(obj, "mime_type", None) or "image/png"
                        if b64:
                            messages.append(
                                OutputItem(
                                    role=ContentRole.ASSISTANT,
                                    content=[
                                        OutputToolResultContent(
                                            call_id=call_id,
                                            mime_type=mime,
                                            data_b64=b64,
                                        )
                                    ],
                                )
                            )
                        continue

                    # 3c) Unrecognized output item: ignore silently but keep diagnostics enabled
                    logger.debug("backend '%s':: unhandled output item type: %s", getattr(self, "name", self),
                                 type(obj).__name__)
                except Exception:
                    logger.debug("backend '%s':: failed to adapt an output item; skipping",
                                 getattr(self, "name", self), exc_info=True)
                    continue

            # Attach summary attributes for observability
            try:
                span.set_attribute("simcore.parts.count", len(messages))
                span.set_attribute("simcore.tool_calls.count", len(tool_calls))
                span.set_attribute("simcore.text.present", bool(text_out))
            except Exception:
                pass

            usage_data = self._extract_usage(resp)
            usage = None
            if usage_data:
                try:
                    usage = UsageContent.model_validate(usage_data)
                except Exception:
                    usage = UsageContent(**usage_data) if isinstance(usage_data, dict) else None

            return Response(
                output=messages,
                usage=usage,
                tool_calls=tool_calls,
                provider_meta=self._extract_provider_meta(resp),
            )

    # ---------------------------------------------------------------------
    # Provider-specific Response HOOKS (override in concrete providers)
    # ---------------------------------------------------------------------
    @abstractmethod
    def _extract_text(self, resp: Any) -> Optional[str]:
        """Return the backend's primary text output, if any."""
        ...

    @abstractmethod
    def _extract_outputs(self, resp: Any) -> Iterable[Any]:
        """Yield backend output items (images, tool calls, etc.)."""
        ...

    @abstractmethod
    def _is_image_output(self, item: Any) -> bool:
        """Return True if the output item represents an image generation result."""
        ...

    @abstractmethod
    def _extract_usage(self, resp: Any) -> dict:
        """Return a normalized usage dict (input/output/total tokens, etc.)."""
        ...

    @abstractmethod
    def _extract_provider_meta(self, resp: Any) -> dict:
        """Return backend-specific metadata for diagnostics (model, ids, raw dump)."""
        ...

    def _normalize_tool_output(self, item: Any) -> Optional[tuple[LLMToolCall, OutputToolResultContent]]:
        """
        Convert a backend-native output item (tool call/result, images, audio, etc.) into a
        normalized (LLMToolCall, OutputToolResultContent) pair. Return None if the item is not a tool
        output you recognize, and the base class will try generic fallbacks.
        """
        return None

    # ---------------------------------------------------------------------
    # Tools
    # ---------------------------------------------------------------------
    class ToolAdapter(Protocol):
        @abstractmethod
        def to_provider(self, tool: BaseLLMTool) -> Any: ...

        @abstractmethod
        def from_provider(self, tool: Any) -> BaseLLMTool: ...

    # -- Tool adaptation helpers -------------------------------------------------
    def set_tool_adapter(self, adapter: "BaseProvider.ToolAdapter") -> None:
        """Register a ToolAdapter for this backend.
        Concrete providers can call this in __init__, or the caller can inject one.
        """
        self._tool_adapter = adapter

    def _tools_to_provider(self, tools: Optional[list[BaseLLMTool]]) -> Optional[list[Any]]:
        """Convert our DTO BaseLLMTool list into backend-native tool specs.
        Returns None if no adapter is registered or tools is falsy.
        """
        if not tools or not getattr(self, "_tool_adapter", None):
            return None
        return [self._tool_adapter.to_provider(t) for t in tools]  # type: ignore[attr-defined]

    def _tools_from_provider(self, provider_tools: Optional[Iterable[Any]]) -> list[BaseLLMTool]:
        """Convert backend-native tool specs into our BaseLLMTool DTOs.
        Returns an empty list if no adapter is registered or input is falsy.
        """
        if not provider_tools or not getattr(self, "_tool_adapter", None):
            return []
        return [self._tool_adapter.from_provider(t) for t in provider_tools]  # type: ignore[attr-defined]

    # ---------------------------------------------------------------------
    # Utilities
    # ---------------------------------------------------------------------

    def supports_streaming(self) -> bool:
        """Return True if this backend exposes an async `stream` method."""
        try:
            return inspect.iscoroutinefunction(getattr(self, "stream", None))
        except Exception:
            return False

    # ---------------------------------------------------------------------
    # Rate-limit observability
    # ---------------------------------------------------------------------
    def record_rate_limit(
            self,
            *,
            status_code: int | None = None,
            retry_after_ms: int | None = None,
            detail: str | None = None,
    ) -> None:
        """Emit a short spaxn when a rate limit is encountered.

        Providers may call this directly; the OrcaClient also tries to call it when
        it detects a 429-like error from the SDK/HTTP layer.
        """
        try:
            attrs = {
                "simcore.provider_name": getattr(self, "name", self.__class__.__name__),
                "http.status_code": status_code if status_code is not None else 429,
            }
            pk = getattr(self, "provider_key", None)
            pl = getattr(self, "provider_label", None)
            if pk is not None:
                attrs["simcore.provider_key"] = pk
            if pl is not None:
                attrs["simcore.provider_label"] = pl
            if retry_after_ms is not None:
                attrs["retry_after_ms"] = retry_after_ms

            with service_span_sync("simcore.backend.ratelimit", attributes=attrs):
                if detail:
                    logger.debug("%s rate-limited: %s", self.name, detail)
        except Exception:  # pragma: no cover - never break on tracing errors
            pass


class ProviderConfigProto(Protocol):
    name: str = ...


class ProviderConfig(BaseModel):
    """Provider wiring (STRICT).

    Fields:
        alias:   User-facing alias / connection name (e.g. "default", "openai", "openai-low-cost").
        backend: Backend identity string registered in the provider_backends registry,
                 e.g. "provider.openai.responses.backend".
        label:   Optional disambiguator for multiple accounts/environments (e.g., "prod", "staging").
        base_url:     Optional custom endpoint.
        api_key:      Direct secret value (already resolved). Prefer env usage in production.
        api_key_env:  Name of environment variable to read the key from (resolved later in the factory).
        model:        Provider's default model for this wiring (clients may override).
        organization: Optional vendor-specific org/account identifier.
        timeout_s:    Default request timeout (seconds). Clients may override.

    Notes:
        - Extra keys are forbidden to catch mistakes early.
        - Secrets precedence is applied OUTSIDE this model (in the backend factory):
          client override -> backend value -> os.environ[api_key_env] (if set) -> None
    """

    alias: str = Field(..., min_length=1)
    backend: str = Field(..., min_length=1)

    label: Optional[str] = None

    base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_key_env: Optional[str] = None

    model: Optional[str] = None
    organization: Optional[str] = None
    timeout_s: Optional[float] = None

    model_config = ConfigDict(extra="forbid")

    @staticmethod
    def _validate_backend_identity(v: str) -> str:
        """Validate a backend identity string like 'provider.openai.responses.backend'."""
        parts = v.split(".")
        if len(parts) != 4:
            raise ProviderConfigurationError(
                f"BACKEND must be 'domain.namespace.group.name', e.g. 'provider.openai.responses.backend' (got {v!r})"
            )

        domain, namespace, group, name = parts

        if not domain or not namespace or not group or not name:
            raise ProviderConfigurationError(
                f"BACKEND identity '{v}' must not contain empty segments"
            )

        if namespace not in ALLOWED_PROVIDER_KINDS:
            raise ProviderConfigurationError(
                f"Unknown backend namespace {namespace!r} in BACKEND identity {v!r}. "
                f"Allowed namespaces: {sorted(ALLOWED_PROVIDER_KINDS)}"
            )

        if name != "backend":
            raise ProviderConfigurationError(
                f"BACKEND identity must end in '.backend' (got {v!r})"
            )

        return v

    @field_validator("alias")
    @classmethod
    def validate_alias(cls, v: str) -> str:
        """Alias is now a simple, non-empty label (no identity semantics)."""
        v = v.strip()
        if not v:
            raise ProviderConfigurationError("alias must be a non-empty string")
        return v

    @field_validator("backend")
    @classmethod
    def validate_backend(cls, v: str) -> str:
        """Validate backend identity string against ALLOWED_PROVIDER_KINDS and shape."""
        return cls._validate_backend_identity(v)
