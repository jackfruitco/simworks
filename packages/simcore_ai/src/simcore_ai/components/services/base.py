"""
BaseService: Abstract base for LLM-backed AI services.

Identity
--------
• Identity is a class-level concept provided by `IdentityMixin`.
  Each concrete service class has a stable `identity: Identity`.
• Instances read `self.identity`, which mirrors the class identity unless overridden
  via `_identity_override` by higher-level builder APIs.
• Class attributes `namespace`, `kind`, and `name` are treated as hints passed to the resolver.
• Prefer `self.identity.as_str` ("namespace.kind.name") or `self.identity.as_tuple3` anywhere a
  label/tuple is needed. Avoid carrying separate string copies.

Prompt plans
------------
• `prompt_plan` may be a `PromptPlan` or an iterable of section specs (canonical dot strings or
  `PromptSection` classes/instances). The `PromptEngine` performs resolution/normalization.
• If no explicit plan is provided, the service falls back to a single section whose identity matches
  the service identity (looked up in `PromptRegistry`).
• Optional 'override_prompt' string replaces the built prompt.message after build.
• The cached prompt is available at the read/write property: service.prompt
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, ClassVar, Union
from typing import Optional, Protocol

from asgiref.sync import async_to_sync

from simcore_ai.client import AIClient
from simcore_ai.components import BaseComponent
from simcore_ai.components.codecs.base import BaseCodec
from simcore_ai.components.promptkit import Prompt, PromptEngine, PromptPlan, PromptSection, PromptSectionSpec
from simcore_ai.identity import Identity, IdentityLike, IdentityMixin
from simcore_ai.tracing import get_tracer, service_span
from simcore_ai.types import LLMRequest, LLMRequestMessage, LLMResponse, LLMTextPart, LLMRole
from .exceptions import ServiceConfigError, ServiceCodecResolutionError, ServiceBuildRequestError

logger = logging.getLogger(__name__)
tracer = get_tracer("simcore_ai.llmservice")


class ServiceEmitter(Protocol):
    def emit_request(self, context: dict, namespace: str, request_dto: LLMRequest) -> None: ...

    def emit_response(self, context: dict, namespace: str, response_dto: LLMResponse) -> None: ...

    def emit_failure(self, context: dict, namespace: str, correlation_id, error: str) -> None: ...

    def emit_stream_chunk(self, context: dict, namespace: str, chunk_dto) -> None: ...

    def emit_stream_complete(self, context: dict, namespace: str, correlation_id) -> None: ...


CodecLike = Union[type[BaseCodec], BaseCodec, IdentityLike]


@dataclass
class BaseService(IdentityMixin, BaseComponent, ABC):
    """
    Abstract base for LLM-backed AI services.

    • Identity is exposed as `self.identity: Identity`, resolved once in `__post_init__` using
      `identity_resolver`. Class attributes `namespace/kind/name` serve only as resolver hints.
    • The canonical string form is `self.identity.as_str` ("namespace.kind.name").
    • Older patterns that rebuilt identity strings or stored separate `identity_str` values are removed.
    """
    abstract: ClassVar[bool] = True

    # Optional per-instance identity override (used by builder-style APIs like using(...)).
    _identity_override: Identity | None = field(default=None, init=False, repr=False)

    # Arbitrary metadata preserved end-to-end (e.g., user_msg, source_view, etc.)
    # Services may declare required keys that must be present in `context`.
    required_context_keys: tuple[str, ...] = ()
    context: dict = field(default_factory=dict)

    # --- Codec pairing (explicit override) ---
    # May be set per-instance to override default resolution.
    _codec_override: type[BaseCodec] | None = None

    provider_name: str | None = None

    # Retry/backoff config
    max_attempts: int = 3
    backoff_initial: float = 0.5  # seconds
    backoff_factor: float = 2.0
    backoff_jitter: float = 0.1  # +/- seconds

    _prompt_plan: PromptPlan | None = None  # setter allows input as PromptPlan or list[PromptSections]
    _prompt_cache: Prompt | None = None  # only caches if all prompt sections have `is_dynamic=False`

    # Prompt overrides
    prompt_engine: PromptEngine | None = None  # override PromptEngine for this service
    prompt_instruction_override: str | None = None  # override full prompt instruction
    prompt_message_override: str | None = None  # override prompt user message

    client: Optional[AIClient] = None
    emitter: ServiceEmitter | None = None

    @property
    def slug(self) -> str:
        """Get slug for Service (from identity string)."""
        return self.identity.as_str

    @property
    def codec(self) -> type[BaseCodec]:
        """
        Effective codec for this service.

        Resolution order:
          1) Per-instance override set via `service.codec = ...`.
          2) Default resolution via `resolve_codec()` / `aresolve_codec()`.

        Always returns a `BaseCodec` subclass or raises ServiceCodecResolutionError.
        """
        if self._codec_override is not None:
            return self._codec_override
        return self.resolve_codec()

    @codec.setter
    def codec(self, value: CodecLike | None) -> None:
        """
        Configure an explicit codec override for this service instance.

        Accepts:
          - BaseCodec subclass
          - BaseCodec instance
          - Identity-like (resolved once to a BaseCodec subclass)
          - None (to clear the override)
        """
        if value is None:
            self._codec_override = None
            return

        try:
            if isinstance(value, type) and issubclass(value, BaseCodec):
                self._codec_override = value
                return

            if isinstance(value, BaseCodec):
                self._codec_override = type(value)
                return

            # Treat as identity-like
            resolved = Identity.resolve.for_(BaseCodec, value)
            if resolved is None:
                raise ServiceCodecResolutionError(
                    f"Could not resolve codec from {value!r}"
                )
            self._codec_override = resolved
        except Exception as err:
            raise ServiceCodecResolutionError(
                f"Invalid codec assignment for {self.__class__.__name__}"
            ) from err

    @property
    def prompt_plan(self) -> PromptPlan | None:
        """Get PromptPlan."""
        return self._prompt_plan

    @prompt_plan.setter
    def prompt_plan(self, plan_: Any) -> None:
        """Set prompt plan for Service. Accepts any PromptPlan-like value.

        Accepts:
          - None: clears the plan
          - PromptPlan: stored as-is
          - iterable of PromptSectionSpec / section identifiers: coerced via PromptPlan.from_sections
        """
        # Clear Plan
        if plan_ is None:
            self._prompt_plan = None
            self._prompt_cache = None
            return

        # Set attr if provided as PromptPlan already
        if isinstance(plan_, PromptPlan):
            self._prompt_plan = plan_
            if hasattr(self, "prompt"):
                setattr(self, "prompt", None)
            return

        # Coerce from raw sections / specs, then set attr
        try:
            built_ = PromptPlan.from_sections(plan_)  # type: ignore[arg-type]
        except Exception as e:
            raise ServiceBuildRequestError(f"Invalid prompt plan: {e}") from e

        self._prompt_plan = built_
        if hasattr(self, "prompt"):
            setattr(self, "prompt", None)

    @property
    def prompt(self) -> Prompt:
        """
        Synchronous, cache-aware accessor for the Prompt.

        Uses `get_prompt()` under the hood so callers can safely use `service.prompt`
        in sync codepaths without re-implementing caching semantics.
        """
        return async_to_sync(self.aget_prompt)()

    @prompt.setter
    def prompt(self, p: Prompt | None) -> None:
        """Set (or clear) cached prompt for Service."""
        self._prompt_cache = p

    @property
    def has_dynamic_prompt(self) -> bool:
        """If prompt plan includes dynamic sections."""
        plan = self._prompt_plan
        if not plan:
            return True  # no plan configured; treat as dynamic / non-cacheable
        sections = getattr(plan, "items", None) or getattr(plan, "sections", None) or ()
        return any(getattr(section, "is_dynamic", False) for section in sections)

    def __post_init__(self) -> None:
        """
        Post-init normalization.

        Identity is class-level via `IdentityMixin`; this method only normalizes
        context and enforces required context keys.
        """
        if not isinstance(self.context, dict):
            try:
                self.context = dict(self.context)  # type: ignore[arg-type]
            except Exception:
                self.context = {}
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
        """
        Exponential backoff with jitter between retries. `attempt` starts at 1.
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

    # ----------------------------------------------------------------------
    # Prompt resolution (async-first)
    # ----------------------------------------------------------------------
    def _get_registry_section_or_none(self) -> PromptSectionSpec | None:
        """
        Return a `PromptSection` class from the registry using `self.identity`, or None if not found.
        Pure lookup; no exceptions.
        """
        try:
            section_cls = Identity.resolve.try_for_(PromptSection, self.identity)
            return section_cls
        except Exception:
            logger.warning(
                "Could not resolve PromptSection from identity: %s",
                self.identity.as_str,
                exc_info=True,
            )
            return None

    async def aget_prompt(self) -> Prompt:
        """
        Async, cache-aware accessor for the Prompt.

        Respects `has_dynamic_prompt`:
          - If no dynamic sections and a cached Prompt exists, returns it.
          - Otherwise builds a fresh Prompt via `_get_prompt()` and caches it
            when safe.
        """
        # If we have a cached prompt and it's safe to reuse, return it
        if self._prompt_cache is not None and not self.has_dynamic_prompt:
            return self._prompt_cache

        # Always build fresh when dynamic; may cache when static
        prompt = await self._aget_prompt()

        if not self.has_dynamic_prompt:
            self._prompt_cache = prompt

        return prompt

    async def _aget_prompt(self) -> Prompt:
        """
        Build a Prompt using the configured PromptEngine.

        This is a pure builder: it does not read or write the prompt cache.
        Use `get_prompt()` / `prompt` for cache-aware access.
        """
        async with service_span(
                f"LLMService.{self.__class__.__name__}._build_prompt",
                **self.flatten_context(),
        ):
            # 1) Using both overrides: build directly
            if self.prompt_instruction_override and self.prompt_message_override:
                return Prompt(
                    instruction=str(self.prompt_instruction_override),
                    message=str(self.prompt_message_override),
                )

            # 2) Use explicit plan if provided
            plan = self._prompt_plan

            # 3) Fallback: single section matching identity
            if not plan:
                section_cls = self._get_registry_section_or_none()
                if section_cls is None:
                    ident_str = self.identity.as_str
                    raise ServiceBuildRequestError(
                        f"No prompt plan provided and no PromptSection registered for identity '{ident_str}'."
                    )
                plan = PromptPlan.from_sections([section_cls])

            # Ensure already coerced to PromptPlan
            assert isinstance(plan, PromptPlan)

            logger.debug(
                "prompt plan resolved: %s",
                getattr(plan, "describe", lambda: plan)(),
            )

            engine = self.prompt_engine or PromptEngine
            ctx = {"context": self.context, "service": self}

            abuild = getattr(engine, "abuild_from", None)
            if callable(abuild):
                prompt_: Prompt = await abuild(plan=plan, **ctx)  # type: ignore[arg-type]
            else:
                build = getattr(engine, "build_from", None)
                if not callable(build):
                    raise ServiceBuildRequestError(
                        "PromptEngine has no build_from/abuild_from callable"
                    )
                prompt_ = build(plan=plan, **ctx)  # type: ignore[arg-type]

            # Apply optional overrides
            if self.prompt_instruction_override is not None:
                try:
                    setattr(prompt_, "instruction", str(self.prompt_instruction_override))
                except Exception:
                    logger.warning(
                        "failed to override prompt developer instruction; ignoring"
                    )

            if self.prompt_message_override is not None:
                try:
                    setattr(prompt_, "message", str(self.prompt_message_override))
                except Exception:
                    logger.warning(
                        "failed to override prompt user message; ignoring"
                    )

            return prompt_

    # ----------------------------------------------------------------------
    # Codec resolution (async-first)
    # ----------------------------------------------------------------------
    async def aresolve_codec(self) -> type[BaseCodec]:
        """
        Async-first codec resolver used behind `codec`.

        Order:
          1) Per-instance override (`_codec_override`) if set.
          2) Registry by `self.identity`.
          3) Registry by ("default", kind, name).

        Always returns a `BaseCodec` subclass.

        Raises:
          ServiceCodecResolutionError if no codec can be resolved.
        """
        if self._codec_override is not None:
            return self._codec_override

        ident = self.identity
        candidates: tuple[IdentityLike, ...] = (
            ident,
            Identity(namespace="default", kind=ident.kind, name=ident.name),
        )

        for candidate in candidates:
            codec_cls = Identity.resolve.try_for_(BaseCodec, candidate)
            if codec_cls is not None:
                return codec_cls

        raise ServiceCodecResolutionError(
            namespace=ident.namespace,
            kind=ident.kind,
            name=ident.name,
            codec=None,
            service=self.__class__.__name__,
        )

    def resolve_codec(self) -> type[BaseCodec]:
        """Sync wrapper around aresolve_codec()."""
        return async_to_sync(self.aresolve_codec)()


    # --- Identity helpers -------------------------------------------------
    async def abuild_request(self, **ctx) -> LLMRequest:
        """
        Build a provider-agnostic `LLMRequest` for this service from the engine-produced `Prompt`.

        Default implementation uses the PromptEngine output to create messages and
        stamps identity and codec routing. Subclasses may override hooks instead of
        replacing this whole method.

        Raises
        ------
        ServiceBuildRequestError
            If both the instruction and user message are empty.
        """
        async with service_span(f"LLMService.{self.__class__.__name__}.build_request", **self.flatten_context()):
            # 1) Get or build prompt is available
            prompt = await self.aget_prompt()

            # 2) Build messages via hooks
            messages: list[LLMRequestMessage] = []
            messages += await self._abuild_request_instructions(prompt, **ctx)
            messages += await self._abuild_request_user_input(prompt, **ctx)
            messages += await self._abuild_request_extras(prompt, **ctx)

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
            # attach context for downstream tracing/providers
            req.context = dict(self.context)

            # 4) Resolve codec and attach response format and codec identity
            codec = self.resolve_codec()
            req.codec_identity = codec.identity.as_str

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
            req = await self._afinalize_request(req, **ctx)
            return req

    # --------------------------- build hooks ---------------------------
    def _coerce_role(self, value: str | LLMRole) -> LLMRole:
        """Coerce an arbitrary role input to a valid `LLMRole` Enum.

        Rules:
        - If an `LLMRole` is passed, return it unchanged.
        - If a string is passed, try value-based lookup case-insensitively (e.g., "user" → LLMRole.USER).
        - If that fails, try name-based lookup (e.g., "USER" → LLMRole.USER).
        - Fallback to `LLMRole.SYSTEM` on unknown inputs.
        """
        if isinstance(value, LLMRole):
            return value
        v = str(value or "").strip()
        if not v:
            return LLMRole.SYSTEM
        # Prefer value-based, case-insensitive
        try:
            return LLMRole(v.lower())
        except Exception:
            pass
        # Fallback: name-based, case-insensitive (Enum names are upper-case)
        try:
            return LLMRole(v.upper())
        except Exception:
            return LLMRole.SYSTEM

    async def _abuild_request_instructions(self, prompt: Prompt, **ctx) -> list[LLMRequestMessage]:
        """Create developer messages from prompt.instruction (if present)."""
        messages: list[LLMRequestMessage] = []
        instruction = getattr(prompt, "instruction", None)
        if instruction:
            messages.append(LLMRequestMessage(role=LLMRole.DEVELOPER, content=[LLMTextPart(text=str(instruction))]))
        return messages

    async def _abuild_request_user_input(self, prompt: Prompt, **ctx) -> list[LLMRequestMessage]:
        """Create user messages from prompt.message (if present)."""
        messages: list[LLMRequestMessage] = []
        message = getattr(prompt, "message", None)
        if message:
            messages.append(LLMRequestMessage(role=LLMRole.USER, content=[LLMTextPart(text=str(message))]))
        return messages

    async def _abuild_request_extras(self, prompt: Prompt, **ctx) -> list[LLMRequestMessage]:
        """Create extra messages from prompt.extra_messages ((role, text) pairs)."""
        messages: list[LLMRequestMessage] = []
        extras = getattr(prompt, "extra_messages", None) or []
        for role, text in extras:
            if text:
                llm_role: LLMRole = self._coerce_role(role)
                messages.append(LLMRequestMessage(role=llm_role, content=[LLMTextPart(text=str(text))]))
        return messages

    async def _afinalize_request(self, req: LLMRequest, **ctx) -> LLMRequest:
        """Final request customization hook (no-op by default)."""
        return req

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
        • Replaces the former private `_get_client` usage.
        """
        if self.client is not None:
            return self.client
        self.client = self._resolve_client()
        return self.client

    def _resolve_client(self, codec: BaseCodec | None = None) -> AIClient:
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
        Execute the service (non-streaming) and emit request/response events via the configured emitter.
        Uses only `self.context` for domain data; identity is read from `self.identity`.
        """
        if not self.emitter:
            raise ServiceConfigError("emitter not provided")
        ident = self.identity
        identity_label = f"{ident.namespace}.{ident.kind}.{ident.name}"
        try:
            codec_label = Identity.get_for(self.codec).as_str if self.codec is not None else Identity.get_for(
                self.resolve_codec()).as_str
        except Exception:
            codec_label = "unknown"
        attrs = {
            "identity": identity_label,
            "codec": codec_label,
        }
        # include a shallow context snapshot for tracing
        attrs.update(self.flatten_context())

        logger.info("llm.service.start", extra=attrs)
        async with service_span(f"LLMService.{self.__class__.__name__}.run", **attrs):
            req = await self.abuild_request()
            req.stream = False

            client = self.get_client()
            self.emitter.emit_request(self.context, self.identity.as_str, req)

            attempt = 1
            while attempt <= max(1, self.max_attempts):
                try:
                    resp: LLMResponse = await client.send_request(req)
                    if getattr(resp, "codec", None) is None:
                        resp.codec = req.codec_identity
                    resp.namespace, resp.kind, resp.name = ident.namespace, ident.kind, ident.name
                    if getattr(resp, "request_correlation_id", None) is None:
                        resp.request_correlation_id = req.correlation_id
                    self.emitter.emit_response(self.context, self.identity.as_str, resp)
                    await self.on_success(self.context, resp)  # pass context to app hooks
                    logger.info("llm.service.success",
                                extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt})
                    return resp
                except Exception as e:
                    if attempt >= max(1, self.max_attempts):
                        self.emitter.emit_failure(self.context, self.identity.as_str, req.correlation_id, str(e))
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
        Execute the service with streaming and emit stream events via the configured emitter.
        Uses only `self.context` for domain data; identity is read from `self.identity`.
        """
        if not self.emitter:
            raise ServiceConfigError("emitter not provided")
        ident = self.identity
        identity_label = f"{ident.namespace}.{ident.kind}.{ident.name}"
        try:
            codec_label = Identity.get_for(self.codec).as_str if self.codec is not None else Identity.get_for(
                self.resolve_codec()).as_str
        except Exception:
            codec_label = "unknown"
        attrs = {
            "identity": identity_label,
            "codec": codec_label,
        }
        attrs.update(self.flatten_context())

        async with service_span(f"LLMService.{self.__class__.__name__}.run_stream", **attrs):
            req = await self.abuild_request()
            req.stream = True

            client = self.get_client()
            self.emitter.emit_request(self.context, self.identity.as_str, req)

            attempt = 1
            started = False
            while attempt <= max(1, self.max_attempts) and not started:
                try:
                    async for chunk in client.stream_request(req):
                        started = True
                        self.emitter.emit_stream_chunk(self.context, self.identity.as_str, chunk)
                    self.emitter.emit_stream_complete(self.context, self.identity.as_str, req.correlation_id)
                    return
                except Exception as e:
                    if started or attempt >= max(1, self.max_attempts):
                        self.emitter.emit_failure(self.context, self.identity.as_str, req.correlation_id, str(e))
                        await self.on_failure(self.context, e)
                        logger.exception("llm.service.stream.error",
                                         extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt})
                        raise
                    logger.warning("llm.service.stream.retrying",
                                   extra={**attrs, "attempt": attempt, "max_attempts": self.max_attempts})
                    await self._backoff_sleep(attempt)
                    attempt += 1

    async def on_success(self, context: dict, resp: LLMResponse) -> None:
        ...

    async def on_failure(self, context: dict, err: Exception) -> None:
        ...
