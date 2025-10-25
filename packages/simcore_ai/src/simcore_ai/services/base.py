# simcore_ai/services/base.py
"""
BaseLLMService: Abstract base for LLM-backed AI services.
Provides identity fields (namespace, kind, name) to disambiguate service identity.
The canonical string form is `identity_str` ("namespace.kind.name").
The legacy `namespace` field is deprecated in favor of `identity_str` and `namespace`.

Prompt plan support:
    - The `prompt_plan` is now a **list of canonical section identities ("namespace:kind:name") or PromptSection classes**
      (no role tuples). The service uses a PromptEngine to build a single Prompt aggregate which is then converted into
      request messages (developer/user + extras).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence, Callable
from dataclasses import dataclass, field
from typing import Optional, Protocol

from typing import Any
from simcore_ai.promptkit.resolvers import resolve_section, PromptSectionResolutionError

from simcore_ai.codecs import (
    BaseLLMCodec,
    get_codec as _core_get_codec
)
from simcore_ai.identity import Identity
from .exceptions import ServiceConfigError, ServiceCodecResolutionError
from ..client import AIClient
from ..promptkit import Prompt, PromptEngine, PromptSection
from ..tracing import get_tracer, service_span
from ..types import LLMRequest, LLMRequestMessage, LLMResponse, LLMTextPart

logger = logging.getLogger(__name__)
tracer = get_tracer("simcore_ai.llmservice")


class ServiceEmitter(Protocol):
    def emit_request(self, simulation_id: int, namespace: str, request_dto: LLMRequest) -> None: ...

    def emit_response(self, simulation_id: int, namespace: str, response_dto: LLMResponse) -> None: ...

    def emit_failure(self, simulation_id: int, namespace: str, correlation_id, error: str) -> None: ...

    def emit_stream_chunk(self, simulation_id: int, namespace: str, chunk_dto) -> None: ...

    def emit_stream_complete(self, simulation_id: int, namespace: str, correlation_id) -> None: ...



@dataclass
class BaseLLMService:
    """
    Abstract base for LLM-backed AI services. Handles identity fields (namespace, kind, name)
    and canonical identity string (identity_str = "namespace.kind.name").
    The legacy `namespace` field is deprecated; use `identity_str` and `namespace` instead.
    """
    simulation_id: int  # TODO: remove leak from app
    # Optional identity parts; canonical string is identity_str
    namespace: str | None = None
    kind: str | None = None
    name: str | None = None
    identity_str: str | None = None

    # --- Codec configuration (framework-agnostic) ---
    # Prefer setting codec_class or injecting a codec instance; codec_name is a hint for adapter layers.
    codec_name: str | None = None
    codec_class: type[BaseLLMCodec] | None = None
    _codec_instance: BaseLLMCodec | None = None
    # Backwards-compat alias: if older code sets `codec` to a string, we map it to `codec_name` in __post_init__
    codec: str | None = None

    provider_name: str | None = None

    # Retry/backoff config
    max_attempts: int = 3
    backoff_initial: float = 0.5  # seconds
    backoff_factor: float = 2.0
    backoff_jitter: float = 0.1  # +/- seconds

    prompt_plan: Sequence[Any] = field(default_factory=tuple)
    client: Optional[AIClient] = None

    emitter: ServiceEmitter | None = None
    render_section: Callable[[str, str, object], "asyncio.Future[str]"] | None = None

    # Prompt building (via existing Promptkit engine)
    prompt_engine: PromptEngine | None = None
    prompt: Prompt | None = None

    def __post_init__(self):
        # Build canonical identity string from parts
        ident = Identity(
            namespace=self.namespace or "app",
            kind=self.kind or "service",
            name=(self.name or self.__class__.__name__),
        )
        self.identity_str = ident.to_string()
    async def ensure_prompt(self, simulation) -> Prompt:
        """Ensure `self.prompt` is built once via the configured PromptEngine.

        The plan now contains only canonical section identities ("namespace:kind:name")
        or PromptSection classes. We resolve all specs to classes and pass them to
        the engine's `build_from`/`abuild_from` method, along with a context.
        """
        if self.prompt is not None:
            return self.prompt

        plan = self.get_prompt_plan(simulation)
        section_classes: list[type[PromptSection]] = []
        for spec in plan:
            try:
                SectionCls = resolve_section(spec)
            except PromptSectionResolutionError as exc:
                # Legacy fallback path (string key + render_section)
                if self.render_section and isinstance(spec, str):
                    # Build a synthetic Prompt from the rendered text
                    text = await self.render_section(self.identity_str, spec, simulation)
                    self.prompt = Prompt(instruction=text, message="", extra_messages=[], meta={"fallback": True})
                    return self.prompt
                raise
            section_classes.append(SectionCls)

        engine = self.prompt_engine or PromptEngine
        ctx = {"simulation": simulation, "service": self}

        # Prefer async engine if available
        if hasattr(engine, "abuild_from"):
            prompt: Prompt = await engine.abuild_from(section_classes, context=ctx)  # type: ignore[arg-type]
        else:
            prompt: Prompt = engine.build_from(section_classes, context=ctx)  # type: ignore[arg-type]

        self.prompt = prompt
        return prompt

        # Backwards-compatibility: if legacy `codec` (str) was set and no explicit codec_name, copy it over.
        if self.codec_name is None and isinstance(self.codec, str):
            self.codec_name = self.codec

    # --- Identity helpers -------------------------------------------------
    @property
    def identity(self) -> Identity:
        parts = (self.identity_str or "").split(".")
        o = parts[0] if len(parts) > 0 else None
        b = parts[1] if len(parts) > 1 else None
        n = parts[2] if len(parts) > 2 else None
        return Identity.from_parts(namespace=o, kind=b, name=n)

    @property
    def origin_slug(self) -> str:
        return self.identity.namespace

    @property
    def bucket_slug(self) -> str:
        return self.identity.kind

    @property
    def name_slug(self) -> str:
        return self.identity.name

    def get_codec_name(self, simulation) -> str | None:
        """
        Determine the codec name for telemetry/attrs. This does not resolve a codec class/instance.
        Precedence:
          1) explicit `codec_name`
          2) result of `select_codec()` if it returned a string
          3) legacy `codec` string
        """
        if self.codec_name:
            return self.codec_name
        sel = self.select_codec()
        if isinstance(sel, str):
            return sel
        if isinstance(self.codec, str):
            return self.codec
        return None

    def get_prompt_plan(self, simulation) -> Sequence[Any]:
        """Return the prompt plan to use for this invocation.
        Override in subclasses to make the plan dynamic per simulation.
        Defaults to the class/instance `prompt_plan` attribute.

        Each entry may be:
            - (role, section_spec): where section_spec is a canonical string or PromptSection class/instance
            - section_spec: bare section spec (canonical string or PromptSection), in which case two messages
              (developer/user) are emitted if section returns a Prompt with instruction/message.
        """
        return self.prompt_plan

    async def build_request_messages(self, simulation) -> list[LLMRequestMessage]:
        """Build messages from the engine-produced Prompt aggregate.

        Emits `developer` from `prompt.instruction`, `user` from `prompt.message`,
        and any `(role, text)` pairs from `prompt.extra_messages`.
        """
        prompt = await self.ensure_prompt(simulation)
        messages: list[LLMRequestMessage] = []

        instruction = getattr(prompt, "instruction", None) or ""
        message = getattr(prompt, "message", None) or ""
        extras = getattr(prompt, "extra_messages", None) or []

        if instruction:
            messages.append(LLMRequestMessage(role="developer", content=[LLMTextPart(text=str(instruction))]))
        if message:
            messages.append(LLMRequestMessage(role="user", content=[LLMTextPart(text=str(message))]))
        for role, text in extras:
            if text:
                messages.append(LLMRequestMessage(role=str(role), content=[LLMTextPart(text=str(text))]))

        return messages

    def select_codec(self):
        """
        Hook for concrete services to override custom codec selection.
        May return:
          - a codec instance (preferred when constructed externally),
          - a codec class (framework-agnostic, with class-level schema),
          - or a string codec name (to be resolved by adapter layers, e.g., Django).
        Return None to defer to default resolution.
        """
        return None

    def _get_client(self, codec: BaseLLMCodec | None) -> AIClient:
        """Resolve an AIClient for this service.

        Priority:
          1) Explicit `self.client` injected at construction.
          2) Registry lookup by name (`provider_name` treated as a registered client name).
          3) Registry lookup by provider key (if unique), when `provider_name` looks like a provider slug.
        Note: client resolution spans are emitted by caller.
        """
        if self.client is not None:
            return self.client

        from simcore_ai.client.registry import get_ai_client

        # If no provider_name set, use default client from registry
        if not self.provider_name:
            return get_ai_client()

        # First, try resolving by explicit client name
        try:
            return get_ai_client(name=self.provider_name)
        except Exception:
            pass

        # Next, treat provider_name as a provider key (e.g., "openai")
        try:
            return get_ai_client(provider=self.provider_name)
        except Exception as e:
            raise ServiceConfigError(
                "No AI client available. Either inject `client=...` into the service, "
                "or pre-register a client via simcore_ai.client_registry.create_client(...), "
                "or configure via Django settings AI_PROVIDERS."
            ) from e

    def get_codec(self, simulation=None):
        """
        Resolve a codec using identity-aware precedence:

          1) explicitly set `codec_class` (returned directly)
          2) result of `select_codec()` (class or instance)
          3) registry lookup by identity:
             - if `codec_name` is set, try (namespace, codec_name)
             - otherwise, assemble a composite from identity: f"{identity.kind}:{identity.name}"
             - try exact match, then fall back to `(namespace, "default")`

        Raises:
            ServiceCodecResolutionError: if no codec could be resolved.
        """
        # 1) explicit class wins
        if self.codec_class is not None:
            return self.codec_class

        # 2) subclass-provided selection
        sel = self.select_codec()
        if sel is not None:
            return sel

        # 3) registry lookup (core layer, optional)
        if _core_get_codec is not None:
            ident = self.identity
            # Prefer explicit codec_name if provided
            key_name = (self.codec_name or f"{ident.kind}:{ident.name}")
            codec_obj = _core_get_codec(ident.namespace, key_name)
            if codec_obj:
                return codec_obj
            # Fallback to an namespace default
            codec_obj = _core_get_codec(ident.namespace, "default")
            if codec_obj:
                return codec_obj

        # Nothing found: raise
        raise ServiceCodecResolutionError(
            namespace=getattr(self.identity, 'namespace', None),
            kind=getattr(self.identity, 'kind', None),
            name=getattr(self.identity, 'name', None),
            codec_name=self.codec_name,
            service=self.__class__.__name__,
        )

    async def build_request(self) -> LLMRequest:
        """Build a provider-agnostic **LLMRequest** for this service.

        Django-facing services are expected to override this method to assemble
        the final request (messages, response format, codec identity, etc.).

        The base implementation exists only to satisfy type-checkers for callers
        (e.g., the Django runner) and **must** be overridden in concrete services.
        """
        raise NotImplementedError("BaseLLMService.build_request() must be implemented by concrete services")

    async def run(self, simulation) -> LLMResponse | None:
        """
        Run the service for a simulation, emitting request/response events.
        Uses identity fields (namespace, kind, name) and canonical identity_str.
        """
        if not self.emitter:
            raise ServiceConfigError("emitter not provided")
        attrs = {
            "identity": self.identity_str,
            "simulation_id": getattr(simulation, "id", self.simulation_id),
            "codec_name": self.get_codec_name(simulation) or "unknown",
        }
        logger.info("llm.service.start", extra=attrs)
        async with service_span(f"LLMService.{self.__class__.__name__}.run", **attrs):
            messages = await self.build_request_messages(simulation)
            req = LLMRequest(
                messages=messages,
                stream=False,
            )
            # Stamp operation identity onto request
            ident = self.identity
            req.namespace = ident.namespace
            req.kind = ident.kind
            req.name = ident.name

            # Codec resolution and attach codec identity and response format
            codec = self.get_codec(simulation)
            key_name = (self.codec_name or f"{ident.kind}:{ident.name}")
            codec_identity = f"{ident.namespace}.{key_name.replace(':', '.')}"
            req.codec_identity = codec_identity
            schema_cls = getattr(codec, "response_format_cls", None) or getattr(codec, "schema_cls", None) or getattr(
                codec, "output_model", None)
            if schema_cls is not None:
                req.response_format_cls = schema_cls
            if hasattr(codec, "get_response_format"):
                try:
                    rf = codec.get_response_format()
                    if rf is not None:
                        req.response_format = rf
                except Exception:
                    pass

            client = self._get_client(codec)
            self.emitter.emit_request(simulation.id, self.identity_str, req)

            attempt = 1
            last_exc: Exception | None = None
            while attempt <= max(1, self.max_attempts):
                try:
                    resp: LLMResponse = await client.send_request(req)
                    # Copy codec identity if missing and echo operation identity
                    if getattr(resp, "codec_identity", None) is None:
                        resp.codec_identity = req.codec_identity
                    resp.namespace, resp.kind, resp.name = ident.namespace, ident.kind, ident.name
                    # Wire correlation link
                    if getattr(resp, "request_correlation_id", None) is None:
                        resp.request_correlation_id = req.correlation_id
                    self.emitter.emit_response(simulation.id, self.identity_str, resp)
                    await self.on_success(simulation, resp)
                    logger.info("llm.service.success",
                                extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt})
                    return resp
                except Exception as e:
                    last_exc = e
                    if attempt >= max(1, self.max_attempts):
                        self.emitter.emit_failure(simulation.id, self.identity_str, req.correlation_id, str(e))
                        await self.on_failure(simulation, e)
                        logger.exception("llm.service.error",
                                         extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt})
                        raise
                    # backoff then retry
                    logger.warning("llm.service.retrying",
                                   extra={**attrs, "attempt": attempt, "max_attempts": self.max_attempts})
                    await self._backoff_sleep(attempt)
                    attempt += 1

    async def run_stream(self, simulation):
        """
        Run the service for a simulation, streaming responses and emitting events.
        Uses identity fields (namespace, kind, name) and canonical identity_str.
        """
        if not self.emitter:
            raise ServiceConfigError("emitter not provided")
        attrs = {
            "identity": self.identity_str,
            "simulation_id": getattr(simulation, "id", self.simulation_id),
            "codec_name": self.get_codec_name(simulation) or "unknown",
        }
        async with service_span(f"LLMService.{self.__class__.__name__}.run_stream", **attrs):
            messages = await self.build_request_messages(simulation)
            req = LLMRequest(
                messages=messages,
                stream=True,
            )
            # Stamp operation identity onto request
            ident = self.identity
            req.namespace = ident.namespace
            req.kind = ident.kind
            req.name = ident.name

            # Codec resolution and attach codec identity and response format
            codec = self.get_codec(simulation)
            key_name = (self.codec_name or f"{ident.kind}:{ident.name}")
            codec_identity = f"{ident.namespace}.{key_name.replace(':', '.')}"
            req.codec_identity = codec_identity
            schema_cls = getattr(codec, "response_format_cls", None) or getattr(codec, "schema_cls", None) or getattr(
                codec, "output_model", None)
            if schema_cls is not None:
                req.response_format_cls = schema_cls
            if hasattr(codec, "get_response_format"):
                try:
                    rf = codec.get_response_format()
                    if rf is not None:
                        req.response_format = rf
                except Exception:
                    pass

            client = self._get_client(codec)
            self.emitter.emit_request(simulation.id, self.identity_str, req)

            attempt = 1
            started = False
            while attempt <= max(1, self.max_attempts) and not started:
                try:
                    async for chunk in client.stream_request(req):
                        started = True
                        self.emitter.emit_stream_chunk(simulation.id, self.identity_str, chunk)
                    # completed stream without error
                    # When stream completes, emit_stream_complete; attach codec identity and echo operation identity if possible
                    # (If a final response object is available, set fields accordingly)
                    # Since emit_stream_complete doesn't take a response, we can't set fields on chunk, but could emit here if needed
                    self.emitter.emit_stream_complete(simulation.id, self.identity_str, req.correlation_id)
                    return
                except Exception as e:
                    # If stream hasn't started yet, we can retry; otherwise treat as terminal
                    if started or attempt >= max(1, self.max_attempts):
                        self.emitter.emit_failure(simulation.id, self.identity_str, req.correlation_id, str(e))
                        await self.on_failure(simulation, e)
                        logger.exception("llm.service.stream.error",
                                         extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt})
                        raise
                    logger.warning("llm.service.stream.retrying",
                                   extra={**attrs, "attempt": attempt, "max_attempts": self.max_attempts})
                    await self._backoff_sleep(attempt)
                    attempt += 1

    async def on_success(self, simulation, resp: LLMResponse) -> None:
        ...

    async def on_failure(self, simulation, err: Exception) -> None:
        ...
