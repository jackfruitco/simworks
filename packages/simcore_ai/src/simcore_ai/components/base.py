# simcore_ai/components/base.py
import logging
from abc import ABC
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID, uuid4

from .exceptions import ComponentNotFoundError
from ..identity import IdentityLike

if TYPE_CHECKING:
    from simcore_ai.registry import BaseRegistry

logger = logging.getLogger(__name__)

__all__ = ["BaseComponent"]


class BaseComponent(ABC):
    """Abstract base class for all SimCore components."""

    # Markers / metadata
    abstract: ClassVar[bool] = True
    kind: ClassVar[str]

    def __init__(self) -> None:
        self.uuid: UUID = uuid4()

    def __post_init__(self) -> None:
        pass

    # ----------------------------------------------------------------------------------
    # Registry accessors
    # ----------------------------------------------------------------------------------
    @classmethod
    def get_registry(cls) -> BaseRegistry:
        from simcore_ai.registry.singletons import get_registry_for

        registry = get_registry_for(cls)
        if registry is None:
            from ..registry.exceptions import RegistryNotFoundError

            raise RegistryNotFoundError(f"No registry mapped for {cls.__name__}")
        return registry

    @classmethod
    async def aget_registry(cls) -> BaseRegistry:
        return cls.get_registry()

    @classmethod
    def try_get_registry(cls) -> BaseRegistry | None:
        """Return the registry for this component class, or None if not available."""
        from ..registry.exceptions import RegistryNotFoundError

        try:
            return cls.get_registry()
        except (RegistryNotFoundError, NotImplementedError):
            logger.debug("No registry found for %s", cls.__name__)
            return None

    @classmethod
    async def atry_get_registry(cls) -> BaseRegistry | None:
        """Async-safe wrapper around `try_get_registry`."""
        return cls.try_get_registry()

    @classmethod
    def get(cls, ident: IdentityLike) -> type[BaseComponent]:
        """Resolve a registered component type by identity (sync)."""
        registry = cls.get_registry()

        component_ = registry.get(ident)  # type: ignore[attr-defined]
        if component_ is None:
            raise ComponentNotFoundError(f"{ident} not found in registry {cls.__name__}")

        return component_

    @classmethod
    async def aget(cls, ident: IdentityLike) -> type[BaseComponent]:
        """
        Async lookup: resolve a registered component type by identity.

        Delegates to the registry's async API.
        """
        registry = await cls.aget_registry()

        component_ = await registry.aget(ident)  # type: ignore[attr-defined]
        if component_ is None:
            raise ComponentNotFoundError(f"{ident} not found in registry {cls.__name__}")

        return component_

    @classmethod
    def try_get(cls, ident: IdentityLike) -> type[BaseComponent] | None:
        """Sync-safe lookup. Returns None instead of raising."""
        from ..registry.exceptions import RegistryNotFoundError

        try:
            return cls.get(ident)
        except ComponentNotFoundError:
            logger.debug("atry_get: no match for %s (%s)", ident, cls.__name__)
            return None
        except RegistryNotFoundError:
            logger.debug("atry_get: no registry for %s", cls.__name__)
            return None

    @classmethod
    async def atry_get(cls, ident: IdentityLike) -> type[BaseComponent] | None:
        """Async-safe lookup. Returns None instead of raising."""
        from ..registry.exceptions import RegistryNotFoundError

        try:
            return await cls.aget(ident)
        except ComponentNotFoundError:
            logger.debug("atry_get: no match for %s (%s)", ident, cls.__name__)
            return None
        except RegistryNotFoundError:
            logger.debug("atry_get: no registry for %s", cls.__name__)
            return None

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} uuid={self.uuid}>"
