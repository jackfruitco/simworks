"""Registry components for orchestrai_django."""

from .persistence import PersistenceHandlerRegistry

__all__ = ["PersistenceHandlerRegistry", "get_persistence_registry"]

# Singleton instance
_persistence_registry: PersistenceHandlerRegistry | None = None


def get_persistence_registry() -> PersistenceHandlerRegistry | None:
    """Get the global persistence handler registry.

    Returns None if not yet initialized.
    """
    return _persistence_registry


def init_persistence_registry() -> PersistenceHandlerRegistry:
    """Initialize and return the global persistence handler registry."""
    global _persistence_registry
    if _persistence_registry is None:
        _persistence_registry = PersistenceHandlerRegistry()
    return _persistence_registry
