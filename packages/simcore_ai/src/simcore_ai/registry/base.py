# simcore_ai/registry/base.py
from __future__ import annotations

import logging
from threading import RLock
from typing import Callable, Generic, TypeVar, Any, Tuple, Dict

from asgiref.sync import async_to_sync

from simcore_ai.components import ComponentNotFoundError
from simcore_ai.registry.exceptions import RegistryDuplicateError, RegistryCollisionError, RegistryFrozenError

logger = logging.getLogger(__name__)

K = TypeVar("K")
T = TypeVar("T")


class BaseRegistry(Generic[K, T]):
    """Framework-agnostic registry keyed by an identity-like key K storing classes of T."""

    def __init__(self, *, coerce_key: Callable[[Any], K]) -> None:
        self._coerce = coerce_key
        self._lock = RLock()
        self._store: Dict[K, type[T]] = {}
        self._frozen = False

    def _register(self, cls: type[T]) -> None:
        """Internal: register a component class into the store."""
        if not hasattr(cls, "identity"):
            raise ValueError(f"Component {cls} has no identity")
        key = self._coerce(getattr(cls, "identity"))
        with self._lock:
            if self._frozen:
                raise RegistryFrozenError("Registry is frozen")
            if key in self._store:
                if self._store[key] is cls:
                    raise RegistryDuplicateError(f"Component already registered: {key}")
                raise RegistryCollisionError(
                    f"Key already registered to different instance: {key}"
                )
            self._store[key] = cls

    async def aregister(self, cls: type[T], *, strict: bool = False) -> None:
        """
        Async-first registration.

        Registers a component class keyed by its identity.
        If `strict=True`, duplicate registrations raise; otherwise they are logged and ignored.
        """
        try:
            self._register(cls)
        except RegistryDuplicateError:
            if strict:
                raise
            logger.debug("Duplicate registration ignored: %s", cls)

    def register(self, cls: type[T], *, strict: bool = False) -> None:
        """
        Sync wrapper for `aregister`.

        Blocks until registration completes.
        """
        async_to_sync(self.aregister)(cls, strict=strict)

    async def aget(self, key: Any) -> type[T]:
        """
        Async lookup.

        Returns the registered component class for `key` or raises ComponentNotFoundError.
        """
        k = self._coerce(key)
        with self._lock:
            try:
                return self._store[k]
            except KeyError as err:
                raise ComponentNotFoundError(
                    f"Component with identity {key!r} not found or not registered"
                ) from err

    def get(self, key: Any) -> type[T]:
        """
        Sync wrapper for `aget`.

        Blocks until lookup completes.
        """
        return async_to_sync(self.aget)(key)

    async def atry_get(self, key: Any) -> type[T] | None:
        """
        Async safe lookup.

        Returns the component class if found, otherwise None.
        """
        try:
            return await self.aget(key)
        except ComponentNotFoundError:
            return None

    def try_get(self, key: Any) -> type[T] | None:
        """
        Sync wrapper for `atry_get`.

        Returns the component class if found, otherwise None.
        """
        return async_to_sync(self.atry_get)(key)

    async def aall(self) -> Tuple[type[T], ...]:
        """
        Async: return all registered component classes as a tuple.
        """
        with self._lock:
            return tuple(self._store.values())

    def all(self) -> Tuple[type[T], ...]:
        """
        Sync wrapper for `aall`.
        """
        return async_to_sync(self.aall)()

    async def afilter(self, pred) -> Tuple[type[T], ...]:
        """
        Async: return all registered component classes matching predicate `pred`.
        """
        with self._lock:
            return tuple(c for c in self._store.values() if pred(c))

    def filter(self, pred) -> Tuple[type[T], ...]:
        """
        Sync wrapper for `afilter`.
        """
        return async_to_sync(self.afilter)(pred)

    async def aclear(self) -> None:
        """
        Async: clear the registry if not frozen.
        """
        with self._lock:
            if self._frozen:
                raise RegistryFrozenError("Registry is frozen")
            self._store.clear()

    def clear(self) -> None:
        """
        Sync wrapper for `aclear`.
        """
        async_to_sync(self.aclear)()

    async def afreeze(self) -> None:
        """
        Async: mark the registry as frozen (no further mutations).
        """
        with self._lock:
            self._frozen = True

    def freeze(self) -> None:
        """
        Sync wrapper for `afreeze`.
        """
        async_to_sync(self.afreeze)()
