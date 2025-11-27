# simcore_ai/schemas/compiler.py

"""Legacy schema compiler and adapter registry.

This module is kept for backwards compatibility while schema adaptation moves
into codec-local `SchemaAdapter` lists on `BaseCodec` subclasses.

New code should configure schema adaptation via `schema_adapters` on
provider-specific codec classes instead of using this global registry.
"""
import warnings

warnings.warn("simcore_ai.schemas.compiler is deprecated; use codecs instead.", DeprecationWarning, stacklevel=2)

raise DeprecationWarning("simcore_ai.schemas.compiler is deprecated; use codecs instead.")

import logging
from copy import deepcopy
from collections.abc import Callable
from typing import Union, Type, Literal

logger = logging.getLogger(__name__)

ProviderName = Literal["openai", "anthropic", "mistral"]


# Legacy provider-wide adapter registry --------------------------------------
_REGISTRY: dict[ProviderName, list[tuple[int, SchemaAdapter]]] = {}


def register_adapter(provider_name: ProviderName, adapter: SchemaAdapter, order: int = 100) -> None:
    """DEPRECATED: register a SchemaAdapter for this provider.

    This maintains a global adapter registry per provider to support legacy
    call sites that still use the `schema_adapter` decorator and
    `compile_schema(...)` pipeline.

    New code should prefer configuring codec-local `schema_adapters` lists on
    provider-specific codec classes instead of registering adapters here.
    """
    warnings.warn(
        "simcore_ai.schemas.compiler.register_adapter is deprecated; "
        "prefer codec-local `schema_adapters` on codecs instead.",
        DeprecationWarning,
    )
    _REGISTRY.setdefault(provider_name, []).append((order, adapter))


def schema_adapter(provider_name: ProviderName, *, order: int = 100):
    """DEPRECATED decorator for registering schema adapters.

    This decorator supports both class-based adapters implementing
    `adapt(self, schema: dict) -> dict` and simple functions
    `adapt(schema: dict) -> dict`.

    New code should instantiate adapters explicitly and attach them to
    `schema_adapters` on codec classes instead of relying on this global
    registry.
    """

    def _register(target: Union[Type[SchemaAdapter], Callable[[dict], dict]]):
        # Class-based adapter
        if isinstance(target, type):
            instance = target()  # type: ignore[call-arg]
            register_adapter(provider_name, instance, order=order)
            return target

        # Function-based adapter
        if callable(target):
            class _FuncAdapter:
                def adapt(self, schema: dict) -> dict:
                    return target(schema)  # type: ignore[misc]

            register_adapter(provider_name, _FuncAdapter(), order=order)
            return target

        raise TypeError("@schema_adapter target must be a class or callable")

    return _register


def compile_schema(schema: dict, *, provider: ProviderName) -> dict:
    """DEPRECATED: compile a schema for a given provider.

    Runs all registered adapters for the provider (in ascending order) and
    returns the transformed schema. This exists solely for legacy callers.

    New code should configure schema adaptation via codec-local
    `schema_adapters` lists and the `BaseCodec.adapt_schema(...)` pipeline.
    """
    warnings.warn(
        "simcore_ai.schemas.compiler.compile_schema is deprecated; "
        "prefer codec-local schema adaptation on codecs.",
        DeprecationWarning,
    )
    out = deepcopy(schema)
    for _, adapter in sorted(_REGISTRY.get(provider, []), key=lambda t: t[0]):
        out = adapter.adapt(out)
    return out
