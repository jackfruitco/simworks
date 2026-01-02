"""Registry for persistence handler components."""

import logging
from typing import Any
from orchestrai.types import Response
from orchestrai_django.components.persistence import BasePersistenceHandler
from orchestrai.registry import ComponentRegistry

logger = logging.getLogger(__name__)


class PersistenceHandlerRegistry(ComponentRegistry):
    """
    Registry for persistence handler components.

    Routes responses to appropriate handlers based on (namespace, schema_identity)
    with fallback to ("core", schema_identity) for shared handlers.

    Example:
        registry = PersistenceHandlerRegistry()
        registry.register(PatientInitialPersistence)

        # Routes to appropriate handler
        result = await registry.persist(response)
    """

    def __init__(self):
        # Initialize parent registry (provides _lock, _frozen, _store, _coerce)
        super().__init__()

        # Key: (namespace, schema_identity_str)
        # Value: Handler class
        self._handlers: dict[tuple[str, str], type[BasePersistenceHandler]] = {}

    def register(self, handler_cls: type[BasePersistenceHandler]) -> None:
        """
        Register a persistence handler.

        Extracts namespace from handler.identity.namespace and
        schema_identity from handler.schema.identity.as_str.

        Args:
            handler_cls: Persistence handler class to register

        Raises:
            ValueError: If handler is missing identity or schema
        """
        if not hasattr(handler_cls, "identity"):
            raise ValueError(
                f"{handler_cls.__name__} missing identity attribute"
            )

        if not hasattr(handler_cls, "schema") or handler_cls.schema is None:
            raise ValueError(
                f"{handler_cls.__name__} missing schema attribute"
            )

        namespace = handler_cls.identity.namespace
        schema_identity = handler_cls.schema.identity.as_str
        key = (namespace, schema_identity)

        if key in self._handlers:
            logger.warning(
                f"Overriding persistence handler for {key}: "
                f"{self._handlers[key].__name__} → {handler_cls.__name__}"
            )

        self._handlers[key] = handler_cls
        logger.info(
            f"Registered persistence handler: ({namespace}, {schema_identity}) "
            f"→ {handler_cls.__name__}"
        )

    def get(
        self, namespace: str, schema_identity: str
    ) -> type[BasePersistenceHandler] | None:
        """
        Get handler class for (namespace, schema_identity).

        Args:
            namespace: App namespace (e.g., "chatlab")
            schema_identity: Full schema identity string

        Returns:
            Handler class or None if not found
        """
        return self._handlers.get((namespace, schema_identity))

    async def persist(self, response: Response) -> Any:
        """
        Route response to appropriate handler and execute persistence.

        Fallback chain:
            1. (response.namespace, schema_identity) - App-specific handler
            2. ("core", schema_identity) - Core fallback handler
            3. None - Log debug and skip

        Args:
            response: Full Response object with structured_data populated

        Returns:
            Domain object created by handler, or None if no handler found

        Raises:
            Any exception raised by the handler's persist() method
        """
        namespace = response.namespace
        schema_id = response.execution_metadata.get("schema_identity")

        if not namespace or not schema_id:
            logger.warning(
                "Response missing namespace or schema_identity, skipping persistence"
            )
            return None

        # Try app-specific handler
        handler_cls = self.get(namespace, schema_id)
        if handler_cls:
            logger.debug(
                f"Using app-specific handler: ({namespace}, {schema_id})"
            )
            handler = handler_cls()
            return await handler.persist(response)

        # Fallback to core handler
        handler_cls = self.get("core", schema_id)
        if handler_cls:
            logger.debug(
                f"Using core fallback handler: (core, {schema_id})"
            )
            handler = handler_cls()
            return await handler.persist(response)

        # No handler found - skip with debug log
        logger.debug(
            f"No persistence handler for ({namespace}, {schema_id}), skipping"
        )
        return None

    def count(self) -> int:
        """Return number of registered handlers."""
        return len(self._handlers)

    def items(self):
        """Return all registered handlers as (key, handler_cls) tuples."""
        return self._handlers.items()

    def clear(self):
        """Clear all registered handlers (useful for testing)."""
        self._handlers.clear()
