# simcore_ai/components/services/base.py
"""
BaseService: Abstract base for LLM-backed AI services.

Identity
--------
• Identity is a class-level concept provided by `IdentityMixin`.
  Each concrete service class has a stable `identity: Identity`.
• Instances read `self.identity`, which mirrors the class identity.
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

import asyncio
import logging
from abc import ABC
from typing import Any, ClassVar, Union, Optional, Protocol

from asgiref.sync import async_to_sync, sync_to_async

from .exceptions import ServiceConfigError, ServiceCodecResolutionError, ServiceBuildRequestError
from ..base import BaseComponent
from ..codecs.base import BaseCodec
from ..mixins import LifecycleMixin
from ..promptkit import Prompt, PromptEngine, PromptPlan, PromptSection, PromptSectionSpec
from ...client import AIClient
from ...identity import Identity, IdentityLike, IdentityMixin
from ...tracing import get_tracer, service_span
from ...types import LLMRequest, LLMRequestMessage, LLMResponse, LLMTextPart, LLMRole

logger = logging.getLogger(__name__)
tracer = get_tracer("simcore_ai.service")


class ServiceEmitter(Protocol):
    def emit_request(self, context: dict, namespace: str, request_dto: LLMRequest) -> None: ...

    def emit_response(self, context: dict, namespace: str, response_dto: LLMResponse) -> None: ...

    def emit_failure(self, context: dict, namespace: str, correlation_id, error: str) -> None: ...

    def emit_stream_chunk(self, context: dict, namespace: str, chunk_dto) -> None: ...

    def emit_stream_complete(self, context: dict, namespace: str, correlation_id) -> None: ...


CodecLike = Union[type[BaseCodec], BaseCodec, IdentityLike]


class BaseService(IdentityMixin, LifecycleMixin, BaseComponent, ABC):
    """
    Abstract base for LLM-backed AI services.

    • Identity is exposed as `self.identity: Identity`, resolved by `IdentityMixin`.
    • Class attributes (namespace/kind/name) are resolver hints only.
    • Concrete services should rely on `self.identity.as_str` etc. instead of duplicating labels.
    Codec precedence
    ----------------
    1) Per-call override provided at init (`codec=...`)
    2) Explicit codec class (`codec_cls` arg) or class-level default (`BaseService.codec_cls`)
    3) Registry by service identity
    """
    abstract: ClassVar[bool] = True

    # Class-level configuration / hints
    required_context_keys: ClassVar[tuple[str, ...]] = ()
    codec_cls: ClassVar[type[BaseCodec] | None] = None
    prompt_plan: ClassVar[PromptPlan | list[PromptSectionSpec] | list[str] | None] = None
    prompt_engine: ClassVar[PromptEngine | None] = None
    provider_name: ClassVar[str | None] = None

    # Retry/backoff defaults (may be overridden per-instance if needed)
    max_attempts: int = 3
    backoff_initial: float = 0.5  # seconds
    backoff_factor: float = 2.0
    backoff_jitter: float = 0.1  # +/- seconds

    def __init__(
            self,
            *,
            context: Optional[dict[str, Any]] = None,
            codec: CodecLike | None = None,
            codec_cls: CodecLike | None = None,
            prompt_plan: PromptPlan | list[PromptSectionSpec | str] | IdentityLike | None = None,
            client: AIClient | None = None,
            emitter: ServiceEmitter | None = None,
            prompt_engine: PromptEngine | None = None,
            prompt_instruction_override: str | None = None,
            prompt_message_override: str | None = None,
            **kwargs: Any,
    ) -> None:
        """
        BaseService constructor.

        Notes
        -----
        - `context` is stored as a shallow dict copy.
        - `codec` / `codec_cls` / `prompt_plan` may be provided as flexible specs and are normalized.
        - Class-level `codec_cls` / `prompt_plan` / `prompt_engine` act as defaults.
        """
        super().__init__(**kwargs)

        # Context
        if context is None:
            self.context: dict[str, Any] = {}
        elif isinstance(context, dict):
            self.context = dict(context)
        else:
            try:
                self.context = dict(context)  # type: ignore[arg-type]
            except Exception:
                logger.warning(
                    "Invalid context for %s; expected mapping-like, got %r",
                    self.__class__.__name__,
                    type(context),
                )
                self.context = {}

        # Client / emitter
        self.client: AIClient | None = client
        self.emitter: ServiceEmitter | None = emitter

        # Prompt configuration / overrides
        self._prompt_engine: PromptEngine | None = prompt_engine or type(self).prompt_engine
        self.prompt_instruction_override: str | None = prompt_instruction_override
        self.prompt_message_override: str | None = prompt_message_override

        # Codec override (per-instance) and codec class
        self._codec_override: type[BaseCodec] | None = None
        if codec is not None:
            self._codec_override = self._coerce_codec_override(codec)

        # Resolve codec class from arg or class default; store per-instance override
        self._codec_cls: type[BaseCodec] | None = None
        base_codec_spec = codec_cls if codec_cls is not None else type(self).codec_cls
        if base_codec_spec is not None:
            self._codec_cls = self._coerce_codec_cls(base_codec_spec)

        # Prompt plan instance (from arg or class-level default)
        self._prompt_plan: PromptPlan | None = None
        plan_spec = prompt_plan if prompt_plan is not None else type(self).prompt_plan
        if plan_spec is not None:
            self._prompt_plan = self._coerce_prompt_plan_spec(plan_spec)

        # Cached prompt (only used when all sections are non-dynamic)
        self._prompt_cache: Prompt | None = None

        # Validate required context keys
        self.check_required_context()

    @classmethod
    def using(cls, **overrides: Any) -> BaseService:
        """
        Construct a new service instance with per-call configuration overrides.

        This helper is intentionally backend-agnostic. It simply forwards the given
        keyword arguments to the service constructor. Typical overrides include:

            - context: dict[str, Any]
            - codec / codec_cls: CodecLike
            - prompt_plan: PromptPlan | list[PromptSectionSpec | str] | IdentityLike
            - prompt_engine: PromptEngine
            - client: AIClient
            - emitter: ServiceEmitter
            - prompt_instruction_override / prompt_message_override: str

        Task-level concerns (priority, queue, retries, etc.) are handled by the
        Django Tasks layer and MUST NOT be passed here.
        """
        return cls(**overrides)

    @property
    def slug(self) -> str:
        """Get slug for Service (from identity string)."""
        return self.identity.as_str

    @property
    def codec(self) -> BaseCodec:
        raise RuntimeError("Codec property is not available; codecs are instantiated per-call.")

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
        """True if any section in the active plan is dynamic."""
        plan = self._prompt_plan
        if not plan:
            # No explicit plan -> treat as dynamic / non-cacheable
            return True
        sections = getattr(plan, "items", None) or getattr(plan, "sections", None) or ()
        return any(getattr(section, "is_dynamic", False) for section in sections)

    # ----------------------------------------------------------------------
    # Context validation
    # ----------------------------------------------------------------------
    def check_required_context(self) -> None:
        """Validate that required context keys are present.

        This enforces that each key listed in `required_context_keys` exists in `self.context`
        and is not None. Subclasses may override to implement stricter validation.
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

    # ----------------------------------------------------------------------
    # Internal coercion helpers
    # ----------------------------------------------------------------------
    def _coerce_codec_cls(self, value: CodecLike) -> type[BaseCodec]:
        """
        Normalize a CodecLike into a BaseCodec subclass.

        Accepts:
          - BaseCodec subclass -> returned as-is
          - BaseCodec instance -> its type
          - IdentityLike / str -> resolved via Identity
        """
        if isinstance(value, type) and issubclass(value, BaseCodec):
            return value
        if isinstance(value, BaseCodec):
            return type(value)

        resolved = Identity.resolve.try_for_(BaseCodec, value)
        if resolved is None:
            raise ServiceCodecResolutionError(ident=value, codec=None, service=self.__class__.__name__)
        return resolved

    def _coerce_codec_override(self, value: CodecLike) -> type[BaseCodec]:
        """
        Normalize a CodecLike into a BaseCodec subclass for use as `_codec_override`.
        """
        return self._coerce_codec_cls(value)

    def _coerce_prompt_plan_spec(
            self,
            spec: PromptPlan | list[PromptSectionSpec | str] | IdentityLike,
    ) -> PromptPlan:
        """
        Normalize various prompt plan specs into a PromptPlan instance.

        Accepts:
          - PromptPlan -> returned as-is
          - list/tuple of PromptSectionSpec|str -> resolved via PromptPlan.from_any(...)
          - IdentityLike -> resolved via Identity into PromptPlan or PromptSection, then wrapped
        """
        if isinstance(spec, PromptPlan):
            logger.debug("Prompt plan already resolved; returning as-is.")
            return spec

        if isinstance(spec, (list, tuple)):
            return PromptPlan.from_any(spec)

        # Treat anything else as identity-like
        resolved = Identity.resolve.try_for_("PromptPlan", spec)
        if resolved is None:
            raise ServiceBuildRequestError(
                f"Invalid prompt_plan spec for {self.__class__.__name__}: {spec!r}"
            )

        if isinstance(resolved, PromptPlan):
            return resolved

        # If resolution returns a PromptSection or similar, wrap it
        return PromptPlan.from_sections([resolved])

    # ----------------------------------------------------------------------
    # LifecycleMixin lifecycle integration
    # ----------------------------------------------------------------------
    def setup(self, **ctx):
        """Merge incoming context into `self.context` and validate required keys."""
        incoming = ctx.get("context") if "context" in ctx else ctx
        if isinstance(incoming, dict) and incoming:
            # Shallow merge; explicit values win
            self.context.update(incoming)
        self.check_required_context()
        return self

    def teardown(self, **ctx):
        """Teardown hook (no-op by default)."""
        return self

    async def afinalize(self, result, **ctx):
        """Post-processing hook (passthrough by default)."""
        return result

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
        """Flatten `self.context` to `context.*` keys for tracing/logging."""
        from simcore_ai.tracing import flatten_context as flatten_context_
        return flatten_context_(self.context)

    # ----------------------------------------------------------------------
    # Prompt resolution (async-first)
    # ----------------------------------------------------------------------
    def _try_get_matching_prompt_section(self) -> PromptSectionSpec | None:
        """
        Return the PromptSection class with matching Identity for this service, or None if not found.
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
          - Otherwise builds a fresh Prompt via `_aget_prompt()` and caches it
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
        Use `aget_prompt()` / `prompt` for cache-aware access.
        """
        async with service_span(
                f"LLMService.{self.__class__.__name__}._build_prompt",
                attributes=self.flatten_context(),
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
                section_cls = self._try_get_matching_prompt_section()
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

            engine = (
                    self._prompt_engine
                    or type(self).prompt_engine
                    or PromptEngine
            )
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
    # Codec resolution (sync-first)
    # ----------------------------------------------------------------------
    def _codec_label_from_cls(self, codec_cls: type[BaseCodec], fallback: str) -> str:
        """Best-effort label resolution for a codec class."""
        ident = getattr(codec_cls, "identity", None)
        if isinstance(ident, Identity):
            return ident.as_str
        # Allow older codecs to expose a simple "label" string, but don't rely on it.
        label = getattr(ident, "label", None) or getattr(codec_cls, "label", None)
        return str(label) if label else fallback

    def resolve_codec(self) -> tuple[type[BaseCodec], str]:
        """
        Sync codec resolver.

        Precedence:
          1) Per-call override (`codec=` at init) via `_codec_override`
          2) Explicit codec class (`codec_cls` arg) or class-level default (`codec_cls` on the class)
          3) Registry by this service's identity

        Returns:
            (codec_class, codec_label)

        Raises:
            ServiceCodecResolutionError if no codec can be resolved.
        """
        ident: Identity = self.identity
        ident_label = ident.as_str

        # 1) Explicit per-call override
        if self._codec_override is not None:
            codec_cls = self._codec_override
            label = self._codec_label_from_cls(codec_cls, ident_label)
            return codec_cls, label

        # 2) Explicit codec_cls for this instance, then class-level default
        if self._codec_cls is not None:
            codec_cls = self._codec_cls
            label = self._codec_label_from_cls(codec_cls, ident_label)
            return codec_cls, label

        if type(self).codec_cls is not None:
            codec_cls = type(self).codec_cls  # type: ignore[assignment]
            label = self._codec_label_from_cls(codec_cls, ident_label)
            return codec_cls, label

        # 3) Registry by service identity only (single source of truth)
        codec_cls = Identity.resolve.try_for_(BaseCodec, ident)
        if codec_cls is not None:
            label = self._codec_label_from_cls(codec_cls, ident_label)
            return codec_cls, label

        # Nothing matched
        raise ServiceCodecResolutionError(
            ident=ident,
            codec=None,
            service=self.__class__.__name__,
        )

    async def aresolve_codec(self) -> tuple[type[BaseCodec], str]:
        """
        Async wrapper around `resolve_codec()`.

        Keeps codec resolution centralized in the sync path while
        remaining usable from async-only code.
        """
        return await sync_to_async(self.resolve_codec, thread_sensitive=True)()

    # ------------------------------------------------------------------------
    # Service run helpers
    # ------------------------------------------------------------------------
    async def _aprepare_request(self, *, stream: bool, **kwargs: Any) -> LLMRequest:
        """
        Internal helper to build a base LLMRequest and stamp the stream flag.

        Delegates to `abuild_request(...)` and sets `req.stream` accordingly.
        This method relies on `self.context` for contextual data rather than a
        separate `ctx` dict being threaded through.
        """
        req = await self.abuild_request(**kwargs)
        req.stream = stream
        return req

    async def _aprepare_codec(self) -> tuple[BaseCodec | None, str | None]:
        """
        Internal helper to resolve and instantiate a codec for this service call.

        Returns:
            (codec_instance_or_None, codec_label_or_None)
        """
        codec_cls, codec_label = await self.aresolve_codec()

        codec: BaseCodec | None
        try:
            codec = codec_cls(service=self)  # type: ignore[call-arg]
        except TypeError:
            codec = codec_cls()  # type: ignore[call-arg]

        return codec, codec_label

    async def aprepare(
            self, *, stream: bool, **kwargs: Any
    ) -> tuple[LLMRequest, BaseCodec | None, dict[str, Any]]:
        """
        Prepare a request + codec instance + tracing attrs for a single service call.

        Responsibilities:
          - Build the LLMRequest using the current prompt plan and context.
          - Set the `stream` flag on the request.
          - Resolve and instantiate a codec instance (if available).
          - Attach codec identity to the request when available.
          - Build a shared `attrs` dict for logging/tracing.

        Returns:
            (request, codec_instance_or_None, attrs_dict)
        """
        ident: Identity = self.identity

        # Resolve codec and instantiate per-call instance
        codec, codec_label = await self._aprepare_codec()

        # Base attributes for logging/tracing
        attrs: dict[str, Any] = {
            "identity": ident.label,
            "codec": codec_label or "<unknown>",
        }
        attrs.update(self.flatten_context())

        # Build request and stamp stream flag
        req = await self._aprepare_request(stream=stream, **kwargs)

        # Attach codec identity to the request when available; schema hints are handled by the codec.
        if codec_label:
            try:
                req.codec_identity = codec_label  # type: ignore[attr-defined]
            except Exception:
                pass

        return req, codec, attrs

    # ----------------------------------------------------------------------
    # Request construction
    # ----------------------------------------------------------------------
    async def abuild_request(self, **kwargs) -> LLMRequest:
        """
        Build a provider-agnostic `LLMRequest` for this service from the resolved `Prompt`.

        Default implementation uses the PromptEngine output to create messages and
        stamps identity and codec routing. Subclasses may override hooks instead of
        replacing this whole method.

        Raises
        ------
        ServiceBuildRequestError
            If both the instruction and user message are empty.
        """
        async with service_span(
                f"LLMService.{self.__class__.__name__}.build_request",
                attributes=self.flatten_context(),
        ):
            # 1) Get or build prompt if available
            prompt = await self.aget_prompt()

            # 2) Build messages via hooks
            messages: list[LLMRequestMessage] = []
            messages += await self._abuild_request_instructions(prompt)
            messages += await self._abuild_request_user_input(prompt)
            messages += await self._abuild_request_extras(prompt)

            # Validate: at least one of instruction or user message must be present
            instr_present = bool(getattr(prompt, "instruction", None))
            user_present = bool(getattr(prompt, "message", None))
            if not (instr_present or user_present):
                raise ServiceBuildRequestError("Prompt produced no instruction or user message; cannot build request")

            # 3) Create base request and stamp identity (context is kept on self.context only)
            ident = self.identity
            req = LLMRequest(messages=messages, stream=False)
            req.namespace = ident.namespace
            req.kind = ident.kind
            req.name = ident.name

            # 4) Final customization hook (codec/schema are handled later in `arun` via the codec)
            req = await self._afinalize_request(req)
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

    async def _abuild_request_instructions(self, prompt: Prompt) -> list[LLMRequestMessage]:
        """Create developer messages from prompt.instruction (if present)."""
        messages: list[LLMRequestMessage] = []
        instruction = getattr(prompt, "instruction", None)
        if instruction:
            messages.append(LLMRequestMessage(role=LLMRole.DEVELOPER, content=[LLMTextPart(text=str(instruction))]))
        return messages

    async def _abuild_request_user_input(self, prompt: Prompt) -> list[LLMRequestMessage]:
        """Create user messages from prompt.message (if present)."""
        messages: list[LLMRequestMessage] = []
        message = getattr(prompt, "message", None)
        if message:
            messages.append(LLMRequestMessage(role=LLMRole.USER, content=[LLMTextPart(text=str(message))]))
        return messages

    async def _abuild_request_extras(self, prompt: Prompt) -> list[LLMRequestMessage]:
        """Create extra messages from prompt.extra_messages ((role, text) pairs)."""
        messages: list[LLMRequestMessage] = []
        extras = getattr(prompt, "extra_messages", None) or []
        for role, text in extras:
            if text:
                llm_role: LLMRole = self._coerce_role(role)
                messages.append(LLMRequestMessage(role=llm_role, content=[LLMTextPart(text=str(text))]))
        return messages

    async def _afinalize_request(self, req: LLMRequest) -> LLMRequest:
        """Final request customization hook (no-op by default)."""
        return req

    # ----------------------------------------------------------------------
    # Client resolution
    # ----------------------------------------------------------------------
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

    # ----------------------------------------------------------------------
    # Execution
    # ----------------------------------------------------------------------
    async def arun(self, ctx: dict | None = None, **kwargs) -> LLMResponse | None:
        """
        Core async execution path for this service.

        Any per-call `ctx` provided is merged into `self.context` up front so that
        downstream helpers rely solely on `self.context` instead of receiving a
        separate context dict.

        Builds the request, lets the codec prepare/encode, sends via the resolved client,
        lets the codec decode the response, emits events, and returns the final `LLMResponse`.
        A fresh codec instance is created per call and torn down in a finally block.
        """
        if ctx:
            incoming = ctx
            if not isinstance(incoming, dict):
                try:
                    incoming = dict(incoming)  # type: ignore[arg-type]
                except Exception:
                    logger.warning(
                        "Invalid ctx for %s; expected mapping-like, got %r",
                        self.__class__.__name__,
                        type(ctx),
                    )
                    incoming = {}
            if incoming:
                self.context.update(incoming)
                self.check_required_context()

        if not self.emitter:
            raise ServiceConfigError("emitter not provided")

        ident: Identity = self.identity

        # Prepare request + codec instance + attrs for this call
        req, codec, attrs = await self.aprepare(stream=False, **kwargs)

        logger.info("simcore.service.%s.run" % self.__class__.__name__, extra=attrs)
        async with service_span(
                f"simcore.service.{self.__class__.__name__}.run",
                attributes=attrs,
        ):
            try:
                if codec is not None:
                    await codec.asetup(context=self.context)
                    await codec.aencode(req)

                client = self.get_client()
                self.emitter.emit_request(self.context, self.identity.as_str, req)

                attempt = 1
                while attempt <= max(1, self.max_attempts):
                    try:
                        resp: LLMResponse = await client.send_request(req)

                        # Tag response identity/correlation
                        resp.namespace, resp.kind, resp.name = ident.namespace, ident.kind, ident.name
                        if getattr(resp, "request_correlation_id", None) is None:
                            resp.request_correlation_id = req.correlation_id

                        # Attach codec identity if missing (write-safe fields only)
                        if hasattr(resp, "codec_identity"):
                            if not getattr(resp, "codec_identity", None):
                                try:
                                    resp.codec_identity = req.codec_identity  # type: ignore[attr-defined]
                                except Exception:
                                    pass

                        # Let the codec decode/shape the response
                        if codec is not None:
                            await codec.adecode(resp)

                        self.emitter.emit_response(self.context, self.identity.as_str, resp)
                        await self.on_success(self.context, resp)

                        logger.info(
                            "llm.service.success",
                            extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt},
                        )
                        return resp
                    except Exception as e:
                        if attempt >= max(1, self.max_attempts):
                            self.emitter.emit_failure(self.context, self.identity.as_str, req.correlation_id, str(e))
                            await self.on_failure(self.context, e)
                            logger.exception(
                                "llm.service.error",
                                extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt},
                            )
                            raise
                        logger.warning(
                            "llm.service.retrying",
                            extra={**attrs, "attempt": attempt, "max_attempts": self.max_attempts},
                        )
                        await self._backoff_sleep(attempt)
                        attempt += 1
            finally:
                if codec is not None:
                    try:
                        await codec.ateardown()
                    except Exception:
                        logger.debug("codec teardown failed; continuing", exc_info=True)
        return None

    async def run_stream(self, ctx: dict | None = None, **kwargs):
        """
        Execute the service with streaming enabled.

        Any per-call `ctx` provided is merged into `self.context` up front so that
        downstream helpers rely solely on `self.context`.

        The codec is constructed per call, used to prepare the request, decode chunks,
        and finalize the stream, then torn down.
        """
        if ctx:
            incoming = ctx
            if not isinstance(incoming, dict):
                try:
                    incoming = dict(incoming)  # type: ignore[arg-type]
                except Exception:
                    logger.warning(
                        "Invalid ctx for %s; expected mapping-like, got %r",
                        self.__class__.__name__,
                        type(ctx),
                    )
                    incoming = {}
            if incoming:
                self.context.update(incoming)
                self.check_required_context()

        if not self.emitter:
            raise ServiceConfigError("emitter not provided")

        # Prepare request + codec instance + attrs for this call
        req, codec, attrs = await self.aprepare(stream=True, **kwargs)

        logger.info("simcore.service.%s.run_stream" % self.__class__.__name__, extra=attrs)
        async with service_span(
                f"simcore.service.{self.__class__.__name__}.run_stream",
                attributes=self.flatten_context()
        ):
            try:
                if codec is not None:
                    await codec.asetup(context=self.context)
                    await codec.aencode(req)

                client = self.get_client()
                self.emitter.emit_request(self.context, self.identity.as_str, req)

                attempt = 1
                started = False
                while attempt <= max(1, self.max_attempts) and not started:
                    try:
                        async for chunk in client.stream_request(req):
                            started = True
                            # Let the codec inspect/transform chunks
                            if codec is not None:
                                try:
                                    await codec.adecode_chunk(chunk)
                                except AttributeError:
                                    # Older codecs may not implement the hook
                                    pass
                            self.emitter.emit_stream_chunk(self.context, self.identity.as_str, chunk)

                        # Allow codec to finalize any stream-level state
                        if codec is not None:
                            try:
                                await codec.afinalize_stream()
                            except AttributeError:
                                pass

                        self.emitter.emit_stream_complete(self.context, self.identity.as_str, req.correlation_id)
                        return
                    except Exception as e:
                        if started or attempt >= max(1, self.max_attempts):
                            self.emitter.emit_failure(self.context, self.identity.as_str, req.correlation_id, str(e))
                            await self.on_failure(self.context, e)
                            logger.exception(
                                "llm.service.stream.error",
                                extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt},
                            )
                            raise
                        logger.warning(
                            "llm.service.stream.retrying",
                            extra={**attrs, "attempt": attempt, "max_attempts": self.max_attempts},
                        )
                        await self._backoff_sleep(attempt)
                        attempt += 1
            finally:
                if codec is not None:
                    try:
                        await codec.ateardown()
                    except Exception:
                        logger.debug("codec teardown failed; continuing", exc_info=True)

    # ----------------------------------------------------------------------
    # Result hooks
    # ----------------------------------------------------------------------
    async def on_success(self, context: dict, resp: LLMResponse) -> None:
        ...

    async def on_failure(self, context: dict, err: Exception) -> None:
        ...
