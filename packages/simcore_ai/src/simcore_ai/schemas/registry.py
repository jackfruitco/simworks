"""
This module stores response schema classes keyed by (namespace, kind, name) tuples.
It enforces uniqueness of these tuple keys by raising DuplicateResponseSchemaIdentityError on duplicates.
"""

import logging
import threading

_logger = logging.getLogger(__name__)


class DuplicateResponseSchemaIdentityError(Exception):
    """Raised when a duplicate (namespace, kind, name) key is registered with a different schema class."""


class RegistryLookupError(Exception):
    """Generic registry lookup error."""


class ResponseSchemaNotFoundError(RegistryLookupError):
    """Raised when a response schema is not found in the registry."""


class ResponseSchemaRegistry:
    _items: dict[str, type] = {}
    _lock = threading.RLock()

    @classmethod
    def _key(cls, namespace: str, kind: str, name: str) -> str:
        return f"{namespace}.{kind}.{name}"

    @classmethod
    def _identity_for_cls(cls, schema_cls: type) -> tuple[str, str, str]:
        try:
            namespace = getattr(schema_cls, "namespace")
            kind = getattr(schema_cls, "kind")
            name = getattr(schema_cls, "name")
        except AttributeError as err:
            raise ValueError(
                f"Schema class {schema_cls} must have 'namespace', 'kind', and 'name' attributes"
            ) from err
        if not all(isinstance(x, str) for x in (namespace, kind, name)):
            raise ValueError(
                f"Schema class {schema_cls} attributes 'namespace', 'kind', and 'name' must be strings"
            )
        return namespace, kind, name

    @classmethod
    def register(cls, schema_cls: type) -> None:
        namespace, kind, name = cls._identity_for_cls(schema_cls)
        key = cls._key(namespace, kind, name)
        with cls._lock:
            if key in cls._items:
                existing_cls = cls._items[key]
                if existing_cls is schema_cls:
                    # same class already registered under this key, no-op
                    return
                raise DuplicateResponseSchemaIdentityError(
                    f"Duplicate registration for key {key} with different schema classes: "
                    f"{existing_cls} vs {schema_cls}"
                )
            cls._items[key] = schema_cls
            _logger.info(f"Registered response schema {schema_cls} under key {key}")

    @classmethod
    def has(cls, namespace: str, kind: str, name: str = "default") -> bool:
        key = cls._key(namespace, kind, name)
        with cls._lock:
            return key in cls._items

    @classmethod
    def get(cls, namespace: str, kind: str, name: str = "default") -> type:
        key = cls._key(namespace, kind, name)
        with cls._lock:
            if key not in cls._items:
                _logger.warning(f"Response schema not found for key {key}")
                raise ResponseSchemaNotFoundError(f"Schema not found for key {key}")
            return cls._items[key]

    @classmethod
    def get_by_key(cls, key: str) -> type:
        with cls._lock:
            if key not in cls._items:
                _logger.warning(f"Response schema not found for key {key}")
                raise ResponseSchemaNotFoundError(f"Schema not found for key {key}")
            return cls._items[key]

    @classmethod
    def get_str(cls, dot: str) -> type:
        parts = dot.split(".")
        if len(parts) != 3:
            _logger.warning(f"Invalid schema key format: '{dot}', expected 'namespace.kind.name'")
            raise ResponseSchemaNotFoundError(
                f"Invalid schema key format: '{dot}', expected 'namespace.kind.name'"
            )
        namespace, kind, name = parts
        return cls.get(namespace, kind, name)

    @classmethod
    def require(cls, namespace: str, kind: str, name: str = "default") -> type:
        return cls.get(namespace, kind, name)

    @classmethod
    def require_str(cls, dot: str) -> type:
        return cls.get_str(dot)

    @classmethod
    def all(cls) -> dict[str, type]:
        with cls._lock:
            return dict(cls._items)

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._items.clear()
            _logger.debug("Cleared all response schemas from registry")


def register_schema(namespace: str, kind: str, name: str, schema_cls: type) -> None:
    if not hasattr(schema_cls, "namespace"):
        setattr(schema_cls, "namespace", namespace)
    if not hasattr(schema_cls, "kind"):
        setattr(schema_cls, "kind", kind)
    if not hasattr(schema_cls, "name"):
        setattr(schema_cls, "name", name)
    ResponseSchemaRegistry.register(schema_cls)


__all__ = [
    "ResponseSchemaRegistry",
    "DuplicateResponseSchemaIdentityError",
    "register_schema",
]
