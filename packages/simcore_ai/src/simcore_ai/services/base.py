# simcore_ai/services/base.py
from __future__ import annotations

import asyncio
import logging
from ..tracing import get_tracer, service_span
from dataclasses import dataclass, field
from typing import Sequence, Optional, Protocol, Callable

from simcore_ai.types.identity import Identity
from simcore_ai.codecs import (
    BaseLLMCodec,
    get_codec as _core_get_codec
)
from simcore_ai.exceptions import ServiceConfigError, ServiceCodecResolutionError
from ..client import AIClient
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
    namespace: str
    simulation_id: int  # TODO: remove leak from app

    # --- Codec configuration (framework-agnostic) ---
    # Prefer setting codec_class or injecting a codec instance; codec_name is a hint for adapter layers.
    codec_name: str | None = None
    codec_class: type[BaseLLMCodec] | None = None
    _codec_instance: BaseLLMCodec | None = None
    # Backwards-compat alias: if older code sets `codec` to a string, we map it to `codec_name` in __post_init__
    codec: str | None = None

    # Optional class-level identity parts (framework-agnostic)
    origin: str | None = None
    bucket: str | None = None
    name: str | None = None
    provider_name: str | None = None

    # Retry/backoff config
    max_attempts: int = 3
    backoff_initial: float = 0.5  # seconds
    backoff_factor: float = 2.0
    backoff_jitter: float = 0.1  # +/- seconds

    prompt_plan: Sequence[tuple[str, str]] = field(default_factory=tuple)
    client: Optional[AIClient] = None

    emitter: ServiceEmitter | None = None
    render_section: Callable[[str, str, object], "asyncio.Future[str]"] | None = None

    def __post_init__(self):
        # If no explicit namespace string was provided, derive a normalized identity from parts
        if not getattr(self, "namespace", None):
            ident = Identity(
                namespace=self.origin or "app",
                bucket=self.bucket or "service",
                name=(self.name or self.__class__.__name__),
            )
            self.namespace = ident.to_string()
        else:
            # Normalize any provided namespace string into canonical "ns.bucket.name" form
            parts = (self.namespace or "").split(".")
            ns = parts[0] if len(parts) > 0 else None
            buck = parts[1] if len(parts) > 1 else None
            nm = parts[2] if len(parts) > 2 else None
            ident = Identity.from_parts(namespace=ns, bucket=buck, name=nm)
            self.namespace = ident.to_string()

        # Backwards-compatibility: if legacy `codec` (str) was set and no explicit codec_name, copy it over.
        if self.codec_name is None and isinstance(self.codec, str):
            self.codec_name = self.codec

    # --- Identity helpers -------------------------------------------------
    @property
    def identity(self):
        parts = (self.namespace or "").split(".")
        ns = parts[0] if len(parts) > 0 else None
        buck = parts[1] if len(parts) > 1 else None
        nm = parts[2] if len(parts) > 2 else None
        return Identity.from_parts(namespace=ns, bucket=buck, name=nm)

    @property
    def origin_slug(self) -> str:
        return self.identity.namespace

    @property
    def bucket_slug(self) -> str:
        return self.identity.bucket

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

    async def build_messages(self, simulation) -> list[LLMRequestMessage]:
        if not self.render_section:
            raise ServiceConfigError("render_section callable not provided")
        msgs: list[LLMRequestMessage] = []
        for role, section_key in self.prompt_plan:
            text = await self.render_section(self.namespace, section_key, simulation)
            msgs.append(LLMRequestMessage(role=role, content=[LLMTextPart(text=text)]))
        return msgs

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
             - otherwise, assemble a composite from identity: f"{identity.bucket}:{identity.name}"
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
            key_name = (self.codec_name or f"{ident.bucket}:{ident.name}")
            codec_obj = _core_get_codec(ident.namespace, key_name)
            if codec_obj:
                return codec_obj
            # Fallback to a namespace default
            codec_obj = _core_get_codec(ident.namespace, "default")
            if codec_obj:
                return codec_obj

        # Nothing found: raise
        raise ServiceCodecResolutionError(
            namespace=getattr(self.identity, 'namespace', None),
            bucket=getattr(self.identity, 'bucket', None),
            name=getattr(self.identity, 'name', None),
            codec_name=self.codec_name,
            service=self.__class__.__name__,
        )

    async def run(self, simulation) -> LLMResponse:
        if not self.emitter:
            raise ServiceConfigError("emitter not provided")
        attrs = {
            "namespace": self.namespace,
            "simulation_id": getattr(simulation, "id", self.simulation_id),
            "codec_name": self.get_codec_name(simulation) or "unknown",
        }
        logger.info("llm.service.start", extra=attrs)
        async with service_span(f"LLMService.{self.__class__.__name__}.run", **attrs):
            messages = await self.build_messages(simulation)
            req = LLMRequest(
                messages=messages,
                stream=False,
            )
            # Stamp operation identity onto request
            ident = self.identity
            req.namespace = ident.namespace
            req.bucket = ident.bucket
            req.name = ident.name

            # Codec resolution and attach codec identity and response format
            codec = self.get_codec(simulation)
            key_name = (self.codec_name or f"{ident.bucket}:{ident.name}")
            codec_identity = f"{ident.namespace}.{key_name.replace(':','.')}"
            req.codec_identity = codec_identity
            schema_cls = getattr(codec, "response_format_class", None) or getattr(codec, "schema_cls", None) or getattr(codec, "output_model", None)
            if schema_cls is not None:
                req.response_format_class = schema_cls
            if hasattr(codec, "get_response_format"):
                try:
                    rf = codec.get_response_format()
                    if rf is not None:
                        req.response_format = rf
                except Exception:
                    pass

            client = self._get_client(codec)
            self.emitter.emit_request(simulation.id, self.namespace, req)

            attempt = 1
            last_exc: Exception | None = None
            while attempt <= max(1, self.max_attempts):
                try:
                    resp: LLMResponse = await client.send_request(req)
                    # Copy codec identity if missing and echo operation identity
                    if getattr(resp, "codec_identity", None) is None:
                        resp.codec_identity = req.codec_identity
                    resp.namespace, resp.bucket, resp.name = ident.namespace, ident.bucket, ident.name
                    # Wire correlation link
                    if getattr(resp, "request_correlation_id", None) is None:
                        resp.request_correlation_id = req.correlation_id
                    self.emitter.emit_response(simulation.id, self.namespace, resp)
                    await self.on_success(simulation, resp)
                    logger.info("llm.service.success",
                                extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt})
                    return resp
                except Exception as e:
                    last_exc = e
                    if attempt >= max(1, self.max_attempts):
                        self.emitter.emit_failure(simulation.id, self.namespace, req.correlation_id, str(e))
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
        if not self.emitter:
            raise ServiceConfigError("emitter not provided")
        attrs = {
            "namespace": self.namespace,
            "simulation_id": getattr(simulation, "id", self.simulation_id),
            "codec_name": self.get_codec_name(simulation) or "unknown",
        }
        async with service_span(f"LLMService.{self.__class__.__name__}.run_stream", **attrs):
            messages = await self.build_messages(simulation)
            req = LLMRequest(
                messages=messages,
                stream=True,
            )
            # Stamp operation identity onto request
            ident = self.identity
            req.namespace = ident.namespace
            req.bucket = ident.bucket
            req.name = ident.name

            # Codec resolution and attach codec identity and response format
            codec = self.get_codec(simulation)
            key_name = (self.codec_name or f"{ident.bucket}:{ident.name}")
            codec_identity = f"{ident.namespace}.{key_name.replace(':','.')}"
            req.codec_identity = codec_identity
            schema_cls = getattr(codec, "response_format_class", None) or getattr(codec, "schema_cls", None) or getattr(codec, "output_model", None)
            if schema_cls is not None:
                req.response_format_class = schema_cls
            if hasattr(codec, "get_response_format"):
                try:
                    rf = codec.get_response_format()
                    if rf is not None:
                        req.response_format = rf
                except Exception:
                    pass

            client = self._get_client(codec)
            self.emitter.emit_request(simulation.id, self.namespace, req)

            attempt = 1
            started = False
            while attempt <= max(1, self.max_attempts) and not started:
                try:
                    async for chunk in client.stream_request(req):
                        started = True
                        self.emitter.emit_stream_chunk(simulation.id, self.namespace, chunk)
                    # completed stream without error
                    # When stream completes, emit_stream_complete; attach codec identity and echo operation identity if possible
                    # (If a final response object is available, set fields accordingly)
                    # Since emit_stream_complete doesn't take a response, we can't set fields on chunk, but could emit here if needed
                    self.emitter.emit_stream_complete(simulation.id, self.namespace, req.correlation_id)
                    return
                except Exception as e:
                    # If stream hasn't started yet, we can retry; otherwise treat as terminal
                    if started or attempt >= max(1, self.max_attempts):
                        self.emitter.emit_failure(simulation.id, self.namespace, req.correlation_id, str(e))
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
