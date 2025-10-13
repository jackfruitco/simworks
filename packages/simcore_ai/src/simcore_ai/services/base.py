# simcore_ai/services/base.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Sequence, Optional, Protocol, Callable
import asyncio
import logging
from contextlib import asynccontextmanager
import random

from opentelemetry import trace
from opentelemetry.trace import SpanKind

from ..client import AIClient
from ..types import LLMRequest, LLMRequestMessage, LLMResponse, LLMTextPart, LLMStreamChunk
from ..codecs import OutputCodec
from .identity import ServiceIdentity, slugify

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("simworks.ai.llmservice")

class ServiceEmitter(Protocol):
    def emit_request(self, simulation_id: int, namespace: str, request_dto: LLMRequest) -> None: ...
    def emit_response(self, simulation_id: int, namespace: str, response_dto: LLMResponse) -> None: ...
    def emit_failure(self, simulation_id: int, namespace: str, correlation_id, error: str) -> None: ...
    def emit_stream_chunk(self, simulation_id: int, namespace: str, chunk_dto) -> None: ...
    def emit_stream_complete(self, simulation_id: int, namespace: str, correlation_id) -> None: ...

class ProviderFactory(Protocol):
    def __call__(self, cfg: dict, *, codec: OutputCodec) -> object: ...

ConfigProvider = Callable[[], dict]

@asynccontextmanager
async def service_span(name: str, **attrs):
    with tracer.start_as_current_span(name, kind=SpanKind.INTERNAL) as span:
        for k, v in (attrs or {}).items():
            try: span.set_attribute(k, v)
            except Exception: pass
        try:
            yield span
            span.set_attribute("ok", True)
        except Exception as e:
            span.set_attribute("ok", False)
            span.set_attribute("exception.type", type(e).__name__)
            span.set_attribute("exception.msg", str(e)[:500])
            raise

