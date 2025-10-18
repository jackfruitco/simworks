# simcore_ai/schemas/compiler.py
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Callable, Union, Type, Protocol, Literal

logger = logging.getLogger(__name__)

ProviderName = Literal["openai", "anthropic", "mistral"]


class SchemaAdapter(Protocol):
    """Base class for schema adapters.

    Schema adapters are used to transform a schema for a given provider.
    """

    def adapt(self, schema: dict) -> dict: ...


_REGISTRY: dict[ProviderName, list[tuple[int, SchemaAdapter]]] = {}


def register_adapter(provider_name: ProviderName, adapter: SchemaAdapter, order: int = 100) -> None:
    """Register a SchemaAdapter for this provider (ordered; lower runs first)."""
    _REGISTRY.setdefault(provider_name, []).append((order, adapter))


def schema_adapter(provider_name: ProviderName, *, order: int = 100):
    """
    Decorate a class with `adapt(self, schema)->dict` OR a function `adapt(schema)->dict`
    to auto-register it as a schema adapter for the provider.
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
    """Compile a schema for a given provider by running registered adapters in order."""
    out = deepcopy(schema)
    for _, adapter in sorted(_REGISTRY.get(provider, []), key=lambda t: t[0]):
        out = adapter.adapt(out)
    return out
