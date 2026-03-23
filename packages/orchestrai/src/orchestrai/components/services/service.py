# orchestrai/components/services/service.py
"""
BaseService: Pydantic AI-based service class for LLM-backed operations.

This module provides a simplified service base class that uses Pydantic AI
for LLM execution. It replaces the complex client/provider stack with
Pydantic AI's Agent abstraction.

Key features:
- Cached Agent instance per service class
- Class-based instruction composition via MRO
- Native Pydantic model validation with automatic LLM retry
- Multi-provider support via Pydantic AI
- Task descriptor for queued task execution

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
    from orchestrai.components.instructions import BaseInstruction

    class PatientResponse(BaseModel):
        messages: list[str]

    class BaseInstructions(BaseInstruction):
        instruction = "You are a helpful medical assistant..."

    class GenerateResponse(BaseInstructions, BaseService):
        response_schema = PatientResponse
        # model is optional - uses ORCA_DEFAULT_MODEL env var if not set
        model = "openai-responses:gpt-4o"
        use_native_output = True
"""

from __future__ import annotations

from abc import ABC
import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from functools import cached_property
import logging
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from pydantic import BaseModel

from orchestrai.components.base import BaseComponent
from orchestrai.components.instructions.base import BaseInstruction
from orchestrai.components.instructions.collector import collect_instructions
from orchestrai.components.mixins import LifecycleMixin
from orchestrai.components.services.calls.mixins import ServiceCallMixin
from orchestrai.identity import IdentityMixin
from orchestrai.identity.domains import SERVICES_DOMAIN
from orchestrai.tracing import flatten_context as flatten_context_, get_tracer, service_span

if TYPE_CHECKING:
    from pydantic_ai import Agent
    from pydantic_ai.result import RunResult

    from orchestrai.components.services.task_proxy import ServiceSpec

logger = logging.getLogger(__name__)
tracer = get_tracer("orchestrai.service")

# Type variable for response schema
T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# Provider factory functions (lazy imports — optional provider SDKs)
# ---------------------------------------------------------------------------


def _make_openai_model(model_name: str, api_key: str | None) -> Any:
    from pydantic_ai.models.openai import OpenAIResponsesModel
    from pydantic_ai.providers.openai import OpenAIProvider

    logger.info("Creating OpenAI model '%s'", model_name)
    return OpenAIResponsesModel(model_name, provider=OpenAIProvider(api_key=api_key))


def _make_anthropic_model(model_name: str, api_key: str | None) -> Any:
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    logger.info("Creating Anthropic model '%s'", model_name)
    return AnthropicModel(model_name, provider=AnthropicProvider(api_key=api_key))


def _make_gemini_model(model_name: str, api_key: str | None) -> Any:
    from pydantic_ai.models.gemini import GeminiModel
    from pydantic_ai.providers.google import GoogleProvider

    logger.info("Creating Gemini model '%s'", model_name)
    return GeminiModel(model_name, provider=GoogleProvider(api_key=api_key))


def _make_groq_model(model_name: str, api_key: str | None) -> Any:
    from pydantic_ai.models.groq import GroqModel
    from pydantic_ai.providers.groq import GroqProvider

    logger.info("Creating Groq model '%s'", model_name)
    return GroqModel(model_name, provider=GroqProvider(api_key=api_key))


def _make_mistral_model(model_name: str, api_key: str | None) -> Any:
    from pydantic_ai.models.mistral import MistralModel
    from pydantic_ai.providers.mistral import MistralProvider

    logger.info("Creating Mistral model '%s'", model_name)
    return MistralModel(model_name, provider=MistralProvider(api_key=api_key))


def _make_cohere_model(model_name: str, api_key: str | None) -> Any:
    from pydantic_ai.models.cohere import CohereModel
    from pydantic_ai.providers.cohere import CohereProvider

    logger.info("Creating Cohere model '%s'", model_name)
    return CohereModel(model_name, provider=CohereProvider(api_key=api_key))


