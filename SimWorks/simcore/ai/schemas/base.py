# simcore/ai/schemas/base.py

from pydantic import BaseModel, ConfigDict


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrictOutputSchema(StrictBaseModel):
    pass
