"""Registry for persistence handler components.

Simplified architecture for Pydantic AI:
- Handlers are registered by schema class (module.classname)
- No identity needed for handlers or schemas
- Lookup by schema class at persist time
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PersistenceHandlerRegistry:
    """
    Registry for persistence handler components.

    Routes responses to handlers based on schema class.
    No identity system required - uses schema module.classname as key.

    Example:
        registry = PersistenceHandlerRegistry()
        registry.register(PatientInitialPersistence)

        # Routes by schema class
        handler = registry.get_for_schema(PatientInitialOutputSchema)
        result = await handler.persist(response)
    """

    def __init__(self):
        # Key: schema class qualified name (module.classname)
        # Value: Handler class
        self._handlers: dict[str, type] = {}

        # Also keep direct class reference for isinstance checks
        self._schema_to_handler: dict[type, type] = {}

    def _schema_key(self, schema_cls: type) -> str:
        """Get registry key for a schema class."""
        return f"{schema_cls.__module__}.{schema_cls.__name__}"

    def register(self, handler_cls: type) -> None:
        """
        Register a persistence handler.

        Args:
            handler_cls: Persistence handler class with 'schema' attribute

        Raises:
            ValueError: If handler is missing schema attribute
        """
        schema_cls = getattr(handler_cls, "schema", None)
        if schema_cls is None:
            raise ValueError(
                f"{handler_cls.__name__} missing 'schema' class attribute"
            )

        key = self._schema_key(schema_cls)

        if key in self._handlers:
            logger.warning(
                f"Overriding persistence handler for {key}: "
                f"{self._handlers[key].__name__} → {handler_cls.__name__}"
            )

        self._handlers[key] = handler_cls
        self._schema_to_handler[schema_cls] = handler_cls

        logger.info(
            f"Registered persistence handler: {key} → {handler_cls.__name__}"
        )

    def get_for_schema(self, schema_cls: type) -> type | None:
        """
        Get handler class for a schema class.

        Args:
            schema_cls: The Pydantic model class

        Returns:
            Handler class or None if not found
        """
        # Try direct lookup first
        if schema_cls in self._schema_to_handler:
            return self._schema_to_handler[schema_cls]

        # Fall back to string key (for deserialized lookups)
        key = self._schema_key(schema_cls)
        return self._handlers.get(key)

    def get_by_name(self, schema_name: str) -> type | None:
        """
        Get handler class by schema qualified name.

        Args:
            schema_name: Schema module.classname string

        Returns:
            Handler class or None if not found
        """
        return self._handlers.get(schema_name)

    async def persist(
        self,
        *,
        schema_cls: type | None = None,
        schema_name: str | None = None,
        data: Any,
        context: dict[str, Any],
    ) -> Any:
        """
        Route to appropriate handler and execute persistence.

        Args:
            schema_cls: Schema class (preferred)
            schema_name: Schema module.classname (fallback)
            data: Validated response data (Pydantic model instance or dict)
            context: Execution context (simulation_id, etc.)

        Returns:
            Domain object created by handler, or None if no handler found
        """
        # Find handler
        handler_cls = None
        lookup_key = None

        if schema_cls is not None:
            handler_cls = self.get_for_schema(schema_cls)
            lookup_key = self._schema_key(schema_cls)
        elif schema_name is not None:
            handler_cls = self.get_by_name(schema_name)
            lookup_key = schema_name

        if handler_cls is None:
            logger.debug(f"No persistence handler for {lookup_key}, skipping")
            return None

        logger.debug(f"Using handler {handler_cls.__name__} for {lookup_key}")

        # Instantiate and execute
        handler = handler_cls()
        return await handler.persist(data=data, context=context)

    def count(self) -> int:
        """Return number of registered handlers."""
        return len(self._handlers)

    def items(self):
        """Return all registered handlers as (schema_name, handler_cls) tuples."""
        return self._handlers.items()

    def clear(self):
        """Clear all registered handlers (useful for testing)."""
        self._handlers.clear()
        self._schema_to_handler.clear()
