from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


class ModifierDefinition(BaseModel):
    key: str
    label: str
    description: str
    prompt_fragment: str | None = None


class SelectionConfig(BaseModel):
    mode: Literal["single", "multiple"]
    required: bool = False


class ModifierGroup(BaseModel):
    key: str
    label: str
    description: str
    selection: SelectionConfig
    modifiers: list[ModifierDefinition]


class ModifierCatalog(BaseModel):
    lab: str
    version: int
    groups: list[ModifierGroup]


@dataclass
class ResolvedModifier:
    key: str
    group_key: str
    definition: ModifierDefinition
