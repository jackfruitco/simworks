# simcore/ai/schemas/base.py
from __future__ import annotations

from typing import get_type_hints, Literal

from pydantic import BaseModel, ConfigDict, create_model


class StrictBaseModel(BaseModel):
    """Default strict model used across SimWorks."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class StrictOutputSchema(StrictBaseModel):
    """Marker/base for LLM output schemas."""
    pass


Boolish = Literal["true", "false", "partial"]


def project_from(
    BaseCls,
    *,
    include: tuple[str, ...] | None = None,
    name: str | None = None,
    overrides: dict | None = None,
) -> type[StrictBaseModel]  :
    """
    Build a new StrictBaseModel by selecting (and optionally overriding) fields from BaseCls.

    - include: keep only these fields (None = keep all)
    - overrides: {field: NewType | (NewType, default)}
    """
    hints = get_type_hints(BaseCls, include_extras=True)
    overrides = overrides or {}

    # seed
    if include:
        fields = {k: (hints[k] if k in hints else overrides[k]) for k in include if (k in hints or k in overrides)}
    else:
        fields = dict(hints)

    # exclude
    # if exclude:
    #     for k in exclude:
    #         fields.pop(k, None)

    # apply overrides + defaults
    final_fields = {}
    for k, ann in fields.items():
        ann = overrides.get(k, ann)
        default = ...
        if isinstance(ann, tuple) and len(ann) == 2:
            ann, default = ann
        final_fields[k] = (ann, default)

    return create_model(name or f"{BaseCls.__name__}Projection", __base__=StrictBaseModel, **final_fields)