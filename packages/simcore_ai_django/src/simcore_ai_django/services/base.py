# simcore_ai_django/services/base.py
from __future__ import annotations

from typing import Any, Callable, Awaitable

from simcore_ai.identity import coerce_identity_key
from simcore_ai.services.base import BaseLLMService
from simcore_ai.services.exceptions import ServiceCodecResolutionError
from simcore_ai.tracing import service_span_sync
from simcore_ai.types import LLMResponse
from simcore_ai_django.codecs.registry import CodecRegistry
from simcore_ai_django.execution.helpers import (
    settings_default_backend as _exec_default_backend,
    settings_default_mode as _exec_default_mode,
)
from simcore_ai_django.prompts.render_section import \
    render_section as _default_renderer  # async (namespace, section_key, context) -> str
from simcore_ai_django.services.helpers import _kind_name_from_codec_name
from simcore_ai_django.services.mixins import ServiceExecutionMixin
from simcore_ai_django.signals import emitter as _default_emitter  # DjangoSignalEmitter instance

__all__ = [
    "DjangoBaseLLMService",
    "DjangoExecutableLLMService",
]

RenderSection = Callable[[str, str, dict], Awaitable[str]]


class DjangoBaseLLMService(BaseLLMService):
    # NOTE: Uses BaseLLMService.get_or_build_prompt for prompt assembly.
    """
    Django-aware convenience subclass of BaseLLMService.

    It keeps the core retry/backoff + tracing behavior from BaseLLMService,
    but provides Django defaults for:
      - emitter: a Django-signal (and/or Outbox) emitter
      - render_section: template/prompt rendering that can reach Django models
      - codec resolution: overrides `get_codec()` to resolve via Django's codec registry

    You can still override any of these by passing them explicitly to __init__ or by subclassing.

    Build Request (hooks)
    ---------------------
    `BaseLLMService` provides a concrete `build_request(**ctx) -> LLMRequest`
    that assembles the final provider-agnostic request using hooks:
      - `_build_request_instructions(prompt, **ctx) -> list[LLMRequestMessage]` (developer/instruction parts)
      - `_build_request_user_input(prompt, **ctx) -> list[LLMRequestMessage]` (user input parts)
      - `_build_request_extras(prompt, **ctx) -> list[LLMRequestMessage]` (optional additional messages)

    Prompt assembly is delegated to BaseLLMService.get_or_build_prompt(), which uses the PromptEngine and (optional) PromptPlan.

    Most services should **not** override `build_request` directly. Prefer overriding the hook methods above;
    `DjangoBaseLLMService` inherits the core behavior unchanged and simply provides Django-friendly defaults.

    Identity Defaults
    -----------------
    Identity is resolved via the class's `identity_resolver_cls` (Django variant). Semantics:
      - `namespace`: resolver arg/attr → Django AppConfig.label → module root → "default"
      - `kind`: resolver arg/attr → "default"
      - `name`: explicit arg/attr (no token strip) → derived from class name with token stripping
    The canonical string is dot-only: `namespace.kind.name` accessible via `self.identity.as_str`.

    ---
    **Codec Resolution Summary**

    A `DjangoBaseLLMService` can provide or obtain a codec in several ways:

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
    encoded on the response via `resp.codec_identity` (dot-only triple string). This guarantees that deferred or replayed
    responses use the same intended codec even if the service's defaults have changed. If no
    `codec_identity` is present, it falls back to `get_codec()` (which uses `CodecRegistry.get(...)`).

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

    def get_codec(self) -> Any:
        """
        Django-aware codec resolution.

        Returns
        -------
        Any
            A codec **class or instance**. Both forms are supported by the runner and by
            codec execution helpers. Concrete services may also override this to return a
            preconfigured instance.

        Resolution order
        ----------------
        1. Explicit `codec_class` on the service.
        2. Result of `select_codec()` (if the subclass overrides it).
        3. Django registry via `(namespace, kind, name)` with fallbacks:
           - (namespace, codec_kind, codec_name) if `codec_name` is set
           - (namespace, "default", "default")
        4. Core registry (if available) with the same fallbacks.
        5. Raise `ServiceCodecResolutionError` if no codec found.

        Notes
        -----
        `codec_name` may be either `"default"` or `"kind.name"` (dot-only).
        """
        ident = getattr(self, "identity", None)
        if ident is None:
            raise ServiceCodecResolutionError(
                namespace="unknown", kind="unknown", name=getattr(self, "__class__", type(self)).__name__,
                codec=self.codec_name, service=self.__class__.__name__
            )
        namespace = ident.namespace
        kind = ident.kind
        name = ident.name
        c_kind, c_name = _kind_name_from_codec_name(getattr(self, "codec_name", None), kind, name)

        with service_span_sync(
                "svc.get_codec",
                attributes={
                    "svc.class": self.__class__.__name__,
                    "ai.identity": ident.as_str,
                    "svc.codec_kind": c_kind,
                    "svc.codec_name": c_name,
                    **self.flatten_context(),
                },
        ):
            # 1) explicit class wins
            if getattr(self, "codec_class", None) is not None:
                return self.codec_class

            # 2) subclass-provided selection
            sel = self.select_codec()
            if sel is not None:
                return sel

            # 3) Django registry (triple-based)
            try:
                if namespace and c_kind and c_name:
                    obj = CodecRegistry.get(identity=(namespace, c_kind, c_name))
                    if obj:
                        return obj
                if namespace:
                    obj = CodecRegistry.get(identity=(namespace, "default", "default"))
                    if obj:
                        return obj
            except Exception:
                # Record the error but continue to core fallback
                pass

            # 4) Core registry (optional)
            try:
                from simcore_ai.codecs.registry import get_codec as _core_get_codec
            except Exception:
                _core_get_codec = None

            if _core_get_codec is not None and namespace:
                obj = None
                if c_kind and c_name:
                    obj = _core_get_codec((namespace, c_kind, c_name))
                if not obj:
                    obj = _core_get_codec((namespace, "default", "default"))
                if obj:
                    return obj

            # 5) Miss: raise rich error
            raise ServiceCodecResolutionError(
                namespace=namespace,
                kind=kind,
                name=name,
                codec=(f"{c_kind}.{c_name}" if c_kind and c_name else None),
                service=self.__class__.__name__,
            )

    def resolve_codec_for_response(self, resp: LLMResponse) -> Any:
        """
        Resolve a codec for a received response.

        Preference order:
        1) If `resp.codec_identity` is present, resolve that exact codec identity via registries
           (dot-only `namespace.kind.name`).
           - Try Django registry first, then core registry.
        2) Fallback to this service's `get_codec()` resolution (request-time rules).

        Raises
        ------
        ServiceCodecResolutionError
            If no codec can be resolved from the response identity nor defaults.
        """
        with service_span_sync(
                "svc.get_codec.for_response",
                attributes={
                    "svc.class": self.__class__.__name__,
                    "resp.correlation_id": getattr(resp, "correlation_id", None),
                    "resp.request_correlation_id": getattr(resp, "request_correlation_id", None),
                    "resp.codec_identity": getattr(resp, "codec_identity", None),
                    **self.flatten_context(),
                },
        ):
            cid = getattr(resp, "codec_identity", None)
            if cid:
                try:
                    key = coerce_identity_key(cid)
                    if key is not None:
                        ns, kd, nm = key
                    else:
                        raise ValueError("invalid codec_identity")
                    # 1) Django registry
                    obj = CodecRegistry.get(identity=(ns, kd, nm))
                    if obj:
                        return obj
                    # 2) Core registry
                    try:
                        from simcore_ai.codecs.registry import get_codec as _core_get_codec
                    except Exception:
                        _core_get_codec = None
                    if _core_get_codec is not None:
                        obj = _core_get_codec((ns, kd, nm))
                        if obj:
                            return obj
                except Exception:
                    # Malformed or unresolvable codec identity; fall back to request-time rules
                    return self.get_codec()
            # 3) Fallback to request-time resolution
            return self.get_codec()

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
        from simcore_ai_django.services.promote import promote_request_for_service
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


class DjangoExecutableLLMService(ServiceExecutionMixin, DjangoBaseLLMService):
    """
    A Django-ready service base **with execution helpers**.

    Inherits Django defaults (codec/emitter/renderer) and adds `.execute(...)`
    and builder-style `.using(...).enqueue/execute(...)`. Orchestration is handled
    by `simcore_ai_django.execution.entrypoint`.
    """
    pass
