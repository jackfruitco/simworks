# orchestrai/types/base.py


from typing import Literal

from pydantic import BaseModel, ConfigDict


class StrictBaseModel(BaseModel):
    """Default Pydantic strict model used across SimWorks."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


Boolish = Literal["true", "false", "partial"]
