"""Django-aware prompt_section decorator and identity management for PromptSection classes.

This module provides a decorator to register PromptSection classes with automatic
derivation and assignment of a tuple3 identity (origin, bucket, name). The identity
is derived with Django app awareness, falling back to class attributes or explicit
overrides.

The decorator supports both no-argument and argument forms, allowing flexible usage
patterns while ensuring consistent prompt identity and registration.
"""
from __future__ import annotations

import logging
import warnings
from collections.abc import Callable
from typing import Type, Optional, overload, Any

from simcore_ai.promptkit import PromptSection, PromptRegistry
from simcore_ai_django.identity import derive_django_identity_for_class

logger = logging.getLogger(__name__)


def _ensure_identity(
        cls: Type[PromptSection],
        origin: Optional[str] = None,
        bucket: Optional[str] = None,
        name: Optional[str] = None,
) -> None:
    """
    Ensure that a PromptSection class has its identity tuple3 (origin, bucket, name) set.

    The identity is determined according to the following precedence:
      1. Explicit parameters passed to this function (origin, bucket, name).
      2. Existing class attributes on `cls` named 'origin', 'bucket', and 'name'.
      3. If any part is missing or empty, derive the identity using Django-aware logic
         via `derive_django_identity_for_class`.

    Parameters:
        cls (Type[PromptSection]): The PromptSection subclass to set identity on.
        origin (Optional[str]): Optional override for the origin part of the identity.
        bucket (Optional[str]): Optional override for the bucket part of the identity.
        name (Optional[str]): Optional override for the name part of the identity.

    Behavior:
        - If all three parts are present and non-empty strings (from args or class attrs),
          they are assigned to the class attributes.
        - Otherwise, the identity is derived using Django app label and class naming conventions.
        - Logs the identity setting or derivation for audit/debug purposes.

    Returns:
        None. The class `cls` is mutated in-place with 'origin', 'bucket', and 'name' attributes.
    """
    current_origin = origin or getattr(cls, "origin", None)
    current_bucket = bucket or getattr(cls, "bucket", None)
    current_name = name or getattr(cls, "name", None)

    has_parts = all(
        isinstance(part, str) and part
        for part in (current_origin, current_bucket, current_name)
    )
    if has_parts:
        setattr(cls, "origin", current_origin)
        setattr(cls, "bucket", current_bucket)
        setattr(cls, "name", current_name)
        logger.info(
            "Prompt identity set for %s -> %s.%s.%s",
            cls.__name__,
            current_origin,
            current_bucket,
            current_name,
        )
        return

    org, buck, nm = derive_django_identity_for_class(
        cls,
        origin=current_origin,
        bucket=current_bucket,
        name=current_name,
    )
    setattr(cls, "origin", org)
    setattr(cls, "bucket", buck)
    setattr(cls, "name", nm)
    logger.info("Prompt identity derived for %s -> %s.%s.%s", cls.__name__, org, buck, nm)


@overload
def prompt_section(
        cls: Type[PromptSection],
) -> Type[PromptSection]:
    ...


@overload
def prompt_section(
        *,
        origin: Optional[str] = None,
        bucket: Optional[str] = None,
        name: Optional[str] = None,
) -> Callable[[Type[PromptSection]], Type[PromptSection]]:
    ...


def prompt_section(
        cls: Optional[Type[PromptSection]] = None,
        *,
        origin: Optional[str] = None,
        bucket: Optional[str] = None,
        name: Optional[str] = None,
) -> Any:
    """
    Django-aware decorator that registers a PromptSection subclass and auto-fills its identity.

    This decorator can be used in two forms:
      1. Without arguments:
         @prompt_section
         class MyPrompt(PromptSection):
             ...
      2. With optional keyword arguments to override identity parts:
         @prompt_section(origin="myapp", bucket="custom", name="MyPrompt")
         class MyPrompt(PromptSection):
             ...

    Parameters:
        cls (Optional[Type[PromptSection]]): The class being decorated (only when used without arguments).
        origin (Optional[str]): Optional origin override (usually Django app label).
        bucket (Optional[str]): Optional bucket override; defaults to "default" if not provided.
        name (Optional[str]): Optional name override; if not provided, derived from class name.

    Behavior:
        - Ensures the class has a fully specified identity tuple (origin, bucket, name),
          using explicit overrides or Django-aware derivation.
        - Registers the class with PromptRegistry.
        - Marks the class with a private attribute `_is_registered_prompt` to indicate registration.

    Returns:
        The decorated class, with identity properties set and registration completed.

    Notes:
        - We do *not* delegate to the core decorator for identity derivation here because
          we want to control the Django-aware derivation process explicitly before registration.
        - If desired, one could delegate to the core decorator *after* identity derivation
          by calling it inside this decorator after `_ensure_identity`.

    Examples:
        @prompt_section
        class MyPrompt(PromptSection):
            ...

        @prompt_section(origin="myapp", bucket="special", name="CustomPrompt")
        class CustomPrompt(PromptSection):
            ...
    """

    def decorator(inner_cls: Type[PromptSection]) -> Type[PromptSection]:
        actual_bucket = bucket or "default"
        _ensure_identity(inner_cls, origin=origin, bucket=actual_bucket, name=name)
        PromptRegistry.register(inner_cls)
        setattr(inner_cls, "_is_registered_prompt", True)
        return inner_cls

    if cls is not None:
        return decorator(cls)
    return decorator


@overload
def prompt_scenario(
        *,
        origin: Optional[str] = None,
        bucket: Optional[str] = None,
        name: Optional[str] = None,
) -> Callable[[Type[PromptSection]], Type[PromptSection]]:
    ...


@overload
def prompt_scenario(
        *,
        origin: Optional[str] = None,
        bucket: Optional[str] = None,
        name: Optional[str] = None,
) -> Callable[[Type[PromptSection]], Type[PromptSection]]:
    ...


def prompt_scenario(
        cls: Optional[Type[PromptSection]] = None,
        *,
        origin: Optional[str] = None,
        bucket: Optional[str] = None,
        name: Optional[str] = None,
) -> Any:
    # TODO implement simcore_ai_django `prompt_scenario` decorator
    warnings.warn("`prompt_scenario` decorator is not yet implemented")
    return cls