@dataclass
class LLMServiceBase:
    namespace: str
    codec_name: str
    simulation_id: int

    # Optional class-level identity parts (framework-agnostic)
    origin: str | None = None
    bucket: str | None = None
    name: str | None = None

    # Retry/backoff config
    max_attempts: int = 3
    backoff_initial: float = 0.5  # seconds
    backoff_factor: float = 2.0
    backoff_jitter: float = 0.1   # +/- seconds

    prompt_plan: Sequence[tuple[str, str]] = field(default_factory=tuple)
    client: Optional[AIClient] = None

    emitter: ServiceEmitter | None = None
    provider_factory: ProviderFactory | None = None
    config_provider: ConfigProvider | None = None
    get_codec: Callable[[str, str], OutputCodec] | None = None
    render_section: Callable[[str, str, object], "asyncio.Future[str]"] | None = None

    def __post_init__(self):
        # If no explicit namespace was provided, try to build it from identity parts
        # default service name comes from the class name if not explicitly set
        if not getattr(self, "namespace", None):
            o = self.origin or "app"
            b = self.bucket or "service"
            n = self.name or self.__class__.__name__
            self.namespace = ServiceIdentity(o, b, n).namespace
        else:
            # normalize provided namespace to a slug form
            self.namespace = slugify(self.namespace)

    # --- Identity helpers -------------------------------------------------
    @property
    def identity(self) -> ServiceIdentity:
        """Immutable identity for this service instance, derived from (origin,bucket,name)."""
        return ServiceIdentity(self.origin or "app", self.bucket or "service", self.name or self.__class__.__name__)

    @property
    def origin_slug(self) -> str:
        return self.identity.origin_slug

    @property
    def bucket_slug(self) -> str:
        return self.identity.bucket_slug

    @property
    def name_slug(self) -> str:
        return self.identity.name_slug

    async def build_messages(self, simulation) -> list[LLMRequestMessage]:
        if not self.render_section:
            raise RuntimeError("render_section callable not provided")
        msgs: list[LLMRequestMessage] = []
        for role, section_key in self.prompt_plan:
            text = await self.render_section(self.namespace, section_key, simulation)
            msgs.append(LLMRequestMessage(role=role, content=[LLMTextPart(text=text)]))
        return msgs

    def select_codec_name(self, simulation) -> str:
        return self.codec_name

    async def _backoff_sleep(self, attempt: int) -> None:
        """Exponential backoff with jitter: initial * factor^(attempt-1) +/- jitter."""
        base = self.backoff_initial * (self.backoff_factor ** max(0, attempt - 1))
        jitter = (random.random() * 2 - 1) * self.backoff_jitter if self.backoff_jitter > 0 else 0.0
        delay = max(0.0, base + jitter)
        try:
            logger.debug("llm.service.backoff", extra={"attempt": attempt, "delay": delay})
        except Exception:
            pass
        await asyncio.sleep(delay)

    def _get_client(self, codec: OutputCodec) -> AIClient:
        if self.client:
            return self.client
        if not self.provider_factory or not self.config_provider:
            raise RuntimeError("provider_factory and config_provider must be provided")
        provider = self.provider_factory(self.config_provider(), codec=codec)
        return AIClient(provider)

    async def run(self, simulation) -> LLMResponse:
        if not self.emitter or not self.get_codec:
            raise RuntimeError("emitter/get_codec not provided")
        attrs = {
            "namespace": self.namespace,
            "simulation_id": getattr(simulation, "id", self.simulation_id),
            "codec_name": self.select_codec_name(simulation),
        }
        logger.info("llm.service.start", extra=attrs)
        async with service_span(f"LLMService.{self.__class__.__name__}.run", **attrs):
            messages = await self.build_messages(simulation)
            req = LLMRequest(
                lab_key=self.namespace,
                simulation_id=simulation.id,
                messages=messages,
            )
            # Attach response format class from codec if available
            codec = self.get_codec(self.namespace, self.select_codec_name(simulation))
            schema_cls = getattr(codec, "schema_cls", None) or getattr(codec, "output_model", None)
            if schema_cls is not None:
                req.response_format_cls = schema_cls

            client = self._get_client(codec)
            self.emitter.emit_request(simulation.id, self.namespace, req)

            attempt = 1
            last_exc: Exception | None = None
            while attempt <= max(1, self.max_attempts):
                try:
                    # annotate span with attempt info if present
                    try:
                        from opentelemetry.trace import get_current_span
                        span = get_current_span()
                        if span and span.is_recording():
                            span.set_attribute("llm.attempt", attempt)
                            span.set_attribute("llm.max_attempts", self.max_attempts)
                    except Exception:
                        pass

                    resp: LLMResponse = await client.send_request(req)
                    self.emitter.emit_response(simulation.id, self.namespace, resp)
                    await self.on_success(simulation, resp)
                    logger.info("llm.service.success", extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt})
                    return resp
                except Exception as e:
                    last_exc = e
                    # add event to span
                    try:
                        from opentelemetry.trace import get_current_span
                        span = get_current_span()
                        if span and span.is_recording():
                            span.add_event("llm.service.attempt_failed", {"exception.type": type(e).__name__, "exception.msg": str(e)[:500], "attempt": attempt})
                    except Exception:
                        pass

                    if attempt >= max(1, self.max_attempts):
                        self.emitter.emit_failure(simulation.id, self.namespace, req.correlation_id, str(e))
                        await self.on_failure(simulation, e)
                        logger.exception("llm.service.error", extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt})
                        raise
                    # backoff then retry
                    logger.warning("llm.service.retrying", extra={**attrs, "attempt": attempt, "max_attempts": self.max_attempts})
                    await self._backoff_sleep(attempt)
                    attempt += 1

    async def run_stream(self, simulation):
        if not self.emitter or not self.get_codec:
            raise RuntimeError("emitter/get_codec not provided")
        attrs = {
            "namespace": self.namespace,
            "simulation_id": getattr(simulation, "id", self.simulation_id),
            "codec_name": self.select_codec_name(simulation),
        }
        async with service_span(f"LLMService.{self.__class__.__name__}.run_stream", **attrs):
            messages = await self.build_messages(simulation)
            req = LLMRequest(
                lab_key=self.namespace,
                simulation_id=simulation.id,
                messages=messages,
                stream=True,
            )
            # Attach response format class from codec if available
            codec = self.get_codec(self.namespace, self.select_codec_name(simulation))
            schema_cls = getattr(codec, "schema_cls", None) or getattr(codec, "output_model", None)
            if schema_cls is not None:
                req.response_format_cls = schema_cls

            client = self._get_client(codec)
            self.emitter.emit_request(simulation.id, self.namespace, req)

            attempt = 1
            started = False
            while attempt <= max(1, self.max_attempts) and not started:
                try:
                    # annotate span
                    try:
                        from opentelemetry.trace import get_current_span
                        span = get_current_span()
                        if span and span.is_recording():
                            span.set_attribute("llm.attempt", attempt)
                            span.set_attribute("llm.max_attempts", self.max_attempts)
                    except Exception:
                        pass

                    async for chunk in client.stream_request(req):
                        started = True
                        self.emitter.emit_stream_chunk(simulation.id, self.namespace, chunk)
                    # completed stream without error
                    self.emitter.emit_stream_complete(simulation.id, self.namespace, req.correlation_id)
                    return
                except Exception as e:
                    # If stream hasn't started yet, we can retry; otherwise treat as terminal
                    if started or attempt >= max(1, self.max_attempts):
                        self.emitter.emit_failure(simulation.id, self.namespace, req.correlation_id, str(e))
                        await self.on_failure(simulation, e)
                        logger.exception("llm.service.stream.error", extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt})
                        raise
                    logger.warning("llm.service.stream.retrying", extra={**attrs, "attempt": attempt, "max_attempts": self.max_attempts})
                    await self._backoff_sleep(attempt)
                    attempt += 1

    async def on_success(self, simulation, resp: LLMResponse) -> None: ...
    async def on_failure(self, simulation, err: Exception) -> None: ...