from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from slugify import slugify

__all__ = [
    "FindingDefinition",
    "build_finding_dictionary_instruction",
    "get_finding_definition",
    "list_finding_definitions",
    "normalize_finding_code",
    "normalize_finding_kind",
]


@dataclass(frozen=True)
class FindingDefinition:
    kind: str
    code: str
    title: str
    synonyms: tuple[str, ...] = ()

    @property
    def slug(self) -> str:
        return slugify(self.kind, separator="_")


FINDING_DEFINITIONS: tuple[FindingDefinition, ...] = (
    FindingDefinition(
        kind="active_bleeding",
        code="active_bleeding",
        title="Active Bleeding",
        synonyms=("uncontrolled bleeding", "visible hemorrhage"),
    ),
    FindingDefinition(
        kind="cool_clammy_skin",
        code="cool_clammy_skin",
        title="Cool Clammy Skin",
        synonyms=("clammy skin", "cold clammy skin"),
    ),
    FindingDefinition(
        kind="altered_mental_status",
        code="altered_mental_status",
        title="Altered Mental Status",
        synonyms=("ams", "confusion", "decreased responsiveness"),
    ),
    FindingDefinition(
        kind="diminished_breath_sounds",
        code="diminished_breath_sounds",
        title="Diminished Breath Sounds",
        synonyms=("reduced breath sounds", "decreased breath sounds"),
    ),
    FindingDefinition(
        kind="absent_breath_sounds",
        code="absent_breath_sounds",
        title="Absent Breath Sounds",
        synonyms=("no breath sounds", "silent chest"),
    ),
    FindingDefinition(
        kind="tracheal_deviation",
        code="tracheal_deviation",
        title="Tracheal Deviation",
        synonyms=("deviated trachea",),
    ),
    FindingDefinition(
        kind="airway_secretions",
        code="airway_secretions",
        title="Airway Secretions",
        synonyms=("gurgling airway", "bloody airway"),
    ),
    FindingDefinition(
        kind="cyanosis",
        code="cyanosis",
        title="Cyanosis",
        synonyms=("cyanotic appearance", "blue lips"),
    ),
)


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


@lru_cache(maxsize=1)
def _finding_index() -> dict[str, FindingDefinition]:
    index: dict[str, FindingDefinition] = {}
    for definition in FINDING_DEFINITIONS:
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
                    f"Ambiguous finding dictionary token {candidate!r}: "
                    f"{existing.code!r} vs {definition.code!r}"
                )
            index[normalized] = definition
    return index


def normalize_finding_kind(value: Any) -> str:
    raw_value = value.value if hasattr(value, "value") else value
    if not isinstance(raw_value, str):
        raise ValueError("finding kind must be a string")
    normalized = _normalize_text(raw_value)
    if not normalized:
        raise ValueError("finding kind cannot be blank")
    definition = _finding_index().get(normalized)
    if definition is None:
        allowed = ", ".join(defn.kind for defn in FINDING_DEFINITIONS)
        raise ValueError(f"Invalid finding kind {raw_value!r}. Allowed values: {allowed}.")
    return definition.kind


def normalize_finding_code(value: Any) -> str:
    return get_finding_definition(value).code


def get_finding_definition(value: Any) -> FindingDefinition:
    normalized_kind = normalize_finding_kind(value)
    for definition in FINDING_DEFINITIONS:
        if definition.kind == normalized_kind:
            return definition
    raise RuntimeError(f"Finding dictionary missing definition for {normalized_kind!r}")


def list_finding_definitions() -> tuple[FindingDefinition, ...]:
    return FINDING_DEFINITIONS


def build_finding_dictionary_instruction() -> str:
    lines = [
        "### Assessment Finding Dictionary",
        "- Use canonical finding terms from this list when possible.",
    ]
    for definition in FINDING_DEFINITIONS:
        lines.append(f"- `{definition.kind}` / `{definition.code}`: {definition.title}")
    return "\n".join(lines) + "\n"
