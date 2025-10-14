from __future__ import annotations

from simcore_ai.exceptions import ServiceCodecResolutionError
from simcore_ai.services.base import BaseLLMService
from simcore_ai.tracing import service_span_sync
from simcore_ai.types import LLMResponse
from simcore_ai_django.codecs import get_codec as _registry_get_codec  # (namespace, codec_name) -> BaseLLMCodec
from simcore_ai_django.prompts.render_section import \
    render_section as _default_renderer  # async (namespace, section_key, simulation) -> str
from simcore_ai_django.services.helpers import _infer_namespace_from_module, _parse_codec_identity
from simcore_ai_django.signals import emitter as _default_emitter  # DjangoSignalEmitter instance


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
       will resolve a codec automatically using the Django codec registry, matching on `(namespace, codec_name)`
       and falling back to `"default"` when needed.

    The result may be a codec instance, codec class, or `None` (for stateless runs).

    **Handling Responses**

    When handling a response object, call `resolve_codec_for_response(resp)` to prefer the codec
    encoded on the response via `resp.codec_identity`. This guarantees that deferred or replayed
    responses use the same intended codec even if the service's defaults have changed. If no
    `codec_identity` is present, it falls back to `get_codec()`.
    """

    def __post_init__(self):
        super().__post_init__()
        # Inject Django defaults only if not provided explicitly
        if self.emitter is None:
            self.emitter = _default_emitter
        if self.render_section is None:
            self.render_section = _default_renderer

        # -----------------------------
        # Derive identity defaults
        # -----------------------------
        # namespace: default to Django app_label
        if not getattr(self, "namespace", None):
            self.namespace = _infer_namespace_from_module(self.__class__.__module__)
        # bucket: default fallback
        if not getattr(self, "bucket", None):
            self.bucket = "default"
        # name: from class name without 'Service' suffix
        if not getattr(self, "name", None):
            cls_name = self.__class__.__name__
            core = cls_name[:-7] if cls_name.endswith("Service") else cls_name
            self.name = (
                core.strip()
                .replace(" ", "_")
                .replace("-", "_")
            ).lower()
        # codec_name: if not set, compose from bucket:name for registry lookups
        if not getattr(self, "codec_name", None):
            self.codec_name = f"{self.bucket}:{self.name}"

    def get_codec(self, simulation=None):
        """
        Django-aware codec resolution.

        ---
        **Resolution Order**
        1. Explicitly injected `codec_class` on the service.
        2. Result of `select_codec()` (if the subclass overrides it).
        3. Django registry via `(namespace, codec_name)` with fallbacks:
           - (namespace, f"{bucket}:{name}") if codec_name is unset
           - (namespace, "default")
        4. Core registry (if available) via `(namespace, codec_name)` with same fallbacks.
        5. Raise `ServiceCodecResolutionError` if no codec found.
        """
        ns = getattr(self, "namespace", None)
        bucket = getattr(self, "bucket", None) or "default"
        name = getattr(self, "name", None)
        codec_name = getattr(self, "codec_name", None) or (f"{bucket}:{name}" if name else None)

        with service_span_sync(
                "svc.get_codec",
                attributes={
                    "svc.class": self.__class__.__name__,
                    "svc.namespace": ns,
                    "svc.bucket": bucket,
                    "svc.name": name,
                    "svc.codec_name": codec_name,
                },
        ):
            # 1) explicit class wins
            if getattr(self, "codec_class", None) is not None:
                return self.codec_class

            # 2) subclass-provided selection
            sel = self.select_codec()
            if sel is not None:
                return sel

            # 3) Django registry
            try:
                if ns and codec_name:
                    obj = _registry_get_codec(ns, codec_name)
                    if obj:
                        return obj
                if ns:
                    obj = _registry_get_codec(ns, "default")
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

            if _core_get_codec is not None and ns:
                obj = None
                if codec_name:
                    obj = _core_get_codec(ns, codec_name)
                if not obj:
                    obj = _core_get_codec(ns, "default")
                if obj:
                    return obj

            # 5) Miss: raise rich error
            raise ServiceCodecResolutionError(
                namespace=ns,
                bucket=bucket,
                name=name,
                codec_name=codec_name,
                service=self.__class__.__name__,
            )

    def resolve_codec_for_response(self, resp: LLMResponse):
        """
        Resolve a codec for a received response.

        Preference order:
        1) If `resp.codec_identity` is present, resolve that exact codec identity via registries.
           - First try the Django codec registry: (namespace, codec_name)
           - Then try the core registry with the same pair
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
                ns, key = _parse_codec_identity(cid)
                if ns and key:
                    # 1) Django registry
                    obj = _registry_get_codec(ns, key)
                    if obj:
                        return obj
                    # 2) Core registry
                    try:
                        from simcore_ai.codecs.registry import get_codec as _core_get_codec
                    except Exception:
                        _core_get_codec = None
                    if _core_get_codec is not None:
                        obj = _core_get_codec(ns, key)
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
