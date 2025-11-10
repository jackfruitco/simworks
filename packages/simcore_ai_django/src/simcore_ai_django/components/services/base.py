# simcore_ai_django/services/base.py
from __future__ import annotations

import logging
from abc import ABC
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from simcore_ai.components import BaseCodec
from simcore_ai.components.promptkit import PromptSection
from simcore_ai.components.promptkit.engine import SectionSpec
from simcore_ai.components.services.base import BaseService
from simcore_ai.identity import Identity
from simcore_ai.registry.exceptions import RegistryError, RegistryLookupError
from simcore_ai.tracing import service_span_sync
from simcore_ai.types import LLMResponse
from simcore_ai_django.components.promptkit.render_section import \
    render_section as _default_renderer  # async (namespace, section_key, context) -> str
from simcore_ai_django.components.services.helpers import _kind_name_from_codec_name
from simcore_ai_django.components.services.mixins import ServiceExecutionMixin
from simcore_ai_django.execution.helpers import (
    settings_default_backend as _exec_default_backend,
    settings_default_mode as _exec_default_mode,
)
from simcore_ai_django.signals import emitter as _default_emitter  # DjangoSignalEmitter instance

__all__ = [
    "DjangoBaseService",
    "DjangoExecutableLLMService",
]

logger = logging.getLogger(__name__)

RenderSection = Callable[[str, str, dict], Awaitable[str]]


