# packages/simcore_ai/src/simcore_ai/api/protocols.py
from __future__ import annotations

"""
Structural typing contracts for core artifacts.

These Protocols define the minimal method surfaces that concrete implementations
should provide. They are intentionally provider-agnostic and contain no Django
imports or assumptions.

Conventions
----------
- Public APIs are **async-first**. Implementations should provide the async
  methods as primary entry points (`acall`, `apersist`), and may offer sync
  adapters (`call`, `persist`) that delegate via `async_to_sync` when needed.
- Callers can type against these Protocols to accept any object that "quacks"
  like the interface, regardless of inheritance (e.g., Pydantic models or plain
  classes are fine).

Note: These are *contracts*, not default logic. Default behavior belongs in ABCs
on the Django layer (e.g., simcore_ai_django.api.abc).
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CodecProto(Protocol):
    """
    Contract for codecs that persist model/DTO items.

    Implementations should prefer the async path (`apersist`). The sync path
    (`persist`) may be an adapter that calls into the async method.
    """

    async def apersist(self, item: Any, *, ctx: dict | None = None) -> Any:
        ...

    def persist(self, item: Any, *, ctx: dict | None = None) -> Any:
        ...


@runtime_checkable
class LLMServiceProto(Protocol):
    """
    Contract for LLM-backed services (routing, invocation, tools, etc.).

    Implementations should prefer the async path (`acall`). The sync path
    (`call`) may be an adapter that calls into the async method.
    """

    async def acall(self, request: Any) -> Any:
        ...

    def call(self, request: Any) -> Any:
        ...


__all__ = [
    "CodecProto",
    "LLMServiceProto",
]
