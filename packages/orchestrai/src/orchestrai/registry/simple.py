"""Small registry used by the Celery-like app lifecycle."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterator, Sequence

from orchestrai.components.services.service import BaseService
from orchestrai.registry.base import BaseRegistry
from orchestrai.registry.exceptions import RegistryFrozenError


def _coerce_to_str(value: Any) -> str:
    return str(value)


class Registry(BaseRegistry[str, Any]):
    def __init__(self) -> None:
        super().__init__(coerce_key=_coerce_to_str)
        self._finalize_callbacks: list[Callable[[Any], None]] = []

    def register(self, name: str, obj: Any) -> None:
        key = self._coerce(name)
        with self._lock:
            if self._frozen:
                raise RegistryFrozenError("Registry is frozen")
            if key not in self._store:
                self._store[key] = obj

    def get(self, name: str) -> Any:
        return super().get(name)

    def all(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._store)

    def add_finalize_callback(self, callback: Callable[[Any], None]) -> Callable[[Any], None]:
        """Register a callback executed during :meth:`finalize`.

        Registries manage their own freeze cycle; attaching callbacks here keeps
        shared decorators co-located with registry mutation without forcing the
        app to understand every registry's lifecycle.
        """

        self._finalize_callbacks.append(callback)
        return callback

    def finalize(self, *, app: Any | None = None) -> None:
        """Run registry-level finalizers then freeze the registry."""

        callbacks: Sequence[Callable[[Any], None]]
        callbacks = tuple(self._finalize_callbacks)
        for callback in callbacks:
            callback(app or self)
        self.freeze()

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return self._coerce(name) in self._store

    def __iter__(self) -> Iterator[tuple[str, Any]]:  # pragma: no cover - convenience
        return iter(self._store.items())


class ServicesRegistry(Registry):
    """Registry with helpers to run registered services.

    Exposes convenience methods that mirror the old ``Service.task`` helpers:
    ``schedule``/``start`` for sync execution and ``aschedule``/``astart`` for
    async execution. All helpers accept either a service class, an instance, or
    a registered name.
    """

    def _resolve_service(self, service: str | type[BaseService] | BaseService):
        if isinstance(service, str):
            return self.get(service)
        return service

    def _build_instance(self, service: str | type[BaseService] | BaseService, context: dict) -> BaseService:
        svc = self._resolve_service(service)
        if isinstance(svc, type) and issubclass(svc, BaseService):
            return svc.using(context=context)
        if isinstance(svc, BaseService):
            svc.context.update(context)
            return svc
        raise TypeError(f"Unsupported service spec: {service!r}")

    def start(self, service: str | type[BaseService] | BaseService, /, **context):
        """Run the given service synchronously."""

        instance = self._build_instance(service, context)
        return instance.execute()

    def schedule(self, service: str | type[BaseService] | BaseService, /, **context):
        """Alias for :meth:`start` for compatibility with enqueue semantics."""

        return self.start(service, **context)

    async def astart(self, service: str | type[BaseService] | BaseService, /, **context):
        """Run the given service asynchronously."""

        instance = self._build_instance(service, context)
        return await instance.aexecute()

    async def aschedule(self, service: str | type[BaseService] | BaseService, /, **context):
        """Alias for :meth:`astart` mirroring ``schedule``."""

        return await self.astart(service, **context)
