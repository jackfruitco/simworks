"""
Pydantic AI Service Base.

This module provides a simplified service base class that uses Pydantic AI
for LLM execution. It replaces the complex client/codec/provider stack with
Pydantic AI's Agent abstraction.

Key features:
- Cached Agent instance per service class
- @system_prompt decorators for prompt composition
- Native Pydantic model validation with automatic LLM retry
- Multi-provider support via Pydantic AI
- Simplified execution flow

Usage:
    from pydantic import BaseModel
    from orchestrai.components.services.pydantic_ai_service import PydanticAIService
    from orchestrai.prompts import system_prompt

    class PatientResponse(BaseModel):
        messages: list[str]

    class GenerateResponse(PydanticAIService):
        response_schema = PatientResponse
        model = "openai:gpt-4o"

        @system_prompt(weight=100)
        def base_instructions(self) -> str:
            return "You are a helpful medical assistant..."

        @system_prompt(weight=50)
        async def patient_context(self, ctx) -> str:
            return f"Patient: {ctx.deps['patient_name']}"
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC
from datetime import datetime, UTC
from functools import cached_property
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel

from orchestrai.components.base import BaseComponent
from orchestrai.components.mixins import LifecycleMixin
from orchestrai.components.services.calls import ServiceCall
from orchestrai.components.services.calls.mixins import ServiceCallMixin
from orchestrai.identity import Identity, IdentityMixin
from orchestrai.identity.domains import SERVICES_DOMAIN
from orchestrai.prompts.decorators import collect_prompts, render_prompt_methods
from orchestrai.tracing import get_tracer, service_span

if TYPE_CHECKING:
    from pydantic_ai import Agent
    from pydantic_ai.result import RunResult

logger = logging.getLogger(__name__)
tracer = get_tracer("orchestrai.pydantic_ai_service")

# Type variable for response schema
T = TypeVar("T", bound=BaseModel)


class PydanticAIService(IdentityMixin, LifecycleMixin, ServiceCallMixin, BaseComponent, ABC, Generic[T]):
    """
    Simplified service base class using Pydantic AI for LLM execution.

    This replaces the complex client/codec/provider stack with Pydantic AI's
    Agent abstraction, providing:

    - Native multi-provider support (OpenAI, Anthropic, Gemini, etc.)
    - Automatic validation retry on schema failures
    - Provider failover via FallbackModel
    - Simplified prompt composition via @system_prompt decorators

    Class Attributes:
        model: Pydantic AI model identifier (e.g., "openai:gpt-4o", "anthropic:claude-3-5-sonnet")
        fallback_models: Optional list of fallback model identifiers
        response_schema: Pydantic model class for structured output
        required_context_keys: Keys that must be present in context

    Example:
        class PatientService(PydanticAIService):
            model = "openai:gpt-4o"
            response_schema = PatientResponse

            @system_prompt(weight=100)
            def instructions(self) -> str:
                return "You are a patient simulator..."
    """

    abstract: ClassVar[bool] = True
    DOMAIN: ClassVar[str] = SERVICES_DOMAIN
    domain: ClassVar[str | None] = SERVICES_DOMAIN

    # Pydantic AI model configuration
    model: ClassVar[str] = "openai:gpt-4o"
    fallback_models: ClassVar[list[str]] = []

    # Response schema (Pydantic model)
    response_schema: ClassVar[type[BaseModel] | None] = None

    # Required context keys
    required_context_keys: ClassVar[tuple[str, ...]] = ()

    # Retry configuration (for service-level retries, not LLM validation retries)
    max_retries: int = 3

    def __init__(
        self,
        *,
        context: dict[str, Any] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the service.

        Args:
            context: Service execution context (e.g., simulation_id, user info)
            model: Override the class-level model identifier
            **kwargs: Additional arguments passed to parent classes
        """
        super().__init__(**kwargs)

        # Context management
        self.context: dict[str, Any] = dict(context) if context else {}

        # Model override
        self._model_override: str | None = model

        # Cached prompt methods (collected from class)
        self._prompt_methods = collect_prompts(type(self))

        # Agent instance (lazily created)
        self._agent: Agent | None = None

    @property
    def effective_model(self) -> str:
        """Get the effective model identifier (instance override or class default)."""
        return self._model_override or type(self).model

    @cached_property
    def agent(self) -> Agent:
        """
        Cached Pydantic AI Agent instance.

        The agent is configured with:
        - Model (with optional fallbacks)
        - Result type (response_schema)
        - System prompts (collected from @system_prompt decorated methods)
        """
        from pydantic_ai import Agent

        # Build model with fallbacks
        model = self.effective_model
        if self.fallback_models:
            try:
                from pydantic_ai.models.fallback import FallbackModel
                model = FallbackModel(model, *self.fallback_models)
            except ImportError:
                logger.warning("FallbackModel not available, using primary model only")

        # Create agent
        agent = Agent(
            model=model,
            result_type=self.response_schema,
        )

        # Register system prompt methods
        for pm in self._prompt_methods:
            # Get the bound method and create a wrapper
            method_name = pm.name

            # Create a closure to capture the method name
            def make_prompt_fn(name: str, is_dynamic: bool):
                async def prompt_fn(ctx=None):
                    bound_method = getattr(self, name)
                    if is_dynamic and ctx is not None:
                        result = bound_method(ctx)
                    else:
                        result = bound_method()
                    if asyncio.iscoroutine(result):
                        result = await result
                    return result or ""
                return prompt_fn

            prompt_fn = make_prompt_fn(method_name, pm.is_dynamic)
            agent.system_prompt(prompt_fn, dynamic=pm.is_dynamic)

        return agent

    def check_required_context(self) -> None:
        """Validate that required context keys are present."""
        required = self.required_context_keys or ()
        missing = [key for key in required if self.context.get(key) is None]
        if missing:
            raise ValueError(f"Missing required context keys: {', '.join(missing)}")

    def setup(self, **ctx: Any) -> "PydanticAIService":
        """Merge incoming context and validate required keys."""
        incoming = ctx.get("context") if "context" in ctx else ctx
        if isinstance(incoming, dict) and incoming:
            self.context.update(incoming)
        self.check_required_context()
        return self

    def teardown(self, **ctx: Any) -> "PydanticAIService":
        """Teardown hook (no-op by default)."""
        return self

    def finalize(self, result: Any, **ctx: Any) -> Any:
        """Post-processing hook (passthrough by default)."""
        return result

    async def arun(self, **ctx: Any) -> RunResult[T]:
        """
        Execute the service using Pydantic AI Agent.

        This is the main execution method. It:
        1. Builds the system prompt from @system_prompt methods
        2. Gets the user message from context
        3. Executes the agent with the prompts
        4. Returns the validated result

        Args:
            **ctx: Additional context to merge before execution

        Returns:
            RunResult containing the validated response and metadata
        """
        from pydantic_ai import RunContext

        LOG_CAT = "pydantic_ai.run"

        # Merge context
        if ctx:
            self.context.update(ctx)

        # Create service call for tracking
        call = self._create_call(
            payload=ctx,
            context=self.context,
            dispatch={"service": self.identity.as_str},
            service=self.identity.as_str,
        )
        call.status = "running"
        call.started_at = datetime.now(UTC)

        try:
            async with service_span(
                f"pydantic_ai.{self.__class__.__name__}.run",
                attributes={"service.identity": self.identity.as_str},
            ):
                # Get user message from context
                user_message = self.context.get("user_message", "")
                message_history = self.context.get("message_history")

                # Build system prompt from decorated methods
                system_prompt = await render_prompt_methods(
                    self,
                    self._prompt_methods,
                    ctx=RunContext(deps=self.context, retry=0, tool_name=None),
                )

                # Execute agent
                result = await self.agent.run(
                    user_message,
                    system_prompt=system_prompt if system_prompt else None,
                    deps=self.context,
                    message_history=message_history,
                )

                # Update call with result
                call.status = "completed"
                call.finished_at = datetime.now(UTC)

                # Extract usage if available
                if result.usage():
                    call.input_tokens = result.usage().input_tokens or 0
                    call.output_tokens = result.usage().output_tokens or 0
                    call.total_tokens = result.usage().total_tokens or 0

                await self.on_success(self.context, result)
                return result

        except Exception as e:
            call.status = "failed"
            call.finished_at = datetime.now(UTC)
            call.error = str(e)
            await self.on_failure(self.context, e)
            raise

    async def on_success(self, context: dict[str, Any], result: RunResult[T]) -> None:
        """Called after successful execution. Override in subclasses."""
        pass

    async def on_failure(self, context: dict[str, Any], error: Exception) -> None:
        """Called after failed execution. Override in subclasses."""
        pass

    @property
    def slug(self) -> str:
        """Get slug for service (from identity string)."""
        return self.identity.as_str

    def flatten_context(self) -> dict[str, Any]:
        """Flatten context for tracing/logging."""
        from orchestrai.tracing import flatten_context as flatten_context_
        return flatten_context_(self.context)