#: Built-in provider dispatch table.  Maps the provider prefix (extracted from
#: ``"provider:model"`` strings) to a factory ``(model_name, api_key) -> model``.
_BUILTIN_PROVIDER_FACTORIES: dict[str, Callable[[str, str | None], Any]] = {
    "openai": _make_openai_model,
    "anthropic": _make_anthropic_model,
    "google": _make_gemini_model,
    "gemini": _make_gemini_model,
    "groq": _make_groq_model,
    "mistral": _make_mistral_model,
    "cohere": _make_cohere_model,
}


_task_proxy_factory: Callable[[Any], Any] | None = None


def register_task_proxy_factory(factory: Callable[[Any], Any] | None) -> None:
    """Register a task proxy factory used for service `.task` access."""

    global _task_proxy_factory
    _task_proxy_factory = factory


def resolve_task_proxy(spec: Any) -> Any:
    """Return the configured task proxy for ``spec`` or the core default."""

    factory = _task_proxy_factory
    if factory is not None:
        proxy = factory(spec)
        if proxy is not None:
            return proxy
    return CoreTaskProxy(spec)


class TaskDescriptor:
    """Descriptor that provides a task proxy for service execution.

    When accessed on a class, returns a CoreTaskProxy that can be used
    for inline execution or task enqueueing.

    External integration layers can register a custom task proxy factory
    while the core package remains framework-neutral.
    """

    def __get__(self, instance: Any, owner: type | None = None) -> Any:
        from orchestrai.components.services.task_proxy import ServiceSpec

        service_cls = owner or type(instance)
        kwargs: dict[str, Any] = {}
        if instance is not None:
            context = getattr(instance, "context", None)
            if context is not None:
                try:
                    kwargs["context"] = dict(context)
                except Exception:
                    kwargs["context"] = context
        return resolve_task_proxy(ServiceSpec(service_cls, kwargs))


class CoreTaskProxy:
    """Proxy for executing a service inline via its lifecycle helpers."""

    def __init__(self, spec: ServiceSpec):
        self._spec = spec

    def _build(self) -> ServiceCallMixin:
        return self._spec.service_cls(**self._spec.service_kwargs)

    def using(self, **service_kwargs: Any) -> CoreTaskProxy:
        return resolve_task_proxy(self._spec.using(**service_kwargs))

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

    def enqueue(self, **payload: Any) -> str:
        """Execute inline and return the generated call ID."""

        return self.run(**payload).id

    async def aenqueue(self, **payload: Any) -> str:
        """Async variant of :meth:`enqueue`."""

        return (await self.arun(**payload)).id

    def _dispatch_meta(self, service: ServiceCallMixin) -> dict[str, Any]:
        identity = getattr(service, "identity", None)
        ident_str = getattr(identity, "as_str", None)
        dispatch = {"service": ident_str or service.__class__.__name__}
        spec_dispatch = getattr(self._spec, "dispatch_kwargs", None)
        if spec_dispatch:
            dispatch.update(spec_dispatch)
        return dispatch


