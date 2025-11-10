# simcore_ai/components/base.py
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Any, TypeVar
from uuid import UUID, uuid4

from simcore_ai.components import ComponentNotFoundError
from simcore_ai.identity import IdentityLike
from simcore_ai.registry.exceptions import RegistryNotFoundError

from asgiref.sync import async_to_sync

if TYPE_CHECKING:
    from simcore_ai.registry import BaseRegistry

logger = logging.getLogger(__name__)

__all__ = ["BaseComponent"]

T = TypeVar("T")


@dataclass
class BaseComponent(ABC):
    """Abstract base class for all SimCore components.

    Async-first lifecycle with sync wrappers:
      - asetup -> arun -> ateardown (primary)
      - setup -> run -> teardown -> execute (sync wrappers)
    """
    abstract: ClassVar[bool] = True
    uuid: UUID = field(default_factory=uuid4, init=False, repr=False)

    # -------------------------------------------------------------------------------------
    # ---------- class methods ------------------------------------------------------------
    # -------------------------------------------------------------------------------------
    @classmethod
    async def aget_registry(cls) -> BaseRegistry:
        """
        Async registry accessor.

        Subclasses must override this to return the registry responsible for this component type.
        """
        raise NotImplementedError(f"{cls.__name__} must implement aget_registry()")

    @classmethod
    def get_registry(cls) -> BaseRegistry:
        """
        Sync wrapper for `aget_registry`.

        Intended for use in sync-only contexts such as `__init_subclass__`
        or legacy callers.
        """
        return async_to_sync(cls.aget_registry)()

    @classmethod
    async def atry_get_registry(cls) -> BaseRegistry | None:
        """
        Async-safe registry accessor.

        Returns the registry for this component type, or None if not available.
        """
        try:
            return await cls.aget_registry()
        except (RegistryNotFoundError, NotImplementedError):
            logger.debug("No registry found for %s", cls.__name__)
            return None

    @classmethod
    def try_get_registry(cls) -> BaseRegistry | None:
        """
        Sync wrapper for `atry_get_registry`.

        Returns the registry for this component type, or None.
        """
        return async_to_sync(cls.atry_get_registry)()

    @classmethod
    async def aget(cls, ident: IdentityLike) -> type["BaseComponent"]:
        """
        Async lookup: resolve a registered component type by identity.

        Raises:
            RegistryNotFoundError if no registry is configured.
            ComponentNotFoundError if the component is not registered.
        """
        registry = await cls.aget_registry()
        if registry is None:
            raise RegistryNotFoundError(f"No registry found for {cls.__name__}")

        component_ = await registry.aget(ident)  # type: ignore[attr-defined]

        if component_ is None:
            raise ComponentNotFoundError(f"{ident} not found in registry {cls.__name__}")

        return component_

    @classmethod
    def get(cls, ident: IdentityLike) -> type["BaseComponent"]:
        """
        Sync wrapper for `aget`.

        Resolves the registered component type or raises on failure.
        """
        return async_to_sync(cls.aget)(ident)

    @classmethod
    async def atry_get(cls, ident: IdentityLike) -> type["BaseComponent"] | None:
        """
        Async-safe lookup.

        Returns the registered component type if found, otherwise None.
        """
        try:
            return await cls.aget(ident)
        except ComponentNotFoundError:
            logger.debug("atry_get: no match for %s (%s)", ident, cls.__name__)
            return None
        except RegistryNotFoundError:
            logger.debug("atry_get: no registry for %s", cls.__name__)
            return None

    @classmethod
    def try_get(cls, ident: IdentityLike) -> type["BaseComponent"] | None:
        """
        Sync wrapper for `atry_get`.

        Returns the registered component type if found, otherwise None.
        """
        return async_to_sync(cls.atry_get)(ident)

    # -------------------------------------------------------------------------------------
    # ---------- abstract class methods ---------------------------------------------------
    # -------------------------------------------------------------------------------------

    # -------------------------------------------------------------------------------------
    # ---------- async lifecycle (primary) ------------------------------------------------
    # -------------------------------------------------------------------------------------
    async def asetup(self, *, context: dict[str, Any] | None = None) -> None:
        """Async setup hook. Override to allocate resources or prepare context."""
        return None

    @abstractmethod
    async def arun(self, *args: Any, **kwargs: Any) -> T:
        """Async work hook. Subclasses must implement core logic."""
        raise NotImplementedError

    async def ateardown(self, *, context: dict[str, Any] | None = None) -> None:
        """Async teardown hook. Override to release resources. Default no-op."""
        return None

    async def aexecute(
        self,
        *args: Any,
        context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> T:
        """Async execution template (asetup -> arun -> ateardown)."""
        try:
            await self.asetup(context=context)
            return await self.arun(*args, **kwargs)
        finally:
            await self.ateardown(context=context)

    # -------------------------------------------------------------------------------------
    # ---------- sync wrappers (convenience) ---------------------------------------------
    # -------------------------------------------------------------------------------------
    def setup(self, *, context: dict[str, Any] | None = None) -> None:
        """Sync wrapper for asetup(); blocks until completion."""
        async_to_sync(self.asetup)(context=context)

    def run(self, *args: Any, **kwargs: Any) -> T:
        """Sync wrapper for arun(); blocks until completion."""
        return async_to_sync(self.arun)(*args, **kwargs)

    def teardown(self, *, context: dict[str, Any] | None = None) -> None:
        """Sync wrapper for ateardown(); blocks until completion."""
        async_to_sync(self.ateardown)(context=context)

    def execute(
        self,
        *args: Any,
        context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> T:
        """Sync execution template (setup -> run -> teardown)."""
        try:
            self.setup(context=context)
            return self.run(*args, **kwargs)
        finally:
            self.teardown(context=context)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} uuid={self.uuid}>"
