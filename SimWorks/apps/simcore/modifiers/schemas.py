from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ModifierDefinitionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    description: str
    prompt_fragment: str | None = None


class SelectionConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["single", "multiple"]
    required: bool = False


class ModifierGroupSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    description: str
    selection: SelectionConfigSchema
    modifiers: list[ModifierDefinitionSchema]


class ModifierCatalogSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lab: str
    version: int
    groups: list[ModifierGroupSchema]


@dataclass
class ResolvedModifier:
    key: str
    group_key: str
    definition: ModifierDefinitionSchema
