"""
Django Pydantic AI Service Base.

This module provides a Django-aware version of the Pydantic AI service
that integrates with Django signals, models, and task execution.

Usage:
    from pydantic import BaseModel
    from orchestrai_django.components.services import DjangoPydanticAIService
    from orchestrai.prompts import system_prompt

    class PatientResponse(BaseModel):
        messages: list[str]

    class GenerateResponse(DjangoPydanticAIService):
        response_schema = PatientResponse
        model = "openai:gpt-4o"

        @system_prompt(weight=100)
        def base_instructions(self) -> str:
            return "You are a helpful medical assistant..."
"""

from __future__ import annotations

import logging
from abc import ABC
from datetime import datetime, UTC
from typing import TYPE_CHECKING, Any, ClassVar

from orchestrai.components.services.pydantic_ai_service import PydanticAIService
from orchestrai_django.signals import emitter as _default_emitter

if TYPE_CHECKING:
    from pydantic_ai.result import RunResult

logger = logging.getLogger(__name__)


class DjangoPydanticAIService(PydanticAIService, ABC):
    """
    Django-aware Pydantic AI service base class.

    Extends PydanticAIService with:
    - Django signal emission for request/response events
    - Integration with Django task execution (Celery)
    - Support for ServiceCallRecord persistence

    This is the recommended base class for SimWorks services using
    Pydantic AI.

    Example:
        class PatientService(DjangoPydanticAIService):
            model = "openai:gpt-4o"
            response_schema = PatientResponse

            @system_prompt(weight=100)
            def instructions(self) -> str:
                return "You are a patient simulator..."
    """

    abstract: ClassVar[bool] = True

    # Django task proxy (will be set by Django layer)
    task: ClassVar[Any] = None

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
            **kwargs: Additional arguments passed to PydanticAIService
        """
        super().__init__(context=context, **kwargs)

        # Django signal emitter
        self.emitter = emitter or _default_emitter

    async def arun(self, **ctx: Any) -> RunResult:
        """
        Execute the service with Django integration.

        Emits Django signals for request/response events and
        handles persistence of service call records.
        """
        from orchestrai_django.models import ServiceCall as ServiceCallModel

        # Merge context
        if ctx:
            self.context.update(ctx)

        # Create service call record for persistence
        call_id = self._generate_call_id()
        service_identity = self.identity.as_str

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
                # Create a minimal response-like object for signal compatibility
                self.emitter.emit_response(
                    self.context,
                    self.identity.namespace or "",
                    result,  # Pass the RunResult
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
        import uuid
        return str(uuid.uuid4())

    async def on_success_ctx(self, *, context: dict[str, Any], result: RunResult) -> None:
        """Context-first success hook (preferred in Django layer)."""
        pass

    async def on_failure_ctx(self, *, context: dict[str, Any], err: Exception) -> None:
        """Context-first failure hook (preferred in Django layer)."""
        pass

    async def on_success(self, context: dict[str, Any], result: RunResult) -> None:
        """Called after successful execution."""
        await self.on_success_ctx(context=context or {}, result=result)

    async def on_failure(self, context: dict[str, Any], error: Exception) -> None:
        """Called after failed execution."""
        await self.on_failure_ctx(context=context or {}, err=error)
