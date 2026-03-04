"""
System prompt decorators for service methods.

This module provides the @system_prompt decorator for marking service methods
as prompt components. Methods are collected and composed into the system prompt
based on their weight (higher weight = earlier in the prompt).

The decorator supports both sync and async methods, and can optionally receive
a RunContext for accessing dependencies.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
import inspect
from typing import (
    TYPE_CHECKING,
    Any,
    Protocol,
    TypeVar,
    overload,
)

if TYPE_CHECKING:
    pass

__all__ = [
    "PromptMethod",
    "SystemPromptResult",
    "collect_prompts",
    "system_prompt",
]

# Type for prompt method return values
SystemPromptResult = str | None

# Marker attributes set on decorated methods
_PROMPT_WEIGHT_ATTR = "_orca_prompt_weight"
_PROMPT_MARKER_ATTR = "_orca_is_system_prompt"
_PROMPT_DYNAMIC_ATTR = "_orca_prompt_dynamic"


class PromptMethodProtocol(Protocol):
    """Protocol for methods that can be decorated as system prompts."""

    def __call__(
        self, *args: Any, **kwargs: Any
    ) -> SystemPromptResult | Coroutine[Any, Any, SystemPromptResult]: ...


F = TypeVar("F", bound=PromptMethodProtocol)


@dataclass(frozen=True, slots=True)
class PromptMethod:
    """Represents a collected prompt method with its metadata."""

    weight: int
    method: Callable[..., SystemPromptResult | Coroutine[Any, Any, SystemPromptResult]]
    is_dynamic: bool
    name: str

    def __lt__(self, other: PromptMethod) -> bool:
        """Sort by weight descending (higher weight = earlier)."""
        if not isinstance(other, PromptMethod):
            return NotImplemented
        return self.weight > other.weight  # Reversed for descending order


@overload
def system_prompt[F: PromptMethodProtocol](fn: F) -> F: ...


@overload
def system_prompt(
    *,
    weight: int = 100,
    dynamic: bool = False,
) -> Callable[[F], F]: ...


def system_prompt[F: PromptMethodProtocol](
    fn: F | None = None,
    *,
    weight: int = 100,
    dynamic: bool = False,
) -> F | Callable[[F], F]:
    """
    Mark a service method as a system prompt component.

    The decorated method will be called during agent execution to build
    the system prompt. Methods are ordered by weight (higher weight = earlier
    in the prompt).

    Args:
        fn: The method to decorate (when used without parentheses)
        weight: Prompt ordering weight. Higher weights appear earlier in the
               composed system prompt. Default: 100.
        dynamic: If True, the prompt requires runtime context (RunContext)
                and cannot be cached. Default: False.

    Usage:
        # Simple static prompt (highest priority)
        @system_prompt(weight=100)
        def base_instructions(self) -> str:
            return "You are a helpful assistant..."

        # Dynamic prompt with context
        @system_prompt(weight=50, dynamic=True)
        async def patient_context(self, ctx: RunContext) -> str:
            sim = ctx.deps['simulation']
            return f"Patient name: {sim.patient_name}"

        # Without parentheses (uses defaults)
        @system_prompt
        def default_instructions(self) -> str:
            return "Default instructions..."

    Returns:
        The decorated method with prompt metadata attached.
    """

    def decorator(func: F) -> F:
        # Attach metadata to the function
        setattr(func, _PROMPT_WEIGHT_ATTR, weight)
        setattr(func, _PROMPT_MARKER_ATTR, True)
        setattr(func, _PROMPT_DYNAMIC_ATTR, dynamic)
        return func

    # Handle both @system_prompt and @system_prompt(...)
    if fn is not None:
        return decorator(fn)
    return decorator


def is_system_prompt(method: Any) -> bool:
    """Check if a method is decorated as a system prompt."""
    return getattr(method, _PROMPT_MARKER_ATTR, False) is True


def get_prompt_weight(method: Any) -> int:
    """Get the weight of a system prompt method."""
    return getattr(method, _PROMPT_WEIGHT_ATTR, 100)


def is_dynamic_prompt(method: Any) -> bool:
    """Check if a prompt method requires dynamic context."""
    return getattr(method, _PROMPT_DYNAMIC_ATTR, False) is True


def collect_prompts(cls: type) -> list[PromptMethod]:
    """
    Collect all @system_prompt decorated methods from a class.

    Searches through the class and its bases for methods marked with
    @system_prompt, and returns them sorted by weight (descending).

    Args:
        cls: The class to inspect for prompt methods.

    Returns:
        List of PromptMethod objects sorted by weight (highest first).
    """
    prompts: list[PromptMethod] = []
    seen_names: set[str] = set()

    # Walk through MRO to find all prompt methods
    for klass in cls.__mro__:
        if klass is object:
            continue

        for name in dir(klass):
            if name in seen_names:
                continue

            try:
                attr = getattr(klass, name, None)
            except AttributeError:
                continue

            if attr is None:
                continue

            # Check if it's a method/function with the prompt marker
            if callable(attr) and is_system_prompt(attr):
                seen_names.add(name)
                prompts.append(
                    PromptMethod(
                        weight=get_prompt_weight(attr),
                        method=attr,
                        is_dynamic=is_dynamic_prompt(attr),
                        name=name,
                    )
                )

    # Sort by weight descending (higher weight = earlier in prompt)
    prompts.sort()
    return prompts


async def render_prompt_methods(
    instance: Any,
    prompts: list[PromptMethod],
    ctx: Any | None = None,
) -> str:
    """
    Render all prompt methods and compose them into a single string.

    Args:
        instance: The service instance to call methods on.
        prompts: List of PromptMethod objects to render.
        ctx: Optional RunContext to pass to dynamic prompts.

    Returns:
        Composed system prompt string with all sections joined.
    """
    parts: list[str] = []

    for pm in prompts:
        # Get the bound method from the instance
        bound_method = getattr(instance, pm.name)

        # Determine if method accepts context
        sig = inspect.signature(bound_method)
        params = list(sig.parameters.keys())

        # Call the method (with or without context)
        if pm.is_dynamic and ctx is not None and len(params) > 0:
            result = bound_method(ctx)
        else:
            result = bound_method()

        # Handle async methods
        if asyncio.iscoroutine(result):
            result = await result

        # Add non-empty results
        if result is not None:
            text = str(result).strip()
            if text:
                parts.append(text)

    return "\n\n".join(parts)
