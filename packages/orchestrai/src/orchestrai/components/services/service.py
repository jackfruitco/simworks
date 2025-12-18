# orchestrai/components/services/services.py
"""
BaseService: Abstract base for LLM-backed AI services.

Identity
--------
• Identity is a class-level concept provided by `IdentityMixin`.
  Each concrete service class has a stable `identity: Identity`.
• Instances read `self.identity`, which mirrors the class identity.
• Class attributes `domain`, `namespace`, `group`, and `name` are treated as hints passed to the resolver.
  Legacy `kind` is also accepted as an alias for `group`.
• Prefer `self.identity.as_str` ("domain.namespace.group.name") or `self.identity.as_tuple` anywhere a
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
from typing import TYPE_CHECKING

from asgiref.sync import async_to_sync, sync_to_async

from .exceptions import ServiceConfigError, ServiceCodecResolutionError, ServiceBuildRequestError
from ..base import BaseComponent
from ..codecs.codec import BaseCodec
from ..mixins import LifecycleMixin
from ..promptkit import Prompt, PromptEngine, PromptPlan, PromptSection, PromptSectionSpec
from ...identity import Identity, IdentityLike, IdentityMixin
from ...tracing import get_tracer, service_span, SpanPath
from ...types import Request, Response, StrictBaseModel
from ...types.content import ContentRole
from ...types.input import InputTextContent
from ...types.messages import InputItem
from ...registry.exceptions import RegistryLookupError
from ...resolve import (
    apply_schema_adapters,
    resolve_codec,
    resolve_prompt_plan,
    resolve_schema,
)

if TYPE_CHECKING:  # pragma: no cover
    from orchestrai.client import OrcaClient

logger = logging.getLogger(__name__)
tracer = get_tracer("orchestrai.service")

LOG_LENGTH_LIMIT: int = 250


class ServiceEmitter(Protocol):
    def emit_request(self, context: dict, namespace: str, request_dto: Request) -> None: ...

    def emit_response(self, context: dict, namespace: str, response_dto: Response) -> None: ...

    def emit_failure(self, context: dict, namespace: str, correlation_id, error: str) -> None: ...

    def emit_stream_chunk(self, context: dict, namespace: str, chunk_dto) -> None: ...

    def emit_stream_complete(self, context: dict, namespace: str, correlation_id) -> None: ...


CodecLike = Union[type[BaseCodec], BaseCodec, IdentityLike]


class BaseService(IdentityMixin, LifecycleMixin, BaseComponent, ABC):
    """
    Abstract base for LLM-backed AI services.

    • Identity is exposed as `self.identity: Identity`, resolved by `IdentityMixin`.
    • Class attributes (domain/namespace/group/name) are resolver hints only (legacy `kind` is accepted as group).
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
    codec_cls: ClassVar[type[BaseCodec] | None] = None  # Deprecated, see `codecs`

    codecs: list[BaseCodec] = []

    prompt_plan: ClassVar[PromptPlan | list[PromptSectionSpec] | list[str] | None] = None
    prompt_engine: ClassVar[PromptEngine | None] = None
    provider_name: ClassVar[str | None] = None

    _span_root: ClassVar[SpanPath | None] = None

    # Retry/backoff defaults (may be overridden per-instance if needed)
    max_attempts: int = 3
    backoff_initial: float = 0.5  # seconds
    backoff_factor: float = 2.0
    backoff_jitter: float = 0.1  # +/- seconds

    dry_run: bool = False

    def __init__(
            self,
            *,
            context: Optional[dict[str, Any]] = None,
            codec: CodecLike | None = None,
            codec_cls: CodecLike | None = None,
            prompt_plan: PromptPlan | list[PromptSectionSpec | str] | IdentityLike | None = None,
            client: OrcaClient | None = None,
            emitter: ServiceEmitter | None = None,
            prompt_engine: PromptEngine | None = None,
            prompt_instruction_override: str | None = None,
            prompt_message_override: str | None = None,
            response_schema: type[StrictBaseModel] | None = None,
            dry_run: bool | None = None,
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

        self.span_prefix = f"{self.__class__.__module__}.{self.__class__.__name__}"

        # Context
        if context is None:
            self.context: dict[str, Any] = {}
        elif isinstance(context, dict):
            self.context = dict(context)
        else:
            try:
                self.context = dict(context)  # type: ignore[arg-type]
            except Exception:
                logger.error(
                    "Invalid context for %s; expected mapping-like, got %r",
                    self.__class__.__name__,
                    type(context),
                )
                self.context = {}

        # Client / emitter
        self.client: OrcaClient | None = client
        self.emitter: ServiceEmitter | None = emitter

        # Dry-run flag (prefer explicit arg, then context override, else class default)
        context_dry_run = None
        if "dry_run" in self.context:
            context_dry_run = bool(self.context.pop("dry_run"))

        self.dry_run = (
            bool(dry_run)
            if dry_run is not None
            else context_dry_run
            if context_dry_run is not None
            else type(self).dry_run
        )

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
        self._prompt_plan_source: str | None = None
        plan_spec = None
        if prompt_plan is not None:
            plan_spec = prompt_plan
            self._prompt_plan_source = "override"
        elif type(self).prompt_plan is not None:
            plan_spec = type(self).prompt_plan
            self._prompt_plan_source = "class"

        if plan_spec is not None:
            self._prompt_plan = self._coerce_prompt_plan_spec(plan_spec)

        # Cached prompt (only used when all sections are non-dynamic)
        self._prompt_cache: Prompt | None = None

        # Component store (for registry-backed resolution)
        from ...registry.active_app import get_component_store as _get_component_store

        self.component_store = _get_component_store()

        self._schema_resolution = resolve_schema(
            identity=self.identity,
            override=response_schema,
            default=getattr(type(self), "response_schema", None),
            store=self.component_store,
        )
        self._resolved_schema_json = self._schema_resolution.selected.meta.get("schema_json")
        self.response_schema: type[StrictBaseModel] | None = self._schema_resolution.value
        self._set_context(self._schema_resolution.context("schema"), log_cat="schema")

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
            - client: OrcaClient
            - emitter: ServiceEmitter
            - prompt_instruction_override / prompt_message_override: str
            - dry_run: bool

        Task-level concerns (priority, queue, retries, etc.) are handled by the
        Django Tasks layer and MUST NOT be passed here.
        """
        return cls(**overrides)

    @property
    def slug(self) -> str:
        """Get slug for Service (from identity string)."""
        return self.identity.as_str

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
        logger.debug(self._build_stdout(
            "context",
            f"validated required context keys: {', '.join(map(str, required))}",
            indent_level=1,
            success=True
        ))

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
        LOG_CAT = "prompt.plan"
        if isinstance(spec, PromptPlan):
            logger.debug(self._build_stdout(
                LOG_CAT, "coercion skipped -- already PromptPlan", indent_level=2, success=True)
            )
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

    def finalize(self, result, **ctx):
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
        from orchestrai.tracing import flatten_context as flatten_context_
        return flatten_context_(self.context)

    @property
    def span_root(self) -> SpanPath:
        """
        Root span path for this service.

        Subclasses may override the class-level `_span_root` with a `SpanPath`
        instance. If not set, this defaults to `orchestrai.svc.<ClassName>`.
        """
        root = getattr(type(self), "_span_root", None)
        if isinstance(root, SpanPath):
            return root
        return SpanPath(("orchestrai", "svc", self.__class__.__name__))

    def _span(self, *segments: str) -> str:
        """Helper to build a child span name from the service's span root."""
        return str(self.span_root.child(*segments))

    def _build_stdout(
            self,
            part: str | None = None,
            msg: str | None = None,
            indent_level: int = 1,
            success: Any = None
    ) -> str:
        """
        Build a clean stdout line for the service runner.

        success:
            True  -> shows a checkmark
            False -> shows a cross
            "N/A" -> shows a checkmark (greyed)
            None  -> shows no symbol
            Anything else -> shows a warning symbol
        """
        # TODO override ident_level=1 for testing
        indent_level = 1
        prefix = "--" * min(4, indent_level)
        label = f"[{part}]: " if part else ""

        symbol = ""
        if success:
            symbol = " ✅ "
        elif success is False:
            symbol = " ❌ "
        elif success == "N/A":
            symbol = " ☑️ "
        elif success is not None:
            symbol = " ⚠️ "

        return f"{prefix}{symbol}{label}{msg}"

    def _set_context(self, values: dict[str, Any], log_cat: str | None = None) -> None:
        """Set values in `self.context` and log them."""
        added: list[str] = []
        for key, value in values.items():
            try:
                self.context[key] = value
                added.append(str(key))
            except Exception:
                logger.debug(
                    self._build_stdout(
                        log_cat,
                        f"could not set context[{key}]: {value!r}",
                        indent_level=3,
                        success="non-fatal",
                    ),
                    exc_info=True,
                )
        if added:
            logger.debug(self._build_stdout(
                log_cat,
                f"set context[{', '.join(added)}]", indent_level=3, success=True
            ))

    # ----------------------------------------------------------------------
    # Prompt resolution (async-first)
    # ----------------------------------------------------------------------
    def _resolve_prompt_plan(self) -> tuple[PromptPlan | None, str]:
        """
        Resolve the prompt plan for this service following precedence rules.

        Precedence:
          1) Runtime overrides passed to the constructor
          2) Service class definition
          3) Automagic identity match (PromptSection.identity == service.identity)
        """
        LOG_CAT = "prompt"
        resolution = resolve_prompt_plan(self)
        self._set_context(resolution.context("prompt.plan"), log_cat=LOG_CAT)

        branch = resolution.branch
        plan = resolution.value

        if plan is None:
            logger.debug(self._build_stdout(
                LOG_CAT,
                f"no prompt plan resolved for {self.identity.as_str}; continuing without one",
                indent_level=2,
                success="non-fatal",
            ))
        else:
            logger.debug(self._build_stdout(
                LOG_CAT,
                f"resolved prompt plan ({branch})",
                indent_level=2,
                success=True,
            ))
        return plan, branch

    async def aget_prompt(self) -> Prompt:
        """
        Async, cache-aware accessor for the Prompt.

        Respects `has_dynamic_prompt`:
          - If no dynamic sections and a cached Prompt exists, returns it.
          - Otherwise builds a fresh Prompt via `_aget_prompt()` and caches it
            when safe.
        """
        LOG_CAT = "prompt"
        self._set_context(
            {
                "prompt.source": "<unknown>",
                "prompt.updated_cache": "<unknown>",
            },
            log_cat=LOG_CAT
        )

        # If we have a cached prompt and it's safe to reuse, return it
        if self._prompt_cache is not None and not self.has_dynamic_prompt:
            logger.debug(self._build_stdout(
                LOG_CAT, "resolved from cache", indent_level=3, success=True
            ))
            self.context["prompt.source"] = "cache"
            return self._prompt_cache

        # Always build fresh when dynamic; may cache when static
        prompt = await self._aget_prompt()

        if not self.has_dynamic_prompt:
            self._prompt_cache = prompt
            logger.debug(self._build_stdout(
                LOG_CAT, "cached", indent_level=3, success=True
            ))

        return prompt

    async def _aget_prompt(self) -> Prompt:
        """
        Build a Prompt using the configured PromptEngine.

        This is a pure builder: it does not read or write the prompt cache.
        Use `aget_prompt()` / `prompt` for cache-aware access.
        """
        LOG_CAT = "prompt"

        self._set_context(
            {
                "prompt.plan.source": "<unknown>",
                "prompt.engine": "<unknown>",
                "prompt.instruction.override": False,
                "prompt.message.override": False,
            },
            log_cat=LOG_CAT
        )

        # 1) Using both overrides: build directly
        if self.prompt_instruction_override and self.prompt_message_override:
            self.context["prompt.plan.source"] = "overrides"
            logger.debug(self._build_stdout(
                LOG_CAT, f"resolved (from overrides)",
                indent_level=3, success=True
            ))
            return Prompt(
                instruction=str(self.prompt_instruction_override),
                message=str(self.prompt_message_override),
            )

        plan, plan_source = self._resolve_prompt_plan()
        self.context["prompt.plan.source"] = plan_source

        # Ensure already coerced to PromptPlan
        if plan is not None:
            assert isinstance(plan, PromptPlan)

        logger.debug(self._build_stdout(
            LOG_CAT,
            f"resolved (from {self.context['prompt.plan.source']}): "
            f"{getattr(plan, 'describe', lambda: plan)()}",
            indent_level=3, success=True,
        ))

        engine = (
                self._prompt_engine
                or type(self).prompt_engine
                or PromptEngine
        )
        self.context["prompt.engine"] = repr(engine)

        ctx = {"context": self.context, "service": self}

        async with service_span(
                self._span("run", "prepare", "prompt", "build"),
                attributes=self.flatten_context(),
        ):
            abuild = getattr(engine, "abuild_from", None)
            if callable(abuild):
                self.context["prompt.engine.build_method"] = repr(abuild)
                prompt_: Prompt = await abuild(plan=plan, **ctx)  # type: ignore[arg-type]
            else:
                build = getattr(engine, "build_from", None)
                if not callable(build):
                    raise ServiceBuildRequestError(
                        "PromptEngine has no build_from/abuild_from callable"
                    )
                self.context["prompt.engine.build_method"] = repr(build)
                prompt_ = build(plan=plan, **ctx)  # type: ignore[arg-type]
        logger.debug(self._build_stdout(
            LOG_CAT,
            f"initial build complete: "
            f"instruction={prompt_.instruction[:25]}...,"
            f"message={(prompt_.message or '')[:25]}...",
            indent_level=3, success=True
        ))

        # Apply optional overrides
        if self.prompt_instruction_override is not None:
            try:
                self.context["prompt.instruction.override"] = True
                setattr(prompt_, "instruction", str(self.prompt_instruction_override))
                logger.debug(self._build_stdout(
                    LOG_CAT,
                    f"found instruction override: {self.prompt_instruction_override[:250]}",
                    indent_level=4,
                    success=True
                ))
            except Exception as err:
                logger.debug(self._build_stdout(
                    LOG_CAT,
                    f"could not override instruction; ignoring: {type(err).__name__}: {str(err)}",
                    indent_level=4, success="non-fatal"
                ), exc_info=True)

        if self.prompt_message_override is not None:
            try:
                instr_override = self.context["prompt.instruction.override"]
                setattr(prompt_, "message", str(self.prompt_message_override))
                self.context["prompt.message.override"] = True
                logger.debug(self._build_stdout(
                    LOG_CAT, f"found message override: {self.prompt_message_override[:250]}",
                    indent_level=3, success=True
                ))
            except Exception as err:
                logger.debug(self._build_stdout(
                    LOG_CAT,
                    f"could not override user message; ignoring: {type(err).__name__}: {str(err)}",
                    indent_level=4, success="non-fatal"
                ), exc_info=True)

        msg = "build complete"
        if all(self.context[f"prompt.{attr}.override"] for attr in ("instruction", "message")):
            msg += " (with overrides)"
        elif self.context["prompt.instruction.override"]:
            msg += " (with instruction override)"
        elif self.context["prompt.message.override"]:
            msg += " (with message override)"

        if logger.isEnabledFor(logging.DEBUG):
            msg += f": instruction={prompt_.instruction[:250]}..., message={prompt_.message[:250]}..."

        logger.debug(self._build_stdout(LOG_CAT, msg, indent_level=2, success=True))

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

    def select_codecs(self) -> tuple[type[BaseCodec], ...]:
        """Select codec classes to use for this service.

        Default behavior:
        - If a response_schema is configured and a provider_name is set,
          ask BaseCodec to return all codecs that match this call signature
          (typically the backend's JSON / structured-output codec).
        - Returns an empty tuple if no codec applies.

        Uses the new backend-based API.
        """
        LOG_CAT = "codec"

        provider_label = (self.provider_name or "").strip()
        provider_ns = provider_label.split(".", 1)[0] if provider_label else ""
        constraints = None
        if self.response_schema and provider_ns:
            constraints = {"provider": provider_ns, "api": "responses", "result_type": "json"}

        resolution = resolve_codec(
            service=self,
            configured=getattr(type(self), "codecs", ()),
            constraints=constraints,
            store=self.component_store,
        )
        self._set_context(resolution.context("codec.select"), log_cat=LOG_CAT)

        candidates = ()
        if resolution.selected.meta.get("candidate_classes"):
            candidates = resolution.selected.meta["candidate_classes"]  # type: ignore[assignment]
        elif resolution.value is not None:
            candidates = (resolution.value,)

        if candidates:
            for cand in candidates:
                logger.debug(self._build_stdout(
                    LOG_CAT,
                    f"selected codec candidate: {getattr(cand, '__name__', repr(cand))}",
                    indent_level=3,
                    success=True,
                ))

        return tuple(candidates)

    def _select_codec_class(self) -> tuple[type[BaseCodec] | None, str | None]:
        """
        Internal codec-class selector.

        Precedence:
          1) Per-call override (`codec=` at init) via `_codec_override`
          2) Explicit codec class (`codec_cls` arg) or class-level default (`codec_cls` on the class)
          3) Automatic selection via the new backend-based API (`select_codecs`)
        """
        LOG_CAT = "codec"

        ident: Identity = self.identity
        ident_label = ident.as_str

        provider_label = (self.provider_name or "").strip()
        provider_ns = provider_label.split(".", 1)[0] if provider_label else ""
        constraints = None
        if self.response_schema and provider_ns:
            constraints = {"provider": provider_ns, "api": "responses", "result_type": "json"}

        resolution = resolve_codec(
            service=self,
            override=self._codec_override,
            explicit=self._codec_cls or type(self).codec_cls,  # type: ignore[arg-type]
            configured=getattr(type(self), "codecs", ()),
            constraints=constraints,
            store=self.component_store,
        )
        self._set_context(resolution.context("codec"), log_cat=LOG_CAT)

        codec_cls = resolution.value
        if codec_cls is None:
            logger.debug(
                self._build_stdout(
                    LOG_CAT,
                    "no codec resolved; continuing without codec",
                    indent_level=2,
                    success="non-fatal",
                )
            )
            return None, None

        label = self._codec_label_from_cls(codec_cls, ident_label)
        logger.debug(
            self._build_stdout(
                LOG_CAT,
                f"resolved codec ({resolution.branch}): {codec_cls.__name__} ({label})",
                indent_level=2,
                success=True,
            )
        )
        return codec_cls, label

    def _attach_response_schema_to_request(self, req: Request, codec: BaseCodec | None = None) -> None:
        """Populate request schema hints when a schema is available."""

        schema_cls = self.response_schema
        if schema_cls is None:
            return

        if getattr(req, "response_schema", None) is None:
            req.response_schema = schema_cls

        schema_json = self._resolved_schema_json
        if schema_json is None:
            try:
                schema_json = schema_cls.model_json_schema()
            except Exception:
                schema_json = None

        if codec is not None and getattr(codec, "schema_adapters", None):
            try:
                schema_json = apply_schema_adapters(schema_cls, getattr(codec, "schema_adapters"))
            except Exception:
                logger.debug("schema adapter application failed", exc_info=True)

        if schema_json is None:
            return

        req.response_schema_json = schema_json
        if getattr(req, "provider_response_format", None) is None:
            req.provider_response_format = schema_json

    # ------------------------------------------------------------------------
    # Service run helpers
    # ------------------------------------------------------------------------
    async def _aprepare_codec(self) -> tuple[BaseCodec | None, str | None]:
        """
        Internal helper to resolve and instantiate a codec for this service call.

        Returns:
            (codec_instance_or_None, codec_label_or_None)
        """
        LOG_CAT = "codec"

        async with service_span(
                self._span("run", "prepare", "codec", "resolve"),
                attributes=self.flatten_context(),
        ):
            codec_cls, codec_label = self._select_codec_class()

            if codec_cls is None:
                # No codec for this call (e.g., unstructured text only)
                self._set_context(
                    {
                        "service.codec.class": "<none>",
                        "service.codec.label": "<none>",
                    },
                    log_cat=LOG_CAT,
                )
                logger.debug(
                    self._build_stdout(
                        LOG_CAT,
                        "no codec prepared for this service call",
                        indent_level=3,
                        success="N/A",
                    )
                )
                return None, None

            try:
                codec: BaseCodec | None = codec_cls(service=self)  # type: ignore[call-arg]
            except Exception:
                logger.debug(
                    self._build_stdout(
                        LOG_CAT,
                        f"could not instantiate codec: {codec_cls!r}",
                        indent_level=3,
                        success="non-fatal",
                    ),
                    exc_info=True,
                )
                return None, codec_label

            self._set_context(
                {
                    "service.codec.class": codec_cls.__name__,
                    "service.codec.label": codec_label or "<unknown>",
                },
                log_cat=LOG_CAT,
            )

            logger.debug(
                self._build_stdout(
                    LOG_CAT,
                    f"prepared: {codec_cls.__name__} ({codec_label})",
                    indent_level=3,
                    success=True,
                )
            )

            return codec, codec_label

    async def aprepare(
            self, *, stream: bool, **kwargs: Any
    ) -> tuple[Request, BaseCodec | None, dict[str, Any]]:
        """
        Prepare a request + codec instance + tracing attrs for a single service call.

        Responsibilities:
          - Build the Request using the current prompt plan and context.
          - Set the `stream` flag on the request.
          - Resolve and instantiate a codec instance (if available).
          - Attach codec identity to the request when available.
          - Build a shared `attrs` dict for logging/tracing.

        Returns:
            (request, codec_instance_or_None, attrs_dict)
        """
        LOG_CAT = "prep"
        ident: Identity = self.identity

        async with service_span(
                self._span("run", "prepare"),
                attributes=self.flatten_context(),
        ):
            # Resolve codec and instantiate per-call instance
            codec, codec_label = await self._aprepare_codec()

            # Base attributes for logging/tracing
            attrs: dict[str, Any] = {
                "identity": ident.label,
                "codec": codec_label or "<unknown>",
            }
            attrs.update(self.flatten_context())

            # Stamp service-level context about this call
            self._set_context(
                {
                    "service.identity": ident.as_str,
                    "llm.stream": bool(stream),
                    "service.codec.label": codec_label or "<unknown>",
                },
                log_cat=LOG_CAT,
            )

            # Build request and stamp stream flag using the new builder API
            req = await self.abuild_request(**kwargs)
            req.stream = bool(stream)

            # Attach structured output hints early so provider backends can consume
            # them even when no codec is selected.
            self._attach_response_schema_to_request(req, codec)

            # Attach codec identity to the request when available; schema hints are handled by the codec.
            if codec_label:
                try:
                    req.codec_identity = codec_label  # type: ignore[attr-defined]
                    logger.debug(self._build_stdout(
                        "llm.request",
                        f"attached codec identity: {req.codec_identity}",
                        indent_level=3,
                        success=True
                    ))
                except Exception as err:
                    logger.debug(self._build_stdout(
                        "llm.request",
                        f"could not attach codec identity: {type(err).__name__}: {str(err)}",
                        indent_level=3,
                        success=False
                    ), exc_info=True)

        return req, codec, attrs

    # ----------------------------------------------------------------------
    # Request construction
    # ----------------------------------------------------------------------
    async def abuild_request(self, **kwargs) -> Request:
        """
        Build a backend-agnostic `Request` for this service from the resolved `Prompt`.

        Default implementation uses the PromptEngine output to create input and
        stamps identity and codec routing. Subclasses may override hooks instead of
        replacing this whole method.

        Raises
        ------
        ServiceBuildRequestError
            If both the instruction and user message are empty.
        """
        LOG_CAT = "llm.request"

        # 1) Get or build prompt if available
        async with service_span(
                self._span("run", "prepare", "request", "prompt"),
                attributes=self.flatten_context(),
        ):
            prompt = await self.aget_prompt()

            # 2) Build input via hooks
            messages: list[InputItem] = []
            messages += await self._abuild_request_instructions(prompt)
            messages += await self._abuild_request_user_input(prompt)
            messages += await self._abuild_request_extras(prompt)

            # Validate: at least one of instruction or user message must be present
            instr_present = bool(getattr(prompt, "instruction", None))
            user_present = bool(getattr(prompt, "message", None))
            if not (instr_present or user_present):
                if self.context.get("prompt.plan.source") == "none":
                    logger.debug(self._build_stdout(
                        LOG_CAT,
                        "prompt empty and no plan resolved; continuing",
                        indent_level=3,
                        success="non-fatal",
                    ))
                else:
                    raise ServiceBuildRequestError(
                        "Prompt produced no instruction or user message; cannot build request"
                    )

            # Stamp basic request content metadata into context for tracing
            self._set_context(
                {
                    "llm.request.message.count": len(messages),
                    "prompt.instruction.present": instr_present,
                    "prompt.message.present": user_present,
                },
                log_cat=LOG_CAT,
            )

        # 3) Create a request and stamp identity (context is kept on self.context only)
        ident = self.identity
        req = Request(input=messages, stream=False)
        req.namespace = ident.namespace
        req.kind = ident.kind
        req.name = ident.name

        # 4) Final customization hook (codec/schema are handled later in `arun` via the codec)
        req = await self._afinalize_request(req)
        return req

    # --------------------------- build hooks ---------------------------
    def _coerce_role(self, value: str | ContentRole) -> ContentRole:
        """Coerce an arbitrary role input to a valid `ContentRole` Enum.

        Rules:
        - If an `ContentRole` is passed, return it unchanged.
        - If a string is passed, try value-based lookup case-insensitively (e.g., "user" → ContentRole.USER).
        - If that fails, try name-based lookup (e.g., "USER" → ContentRole.USER).
        - Fallback to `ContentRole.SYSTEM` on unknown inputs.
        """
        if isinstance(value, ContentRole):
            return value
        v = str(value or "").strip()
        if not v:
            return ContentRole.SYSTEM
        # Prefer value-based, case-insensitive
        try:
            return ContentRole(v.lower())
        except Exception:
            pass
        # Fallback: name-based, case-insensitive (Enum names are upper-case)
        try:
            return ContentRole(v.upper())
        except Exception:
            return ContentRole.SYSTEM

    async def _abuild_request_instructions(self, prompt: Prompt) -> list[InputItem]:
        """Create developer input from prompt.instruction (if present)."""
        messages: list[InputItem] = []
        instruction = getattr(prompt, "instruction", None)
        if instruction:
            messages.append(InputItem(role=ContentRole.DEVELOPER, content=[InputTextContent(text=str(instruction))]))
        logger.debug(self._build_stdout(
            "prompt", "built developer message(s) from p.instruction(s)", indent_level=4, success=True
        ))
        return messages

    async def _abuild_request_user_input(self, prompt: Prompt) -> list[InputItem]:
        """Create user input from prompt.message (if present)."""
        messages: list[InputItem] = []
        message = getattr(prompt, "message", None)
        if message:
            messages.append(InputItem(role=ContentRole.USER, content=[InputTextContent(text=str(message))]))
        logger.debug(self._build_stdout(
            "prompt", "built user message(s) from p.message(s)", indent_level=4, success=True
        ))
        return messages

    async def _abuild_request_extras(self, prompt: Prompt) -> list[InputItem]:
        """Create extra input from prompt.extra_messages ((role, text) pairs)."""
        messages: list[InputItem] = []
        extras = getattr(prompt, "extra_messages", None) or []
        if extras:
            logger.debug(self._build_stdout(
                "prompt",
                f"found {len(extras)} extra message(s) in prompt",
                indent_level=4,
                success="N/A",
            ))
        for role, text in extras:
            if text:
                llm_role: ContentRole = self._coerce_role(role)
                messages.append(InputItem(role=llm_role, content=[InputTextContent(text=str(text))]))
                msg_preview = text[:25] + "..." if len(text) > 25 else text
                logger.debug(self._build_stdout(
                    "prompt",
                    f"built extra {llm_role.name} message from extra_messages: '{msg_preview}'",
                    indent_level=5,
                    success=True
                ))

        return messages

    async def _afinalize_request(self, req: Request) -> Request:
        """Final request customization hook (no-op by default)."""
        logger.debug(self._build_stdout(
            "llm.request",
            f"finalized (no-op; nothing given to finalize)",
            indent_level=2,
            success="N/A",
        ))
        return req

    # ----------------------------------------------------------------------
    # Client resolution
    # ----------------------------------------------------------------------
    def get_client(self) -> OrcaClient:
        """
        Public accessor for the backend client.

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

    def _resolve_client(self, codec: BaseCodec | None = None) -> OrcaClient:
        """Resolve an OrcaClient for this service.

        Policy
        ------
        1) Prefer an injected/registered client (registry-backed) when available.
        2) If the registry has no default client (common when Django autostart
           discovered components but did not build clients), fall back to the
           settings-backed client factory.

        Notes
        -----
        - `provider_name` may be:
            * a client alias (e.g. "default")
            * a provider alias/slug (e.g. "openai")
            * a dotted backend identity (e.g. "openai.responses.default")
        """
        provider_label = (self.provider_name or "").strip()
        provider_ns = provider_label.split(".", 1)[0] if provider_label else ""

        # 1) Fast path: use registry-backed singletons if they exist.
        try:
            from orchestrai.client.registry import get_ai_client

            if not provider_label:
                return get_ai_client()

            # Try explicit client name first.
            try:
                return get_ai_client(name=provider_label)
            except Exception:
                pass

            # Then treat as provider slug.
            return get_ai_client(provider=provider_ns or provider_label)
        except Exception:
            # Registry path failed (often because no default client is configured).
            pass

        # 2) Fallback: build/obtain a client from OrchestraiSettings via the factory.
        try:
            from orchestrai.client.factory import get_orca_client

            if not provider_label:
                return get_orca_client()

            # First assume provider_label is a client alias.
            try:
                return get_orca_client(client=provider_label)
            except Exception:
                # Otherwise treat it as a provider alias/slug.
                return get_orca_client(provider=provider_ns or provider_label)
        except Exception as e:
            raise ServiceConfigError(
                "No AI client available. Either inject `client=...` into the service, "
                "ensure Django autostart builds at least one Orca client, or configure "
                "an ORCA_CONFIG['CLIENT'] entry (and optional CLIENT defaults) so the factory can "
                "construct one."
            ) from e

    # ----------------------------------------------------------------------
    # Execution
    # ----------------------------------------------------------------------
    async def arun(self, **ctx) -> Response | None:
        """
        Core async execution path for non-streaming service calls.

        This is invoked by `LifecycleMixin.aexecute` inside the lifecycle `.run` span.
        All context merging and request/codec preparation is delegated to `_arun_core`.
        """
        return await self._arun_core(stream=False, **ctx)

    async def _arun_core(self, *, stream: bool, **ctx) -> Response | None:
        """
        Shared implementation for non-streaming and streaming runs.

        Handles:
          - merging per-call context into `self.context`
          - validating required context
          - ensuring an emitter is present
          - preparing the request/codec/attrs via `aprepare`
          - resolving the client and emitting the outbound request
          - delegating to `_asend` or `_astream` for IO
        """
        LOG_CAT = "svc.run"

        # Normalize and merge contextual overrides, if provided
        ctx = dict(ctx) if ctx else {}
        raw_ctx = ctx.pop("context", None)
        if raw_ctx:
            incoming = raw_ctx
            if not isinstance(incoming, dict):
                try:
                    incoming = dict(incoming)  # type: ignore[arg-type]
                except Exception:
                    logger.debug(self._build_stdout(
                        LOG_CAT,
                        f"could not parse context (expected mapping-like, but got '{repr(raw_ctx)}')",
                        indent_level=2,
                        success="non-fatal"
                    ), exc_info=True)
                    incoming = {}
            if incoming:
                self.context.update(incoming)
                self.check_required_context()

        if not self.emitter:
            raise ServiceConfigError("emitter not provided")

        ident: Identity = self.identity

        async with service_span(
                self._span("run", "prepare"),
                attributes=self.flatten_context(),
        ):
            # Build request + codec + attrs
            req, codec, attrs = await self.aprepare(stream=stream, **ctx)

            try:
                # Prepare codec for this call
                if codec is not None:
                    async with service_span(
                            self._span("run", "prepare", "codec", "setup"),
                            attributes=self.flatten_context(),
                    ):
                        await codec.asetup(context=self.context)

                    async with service_span(
                            self._span("run", "prepare", "codec", "encode"),
                            attributes=self.flatten_context(),
                    ):
                        await codec.aencode(req)

                # Resolve client
                async with service_span(
                        self._span("run", "prepare", "client"),
                        attributes=self.flatten_context(),
                ):
                    client: OrcaClient = self.get_client()

                # Emit outbound request event
                async with service_span(
                        self._span("run", "prepare", "emit_request"),
                        attributes=self.flatten_context(),
                ):
                    self.emitter.emit_request(self.context, ident.as_str, req)

                self._set_context(
                    {
                        "llm.client.name": getattr(client, "name", "<unknown>"),
                        "llm.request.correlation_id": str(req.correlation_id),
                    }
                )

            except RegistryLookupError as e:
                raise ServiceConfigError(
                    f"No AI client configured for service '{ident.as_str}'. "
                    f"provider_name={self.provider_name!r}. {e}"
                ) from e
            except Exception as e:
                raise ServiceConfigError(
                    f"Service '{ident.as_str}' could not prepare backend IO: {type(e).__name__}: {e}"
                ) from e


        # Delegate to the appropriate IO helper
        if self.dry_run:
            return Response(request=req, output=[], usage=None, tool_calls=[])

        if stream:
            await self._astream(client, req, codec, attrs, ident)
            return None

        return await self._asend(client, req, codec, attrs, ident)

    async def _asend(
            self,
            client: OrcaClient,
            req: Request,
            codec: BaseCodec | None,
            attrs: dict[str, Any],
            ident: Identity,
    ) -> Response | None:
        """
        Non-streaming send/receive with retries, codec decode, and logging.
        """
        async with service_span(self._span("run", "send"), attributes=self.flatten_context()):
            attempt = 1
            max_attempts = max(1, self.max_attempts)
            try:
                while attempt <= max_attempts:
                    self.context.update({
                        "send.attempts": attempt,
                        "send.max_attempts": max_attempts,
                    })
                    async with service_span(
                            self._span("run", "send", "attempt", str(attempt)),
                            attributes=self.flatten_context(),
                    ):
                        try:
                            resp: Response = await client.send_request(req)

                            # Tag response identity/correlation
                            resp.namespace, resp.kind, resp.name = ident.namespace, ident.kind, ident.name
                            if getattr(resp, "request_correlation_id", None) is None:
                                resp.request_correlation_id = req.correlation_id

                            # Attach codec identity if missing (write-safe fields only)
                            if hasattr(resp, "codec_identity") and not getattr(resp, "codec_identity", None):
                                try:
                                    resp.codec_identity = req.codec_identity  # type: ignore[attr-defined]
                                except Exception:
                                    logger.debug(
                                        "failed to propagate codec_identity to response",
                                        exc_info=True,
                                    )

                            # Let the codec decode/shape the response
                            if codec is not None:
                                await codec.adecode(resp)

                            self.emitter.emit_response(self.context, ident.as_str, resp)
                            await self.on_success(self.context, resp)

                            logger.info(
                                "llm.service.success",
                                extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt},
                            )
                            return resp
                        except Exception as e:
                            if attempt >= max_attempts:
                                self.emitter.emit_failure(self.context, ident.as_str, req.correlation_id, str(e))
                                await self.on_failure(self.context, e)
                                logger.exception(
                                    "llm.service.error",
                                    extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt},
                                )
                                raise
                            logger.warning(
                                "llm.service.retrying",
                                extra={**attrs, "attempt": attempt, "max_attempts": max_attempts},
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

    async def _astream(
            self,
            client: OrcaClient,
            req: Request,
            codec: BaseCodec | None,
            attrs: dict[str, Any],
            ident: Identity,
    ) -> None:
        """
        Streaming send/receive with retries, codec chunk decode, and logging.
        """
        logger.info("orchestrai.service.%s.run_stream", self.__class__.__name__, extra=attrs)
        async with service_span(
                f"{self.span_prefix}.run.stream",
                attributes=self.flatten_context(),
        ):
            try:
                attempt = 1
                max_attempts = max(1, self.max_attempts)
                started = False
                while attempt <= max_attempts and not started:
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
                            self.emitter.emit_stream_chunk(self.context, ident.as_str, chunk)

                        # Allow codec to finalize any stream-level state
                        if codec is not None:
                            try:
                                await codec.afinalize_stream()
                            except AttributeError:
                                pass

                        self.emitter.emit_stream_complete(self.context, ident.as_str, req.correlation_id)
                        return
                    except Exception as e:
                        if started or attempt >= max_attempts:
                            self.emitter.emit_failure(self.context, ident.as_str, req.correlation_id, str(e))
                            await self.on_failure(self.context, e)
                            logger.exception(
                                "llm.service.stream.error",
                                extra={**attrs, "correlation_id": str(req.correlation_id), "attempt": attempt},
                            )
                            raise
                        logger.warning(
                            "llm.service.stream.retrying",
                            extra={**attrs, "attempt": attempt, "max_attempts": max_attempts},
                        )
                        await self._backoff_sleep(attempt)
                        attempt += 1
            finally:
                if codec is not None:
                    try:
                        await codec.ateardown()
                    except Exception:
                        logger.debug("codec teardown failed; continuing", exc_info=True)

    async def run_stream(self, **ctx):
        """
        Execute the service with streaming enabled.

        Any per-call `context` provided is merged into `self.context` up front so that
        downstream helpers rely solely on `self.context`.

        The codec is constructed per call, used to prepare the request, decode chunks,
        and finalize the stream, then torn down.
        """
        try:
            self.context["llm.stream"] = True
        except Exception:
            logger.debug("failed to stamp llm.stream into context", exc_info=True)

        async with service_span(
                f"{self.span_prefix}.execute.stream",
                attributes=self.flatten_context(),
        ):
            await self._arun_core(stream=True, **ctx)

    # ----------------------------------------------------------------------
    # Result hooks
    # ----------------------------------------------------------------------
    async def on_success(self, context: dict, resp: Response) -> None:
        ...

    async def on_failure(self, context: dict, err: Exception) -> None:
        ...
