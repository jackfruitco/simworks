from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


class ModifierDefinitionSchema(BaseModel):
    key: str
    label: str
    description: str
    prompt_fragment: str | None = None


class SelectionConfigSchema(BaseModel):
    mode: Literal["single", "multiple"]
    required: bool = False


class ModifierGroupSchema(BaseModel):
    key: str
    label: str
    description: str
    selection: SelectionConfigSchema
    modifiers: list[ModifierDefinitionSchema]


class ModifierCatalogSchema(BaseModel):
    lab: str
    version: int
    groups: list[ModifierGroupSchema]


@dataclass
class ResolvedModifier:
    key: str
    group_key: str
    definition: ModifierDefinitionSchema
