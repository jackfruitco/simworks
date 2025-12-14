"""Small registry used by the Celery-like app lifecycle."""

from __future__ import annotations

from threading import RLock
from typing import Any, Dict, Iterable, Iterator

from orchestrai.components.services.service import BaseService


class Registry:
    def __init__(self) -> None:
        self._items: Dict[str, Any] = {}
        self._lock = RLock()
        self._frozen = False

    def register(self, name: str, obj: Any) -> None:
        with self._lock:
            if self._frozen:
                raise RuntimeError("Registry is frozen")
            if name not in self._items:
                self._items[name] = obj

    def get(self, name: str) -> Any:
        with self._lock:
            return self._items[name]

    def all(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._items)

    def freeze(self) -> None:
        with self._lock:
            self._frozen = True

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._items

    def __iter__(self) -> Iterator[tuple[str, Any]]:  # pragma: no cover - convenience
        return iter(self._items.items())


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