@dataclass
class DjangoBaseService(BaseService, ABC):
    # NOTE: Uses BaseService.get_or_build_prompt for prompt assembly.
    """
    Django-aware convenience subclass of BaseService.

    It keeps the core retry/backoff + tracing behavior from BaseService,
    but provides Django defaults for:
      - emitter: a Django-signal (and/or Outbox) emitter
      - render_section: template/prompt rendering that can reach Django models
      - codec resolution: overrides `get_codec()` to resolve via Django's codec registry

    You can still override any of these by passing them explicitly to __init__ or by subclassing.

    Build Request (hooks)
    ---------------------
    `BaseService` provides a concrete `build_request(**ctx) -> LLMRequest`
    that assembles the final provider-agnostic request using hooks:
      - `_build_request_instructions(prompt, **ctx) -> list[LLMRequestMessage]` (developer/instruction parts)
      - `_build_request_user_input(prompt, **ctx) -> list[LLMRequestMessage]` (user input parts)
      - `_build_request_extras(prompt, **ctx) -> list[LLMRequestMessage]` (optional additional messages)

    Prompt assembly is delegated to BaseService.get_or_build_prompt(), which uses the PromptEngine and (optional) PromptPlan.

    Most services should **not** override `build_request` directly. Prefer overriding the hook methods above;
    `DjangoBaseService` inherits the core behavior unchanged and simply provides Django-friendly defaults.

    Identity Defaults
    -----------------
    Identity is resolved via the class's `identity_resolver_cls` (Django variant). Semantics:
      - `namespace`: resolver arg/attr → Django AppConfig.label → module root → "default"
      - `kind`: resolver arg/attr → "default"
      - `name`: explicit arg/attr (no token strip) → derived from class name with token stripping
    The canonical string is dot-only: `namespace.kind.name` accessible via `self.identity.as_str`.

    ---
    **Codec Resolution Summary**

    A `DjangoBaseService` can provide or obtain a codec in several ways:

    1. **Explicit injection** – Pass a `codec_class` (or `_codec_instance`) when constructing the service.
       ```python
       svc = MyService(codec_class=ChatLabCodec)
       ```
    2. **Custom selection** – Override `select_codec()` in your subclass to return a codec class or instance.
    3. **Default registry lookup** – If neither of the above is defined, the base `get_codec()` method
       resolves via the Django codec registry using the service `identity` (namespace.kind.name). If `codec_name` is set, it maps to `(codec_kind, codec_name)`; otherwise `(kind, name)` is used. Then it falls back to `(namespace, 'default', 'default')`.

    The codec identity is **always** a dot-only triple string `namespace.kind.name` (no colons or pipes).

    The result may be a codec **class or instance**; both are supported by the runner/codec execution path.

    **Handling Responses**

    When handling a response object, call `resolve_codec_for_response(resp)` to prefer the codec
    encoded on the response via `resp.codec` (dot-only triple string). This guarantees that deferred or replayed
    responses use the same intended codec even if the service's defaults have changed. If no
    `codec` is present, it falls back to `get_codec()` (which uses `CodecRegistry.get(...)`).

    **Execution Configuration**

    The following service-level attributes control how the service is dispatched by
    the execution entrypoint. If left as `None`, they fall back to Django settings
    (`AI_EXECUTION_BACKENDS`) and then to hard-coded defaults:

    - `execution_mode`: "sync" | "async" (default: settings.DEFAULT_MODE → "sync")
    - `execution_backend`: "immediate" | "celery" | "django_tasks" (default: settings.DEFAULT_BACKEND → "immediate")
    - `execution_priority`: int in [-100, 100] (default: 0)
    - `execution_run_after`: float seconds until run (default: None → run now)
    - `require_enqueue`: bool (default: False). If True, sync requests are upgraded to async at dispatch time.

    See also
    --------
    `DjangoExecutableLLMService` — a convenience subclass that mixes in
    `ServiceExecutionMixin` to provide `.execute(...)` and builder-style
    `.using(...).enqueue/execute(...)` helpers out of the box.
    """

    render_section: RenderSection | None = None

    # --- Execution configuration knobs (service-level defaults) ---
    execution_mode: str | None = None  # "sync" | "async"
    execution_backend: str | None = None  # "immediate" | "celery" | "django_tasks" (future)
    execution_priority: int | None = None  # -100..100
    execution_run_after: float | None = None  # seconds (or set at call-site)
    require_enqueue: bool = False  # hard rule: force async if True

    def __init__(self, context: dict[str, Any] | None = None, **kwargs):
        """Constructor that passes context through without domain coupling.

        This layer is intentionally generic; it does not inspect domain-specific
        keys (e.g., "simulation_id"). Services/apps are responsible for placing
        any required identifiers into `context` and validating them.
        """
        super().__init__(context=context or {}, **kwargs)

    def __post_init__(self):
        super().__post_init__()
        # Inject Django defaults only if not provided explicitly
        if self.emitter is None:
            self.emitter = _default_emitter

        # Check if a custom renderer is provided (e.g. render from template or request)
        renderer = getattr(self, "render_section", None)
        if renderer is None:
            self.render_section = _default_renderer

        # Execution defaults (service → settings → hardcoded)
        if getattr(self, "execution_mode", None) is None:
            try:
                self.execution_mode = _exec_default_mode()
            except Exception:
                self.execution_mode = "sync"

        if getattr(self, "execution_backend", None) is None:
            try:
                self.execution_backend = _exec_default_backend()
            except Exception:
                self.execution_backend = "immediate"

        if getattr(self, "execution_priority", None) is None:
            self.execution_priority = 0

        if getattr(self, "execution_run_after", None) is None:
            self.execution_run_after = None

    async def aresolve_codec(self) -> type[BaseCodec]:
        """
        Async-first codec resolver with Django semantics.

        Resolution order:

          1) If a per-instance override is configured (`_codec_override`), delegate to `BaseService.aresolve_codec()`.
          2) Try Django codec registry (DjangoBaseCodec) using:
               - (namespace, codec_kind, codec_name) if `codec_name` is set
               - (namespace, "default", "default")
          3) If not found, fall back to the core `BaseService.aresolve_codec()`.

        Always returns a `BaseCodec` subclass or raises ServiceCodecResolutionError.
        """
        # 1) If there's an explicit per-instance override, defer entirely to BaseService
        if getattr(self, "_codec_override", None) is not None:
            return await super().aresolve_codec()

        ident = self.identity
        namespace, kind, name = ident.namespace, ident.kind, ident.name

        # Derive codec kind/name from optional codec_name override
        c_kind, c_name = _kind_name_from_codec_name(
            getattr(self, "codec_name", None),
            kind,
            name,
        )

        # Candidate identities to try in order
        candidates: list[tuple[str, str, str]] = []
        if namespace and c_kind and c_name:
            candidates.append((namespace, c_kind, c_name))
        if namespace:
            candidates.append((namespace, "default", "default"))

        # 2) Try Django codec registry first (if available)
        try:
            from simcore_ai_django.components.codecs import DjangoBaseCodec
        except Exception:
            DjangoBaseCodec = BaseCodec  # Fallback: treat BaseCodec as target

        with service_span_sync(
                "svc.resolve_codec.django",
                attributes={
                    "svc.class": self.__class__.__name__,
                    "ai.identity": ident.as_str,
                    "svc.codec_kind": c_kind,
                    "svc.codec_name": c_name,
                    **self.flatten_context(),
                },
        ):
            for ns, kd, nm in candidates:
                codec_cls = Identity.resolve.try_for_(DjangoBaseCodec, (ns, kd, nm))
                if codec_cls is not None:
                    return codec_cls

        # 3) Fallback to core resolver
        return await super().aresolve_codec()

    def get_response_codec(self, resp: LLMResponse) -> type[BaseCodec]:
        """
        Resolve a codec class for a received response.

        Preference order:

          1) If `resp.codec` is already a `BaseCodec` subclass, return it.
          2) If `resp.codec` is an identity-like value (string or tuple), try:
               - Django codec registry (DjangoBaseCodec) via Identity.resolve.try_for_
               - Core BaseCodec registry via Identity.resolve.try_for_
          3) Fallback to this service's `get_codec()` resolution.

        Raises:
            ServiceCodecResolutionError if no codec can be resolved.
        """
        with service_span_sync(
                "svc.get_codec.from_response",
                attributes={
                    "svc.class": self.__class__.__name__,
                    "resp.correlation_id": getattr(resp, "correlation_id", None),
                    "resp.request_correlation_id": getattr(resp, "request_correlation_id", None),
                    "resp.codec": getattr(resp, "codec", None),
                    **self.flatten_context(),
                },
        ):
            codec_hint = getattr(resp, "codec", None)

            # 1) Direct class
            if isinstance(codec_hint, type) and issubclass(codec_hint, BaseCodec):
                return codec_hint

            # 2) Treat as identity-like and resolve
            if codec_hint:
                ident_like = codec_hint
                try:
                    from simcore_ai_django.components.codecs import DjangoBaseCodec
                except Exception:
                    DjangoBaseCodec = BaseCodec

                # Try Django registry first
                codec_cls = Identity.resolve.try_for_(DjangoBaseCodec, ident_like)
                if codec_cls is not None:
                    return codec_cls

                # Then core BaseCodec registry
                codec_cls = Identity.resolve.try_for_(BaseCodec, ident_like)
                if codec_cls is not None:
                    return codec_cls

            # 3) Fallback to request-time resolution
            return self.resolve_codec()

    def promote_request(self, req, *, context: dict | None = None):
        """Promote a core LLMRequest into a Django-aware request using service identity.

        Parameters
        ----------
        req : LLMRequest
            The provider-agnostic request to promote.
        context : dict | None
            Optional extra context to carry through the promotion pipeline.
            If omitted, `self.context` is used.
        """
        from simcore_ai_django.components.services.promote import promote_request_for_service
        return promote_request_for_service(
            self,
            req,
            context=(context or self.context or {}),
        )

    async def on_success_ctx(self, *, context: dict[str, Any], resp) -> None:
        """Context-first success hook (preferred).

        Override this in subclasses instead of `on_success`. The default
        implementation is a no-op.
        """
        return None

    async def on_failure_ctx(self, *, context: dict[str, Any], err: Exception) -> None:
        """Context-first failure hook (preferred).

        Override this in subclasses instead of `on_failure`. The default
        implementation is a no-op.
        """
        return None

    async def on_success(self, simulation, resp) -> None:
        """Deprecated: domain-coupled signature.

        Kept for backward compatibility. Subclasses should override
        `on_success_ctx(self, *, context: dict[str, Any], resp)` instead.
        This shim delegates to the context-first hook.
        """
        await self.on_success_ctx(context=self.context or {}, resp=resp)

    async def on_failure(self, simulation, err: Exception) -> None:
        """Deprecated: domain-coupled signature.

        Kept for backward compatibility. Subclasses should override
        `on_failure_ctx(self, *, context: dict[str, Any], err: Exception)` instead.
        This shim delegates to the context-first hook.
        """
        await self.on_failure_ctx(context=self.context or {}, err=err)

    def _get_registry_section_or_none(self) -> SectionSpec | None:
        """
        Return a `PromptSection` class from the registry using `self.identity.as_str`, or None if not found.
        Pure lookup; no exceptions.
        """
        logger.debug("Getting registry section via `simcore_ai_django` for %s", self.identity)
        ident_ = self.identity or self.identity.as_str

        try:
            return PromptSection.get_registry().get(ident_)
        except Exception:
            pass

        try:
            return Identity.resolve.for_("PromptSection", ident_)
        except RegistryError:
            pass

        try:
            # fallback to core registry
            from simcore_ai.registry import prompt_sections
            sec = prompt_sections.get(ident_)
            if sec: return sec
        except Exception as e:
            raise RegistryLookupError from e


class DjangoExecutableLLMService(ServiceExecutionMixin, DjangoBaseService, ABC):
    """
    A Django-ready service base **with execution helpers**.

    Inherits Django defaults (codec/emitter/renderer) and adds `.execute(...)`
    and builder-style `.using(...).enqueue/execute(...)`. Orchestration is handled
    by `simcore_ai_django.execution.entrypoint`.
    """
    pass
