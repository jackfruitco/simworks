"""Declarative persistence engine for schema → Django model mapping.

Walks the MRO of a Pydantic schema to merge ``__persist__`` dicts, then
dispatches each mapped field to either an explicit async persist function
or the auto-mapper (when the mapping value is ``None``).

Public API:
    persist_schema(schema, context) → primary domain object or results dict
    resolve_schema_class(fqn)       → Pydantic model class
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import importlib
import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


@dataclass
class PersistContext:
    """Context passed to every persist function."""

    simulation_id: int
    call_id: str
    audit_id: int | None = None
    correlation_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _merge_persist_from_mro(cls: type) -> dict[str, Callable | None]:
    """Merge ``__persist__`` dicts from full MRO (base-first)."""
    merged: dict[str, Callable | None] = {}
    for klass in reversed(cls.__mro__):
        persist_dict = vars(klass).get("__persist__")
        if isinstance(persist_dict, dict):
            merged.update(persist_dict)
    return merged


def _get_primary_from_mro(cls: type) -> str | None:
    """Walk MRO for ``__persist_primary__`` (most-derived wins)."""
    for klass in cls.__mro__:
        primary = vars(klass).get("__persist_primary__")
        if primary is not None:
            return primary
    return None


async def _persist_field_auto(
    *,
    field_name: str,
    value: Any,
    schema: BaseModel,
    context: PersistContext,
) -> Any:
    """Persist a mapped field without an explicit handler.

    Supports nested declarative schemas by recursing when a field value is
    itself a BaseModel with ``__persist__`` declarations.
    """
    if isinstance(value, BaseModel):
        nested_map = _merge_persist_from_mro(type(value))
        if nested_map:
            return await persist_schema(value, context)

    # Auto-map via __orm_model__ on the item type.
    from orchestrai_django.persistence.auto_mapper import auto_persist_field

    return await auto_persist_field(field_name, value, schema, context)


async def persist_schema(schema: BaseModel, context: PersistContext) -> Any:
    """Walk MRO, merge ``__persist__`` declarations, run each persister.

    Returns:
        The primary domain object (if ``__persist_primary__`` is set and
        the field was persisted), otherwise the full results dict, or
        ``None`` if the schema has no ``__persist__`` declarations.
    """
    persist_map = _merge_persist_from_mro(type(schema))
    primary_field = _get_primary_from_mro(type(schema))

    if not persist_map:
        return None

    results: dict[str, Any] = {}

    for field_name, fn_or_none in persist_map.items():
        if field_name not in type(schema).model_fields:
            logger.debug(
                "Skipping persist mapping %r: not a field on %s",
                field_name,
                type(schema).__name__,
            )
            continue

        value = getattr(schema, field_name)

        if fn_or_none is not None:
            # Explicit persist function
            results[field_name] = await fn_or_none(value, context)
        else:
            results[field_name] = await _persist_field_auto(
                field_name=field_name,
                value=value,
                schema=schema,
                context=context,
            )

    # Post-persist hook
    if hasattr(schema, "post_persist"):
        await schema.post_persist(results, context)

    # Return primary domain object
    if primary_field and primary_field in results:
        r = results[primary_field]
        return r[0] if isinstance(r, list) else r

    return results


def resolve_schema_class(fqn: str) -> type:
    """Import and return a Pydantic schema class from a fully-qualified name.

    Args:
        fqn: Dotted path like ``chatlab.orca.schemas.patient.PatientInitialOutputSchema``

    Returns:
        The schema class.

    Raises:
        ImportError: If the module cannot be found.
        AttributeError: If the class does not exist in the module.
    """
    module_path, class_name = fqn.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)
