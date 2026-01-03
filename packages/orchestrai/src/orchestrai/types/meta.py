"""Metadata helpers for structured outputs."""
from collections.abc import Iterable, Mapping

from pydantic import Field, GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

from .base import StrictBaseModel

MetafieldValue = str | int | float | bool | None


class Metafield(StrictBaseModel):
    """Single metadata entry using JSON-primitive values.

    The limited value type keeps generated schemas closed for OpenAI structured
    outputs (`additionalProperties: false`).
    """

    key: str
    value: MetafieldValue


class MetafieldContainer(list[Metafield]):
    """List-backed container that preserves schema while allowing dict-like access."""

    def __init__(self, entries: Iterable[Metafield] | None = None):
        super().__init__(entries or [])

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: type, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        list_schema = handler.generate_schema(list[Metafield])
        return core_schema.no_info_after_validator_function(cls._validate, list_schema)

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return handler(core_schema)

    @classmethod
    def _validate(cls, value: object) -> "MetafieldContainer":
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(Metafield(key=key, value=val) for key, val in value.items())
        if isinstance(value, list):
            return cls(value)

        raise TypeError(f"Cannot coerce {type(value)} into MetafieldContainer")

    def __getitem__(self, key: int | str) -> Metafield | MetafieldValue:
        if isinstance(key, str):
            for entry in self:
                if entry.key == key:
                    return entry.value
            raise KeyError(key)

        return super().__getitem__(key)

    def get(self, key: str, default: MetafieldValue | None = None) -> MetafieldValue | None:
        try:
            return self[key]
        except KeyError:
            return default

    @property
    def as_dict(self) -> dict[str, MetafieldValue]:
        return {entry.key: entry.value for entry in self}


class HasItemMeta(StrictBaseModel):
    """Mixin for models that expose item-level metadata."""

    item_meta: MetafieldContainer = Field(default_factory=MetafieldContainer)


def dict_to_metafields(data: Mapping[str, MetafieldValue] | None) -> MetafieldContainer:
    """Convert a mapping to a list of :class:`Metafield` entries."""

    return MetafieldContainer(Metafield(key=key, value=value) for key, value in (data or {}).items())


def metafields_to_dict(entries: Iterable[Metafield] | None) -> dict[str, MetafieldValue]:
    """Convert a list of :class:`Metafield` entries to a mapping."""

    if entries is None:
        return {}

    return {entry.key: entry.value for entry in entries}
