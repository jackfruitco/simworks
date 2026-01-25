# orchestrai_django/components/services/services.py
"""
Django Pydantic AI Service Base.

This module provides a Django-aware version of the Pydantic AI service
that integrates with Django signals, models, and task execution.

Usage:
    from pydantic import BaseModel
    from orchestrai_django.components.services import DjangoBaseService
    from orchestrai.prompts import system_prompt

    class PatientResponse(BaseModel):
        messages: list[str]

    class GenerateResponse(DjangoBaseService):
        response_schema = PatientResponse
        model = "openai:gpt-4o"

        @system_prompt(weight=100)
        def base_instructions(self) -> str:
            return "You are a helpful medical assistant..."
"""

from __future__ import annotations

import logging
import uuid
from abc import ABC
from typing import TYPE_CHECKING, Any, ClassVar

from orchestrai.components.services import BaseService
from orchestrai_django.signals import emitter as _default_emitter

if TYPE_CHECKING:
    from pydantic_ai.result import RunResult

logger = logging.getLogger(__name__)


class DjangoBaseService(BaseService, ABC):
    """
    Django-aware Pydantic AI service base class.

    Extends BaseService with:
    - Django signal emission for request/response events
    - Integration with Django task execution (Django Tasks framework)
    - Support for ServiceCallRecord persistence
    - Context-first result hooks (on_success_ctx, on_failure_ctx)

    This is the recommended base class for SimWorks services using
    Pydantic AI.

    Example:
        class PatientService(DjangoBaseService):
            model = "openai:gpt-4o"
            response_schema = PatientResponse

            @system_prompt(weight=100)
            def instructions(self) -> str:
                return "You are a patient simulator..."
    """

    abstract: ClassVar[bool] = True

    # Task proxy inherits from BaseService - Django layer patches it via use_django_task_proxy()
    # in the OrchestrAIDjangoConfig.ready() method to provide DjangoTaskProxy with
    # persistence and background execution support.

    def __init__(
        self,
        *,
        context: dict[str, Any] | None = None,
        emitter: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the Django Pydantic AI service.

        Args:
            context: Service execution context
            emitter: Custom emitter for signals (defaults to Django signal emitter)
            **kwargs: Additional arguments passed to BaseService
        """
        # Reject context via arbitrary kwargs
        ctx_from_kwargs = kwargs.pop("ctx", None)
        context_from_kwargs = kwargs.pop("context", None)
        if ctx_from_kwargs is not None or context_from_kwargs is not None:
            raise TypeError(
                f"{type(self).__name__}.__init__ does not accept context via arbitrary kwargs. "
                "Pass context through the 'context' parameter or using(ctx={...})."
            )

        super().__init__(context=context, **kwargs)

        # Django signal emitter
        self.emitter = emitter or _default_emitter

    async def arun(self, **ctx: Any) -> "RunResult":
        """
        Execute the service with Django integration.

        Emits Django signals for request/response events and
        handles persistence of service call records.
        """
        # Merge context
        if ctx:
            self.context.update(ctx)

        try:
            # Emit request signal
            if self.emitter:
                self.emitter.emit_request(
                    self.context,
                    self.identity.namespace or "",
                    None,  # Request DTO - not used with Pydantic AI
                )

            # Execute via parent
            result = await super().arun(**ctx)

            # Emit response signal
            if self.emitter:
                # Pass the RunResult for signal compatibility
                self.emitter.emit_response(
                    self.context,
                    self.identity.namespace or "",
                    result,
                )

            return result

        except Exception as e:
            # Emit failure signal
            if self.emitter:
                self.emitter.emit_failure(
                    self.context,
                    self.identity.namespace or "",
                    self.context.get("correlation_id"),
                    str(e),
                )
            raise

    def _generate_call_id(self) -> str:
        """Generate a unique call ID for this service execution."""
        return str(uuid.uuid4())

    # ------------------------------------------------------------------
    # Result hooks (context-first)
    # ------------------------------------------------------------------
    async def on_success_ctx(self, *, context: dict[str, Any], result: "RunResult") -> None:
        """Context-first success hook (preferred in Django layer).

        Override this in subclasses instead of `on_success` if you want a
        keyword-only context argument.
        """
        pass

    async def on_failure_ctx(self, *, context: dict[str, Any], err: Exception) -> None:
        """Context-first failure hook (preferred in Django layer).

        Override this in subclasses instead of `on_failure` if you want a
        keyword-only context argument.
        """
        pass

    async def on_success(self, context: dict[str, Any], result: "RunResult") -> None:
        """BaseService callback override.

        Delegates to `on_success_ctx` so subclasses can implement either
        style without fighting the BaseService signature.
        """
        await self.on_success_ctx(context=context or {}, result=result)

    async def on_failure(self, context: dict[str, Any], error: Exception) -> None:
        """BaseService callback override.

        Delegates to `on_failure_ctx` so subclasses can implement either
        style without fighting the BaseService signature.
        """
        await self.on_failure_ctx(context=context or {}, err=error)
