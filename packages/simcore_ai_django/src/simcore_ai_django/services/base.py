# simcore_ai_django/services/base.py
from __future__ import annotations

from simcore_ai.identity.utils import parse_dot_identity
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
    render_section as _default_renderer  # async (namespace, section_key, simulation) -> str
from simcore_ai_django.services.helpers import _kind_name_from_codec_name
from simcore_ai_django.services.mixins import ServiceExecutionMixin
from simcore_ai_django.signals import emitter as _default_emitter  # DjangoSignalEmitter instance

__all__ = [
    "DjangoBaseLLMService",
    "DjangoExecutableLLMService",
]


class DjangoBaseLLMService(BaseLLMService):
    """
    Django-aware convenience subclass of BaseLLMService.

    It keeps the core retry/backoff + tracing behavior from BaseLLMService,
    but provides Django defaults for:
      - emitter: a Django-signal (and/or Outbox) emitter
      - render_section: template/prompt rendering that can reach Django models
      - codec resolution: overrides `get_codec()` to resolve via Django's codec registry

    You can still override any of these by passing them explicitly to __init__ or by subclassing.

    ---
    **Codec Resolution Summary**

    A `DjangoBaseLLMService` can provide or obtain a codec in several ways:

    1. **Explicit injection** – Pass a `codec_class` (or `_codec_instance`) when constructing the service.
       ```python
       svc = MyService(codec_class=ChatLabCodec)
       ```
    2. **Custom selection** – Override `select_codec()` in your subclass to return a codec class or instance.
    3. **Default registry lookup** – If neither of the above is defined, the base `get_codec()` method
       will resolve a codec automatically using the Django codec registry, matching on `(namespace, kind, name)`
       tuple and falling back to `"default.default.default"` when needed.

    The codec identity is stored and transmitted as a dot-only triple string `namespace.kind.name`.

    The result may be a codec instance, codec class, or `None` (for stateless runs).

    **Handling Responses**

    When handling a response object, call `resolve_codec_for_response(resp)` to prefer the codec
    encoded on the response via `resp.codec_identity` (dot-only triple string). This guarantees that deferred or replayed
    responses use the same intended codec even if the service's defaults have changed. If no
    `codec_identity` is present, it falls back to `get_codec()`.

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

    # --- Execution configuration knobs (service-level defaults) ---
    # If left as None, these fall back to Django settings and then hard defaults.
    execution_mode: str | None = None  # "sync" | "async"
    execution_backend: str | None = None  # "immediate" | "celery" | "django_tasks" (future)
    execution_priority: int | None = None  # -100..100
    execution_run_after: float | None = None  # seconds (or set at call-site)
    require_enqueue: bool = False  # hard rule: force async if True

    def __post_init__(self):
        super().__post_init__()
        # Inject Django defaults only if not provided explicitly
        if self.emitter is None:
            self.emitter = _default_emitter
        if self.render_section is None:
            self.render_section = _default_renderer

        # -----------------------------
        # Execution defaults (resolve from service → settings → hardcoded)
        # -----------------------------
        if getattr(self, "execution_mode", None) is None:
            # settings fallback → hard default "sync"
            try:
                self.execution_mode = _exec_default_mode()
            except Exception:
                self.execution_mode = "sync"

        if getattr(self, "execution_backend", None) is None:
            # settings fallback → hard default "immediate"
            try:
                self.execution_backend = _exec_default_backend()
            except Exception:
                self.execution_backend = "immediate"

        if getattr(self, "execution_priority", None) is None:
            # hard default priority 0 (middle)
            self.execution_priority = 0

        if getattr(self, "execution_run_after", None) is None:
            # None means "now"; callers can override per-call
            self.execution_run_after = None

        # require_enqueue has a class default of False; leave as-is unless explicitly set on subclass

    def get_codec(self, simulation=None):
        """
        Django-aware codec resolution.

        ---
        **Resolution Order**
        1. Explicitly injected `codec_class` on the service.
        2. Result of `select_codec()` (if the subclass overrides it).
        3. Django registry via `(namespace, kind, name)` with fallbacks:
           - (namespace, codec_kind, codec_name) if codec_name is set
           - (namespace, "default", "default")
        4. Core registry (if available) via `(namespace, kind, name)` with same fallbacks.
        5. Raise `ServiceCodecResolutionError` if no codec found.

        The `codec_name` attribute may be either "default" or "kind.name" form.
        """
        namespace = getattr(self, "namespace", None)
        kind = getattr(self, "kind", None) or "default"
        name = getattr(self, "name", None)
        c_kind, c_name = _kind_name_from_codec_name(getattr(self, "codec_name", None), kind, name)

        with service_span_sync(
                "svc.get_codec",
                attributes={
                    "svc.class": self.__class__.__name__,
                    "svc.namespace": namespace,
                    "svc.kind": kind,
                    "svc.name": name,
                    "svc.codec_kind": c_kind,
                    "svc.codec_name": c_name,
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
                    obj = CodecRegistry.resolve(identity=(namespace, c_kind, c_name))
                    if obj:
                        return obj
                if namespace:
                    obj = CodecRegistry.resolve(identity=(namespace, "default", "default"))
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
                    obj = _core_get_codec(namespace, c_kind, c_name)
                if not obj:
                    obj = _core_get_codec(namespace, "default", "default")
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

    def resolve_codec_for_response(self, resp: LLMResponse):
        """
        Resolve a codec for a received response.

        Preference order:
        1) If `resp.codec_identity` is present, resolve that exact codec identity via registries.
           - First try the Django codec registry: (namespace, kind, name) from dot-only string
           - Then try the core registry with the same triple
        2) Fallback to this service's `get_codec()` resolution (request-time rules).

        Raises:
            ServiceCodecResolutionError if no codec can be found.
        """
        with service_span_sync(
                "svc.get_codec.for_response",
                attributes={
                    "svc.class": self.__class__.__name__,
                    "resp.correlation_id": getattr(resp, "correlation_id", None),
                    "resp.request_correlation_id": getattr(resp, "request_correlation_id", None),
                    "resp.codec_identity": getattr(resp, "codec_identity", None),
                },
        ):
            cid = getattr(resp, "codec_identity", None)
            if cid:
                ns, kd, nm = parse_dot_identity(cid)
                if ns and kd and nm:
                    # 1) Django registry
                    obj = CodecRegistry.resolve(identity=(ns, kd, nm))
                    if obj:
                        return obj
                    # 2) Core registry
                    try:
                        from simcore_ai.codecs.registry import get_codec as _core_get_codec
                    except Exception:
                        _core_get_codec = None
                    if _core_get_codec is not None:
                        obj = _core_get_codec(ns, kd, nm)
                        if obj:
                            return obj
            # 3) Fallback to request-time resolution
            return self.get_codec()

    def promote_request(self, req, *, simulation_pk=None, request_db_pk=None):
        """
        Convenience wrapper to promote a core LLMRequest into a DjangoLLMRequest using
        this service's identity, provider/client metadata, and context.
        """
        from simcore_ai_django.services.promote import promote_request_for_service
        return promote_request_for_service(
            self,
            req,
            simulation_pk=simulation_pk,
            request_db_pk=request_db_pk,
        )

    # Optionally, you can hook success/failure for Django-ish side effects
    async def on_success(self, simulation, resp) -> None:
        # Leave minimal by default; your signal/outbox handlers usually do the persistence.
        # Override in concrete services if you want local side effects.
        return

    async def on_failure(self, simulation, err: Exception) -> None:
        # Same principle as on_success
        return


class DjangoExecutableLLMService(ServiceExecutionMixin, DjangoBaseLLMService):
    """
    A Django-ready service base **with execution helpers**.

    This class combines `DjangoBaseLLMService` (Django-aware defaults for
    codec resolution, renderer, and emitter) with `ServiceExecutionMixin`
    (ergonomic execution API). Use this when you want a drop‑in base that
    can run **now** (sync) or **later** (async) with a single import.

    Highlights
    ----------
    - Inherits all behavior from `DjangoBaseLLMService`.
    - Adds `execute(**ctx)` for immediate, in‑process execution
      (via the configured *immediate* backend).
    - Adds a builder API: `using(**overrides)` → `.execute(**ctx)` / `.enqueue(**ctx)`
      for per‑call control over `backend`, `run_after`, and `priority`.
    - Honors class‑level defaults if defined on your concrete service:
      `execution_mode`, `execution_backend`, `execution_priority`,
      `execution_run_after`, and `require_enqueue`.

    Examples
    --------
    Run immediately using defaults:

        class PatientIntakeService(DjangoExecutableLLMService):
            pass

        PatientIntakeService.execute(user_id=123)

    Enqueue with overrides (Celery):

        PatientIntakeService.using(backend="celery", run_after=60, priority=50).enqueue(user_id=123)

    Notes
    -----
    - All orchestration (mode/backend resolution, queue mapping, trace context)
      is handled in `simcore_ai_django.execution.entrypoint.execute`.
    - Tracing spans are emitted both here (light wrappers) and in the
      entrypoint/backends for full visibility across the call chain.
    """
    pass
