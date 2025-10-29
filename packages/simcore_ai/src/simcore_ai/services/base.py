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
from typing import Any
from typing import Optional, Protocol

from simcore_ai.codecs import (
    BaseLLMCodec,
    get_codec as _core_get_codec
)
from simcore_ai.identity import Identity
from simcore_ai.identity.utils import module_root
from simcore_ai.promptkit.resolvers import resolve_section, PromptSectionResolutionError
from .exceptions import ServiceConfigError, ServiceCodecResolutionError, ServiceBuildRequestError
from ..client import AIClient
from ..promptkit import Prompt, PromptEngine, PromptSection
from ..tracing import get_tracer, service_span
from ..types import LLMRequest, LLMRequestMessage, LLMResponse, LLMTextPart

logger = logging.getLogger(__name__)
tracer = get_tracer("simcore_ai.llmservice")


class ServiceEmitter(Protocol):
    def emit_request(self, context: dict, namespace: str, request_dto: LLMRequest) -> None: ...

    def emit_response(self, context: dict, namespace: str, response_dto: LLMResponse) -> None: ...

    def emit_failure(self, context: dict, namespace: str, correlation_id, error: str) -> None: ...

    def emit_stream_chunk(self, context: dict, namespace: str, chunk_dto) -> None: ...

    def emit_stream_complete(self, context: dict, namespace: str, correlation_id) -> None: ...


