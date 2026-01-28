# orchestrai/components/services/service.py
"""
BaseService: Pydantic AI-based service class for LLM-backed operations.

This module provides a simplified service base class that uses Pydantic AI
for LLM execution. It replaces the complex client/codec/provider stack with
Pydantic AI's Agent abstraction.

Key features:
- Cached Agent instance per service class
- @system_prompt decorators for prompt composition
- Native Pydantic model validation with automatic LLM retry
- Multi-provider support via Pydantic AI
- Task descriptor for Django task execution

Identity
--------
- Identity is a class-level concept provided by `IdentityMixin`.
  Each concrete service class has a stable `identity: Identity`.
- Instances read `self.identity`, which mirrors the class identity.
- Class attributes `domain`, `namespace`, `group`, and `name` are treated
  as hints passed to the resolver.

Usage:
    from pydantic import BaseModel
    from orchestrai.components.services import BaseService
    from orchestrai.prompts import system_prompt

    class PatientResponse(BaseModel):
        messages: list[str]

    class GenerateResponse(BaseService):
        response_schema = PatientResponse
        # model is optional - uses ORCA_DEFAULT_MODEL env var if not set
        model = "openai-responses:gpt-4o"

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
from pydantic_ai.models.openai import OpenAIResponsesModel

from orchestrai.components.base import BaseComponent
from orchestrai.components.mixins import LifecycleMixin
from orchestrai.components.services.calls import ServiceCall
from orchestrai.components.services.calls.mixins import ServiceCallMixin
from orchestrai.identity import IdentityMixin
from orchestrai.identity.domains import SERVICES_DOMAIN
from orchestrai.prompts.decorators import collect_prompts
from orchestrai.tracing import get_tracer, service_span, flatten_context as flatten_context_

if TYPE_CHECKING:
    from pydantic_ai import Agent
    from pydantic_ai.result import RunResult

logger = logging.getLogger(__name__)
tracer = get_tracer("orchestrai.service")

# Type variable for response schema
T = TypeVar("T", bound=BaseModel)


class TaskDescriptor:
    """Descriptor that provides a task proxy for service execution.

    When accessed on a class, returns a CoreTaskProxy that can be used
    for inline execution or task enqueueing.

    The proxy is configured by the Django layer to use DjangoTaskProxy
    when orchestrai_django is installed, enabling background task dispatch.
    """

    def __get__(self, instance: Any, owner: type | None = None) -> "CoreTaskProxy":
        from orchestrai.components.services.task_proxy import CoreTaskProxy, ServiceSpec

        service_cls = owner or type(instance)
        kwargs: dict[str, Any] = {}
        if instance is not None:
            context = getattr(instance, "context", None)
            if context is not None:
                try:
                    kwargs["context"] = dict(context)
                except Exception:
                    kwargs["context"] = context
        return CoreTaskProxy(ServiceSpec(service_cls, kwargs))


class CoreTaskProxy:
    """Proxy for executing a service inline via its lifecycle helpers.

    This is the core implementation - the Django layer replaces this with
    DjangoTaskProxy for persistence and background execution support.
    """

    def __init__(self, spec: "ServiceSpec"):
        from orchestrai.components.services.task_proxy import ServiceSpec
        self._spec = spec

    def _build(self) -> ServiceCallMixin:
        return self._spec.service_cls(**self._spec.service_kwargs)

    def using(self, **service_kwargs: Any) -> "CoreTaskProxy":
        if "queue" in service_kwargs:
            raise ValueError("queue dispatch is not supported for inline tasks")
        return CoreTaskProxy(self._spec.using(**service_kwargs))

    def run(self, **payload: Any):
        service = self._build()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return service.call(
                payload=payload,
                context=getattr(service, "context", None),
                dispatch=self._dispatch_meta(service),
            )

        if loop.is_running():
            raise RuntimeError("Cannot run inline task while an event loop is already running")

        return loop.run_until_complete(
            service.acall(
                payload=payload,
                context=getattr(service, "context", None),
                dispatch=self._dispatch_meta(service),
            )
        )

    async def arun(self, **payload: Any):
        service = self._build()
        return await service.acall(
            payload=payload,
            context=getattr(service, "context", None),
            dispatch=self._dispatch_meta(service),
        )

    def _dispatch_meta(self, service: ServiceCallMixin) -> dict[str, Any]:
        identity = getattr(service, "identity", None)
        ident_str = getattr(identity, "as_str", None)
        return {"service": ident_str or service.__class__.__name__}


class BaseService(IdentityMixin, LifecycleMixin, ServiceCallMixin, BaseComponent, ABC, Generic[T]):
    """
    Pydantic AI-based service class for LLM-backed AI operations.

    This class uses Pydantic AI's Agent abstraction for LLM execution,
    providing:

    - Native multi-provider support (OpenAI, Anthropic, Gemini, etc.)
    - Automatic validation retry on schema failures
    - Provider failover via FallbackModel
    - Simplified prompt composition via @system_prompt decorators

    Class Attributes:
        model: Pydantic AI model identifier (e.g., "openai-responses:gpt-5-nano"). Optional -
            if not set, uses DEFAULT_MODEL from OrchestrAI config.
        fallback_models: Optional list of fallback model identifiers
        response_schema: Pydantic model class for structured output
        required_context_keys: Keys that must be present in context

    Model Resolution:
        1. Instance override (passed to __init__)
        2. Class-level model attribute (if defined by subclass)
        3. DEFAULT_MODEL from OrchestrAI config (ORCA_DEFAULT_MODEL env var)
        4. Hardcoded fallback: "openai-responses:gpt-4o-mini"

    Example:
        class PatientService(BaseService):
            model = "openai-responses:gpt-4o"  # Optional - uses config default if omitted
            response_schema = PatientResponse

            @system_prompt(weight=100)
            def instructions(self) -> str:
                return "You are a patient simulator..."
    """

    abstract: ClassVar[bool] = True
    DOMAIN: ClassVar[str] = SERVICES_DOMAIN
    domain: ClassVar[str | None] = SERVICES_DOMAIN

    # Task proxy for enqueueing/running services
    task: ClassVar[CoreTaskProxy] = TaskDescriptor()

    # Pydantic AI model configuration
    # Empty string = use DEFAULT_MODEL from config (or hardcoded fallback)
    model: ClassVar[str] = ""
    fallback_models: ClassVar[list[str]] = []
    _FALLBACK_MODEL: ClassVar[str] = "openai-responses:gpt-5-nano"

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
        """
        Get the effective model identifier.

        Resolution order:
        1. Instance override (passed to __init__)
        2. Class-level model attribute (if defined by subclass)
        3. DEFAULT_MODEL from OrchestrAI config
        4. Hardcoded fallback (_FALLBACK_MODEL)
        """
        # 1. Instance override
        if self._model_override:
            return self._model_override

        # 2. Class-level model (if subclass defined it)
        class_model = type(self).model
        if class_model:
            return class_model

        # 3. Config default
        from orchestrai import get_current_app
        app = get_current_app()
        if app and app.conf:
            config_default = app.conf.get("DEFAULT_MODEL")
            if config_default:
                return config_default

        # 4. Hardcoded fallback
        return self._FALLBACK_MODEL

    def _get_api_key_for_provider(self, provider: str) -> tuple[str | None, str | None]:
        """
        Get the API key for a provider using configured environment variable.

        Uses ``orchestrai.utils.env.get_api_key()`` which reads from
        ``app.conf["API_KEY_ENVVARS"][provider]`` to determine the env var name.

        Configuration layering:
        - Standalone OrchestrAI: Uses standard env vars (OPENAI_API_KEY, etc.)
        - Django integration: Uses namespaced env vars (ORCA_OPENAI_API_KEY, etc.)
        - User override: Via ORCA_CONFIG["API_KEY_ENVVARS"]

        Args:
            provider: Provider name (e.g., "openai", "anthropic")

        Returns:
            Tuple of (api_key, source_envvar) or (None, None) if not found
        """
        import os

        from orchestrai.utils.env import get_api_key, get_api_key_envvar

        envvar = get_api_key_envvar(provider)
        api_key = get_api_key(provider)

        if api_key:
            logger.debug(
                "API key for %s found via %s",
                provider,
                envvar,
            )
            return api_key, envvar

        # Fallback for backward compatibility: ORCA_PROVIDER_API_KEY
        generic_envvar = "ORCA_PROVIDER_API_KEY"
        generic_key = os.environ.get(generic_envvar)
        if generic_key:
            logger.debug(
                "API key for %s found via generic fallback %s",
                provider,
                generic_envvar,
            )
            return generic_key, generic_envvar

        return None, None

    def _build_model_with_api_key(self, model_str: str) -> Any:
        """
        Build a Pydantic AI model with API key from environment.

        Uses settings-based env var lookup via ``orchestrai.utils.env``.
        The env var name is configured in ``app.conf["API_KEY_ENVVARS"]``.

        Supports: openai, anthropic, google/gemini, groq, mistral, cohere

        Args:
            model_str: Model identifier string (e.g., "openai-responses:gpt-5-nano")

        Returns:
            A Pydantic AI model instance configured with the API key

        Raises:
            ValueError: If no API key is found for a supported provider
        """
        from orchestrai import get_current_app
        from orchestrai.utils.env import get_api_key_envvar

        # Parse provider:model format
        if ":" not in model_str:
            raise ValueError(
                f"Invalid model format '{model_str}'. Expected 'provider:model' "
                f"(e.g., 'openai-responses:gpt-5-nano', 'anthropic:claude-3-5-sonnet')"
            )

        provider, model_name = model_str.split(":", 1)

        # Clean `openai-{API}` provider format
        if "-" in provider: provider = provider.split("-")[0]

        api_key, source_envvar = self._get_api_key_for_provider(provider)

        # Check if API key is required but missing
        # Supported providers are those configured in API_KEY_ENVVARS
        app = get_current_app()
        supported_providers = set(app.conf.get("API_KEY_ENVVARS", {}).keys()) if app and app.conf else set()

        if not api_key and provider in supported_providers:
            configured_envvar = get_api_key_envvar(provider) or f"{provider.upper()}_API_KEY"
            raise ValueError(
                f"No API key found for provider '{provider}'. "
                f"Set {configured_envvar} or ORCA_PROVIDER_API_KEY environment variable."
            )

        # OpenAI
        if provider == "openai":
            from pydantic_ai.models.openai import OpenAIModel
            from pydantic_ai.providers.openai import OpenAIProvider
            logger.info(
                "Creating OpenAI model '%s' with API key from %s",
                model_name,
                source_envvar,
            )
            return OpenAIResponsesModel(model_name, provider=OpenAIProvider(api_key=api_key))

        # Anthropic
        if provider == "anthropic":
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.providers.anthropic import AnthropicProvider
            logger.info(
                "Creating Anthropic model '%s' with API key from %s",
                model_name,
                source_envvar,
            )
            return AnthropicModel(model_name, provider=AnthropicProvider(api_key=api_key))

        # Google/Gemini
        if provider in ("google", "gemini"):
            from pydantic_ai.models.gemini import GeminiModel
            from pydantic_ai.providers.google import GoogleProvider
            logger.info(
                "Creating Gemini model '%s' with API key from %s",
                model_name,
                source_envvar,
            )
            return GeminiModel(model_name, provider=GoogleProvider(api_key=api_key))

        # Groq
        if provider == "groq":
            from pydantic_ai.models.groq import GroqModel
            from pydantic_ai.providers.groq import GroqProvider
            logger.info(
                "Creating Groq model '%s' with API key from %s",
                model_name,
                source_envvar,
            )
            return GroqModel(model_name, provider=GroqProvider(api_key=api_key))

        # Mistral
        if provider == "mistral":
            from pydantic_ai.models.mistral import MistralModel
            from pydantic_ai.providers.mistral import MistralProvider
            logger.info(
                "Creating Mistral model '%s' with API key from %s",
                model_name,
                source_envvar,
            )
            return MistralModel(model_name, provider=MistralProvider(api_key=api_key))

        # Cohere
        if provider == "cohere":
            from pydantic_ai.models.cohere import CohereModel
            from pydantic_ai.providers.cohere import CohereProvider
            logger.info(
                "Creating Cohere model '%s' with API key from %s",
                model_name,
                source_envvar,
            )
            return CohereModel(model_name, provider=CohereProvider(api_key=api_key))

        # Unknown provider - let Pydantic AI handle it
        logger.warning(
            "Unknown provider '%s' - passing model string '%s' to Pydantic AI",
            provider,
            model_str,
        )
        return model_str

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

        # Build model with API key from OrchestrAI config
        model = self._build_model_with_api_key(self.effective_model)

        # Handle fallbacks
        if self.fallback_models:
            try:
                from pydantic_ai.models.fallback import FallbackModel
                fallback_models = [
                    self._build_model_with_api_key(m) for m in self.fallback_models
                ]
                model = FallbackModel(model, *fallback_models)
            except ImportError:
                logger.warning("FallbackModel not available, using primary model only")


        # Create agent
        agent = Agent(
            model=model,
            output_type=self.response_schema,
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

    def setup(self, **ctx: Any) -> "BaseService":
        """Merge incoming context and validate required keys."""
        incoming = ctx.get("context") if "context" in ctx else ctx
        if isinstance(incoming, dict) and incoming:
            self.context.update(incoming)
        self.check_required_context()
        return self

    def teardown(self, **ctx: Any) -> "BaseService":
        """Teardown hook (no-op by default)."""
        return self

    def finalize(self, result: Any, **ctx: Any) -> Any:
        """Post-processing hook (passthrough by default)."""
        return result

    async def arun(self, **ctx: Any) -> "RunResult[T]":
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

                # Execute agent - system prompts are registered on the agent via @system_prompt
                # decorated methods (registered in the agent property). The prompts access
                # self.context through closures, so they get the current context state.
                result = await self.agent.run(
                    user_message,
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

    async def on_success(self, context: dict[str, Any], result: "RunResult[T]") -> None:
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
        return flatten_context_(self.context)


# Re-export for backward compatibility with imports expecting these from this module
__all__ = [
    "BaseService",
    "CoreTaskProxy",
    "TaskDescriptor",
]
