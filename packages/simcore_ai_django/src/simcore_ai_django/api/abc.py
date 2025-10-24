# packages/simcore_ai_django/src/simcore_ai_django/api/abc.py
from __future__ import annotations

"""
Async-first abstract base classes (ABCs) for Django implementations.

These ABCs define the public, provider-agnostic surfaces that concrete
implementations should expose. They intentionally avoid importing Django ORM to
keep layering clean; subclasses may use the ORM as needed.

Conventions
----------
- **Async-first**: implement `acall` / `apersist` as the primary entry points.
- **Sync adapters**: `call` / `persist` delegate to the async methods via
  `asgiref.sync.async_to_sync` and MUST NOT be called from an async context.
- If a subclass only has sync internals, it should still implement the async
  methods and wrap its sync code using `asgiref.sync.sync_to_async(...,
  thread_sensitive=True)`.

Notes
-----
- Identity derivation/registration is handled by decorators/registries, not here.
- Validation and collision policy are enforced in the registries.
"""

from abc import ABC, abstractmethod
import asyncio
from typing import Any, Optional

from asgiref.sync import async_to_sync


def _ensure_not_in_async_adapter(method_name: str) -> None:
    """Raise at runtime if a sync adapter is invoked from an async context.

    This protects against deadlocks when calling `async_to_sync` within a running
    event loop.
    """
    try:
        # Will raise RuntimeError if not in an event loop
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError(
        f"{method_name}() is a sync adapter and must not be called from an async context; "
        f"use the async method instead."
    )


class BaseCodec(ABC):
    """Abstract base for codecs that persist items (DTOs, models, etc.).

    Implementations should prefer the async method (`apersist`). The sync method
    (`persist`) is provided as a convenience adapter that calls into the async
    path via `async_to_sync`.
    """

    @abstractmethod
    async def apersist(self, item: Any, *, ctx: Optional[dict] = None) -> Any:  # pragma: no cover - interface only
        """Persist a single item asynchronously.

        Subclasses may run DB work here (inside transactions as needed). The
        `ctx` dict can carry request-scoped metadata.
        """
        raise NotImplementedError

    def persist(self, item: Any, *, ctx: Optional[dict] = None) -> Any:
        """Sync adapter for `apersist` using `async_to_sync`.

        Do not call this from an async context.
        """
        _ensure_not_in_async_adapter("persist")
        return async_to_sync(self.apersist)(item, ctx=ctx)


class BaseService(ABC):
    """Abstract base for LLM-backed services (routing, inference, tools, etc.).

    Implementations should prefer the async method (`acall`). The sync method
    (`call`) is provided as a convenience adapter that calls into the async
    path via `async_to_sync`.
    """

    @abstractmethod
    async def acall(self, request: Any, *, ctx: Optional[dict] = None) -> Any:  # pragma: no cover - interface only
        """Invoke the service asynchronously and return a result.

        The `ctx` dict can carry request-scoped metadata (tenant, user, etc.).
        """
        raise NotImplementedError

    def call(self, request: Any, *, ctx: Optional[dict] = None) -> Any:
        """Sync adapter for `acall` using `async_to_sync`.

        Do not call this from an async context.
        """
        _ensure_not_in_async_adapter("call")
        return async_to_sync(self.acall)(request, ctx=ctx)


__all__ = [
    "BaseCodec",
    "BaseService",
]