@dataclass
class BaseLLMService:
    """
    Abstract base for LLM-backed AI services. Handles identity fields (namespace, kind, name)
    and canonical identity string (identity_str = "namespace.kind.name").
    The legacy `namespace` field is deprecated; use `identity_str` and `namespace` instead.
    """
    # Arbitrary metadata preserved end-to-end (e.g., user_msg, source_view, etc.)
    # Services may declare required keys that must be present in `context`.
    required_context_keys: tuple[str, ...] = ()
    context: dict = field(default_factory=dict)

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
        # Normalize legacy codec hint → codec_name (if provided as `codec`)
        if self.codec_name is None and isinstance(self.codec, str):
            self.codec_name = self.codec

        # Build canonical identity string from parts
        inferred_ns = self.namespace or module_root(getattr(self, "__module__", "")) or "default"
        inferred_kind = self.kind or "default"
        inferred_name = self.name or self.__class__.__name__
        ident = Identity(namespace=inferred_ns, kind=inferred_kind, name=inferred_name)
        self.identity_str = ident.to_string()

        # Normalize `context` to a plain dict for future consumption
        if not isinstance(self.context, dict):
            try:
                self.context = dict(self.context)  # type: ignore[arg-type]
            except Exception:
                self.context = {}

        # Fail fast if required context keys are missing
        self.check_required_context()


    def check_required_context(self) -> None:
        """Validate that required context keys are present.

        Subclasses may override `required_context_keys` or this method entirely
        to enforce richer validation rules. By default, it ensures each key in
        `required_context_keys` is present and not `None` in `self.context`.
        """
        required = getattr(self, "required_context_keys", ()) or ()
        if not required:
            return
        missing: list[str] = []
        for key in required:
            if self.context.get(key) is None:
                missing.append(str(key))
        if missing:
            raise ServiceConfigError(
                f"Missing required context keys: {', '.join(missing)}",
            )

    # Backwards-compat alias
    def check_required_overrides(self) -> None:  # pragma: no cover
        self.check_required_context()

    async def _backoff_sleep(self, attempt: int) -> None:
        """Exponential backoff with jitter between retries.

        attempt starts at 1.
        """
        try:
            base = max(0.0, float(self.backoff_initial))
            factor = max(1.0, float(self.backoff_factor))
            jitter = float(self.backoff_jitter)
        except Exception:
            base, factor, jitter = 0.5, 2.0, 0.1
        delay = base * (factor ** max(0, attempt - 1))
        # simple symmetric jitter
        delay += (jitter if attempt % 2 else -jitter)
        if delay < 0:
            delay = 0
        await asyncio.sleep(delay)

    def flatten_context(self) -> dict:
        """Flatten `self.context` into trace-friendly attrs as `context.<key>`.

        Uses tracing.flatten_context() to flatten the context dict.
        """
        from simcore_ai.tracing import flatten_context as flatten_context_
        return flatten_context_(self.context)

    async def ensure_prompt(self) -> Prompt:
        """Ensure `self.prompt` is built once via the configured PromptEngine.

        The plan contains canonical section identities ("namespace:kind:name")
        or PromptSection classes. We resolve all specs to classes and pass them to
        the engine's build method with a context dict, never domain objects.
        """
        async with service_span(f"LLMService.{self.__class__.__name__}.ensure_prompt", **self.flatten_context()):
            if self.prompt is not None:
                return self.prompt

            plan = self.get_prompt_plan()
            section_classes: list[type[PromptSection]] = []
            for spec in plan:
                try:
                    SectionCls = resolve_section(spec)
                except PromptSectionResolutionError as exc:
                    # Legacy fallback path (string key + render_section)
                    if self.render_section and isinstance(spec, str):
                        # Build a synthetic Prompt from the rendered text
                        text = await self.render_section(self.identity_str, spec, self.context)
                        self.prompt = Prompt(instruction=text, message="", extra_messages=[], meta={"fallback": True})
                        return self.prompt
                    raise
                section_classes.append(SectionCls)

            engine = self.prompt_engine or PromptEngine
            ctx = {"context": self.context, "service": self}

            # Prefer async engine if available
            abuild = getattr(engine, "abuild_from", None)
            build = getattr(engine, "build_from", None)
            if callable(abuild):
                prompt: Prompt = await abuild(section_classes, context=ctx)  # type: ignore[arg-type]
            elif callable(build):
                prompt = build(section_classes, context=ctx)  # type: ignore[arg-type]
            else:
                raise ServiceBuildRequestError("PromptEngine has no build_from/abuild_from callable")

            self.prompt = prompt
            return prompt

    # --- Identity helpers -------------------------------------------------
    @property
    def identity(self) -> Identity:
        parts = (self.identity_str or "").split(".")
        o = parts[0] if len(parts) > 0 else None
        b = parts[1] if len(parts) > 1 else None
        n = parts[2] if len(parts) > 2 else None
        return Identity.from_parts(namespace=o, kind=b, name=n)

    async def build_request(self, **ctx) -> LLMRequest:
        """Build a provider-agnostic **LLMRequest** for this service.

        Default implementation uses the PromptEngine output to create messages and
        stamps identity and codec routing. Subclasses may override hooks instead of
        replacing this whole method.

        Raises
        ------
        ServiceBuildRequestError
            If both the instruction and user message are empty.
        """
        async with service_span(f"LLMService.{self.__class__.__name__}.build_request", **self.flatten_context()):
            # 1) Ensure prompt is available
            prompt = await self.ensure_prompt()

            # 2) Build messages via hooks
            messages: list[LLMRequestMessage] = []
            messages += await self._build_request_instructions(prompt, **ctx)
            messages += await self._build_request_user_input(prompt, **ctx)
            messages += await self._build_request_extras(prompt, **ctx)

            # Validate: at least one of instruction or user message must be present
            instr_present = bool(getattr(prompt, "instruction", None))
            user_present = bool(getattr(prompt, "message", None))
            if not (instr_present or user_present):
                raise ServiceBuildRequestError("Prompt produced no instruction or user message; cannot build request")

            # 3) Create base request and stamp identity
            ident = self.identity
            req = LLMRequest(messages=messages, stream=False)
            req.namespace = ident.namespace
            req.kind = ident.kind
            req.name = ident.name

            # 4) Resolve codec and attach response format and codec identity
            codec = self.get_codec()
            key_name = (self.codec_name or f"{ident.kind}:{ident.name}")
            req.codec_identity = f"{ident.namespace}.{key_name.replace(':', '.')}"

            # Provider-agnostic response format class
            schema_cls = (
                    getattr(codec, "response_format_cls", None)
                    or getattr(codec, "schema_cls", None)
                    or getattr(codec, "output_model", None)
            )
            if schema_cls is not None:
                req.response_format_cls = schema_cls
            if hasattr(codec, "get_response_format"):
                try:
                    rf = codec.get_response_format()
                    if rf is not None:
                        req.response_format = rf
                except Exception:
                    pass

            # 5) Final customization hook
            req = await self._finalize_request(req, **ctx)
            return req

    # --------------------------- build hooks ---------------------------
    # Allowed role literal set for type-checkers and validation
    _ALLOWED_ROLES = {
        "system", "user", "developer", "assistant", "patient", "instructor", "facilitator",
    }

    def _coerce_role(self, value: str) -> str:
        """Validate role to allowed set; default to 'system' if unknown.

        This keeps runtime safe and makes static checkers happy when combined with
        defensive validation.
        """
        v = str(value or "").strip().lower()
        return v if v in self._ALLOWED_ROLES else "system"

    async def _build_request_instructions(self, prompt: Prompt, **ctx) -> list[LLMRequestMessage]:
        """Create developer messages from prompt.instruction (if present)."""
        messages: list[LLMRequestMessage] = []
        instruction = getattr(prompt, "instruction", None)
        if instruction:
            messages.append(LLMRequestMessage(role="developer", content=[LLMTextPart(text=str(instruction))]))
        return messages

    async def _build_request_user_input(self, prompt: Prompt, **ctx) -> list[LLMRequestMessage]:
        """Create user messages from prompt.message (if present)."""
        messages: list[LLMRequestMessage] = []
        message = getattr(prompt, "message", None)
        if message:
            messages.append(LLMRequestMessage(role="user", content=[LLMTextPart(text=str(message))]))
        return messages

    async def _build_request_extras(self, prompt: Prompt, **ctx) -> list[LLMRequestMessage]:
        """Create extra messages from prompt.extra_messages ((role, text) pairs)."""
        messages: list[LLMRequestMessage] = []
        extras = getattr(prompt, "extra_messages", None) or []
        for role, text in extras:
            if text:
                LLMM_role = self._coerce_role(str(role))
                messages.append(LLMRequestMessage(role=LLMM_role, content=[LLMTextPart(text=str(text))]))
        return messages

    async def _finalize_request(self, req: LLMRequest, **ctx) -> LLMRequest:
        """Final request customization hook (no-op by default)."""
        return req

    @property
    def name_slug(self) -> str:
        return self.identity.name

    def get_codec_name(self) -> str | None:
        """
        Return a string *hint* for the codec to be used, for telemetry/logging only.

        This does NOT resolve a codec class or instance and performs no registry lookups.
        It is intentionally lightweight.

        Precedence:
          1) explicit `self.codec_name` (string)
          2) if `select_codec()` returns a string, use that
          3) legacy `self.codec` (string), if set
          4) otherwise None
        """
        if self.codec_name:
            return self.codec_name
        sel = self.select_codec()
        if isinstance(sel, str):
            return sel
        if isinstance(self.codec, str):
            return self.codec
        return None

    def select_codec(self) -> type[BaseLLMCodec] | BaseLLMCodec | str | None:
        """
        Optional hook for subclasses to override and customize codec selection.

        This method allows a service to explicitly choose which codec to use.
        It should NOT perform registry lookups — that is handled automatically
        by `get_codec()` if this method returns None.

        Return one of the following:
          • A codec **instance** (fully configured, ready to use)
          • A codec **class** (framework-agnostic; typically has class-level schema)
          • A **string** codec hint (e.g., "kind:name") — this will be used
            by `get_codec_name()` and traced but not resolved here
          • `None` to defer to default registry-based resolution

        Examples
        --------
        ```python
        # Example 1: Force a specific codec class
        def select_codec(self):
            return MyCustomCodec

        # Example 2: Dynamically choose based on a service property
        def select_codec(self):
            if self.context.get("use_minimal_schema"):
                return MinimalPatientCodec
            return FullPatientCodec

        # Example 3: Return a string hint only (not resolved here)
        def select_codec(self):
            return "chatlab:patient"
        ```
        """
        return None

    def get_codec(self):
        """
        Resolve and return a codec (class or instance) suitable for execution.

        Resolution order:
          1) explicit `codec_class` on the service (returned as-is)
          2) result of `select_codec()` (if it returns a class or instance)
          3) core registry lookup (if available) using the service identity:
             - prefer `codec_name` if set (e.g., "kind:name")
             - otherwise derive key from identity: f"{identity.kind}:{identity.name}"
             - try exact match, then fall back to namespace "default"
        Raises
        ------
        ServiceCodecResolutionError
            If no codec can be resolved.
        """
        # 1) explicit class wins
        if self.codec_class is not None:
            return self.codec_class

        # 2) subclass-provided selection (class or instance)
        sel = self.select_codec()
        if sel is not None and not isinstance(sel, str):
            return sel

        # 3) registry lookup (core layer, optional)
        if _core_get_codec is not None:
            ident = self.identity
            # Prefer explicit codec_name if provided
            key_name = (self.codec_name or f"{ident.kind}:{ident.name}")
            codec_obj = _core_get_codec(ident.namespace, key_name)
            if codec_obj:
                return codec_obj
            # Fallback to a namespace default
            codec_obj = _core_get_codec(ident.namespace, "default")
            if codec_obj:
                return codec_obj

        # Nothing found: raise
        raise ServiceCodecResolutionError(
            namespace=getattr(self.identity, "namespace", None),
            kind=getattr(self.identity, "kind", None),
            name=getattr(self.identity, "name", None),
            codec=self.codec_name,
            service=self.__class__.__name__,
        )

    def get_prompt_plan(self) -> Sequence[Any]:
        """Return the prompt plan for this invocation.

        Defaults to the class/instance `prompt_plan` attribute.

        Each entry may be:
            - a canonical string or PromptSection class/instance
        """
        return self.prompt_plan

    async def build_request_messages(self) -> list[LLMRequestMessage]:
        """Build messages from the engine-produced Prompt aggregate.

        Emits `developer` from `prompt.instruction`, `user` from `prompt.message`,
        and any `(role, text)` pairs from `prompt.extra_messages`.
        """
        prompt = await self.ensure_prompt()
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

    def get_client(self) -> AIClient:
        """
        Public accessor for the provider client.

        Behavior
        --------
        - If an instance is already set on `self.client`, return it.
        - Otherwise, resolve one via `_resolve_client(...)` using `provider_name`,
          cache it on `self.client`, and return it.

        Notes
        -----
        • Callers across core and Django layers should prefer this method.
        • This replaces the former private `_get_client` usage.
        """
        if self.client is not None:
            return self.client
        self.client = self._resolve_client()
        return self.client

    def _resolve_client(self, codec: BaseLLMCodec | None = None) -> AIClient:
        """
        Internal resolver that performs registry lookups to obtain an AIClient.

        Resolution order
        ----------------
        1) If `provider_name` is falsy -> return the default registry client.
        2) Try explicit client name: `get_ai_client(name=self.provider_name)`.
        3) Fallback to provider slug: `get_ai_client(provider=self.provider_name)`.

        Raises
        ------
        ServiceConfigError
            If no client can be resolved via the registry.

        Notes
        -----
        • External modules should not call this directly; use `get_client()`.
        • `codec` is accepted for future-proofing but is unused here.
        """
        from simcore_ai.client.registry import get_ai_client

        # If no provider_name, use the default client from registry
        if not self.provider_name:
            return get_ai_client()

        # First, try resolving by explicit client name
        try:
            return get_ai_client(name=self.provider_name)
        except Exception:
            pass

        # Next, treat provider_name as a provider slug (e.g., "openai")
        try:
            return get_ai_client(provider=self.provider_name)
        except Exception as e:
            raise ServiceConfigError(
                "No AI client available. Either inject `client=...` into the service, "
                "pre-register a client via simcore_ai.client.registry.get_ai_client(...), "
                "or configure providers in your runtime."
            ) from e

    async def run(self) -> LLMResponse | None:
        """
        Run the service, emitting request/response events.

        This method is domain-agnostic: it relies on `self.context` only.
        """
        if not self.emitter:
            raise ServiceConfigError("emitter not provided")
        ident = self.identity
        identity_label = f"{ident.namespace}.{ident.kind}.{ident.name}"
        attrs = {
            "identity": identity_label,
            "codec_name": self.get_codec_name() or "unknown",
        }
        # include a shallow context snapshot for tracing
        attrs.update(self.flatten_context())

        logger.info("llm.service.start", extra=attrs)
        async with service_span(f"LLMService.{self.__class__.__name__}.run", **attrs):
            req = await self.build_request()
            req.stream = False

            client = self.get_client()
            self.emitter.emit_request(self.context, self.identity_str, req)

            attempt = 1
            while attempt <= max(1, self.max_attempts):
                try:
                    resp: LLMResponse = await client.send_request(req)
                    if getattr(resp, "codec_identity", None) is None:
                        resp.codec_identity = req.codec_identity
                    resp.namespace, resp.kind, resp.name = ident.namespace, ident.kind, ident.name
                    if getattr(resp, "request_correlation_id", None) is None:
                        resp.request_correlation_id = req.correlation_id
                    self.emitter.emit_response(self.context, self.identity_str, resp)
                    await self.on_success(self.context, resp)  # pass context to app hooks
                    logger.info("llm.service.success",
                                extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt})
                    return resp
                except Exception as e:
                    if attempt >= max(1, self.max_attempts):
                        self.emitter.emit_failure(self.context, self.identity_str, req.correlation_id, str(e))
                        await self.on_failure(self.context, e)
                        logger.exception("llm.service.error",
                                         extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt})
                        raise
                    logger.warning("llm.service.retrying",
                                   extra={**attrs, "attempt": attempt, "max_attempts": self.max_attempts})
                    await self._backoff_sleep(attempt)
                    attempt += 1

    async def run_stream(self):
        """
        Run the service with streaming, emitting events.

        This method is domain-agnostic: it relies on `self.context` only.
        """
        if not self.emitter:
            raise ServiceConfigError("emitter not provided")
        ident = self.identity
        identity_label = f"{ident.namespace}.{ident.kind}.{ident.name}"
        attrs = {
            "identity": identity_label,
            "codec_name": self.get_codec_name() or "unknown",
        }
        attrs.update(self.flatten_context())

        async with service_span(f"LLMService.{self.__class__.__name__}.run_stream", **attrs):
            req = await self.build_request()
            req.stream = True

            client = self.get_client()
            self.emitter.emit_request(self.context, self.identity_str, req)

            attempt = 1
            started = False
            while attempt <= max(1, self.max_attempts) and not started:
                try:
                    async for chunk in client.stream_request(req):
                        started = True
                        self.emitter.emit_stream_chunk(self.context, self.identity_str, chunk)
                    self.emitter.emit_stream_complete(self.context, self.identity_str, req.correlation_id)
                    return
                except Exception as e:
                    if started or attempt >= max(1, self.max_attempts):
                        self.emitter.emit_failure(self.context, self.identity_str, req.correlation_id, str(e))
                        await self.on_failure(self.context, e)
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
