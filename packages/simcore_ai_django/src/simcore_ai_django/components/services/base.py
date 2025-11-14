# simcore_ai_django/components/services/base.py
import logging
from abc import ABC
from typing import Any, Callable, Awaitable

from simcore_ai.components import BaseService, PromptSection
from simcore_ai.components.promptkit.engine import SectionSpec
from simcore_ai.identity import Identity
from simcore_ai.registry import get_registry_for
from simcore_ai.registry.exceptions import RegistryError
from simcore_ai.types import LLMResponse
from simcore_ai_django.components.promptkit.render_section import \
    render_section as _default_renderer  # async (namespace, section_key, context) -> str
from simcore_ai_django.signals import emitter as _default_emitter  # DjangoSignalEmitter instance

logger = logging.getLogger(__name__)

RenderSection = Callable[[str, str, dict], Awaitable[str]]

class DjangoBaseService(BaseService, ABC):
    """Django-aware convenience subclass of BaseService.

    It keeps the core retry/backoff + tracing behavior from BaseService,
    but provides Django defaults for:
      - emitter: a Django-signal (and/or Outbox) emitter
      - render_section: template/prompt rendering that can reach Django models

    You can still override any of these by passing them explicitly to __init__
    or by subclassing.

    Build Request (hooks)
    ---------------------
    `BaseService` provides a concrete `abuild_request(**ctx) -> LLMRequest`
    that assembles the final provider-agnostic request using hooks:
      - `_abuild_request_instructions(prompt, **ctx) -> list[LLMRequestMessage]`
      - `_abuild_request_user_input(prompt, **ctx) -> list[LLMRequestMessage]`
      - `_abuild_request_extras(prompt, **ctx) -> list[LLMRequestMessage]`

    Prompt assembly is delegated to `BaseService.aget_prompt()`, which uses the
    PromptEngine and (optional) PromptPlan.

    Most services should **not** override `abuild_request` directly. Prefer
    overriding the hook methods above; `DjangoBaseService` inherits the core
    behavior unchanged and simply provides Django-friendly defaults.

    Identity defaults
    -----------------
    Identity is resolved via the shared `IdentityMixin` used by BaseService.

    Codec resolution
    ----------------
    Codecs are registered once in the core codec registry and addressed by
    tuple3 identity. `DjangoBaseService` does not override codec resolution;
    it inherits the async-first resolver from `BaseService` and the per-call
    codec lifecycle (`aprepare` + `arun` / `run_stream`).
    """

    # Optional async renderer for PromptSection → string
    render_section: RenderSection | None = None

    def __init__(self, context: dict[str, Any] | None = None, **kwargs: Any) -> None:
        """Constructor that passes context through without domain coupling.

        This layer is intentionally generic; it does not inspect domain-specific
        keys (e.g., "simulation_id"). Services/apps are responsible for placing
        any required identifiers into `context` and validating them.
        """
        super().__init__(context=context or {}, **kwargs)

        # Inject Django defaults only if not provided explicitly
        if self.emitter is None:
            self.emitter = _default_emitter

        # Renderer default: async section renderer that can hit Django models/templates
        if getattr(self, "render_section", None) is None:
            self.render_section = _default_renderer

    # ------------------------------------------------------------------
    # Promotion helpers
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Result hooks (context-first)
    # ------------------------------------------------------------------
    async def on_success_ctx(self, *, context: dict[str, Any], resp: LLMResponse) -> None:
        """Context-first success hook (preferred in Django layer).

        Override this in subclasses instead of `on_success` if you want a
        keyword-only context argument.
        """
        return None

    async def on_failure_ctx(self, *, context: dict[str, Any], err: Exception) -> None:
        """Context-first failure hook (preferred in Django layer).

        Override this in subclasses instead of `on_failure` if you want a
        keyword-only context argument.
        """
        return None

    async def on_success(self, context: dict[str, Any], resp: LLMResponse) -> None:
        """BaseService callback override.

        Delegates to `on_success_ctx` so subclasses can implement either
        style without fighting the BaseService signature.
        """
        await self.on_success_ctx(context=context or {}, resp=resp)

    async def on_failure(self, context: dict[str, Any], err: Exception) -> None:
        """BaseService callback override.

        Delegates to `on_failure_ctx` so subclasses can implement either
        style without fighting the BaseService signature.
        """
        await self.on_failure_ctx(context=context or {}, err=err)

    # ------------------------------------------------------------------
    # Prompt registry helper (optional)
    # ------------------------------------------------------------------
    def _get_registry_section_or_none(self) -> SectionSpec | None:
        """Return a `PromptSection` from the registry for this service identity, or None.

        Pure lookup; no exceptions. This is primarily for legacy or advanced
        Django integrations that want to bypass the standard Identity.resolve
        flow used by the core BaseService.
        """
        logger.debug("Getting registry section via `simcore_ai_django` for %s", self.identity)
        ident_ = self.identity.as_str

        # 1) Direct registry lookup via PromptSection
        try:
            return PromptSection.get_registry().get(ident_)
        except Exception:
            pass

        # 2) Identity resolver indirection
        try:
            return Identity.resolve.try_for_("PromptSection", ident_)
        except RegistryError:
            pass

        # 3) Fallback: generic registry mapping
        try:
            reg = get_registry_for(PromptSection)
            if reg is not None:
                return reg.try_get(ident_)
        except Exception:
            pass

        return None

