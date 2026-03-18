from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from slugify import slugify

__all__ = [
    "DiagnosticDefinition",
    "build_diagnostic_dictionary_instruction",
    "get_diagnostic_definition",
    "list_diagnostic_definitions",
    "normalize_diagnostic_code",
    "normalize_diagnostic_kind",
]


@dataclass(frozen=True)
class DiagnosticDefinition:
    kind: str
    code: str
    title: str
    synonyms: tuple[str, ...] = ()

    @property
    def slug(self) -> str:
        return slugify(self.kind, separator="_")


DIAGNOSTIC_DEFINITIONS: tuple[DiagnosticDefinition, ...] = (
    DiagnosticDefinition(
        kind="fast_ultrasound",
        code="fast_ultrasound",
        title="FAST Ultrasound",
        synonyms=("fast exam", "e-fast"),
    ),
    DiagnosticDefinition(
        kind="chest_xray",
        code="chest_xray",
        title="Chest X-Ray",
        synonyms=("cxr", "chest radiograph"),
    ),
    DiagnosticDefinition(
        kind="cbc",
        code="cbc",
        title="Complete Blood Count",
        synonyms=("complete blood count",),
    ),
    DiagnosticDefinition(
        kind="lactate",
        code="lactate",
        title="Serum Lactate",
        synonyms=("serum lactate",),
    ),
    DiagnosticDefinition(
        kind="blood_culture",
        code="blood_culture",
        title="Blood Culture",
        synonyms=("cultures",),
    ),
)


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


@lru_cache(maxsize=1)
def _diagnostic_index() -> dict[str, DiagnosticDefinition]:
    index: dict[str, DiagnosticDefinition] = {}
    for definition in DIAGNOSTIC_DEFINITIONS:
        for candidate in (
            definition.kind,
            definition.code,
            definition.title,
            definition.slug,
            *definition.synonyms,
        ):
            normalized = _normalize_text(candidate)
            existing = index.get(normalized)
            if existing and existing.code != definition.code:
                raise RuntimeError(
                    f"Ambiguous diagnostic dictionary token {candidate!r}: "
                    f"{existing.code!r} vs {definition.code!r}"
                )
            index[normalized] = definition
    return index


def normalize_diagnostic_kind(value: Any) -> str:
    raw_value = value.value if hasattr(value, "value") else value
    if not isinstance(raw_value, str):
        raise ValueError("diagnostic kind must be a string")
    normalized = _normalize_text(raw_value)
    if not normalized:
        raise ValueError("diagnostic kind cannot be blank")
    definition = _diagnostic_index().get(normalized)
    if definition is None:
        allowed = ", ".join(defn.kind for defn in DIAGNOSTIC_DEFINITIONS)
        raise ValueError(f"Invalid diagnostic kind {raw_value!r}. Allowed values: {allowed}.")
    return definition.kind


def normalize_diagnostic_code(value: Any) -> str:
    return get_diagnostic_definition(value).code


def get_diagnostic_definition(value: Any) -> DiagnosticDefinition:
    normalized_kind = normalize_diagnostic_kind(value)
    for definition in DIAGNOSTIC_DEFINITIONS:
        if definition.kind == normalized_kind:
            return definition
    raise RuntimeError(f"Diagnostic dictionary missing definition for {normalized_kind!r}")


def list_diagnostic_definitions() -> tuple[DiagnosticDefinition, ...]:
    return DIAGNOSTIC_DEFINITIONS


def build_diagnostic_dictionary_instruction() -> str:
    lines = [
        "### Diagnostic Dictionary",
        "- Use canonical diagnostic terms from this list when possible.",
    ]
    for definition in DIAGNOSTIC_DEFINITIONS:
        lines.append(f"- `{definition.kind}` / `{definition.code}`: {definition.title}")
    return "\n".join(lines) + "\n"
