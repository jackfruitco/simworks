# orchestrai/registry/base.py


import logging
from threading import RLock
from typing import Callable, Generic, TypeVar, Any, overload, Literal

from asgiref.sync import sync_to_async

from .exceptions import RegistryDuplicateError, RegistryCollisionError, RegistryFrozenError, RegistryLookupError
from ..identity.identity import Identity
from ..components.exceptions import ComponentNotFoundError

logger = logging.getLogger(__name__)

K = TypeVar("K")
T = TypeVar("T")


class BaseRegistry(Generic[K, T]):
    """Framework-agnostic registry keyed by an identity-like key K storing classes of T."""

    def __init__(self, *, coerce_key: Callable[[Any], K]) -> None:
        self._coerce = coerce_key
        self._lock = RLock()
        self._store: dict[K, type[T]] = {}
        self._frozen = False

    def _register(self, cls: type[T]) -> None:
        """Internal: register a component class into the store."""
        key = self._coerce(cls)

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

    # --- registration ---

    def register(self, cls: type[T], *, strict: bool = False) -> None:
        """
        Registers a class in the registry, handling duplicates based on the strict mode.

        The method attempts to register the given class. If the class is already registered
        and `strict` mode is enabled, a `RegistryDuplicateError` is raised. When `strict`
        is disabled, duplicate registrations are ignored, and a debug message is logged.

        :param cls: The class to be registered.
        :param strict: Boolean flag indicating whether duplicate registration should raise
                       an error (True) or be ignored (False). Defaults to False.
        :return: None
        """
        try:
            self._register(cls)
        except RegistryDuplicateError:
            if strict:
                raise
            logger.debug("Duplicate registration ignored: %s", cls)

    async def aregister(self, cls: type[T], *, strict: bool = False) -> None:
        """
        Asynchronously registers a given class using the `register` method. The operation is
        performed in an asynchronous context by converting the synchronous `register`
        method into an asynchronous operation.

        :param cls: The class to be registered.
        :type cls: type[T]
        :param strict: A boolean flag indicating whether to enforce strict registration rules.
        :type strict: bool
        :return: None
        :rtype: None
        """
        return await sync_to_async(self.register)(cls, strict=strict)

    # --- retrieval ---

    def get(self, key: Any) -> type[T]:
        """
        Retrieve a component associated with the given key from the store. If
        the key does not exist in the store, a `ComponentNotFoundError` is
        raised.

        The method safely handles concurrent access to the store using a lock,
        ensuring thread-safety.

        :param key: The identity of the component to retrieve.
        :type key: Any
        :return: The component associated with the given key.
        :rtype: type[T]
        :raises RegistryLookupError: If the component with the specified
            key is not found or is not registered.
        """
        k = self._coerce(key)
        with self._lock:
            try:
                return self._store[k]
            except KeyError as err:
                raise RegistryLookupError(
                    f"Component with identity {key!r} not found or not registered"
                ) from err

    async def aget(self, key: Any) -> type[T]:
        """
        Asynchronously retrieve a component associated with the given key from the store.

        This is a thin async wrapper around `get`.
        """
        return await sync_to_async(self.get)(key)

    def try_get(self, key: Any) -> type[T] | None:
        """
        Attempts to retrieve a value associated with the given key from the object,
        returning None if the key is not found. This method leverages the `get`
        function and handles the `ComponentNotFoundError` exception internally.

        :param key: The key to retrieve a value for.
        :type key: Any
        :return: The value associated with the specified key, or None if the key is not found.
        :rtype: type[T] | None
        """
        try:
            return self.get(key)
        except ComponentNotFoundError:
            return None

    async def atry_get(self, key: Any) -> type[T] | None:
        """
        Asynchronously attempts to retrieve a value associated with the given key. If the
        key is not found, returns None instead of raising an exception.
        """
        try:
            return await self.aget(key)
        except ComponentNotFoundError:
            return None

    # --- counting ---

    def count(self) -> int:
        """Counts the number of registered components in the store."""
        with self._lock:
            return len(self._store)

    async def acount(self) -> int:
        """Asynchronously counts the number of registered components in the store."""
        return await sync_to_async(self.count)()

    # --- enumerate all entries ---
    @overload
    def items(self, *, as_str: Literal[True]) -> tuple[str, ...]:
        ...

    @overload
    def items(self, *, as_str: Literal[False] = False) -> tuple[type[T], ...]:
        ...

    def items(self, *, as_str: bool = False) -> object:
        """
        Return all registered component classes or their identity strings.

        When `as_str` is True, returns a tuple of identity strings.
        Otherwise, returns a tuple of registered classes.
        """
        with self._lock:
            if as_str:
                any_cls = next(iter(self._store.values()), None)
                if any_cls is not None and hasattr(any_cls, "identity"):
                    return tuple(cls.identity.as_str for cls in self._store.values())
            return tuple(self._store.values())

    @overload
    def all(self, *, as_str: Literal[True]) -> tuple[str, ...]:
        ...

    @overload
    def all(self, *, as_str: Literal[False] = False) -> tuple[type[T], ...]:
        ...

    def all(self, *, as_str: bool = False):
        """
        Return all registered component classes or their identity strings.

        When `as_str` is True, returns a tuple of identity strings.
        Otherwise, returns a tuple of registered classes.
        """
        return self.items(as_str=as_str)

    async def aall(self, *, as_str: bool = False):
        """Async wrapper around `all`."""
        return await sync_to_async(self.all)(as_str=as_str)

    @overload
    def keys(self) -> tuple[K, ...]: ...
    @overload
    def keys(self, *, as_csv: Literal[True]) -> str: ...
    @overload
    def keys(self, *, as_csv: Literal[False]) -> tuple[K, ...]: ...

    def keys(self, *, as_csv: bool = False):
        """
        Return all registered component keys.

        When `as_csv` is True, returns a comma-separated string of the keys for
        logging/debugging purposes. Keys are stringified via `str(key)`.
        """
        with self._lock:
            keys_tuple: tuple[K, ...] = tuple(self._store.keys())

        if as_csv:
            def to_str(k: K) -> str:
                ident = getattr(k, "as_str", None)
                return ident if isinstance(ident, str) else str(k)

            return ",".join(to_str(k) for k in keys_tuple)

        return keys_tuple

    # --- labels ---
    def labels(self) -> tuple[str, ...]:
        """Return all registered component identity strings."""
        with self._lock:
            return tuple(cls.identity.as_str for cls in self._store.values())

    async def alabels(self) -> tuple[str, ...]:
        """Async wrapper around `labels`."""
        return await sync_to_async(self.labels)()

    # --- filtering ---

    def filter(self, pred) -> tuple[type[T], ...]:
        """
        Return all registered component classes matching predicate `pred`.
        """
        with self._lock:
            return tuple(c for c in self._store.values() if pred(c))

    async def afilter(self, pred) -> tuple[type[T], ...]:
        """
        Async: return all registered component classes matching predicate `pred`.
        """
        return await sync_to_async(self.filter)(pred)

    # --- mutation / control ---

    def clear(self) -> None:
        """
        Clear the registry if not frozen.
        """
        with self._lock:
            if self._frozen:
                raise RegistryFrozenError("Registry is frozen")
            self._store.clear()

    async def aclear(self) -> None:
        """
        Async: clear the registry if not frozen.
        """
        return await sync_to_async(self.clear)()

    def freeze(self) -> None:
        """
        Mark the registry as frozen (no further mutations).
        """
        with self._lock:
            self._frozen = True

    async def afreeze(self) -> None:
        """
        Async: mark the registry as frozen (no further mutations).
        """
        return await sync_to_async(self.freeze)()


class ComponentRegistry(BaseRegistry[Identity, T]):
    """Registry specialized for Identity-keyed component classes."""

    def __init__(self) -> None:
        super().__init__(coerce_key=Identity.get_for)
