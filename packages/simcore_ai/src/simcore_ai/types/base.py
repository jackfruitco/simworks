# simcore_ai/types/base.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class StrictBaseModel(BaseModel):
    """Default Pydantic strict model used across SimWorks."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @classmethod
    def model_construct_safe(cls, **kwargs) -> StrictBaseModel:
        """Constructs a model without validation.

        This method skips Pydantic's validation and returns a model instance.
        It should only be used when the model is constructed with a known schema.
        """
        return cls.model_construct(**kwargs)


Boolish = Literal["true", "false", "partial"]
