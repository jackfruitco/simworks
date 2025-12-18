# orchestrai_django/components/services/services.py
import logging
from abc import ABC
from typing import Any, Callable, Awaitable, ClassVar

from orchestrai.components import BaseService
from orchestrai.components.promptkit import PromptSectionSpec
from orchestrai.types import Response
from orchestrai_django.components.promptkit.render_section import \
    render_section as _default_renderer  # async (namespace, section_key, context) -> str
from orchestrai_django.signals import emitter as _default_emitter  # DjangoSignalEmitter instance

logger = logging.getLogger(__name__)

RenderSection = Callable[[str, str, dict[str, Any]], Awaitable[str]]


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
    `BaseService` provides a concrete `abuild_request(**ctx) -> Request`
    that assembles the final backend-agnostic request using hooks:
      - `_abuild_request_instructions(prompt, **ctx) -> list[InputItem]`
      - `_abuild_request_user_input(prompt, **ctx) -> list[InputItem]`
      - `_abuild_request_extras(prompt, **ctx) -> list[InputItem]`

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
    tuple4 identity. `DjangoBaseService` does not override codec resolution;
    it inherits the async-first resolver from `BaseService` and the per-call
    codec lifecycle (`aprepare` + `arun` / `run_stream`).
    """

    # Attribute to attach Django "Task" class
    task: ClassVar[Any]

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
        """Promote a core Request into a Django-aware request using service identity.

        Parameters
        ----------
        req : Request
            The backend-agnostic request to promote.
        context : dict | None
            Optional extra context to carry through the promotion pipeline.
            If omitted, `self.context` is used.
        """
        from orchestrai_django.components.services.promote import promote_request_for_service

        return promote_request_for_service(
            self,
            req,
            context=(context or self.context or {}),
        )

    # ------------------------------------------------------------------
    # Result hooks (context-first)
    # ------------------------------------------------------------------
    async def on_success_ctx(self, *, context: dict[str, Any], resp: Response) -> None:
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

    async def on_success(self, context: dict[str, Any], resp: Response) -> None:
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
    def _get_registry_section_or_none(self) -> PromptSectionSpec | None:
        """Return a `PromptSectionSpec` for this service identity, or None.

        This is a thin wrapper over the core BaseService prompt resolution helper
        and is kept for legacy Django integrations that previously relied on a
        Django-side registry lookup. New code should prefer the prompt plan
        mechanisms and `BaseService.aget_prompt()` directly.
        """
        return self._try_get_matching_prompt_section()
