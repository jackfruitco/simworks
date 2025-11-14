# simcore_ai/components/base.py
from __future__ import annotations

import logging
from abc import ABC
from typing import TYPE_CHECKING, ClassVar, TypeVar
from uuid import UUID, uuid4

from asgiref.sync import async_to_sync

from simcore_ai.components import ComponentNotFoundError
from simcore_ai.identity import IdentityLike
from simcore_ai.registry.exceptions import RegistryNotFoundError

if TYPE_CHECKING:
    from simcore_ai.registry import BaseRegistry

logger = logging.getLogger(__name__)

__all__ = ["BaseComponent"]

T = TypeVar("T")


class BaseComponent(ABC):
    """Abstract base class for all SimCore components."""

    # Markers / metadata
    abstract: ClassVar[bool] = True
    kind: ClassVar[BaseComponent]

    def __init__(self) -> None:
        self.uuid: UUID = uuid4()

    def __post_init__(self) -> None:
        pass

    # ----------------------------------------------------------------------------------
    # Registry accessors
    # ----------------------------------------------------------------------------------
    @classmethod
    async def aget_registry(cls) -> BaseRegistry:
        from simcore_ai.registry.singletons import get_registry_for

        registry = get_registry_for(cls)
        if registry is None:
            raise RegistryNotFoundError(f"No registry mapped for {cls.__name__}")
        return registry

    @classmethod
    def get_registry(cls) -> BaseRegistry:
        return async_to_sync(cls.aget_registry)()

    @classmethod
    async def atry_get_registry(cls) -> BaseRegistry | None:
        """Async-safe registry accessor. Returns None if not available."""
        try:
            return await cls.aget_registry()
        except (RegistryNotFoundError, NotImplementedError):
            logger.debug("No registry found for %s", cls.__name__)
            return None

    @classmethod
    def try_get_registry(cls) -> BaseRegistry | None:
        """Sync wrapper for `atry_get_registry`."""
        return async_to_sync(cls.atry_get_registry)()

    @classmethod
    async def aget(cls, ident: IdentityLike) -> type[BaseComponent]:
        """
        Async lookup: resolve a registered component type by identity.
        """
        registry = await cls.aget_registry()
        if registry is None:
            raise RegistryNotFoundError(f"No registry found for {cls.__name__}")

        component_ = await registry.aget(ident)  # type: ignore[attr-defined]
        if component_ is None:
            raise ComponentNotFoundError(f"{ident} not found in registry {cls.__name__}")

        return component_

    @classmethod
    def get(cls, ident: IdentityLike) -> type[BaseComponent]:
        """Sync wrapper for `aget`."""
        return async_to_sync(cls.aget)(ident)

    @classmethod
    async def atry_get(cls, ident: IdentityLike) -> type[BaseComponent] | None:
        """Async-safe lookup. Returns None instead of raising."""
        try:
            return await cls.aget(ident)
        except ComponentNotFoundError:
            logger.debug("atry_get: no match for %s (%s)", ident, cls.__name__)
            return None
        except RegistryNotFoundError:
            logger.debug("atry_get: no registry for %s", cls.__name__)
            return None

    @classmethod
    def try_get(cls, ident: IdentityLike) -> type[BaseComponent] | None:
        """Sync wrapper for `atry_get`."""
        return async_to_sync(cls.atry_get)(ident)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} uuid={self.uuid}>"