class BaseService[T: BaseModel](
    IdentityMixin, LifecycleMixin, ServiceCallMixin, BaseComponent, ABC
):
    """
    Pydantic AI-based service class for LLM-backed AI operations.

    This class uses Pydantic AI's Agent abstraction for LLM execution,
    providing:

    - Native multi-provider support (OpenAI, Anthropic, Gemini, etc.)
    - Automatic validation retry on schema failures
    - Provider failover via FallbackModel
    - Simplified prompt composition via instruction mixins

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

    Provider Registration:
        Third-party providers can be registered without subclassing::

            BaseService.register_provider(
                "myprovider",
                lambda model_name, api_key: MyModel(model_name, api_key=api_key),
            )

    Example:
        @orca.instruction(order=10)
        class PersonaInstruction(BaseInstruction):
            instruction = "You are a patient simulator..."

        class PatientService(PersonaInstruction, BaseService):
            model = "openai-responses:gpt-4o"  # Optional - uses config default if omitted
            response_schema = PatientResponse
            use_native_output = True
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

    # Class-level cache: one built model object per concrete service class.
    # Keyed by class; populated on first access when no instance override is set.
    # Thread-safety: Python's GIL makes the dict read/write atomic for CPython;
    # worst case two threads build the same model simultaneously and one
    # overwrites the other — both produce identical results.
    _class_model_cache: ClassVar[dict[type, Any]] = {}

    # Per-class provider overrides.  Populated via register_provider().
    # Falls back to _BUILTIN_PROVIDER_FACTORIES for unknown names.
    _PROVIDER_FACTORIES: ClassVar[dict[str, Callable[[str, str | None], Any]]] = {}

    # Response schema (Pydantic model)
    response_schema: ClassVar[type[BaseModel] | None] = None

    # Use native structured output (e.g. OpenAI Response Format) instead of tool calls
    use_native_output: ClassVar[bool] = False
    native_output_strict: ClassVar[bool] = True

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

        # Cached instruction classes (collected from class MRO)
        self._instruction_classes = collect_instructions(type(self))

        # Agent instance (lazily created)
        self._agent: Agent | None = None

    # ---------------------------------------------------------------------------
    # Provider registration
    # ---------------------------------------------------------------------------

    @classmethod
    def register_provider(
        cls,
        name: str,
        factory: Callable[[str, str | None], Any],
    ) -> None:
        """Register a custom provider factory.

        The factory receives ``(model_name, api_key)`` and must return a
        Pydantic AI-compatible model object.

        Registered factories are checked before the built-in set, so they can
        also override a built-in provider (e.g. for testing).

        Example::

            BaseService.register_provider(
                "myprovider",
                lambda model_name, api_key: MyModel(model_name, api_key=api_key),
            )
        """
        cls._PROVIDER_FACTORIES[name] = factory

    @classmethod
    def _get_provider_factory(
        cls,
        provider: str,
    ) -> Callable[[str, str | None], Any] | None:
        """Return the factory for *provider*, class-level overrides first."""
        return cls._PROVIDER_FACTORIES.get(provider) or _BUILTIN_PROVIDER_FACTORIES.get(provider)

    # ---------------------------------------------------------------------------
    # Model resolution
    # ---------------------------------------------------------------------------

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
        - Integration layers: May choose namespaced env vars (for example ORCA_OPENAI_API_KEY)
        - User override: Via ORCHESTRAI["API_KEY_ENVVARS"]

        Args:
            provider: Provider name (e.g., "openai", "anthropic")

        Returns:
            Tuple of (api_key, source_envvar) or (None, None) if not found
        """
        from orchestrai.utils.env_utils import get_api_key, get_api_key_envvar

        envvar = get_api_key_envvar(provider)
        api_key = get_api_key(provider)

        if api_key:
            logger.debug(
                "API key for %s found",
                provider,
            )
            return api_key, envvar

        return None, None

    def _build_model_with_api_key(self, model_str: str) -> Any:
        """
        Build a Pydantic AI model with API key from environment.

        Dispatches to a registered factory based on the provider prefix in
        ``"provider:model"`` format.  Use :meth:`register_provider` to add
        support for additional providers at runtime.

        Args:
            model_str: Model identifier string (e.g., "openai-responses:gpt-5-nano")

        Returns:
            A Pydantic AI model instance configured with the API key

        Raises:
            ValueError: If no API key is found for a supported provider
        """
        from orchestrai import get_current_app
        from orchestrai.utils.env_utils import get_api_key_envvar

        if ":" not in model_str:
            raise ValueError(
                f"Invalid model format '{model_str}'. Expected 'provider:model' "
                f"(e.g., 'openai-responses:gpt-5-nano', 'anthropic:claude-3-5-sonnet')"
            )

        provider, model_name = model_str.split(":", 1)

        # Clean `openai-{API}` provider format
        if "-" in provider:
            provider = provider.split("-")[0]

        api_key, _ = self._get_api_key_for_provider(provider)

        # Check if API key is required but missing
        app = get_current_app()
        supported_providers = (
            set(app.conf.get("API_KEY_ENVVARS", {}).keys()) if app and app.conf else set()
        )

        if not api_key and provider in supported_providers:
            configured_envvar = get_api_key_envvar(provider) or f"{provider.upper()}_API_KEY"
            raise ValueError(
                f"No API key found for provider '{provider}'. Set {configured_envvar}."
            )

        factory = type(self)._get_provider_factory(provider)
        if factory is not None:
            return factory(model_name, api_key)

        # Unknown provider - let Pydantic AI handle it
        logger.warning(
            "Unknown provider '%s' - passing model string '%s' to Pydantic AI",
            provider,
            model_str,
        )
        return model_str

    def _build_pydantic_ai_model(self, model_str: str) -> Any:
        """Build model + optional FallbackModel wrapper for a given model string."""
        model = self._build_model_with_api_key(model_str)
        if self.fallback_models:
            try:
                from pydantic_ai.models.fallback import FallbackModel

                fallback_models = [self._build_model_with_api_key(m) for m in self.fallback_models]
                model = FallbackModel(model, *fallback_models)
            except ImportError:
                logger.warning("FallbackModel not available, using primary model only")
        return model

    def _get_or_build_class_model(self) -> Any:
        """Return the class-level cached Pydantic AI model.

        The model is built once per concrete service class and cached in
        ``BaseService._class_model_cache``.  When an instance override is
        active the cache is bypassed and a fresh model is returned.
        """
        if self._model_override:
            # Instance override — always build fresh, never cache
            return self._build_pydantic_ai_model(self._model_override)

        cls = type(self)
        if cls not in BaseService._class_model_cache:
            BaseService._class_model_cache[cls] = self._build_pydantic_ai_model(
                self.effective_model
            )
        return BaseService._class_model_cache[cls]

    # ---------------------------------------------------------------------------
    # Agent
    # ---------------------------------------------------------------------------

    @cached_property
    def agent(self) -> Agent:
        """
        Cached Pydantic AI Agent instance.

        The agent is configured with:
        - Model (with optional fallbacks) — cached at class level for efficiency
        - Result type (response_schema, potentially wrapped in NativeOutput)
        - System prompts (collected from instruction classes)
        """
        from pydantic_ai import Agent, NativeOutput

        # Obtain model — class-level cached unless instance override is set
        model = self._get_or_build_class_model()

        # Configure output type
        output_type = self.response_schema
        if self.use_native_output and output_type is not None:
            output_type = NativeOutput(output_type, strict=self.native_output_strict)

        # Create agent
        agent = Agent(
            model=model,
            output_type=output_type,
        )

        # Register instruction callbacks in deterministic order.
        for instruction_cls in self._instruction_classes:
            has_custom_render = (
                hasattr(instruction_cls, "render_instruction")
                and instruction_cls.render_instruction is not BaseInstruction.render_instruction
            )

            def make_instruction_fn(cls, is_dynamic: bool):
                if is_dynamic:

                    async def instruction_fn(ctx=None):
                        result = cls.render_instruction(self)
                        if asyncio.iscoroutine(result):
                            result = await result
                        return result or ""

                else:
                    static_text = cls.instruction or ""

                    async def instruction_fn(ctx=None, _text: str = static_text):
                        return _text

                return instruction_fn

            # pydantic_ai requires decorator style when dynamic=True.
            agent.system_prompt(dynamic=has_custom_render)(
                make_instruction_fn(instruction_cls, has_custom_render)
            )

        return agent

    # ---------------------------------------------------------------------------
    # Context validation
    # ---------------------------------------------------------------------------

    def check_required_context(self) -> None:
        """Validate that required context keys are present and non-None."""
        required = self.required_context_keys or ()
        missing = [key for key in required if key not in self.context or self.context[key] is None]
        if missing:
            raise ValueError(f"Missing required context keys: {', '.join(missing)}")

    # ---------------------------------------------------------------------------
    # Lifecycle hooks
    # ---------------------------------------------------------------------------

    def setup(self, **ctx: Any) -> BaseService:
        """Merge incoming context and validate required keys."""
        incoming = ctx.get("context") if "context" in ctx else ctx
        if isinstance(incoming, dict) and incoming:
            # Reassign rather than mutating the existing dict to avoid aliasing
            self.context = {**self.context, **incoming}
        self.check_required_context()
        return self

    def teardown(self, **ctx: Any) -> BaseService:
        """Teardown hook (no-op by default)."""
        return self

    def finalize(self, result: Any, **ctx: Any) -> Any:
        """Post-processing hook (passthrough by default)."""
        return result

    # ---------------------------------------------------------------------------
    # Execution
    # ---------------------------------------------------------------------------

    async def arun(self, **ctx: Any) -> RunResult[T]:
        """
        Execute the service using Pydantic AI Agent.

        This is the main execution method. It:
        1. Builds a working context copy (self.context is never mutated)
        2. Builds the system prompt from instruction classes
        3. Gets the user message from context
        4. Executes the agent with the prompts
        5. Returns the validated result

        Args:
            **ctx: Additional context merged for this execution only.
                   Does not modify ``self.context``.

        Returns:
            RunResult containing the validated response and metadata
        """
        # Build a working copy — self.context is never mutated during execution.
        # This prevents context from one call bleeding into the next if the same
        # instance is reused.
        working_ctx: dict[str, Any] = {**self.context, **ctx} if ctx else dict(self.context)

        # Optional per-execution context preparation hook.
        # Temporarily expose as self.context so existing hook implementations
        # can augment it via self.context, then capture any changes.
        prepare_ctx = getattr(self, "_aprepare_context", None)
        if callable(prepare_ctx):
            _saved_ctx = self.context
            self.context = working_ctx
            try:
                await prepare_ctx()
                working_ctx = dict(self.context)
            finally:
                self.context = _saved_ctx

        # Create service call for tracking
        call = self._create_call(
            payload=ctx,
            context=working_ctx,
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
                user_message = working_ctx.get("user_message", "")
                message_history = working_ctx.get("message_history")

                model_settings = None
                context_model_settings = working_ctx.get("model_settings")
                if isinstance(context_model_settings, dict):
                    model_settings = dict(context_model_settings)
                previous_response_id = working_ctx.get(
                    "previous_provider_response_id"
                ) or working_ctx.get("previous_response_id")
                if previous_response_id:
                    model_settings = {
                        **dict(model_settings or {}),
                        "openai_previous_response_id": previous_response_id,
                    }

                # Execute agent. Instruction callbacks are registered on the agent and
                # capture the service instance to read the latest context state.
                result = await self.agent.run(
                    user_message,
                    deps=working_ctx,
                    message_history=message_history,
                    model_settings=model_settings,
                )

                # Update call with result
                call.status = "completed"
                call.finished_at = datetime.now(UTC)

                # Extract usage if available
                if result.usage():
                    call.input_tokens = result.usage().input_tokens or 0
                    call.output_tokens = result.usage().output_tokens or 0
                    call.total_tokens = result.usage().total_tokens or 0

                await self.on_success(working_ctx, result)
                return result

        except Exception as e:
            call.status = "failed"
            call.finished_at = datetime.now(UTC)
            call.error = str(e)
            await self.on_failure(working_ctx, e)
            raise

    async def on_success(self, context: dict[str, Any], result: RunResult[T]) -> None:
        """Called after successful execution. Override in subclasses."""

    async def on_failure(self, context: dict[str, Any], error: Exception) -> None:
        """Called after failed execution. Override in subclasses."""

    @property
    def slug(self) -> str:
        """Get slug for service (from identity string)."""
        return self.identity.as_str

    def flatten_context(self) -> dict[str, Any]:
        """Flatten context for tracing/logging."""
        return flatten_context_(self.context)


__all__ = [
    "BaseService",
    "CoreTaskProxy",
    "TaskDescriptor",
    "register_task_proxy_factory",
    "resolve_task_proxy",
]
