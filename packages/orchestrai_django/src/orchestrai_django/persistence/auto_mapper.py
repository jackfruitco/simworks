"""Auto-mapper for Pydantic output items → Django model instances.

When a schema field has ``__persist__ = {"field": None}``, the engine
delegates to this module which reads ``__orm_model__`` from the Pydantic
item class and creates Django model instances by matching field names.

Public API:
    auto_persist_field(field_name, value, schema, context) → created instances
    OrmOverride        — Annotated descriptor to override __orm_model__ per-field
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dc_field
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from orchestrai_django.persistence.engine import PersistContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrmOverride:
    """Annotated descriptor to override ``__orm_model__`` for a specific field.

    Usage::

        class MySchema(BaseModel):
            feedback: Annotated[
                list[ResultMetafield],
                OrmOverride(model="simulation.SimulationFeedback"),
            ] = Field(...)
    """

    model: str
    field_map: dict[str, str] = dc_field(default_factory=dict)


def _get_orm_override(field_info: Any) -> OrmOverride | None:
    """Extract ``OrmOverride`` from field metadata (Annotated[..., OrmOverride(...)])."""
    for meta in field_info.metadata or []:
        if isinstance(meta, OrmOverride):
            return meta
    return None


async def auto_persist_field(
    field_name: str,
    value: Any,
    schema: BaseModel,
    context: PersistContext,
) -> Any:
    """Auto-persist a field using ``__orm_model__`` from item types.

    Handles both single items and lists. For lists, creates one Django
    instance per item.
    """
    from django.apps import apps

    field_info = type(schema).model_fields[field_name]
    orm_override = _get_orm_override(field_info)

    if isinstance(value, list):
        results = []
        for item in value:
            model_ref = orm_override.model if orm_override else getattr(type(item), "__orm_model__", None)
            field_map = orm_override.field_map if orm_override else getattr(type(item), "__orm_field_map__", {})
            if model_ref is None:
                raise ValueError(
                    f"No __orm_model__ on {type(item).__name__} and no OrmOverride "
                    f"on field {field_name!r}"
                )
            model_cls = apps.get_model(*model_ref.split(".", 1))
            results.append(await _create_orm_instance(item, model_cls, field_map, context))
        return results
    else:
        model_ref = orm_override.model if orm_override else getattr(type(value), "__orm_model__", None)
        field_map = orm_override.field_map if orm_override else getattr(type(value), "__orm_field_map__", {})
        if model_ref is None:
            raise ValueError(
                f"No __orm_model__ on {type(value).__name__} and no OrmOverride "
                f"on field {field_name!r}"
            )
        model_cls = apps.get_model(*model_ref.split(".", 1))
        return await _create_orm_instance(value, model_cls, field_map, context)


async def _create_orm_instance(
    item: Any,
    model_cls: type,
    field_map: dict[str, str],
    context: PersistContext,
) -> Any:
    """Create a Django model instance from a Pydantic model via field mapping.

    Field resolution rules:
        1. If pydantic field name is in ``field_map``, use the mapped Django field name.
        2. If pydantic field name matches a Django model field name, use it directly.
        3. Otherwise, skip the field (debug log).

    Context injection:
        ``simulation_id`` is always injected from context if the model has the field.
    """
    kwargs: dict[str, Any] = {}
    model_field_names = {f.name for f in model_cls._meta.get_fields() if hasattr(f, "column")}

    for pydantic_field in type(item).model_fields:
        # 1. Check explicit field map
        if pydantic_field in field_map:
            orm_field = field_map[pydantic_field]
        # 2. Check direct name match
        elif pydantic_field in model_field_names:
            orm_field = pydantic_field
        # 3. No match — skip
        else:
            logger.debug(
                "Skipping %s.%s: no matching field on %s and not in __orm_field_map__",
                type(item).__name__,
                pydantic_field,
                model_cls.__name__,
            )
            continue

        value = getattr(item, pydantic_field)
        if isinstance(value, (str, int, float, bool)) or value is None:
            kwargs[orm_field] = value
        elif hasattr(value, "value"):  # Enum
            kwargs[orm_field] = value.value
        else:
            kwargs[orm_field] = str(value)

    # Inject context fields — Django FK fields are named "simulation" but accept
    # "simulation_id" for raw ID assignment.
    if "simulation" in model_field_names and "simulation_id" not in kwargs:
        kwargs["simulation_id"] = context.simulation_id

    return await model_cls.objects.acreate(**kwargs)
