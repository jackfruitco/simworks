from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

__all__ = [
    "CauseKindDefinition",
    "build_cause_dictionary_instruction",
    "get_cause_definition",
    "list_cause_definitions",
    "normalize_cause_kind",
]


@dataclass(frozen=True)
class CauseKindDefinition:
    kind: str
    code: str
    title: str
    synonyms: tuple[str, ...] = ()


CAUSE_KIND_DEFINITIONS: tuple[CauseKindDefinition, ...] = (
    CauseKindDefinition(
        kind="injury",
        code="INJURY",
        title="Injury",
        synonyms=("trauma", "wound", "mechanism of injury"),
    ),
    CauseKindDefinition(
        kind="illness",
        code="ILLNESS",
        title="Illness",
        synonyms=("medical", "medical illness", "disease"),
    ),
)


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


@lru_cache(maxsize=1)
def _cause_index() -> dict[str, CauseKindDefinition]:
    index: dict[str, CauseKindDefinition] = {}
    for definition in CAUSE_KIND_DEFINITIONS:
        for candidate in (definition.kind, definition.code, definition.title, *definition.synonyms):
            normalized = _normalize_text(candidate)
            existing = index.get(normalized)
            if existing and existing.kind != definition.kind:
                raise RuntimeError(
                    f"Ambiguous cause dictionary token {candidate!r}: "
                    f"{existing.kind!r} vs {definition.kind!r}"
                )
            index[normalized] = definition
    return index


def normalize_cause_kind(value: Any) -> str:
    raw_value = value.value if hasattr(value, "value") else value
    if not isinstance(raw_value, str):
        raise ValueError("cause_kind must be a string")
    normalized = _normalize_text(raw_value)
    if not normalized:
        raise ValueError("cause_kind cannot be blank")
    definition = _cause_index().get(normalized)
    if definition is None:
        allowed = ", ".join(defn.kind for defn in CAUSE_KIND_DEFINITIONS)
        raise ValueError(f"Invalid cause_kind {raw_value!r}. Allowed values: {allowed}.")
    return definition.kind


def get_cause_definition(value: Any) -> CauseKindDefinition:
    normalized = normalize_cause_kind(value)
    for definition in CAUSE_KIND_DEFINITIONS:
        if definition.kind == normalized:
            return definition
    raise RuntimeError(f"Cause dictionary missing definition for {normalized!r}")


def list_cause_definitions() -> tuple[CauseKindDefinition, ...]:
    return CAUSE_KIND_DEFINITIONS


def build_cause_dictionary_instruction() -> str:
    lines = [
        "### Cause Dictionary",
        "- `cause_kind` must always be one of the canonical values below.",
    ]
    for definition in CAUSE_KIND_DEFINITIONS:
        lines.append(f"- `{definition.kind}` (`{definition.code}`): {definition.title}")
    return "\n".join(lines) + "\n"
