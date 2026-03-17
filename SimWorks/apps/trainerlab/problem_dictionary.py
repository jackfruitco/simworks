from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from slugify import slugify

__all__ = [
    "ProblemDefinition",
    "build_problem_dictionary_instruction",
    "get_problem_definition",
    "list_problem_definitions",
    "normalize_problem_code",
    "normalize_problem_kind",
]


@dataclass(frozen=True)
class ProblemDefinition:
    kind: str
    code: str
    title: str
    default_march_category: str | None = None
    synonyms: tuple[str, ...] = ()

    @property
    def slug(self) -> str:
        return slugify(self.kind)


PROBLEM_DEFINITIONS: tuple[ProblemDefinition, ...] = (
    ProblemDefinition(
        kind="hemorrhage",
        code="hemorrhage",
        title="Hemorrhage",
        default_march_category="M",
        synonyms=("bleeding", "massive hemorrhage", "severe bleeding"),
    ),
    ProblemDefinition(
        kind="open_wound",
        code="open_wound",
        title="Open Wound",
        default_march_category="M",
        synonyms=("wound", "soft tissue wound", "hole"),
    ),
    ProblemDefinition(
        kind="open_chest_wound",
        code="open_chest_wound",
        title="Open Chest Wound",
        default_march_category="R",
        synonyms=("sucking chest wound", "chest wound"),
    ),
    ProblemDefinition(
        kind="airway_obstruction",
        code="airway_obstruction",
        title="Airway Obstruction",
        default_march_category="A",
        synonyms=("airway compromise", "obstructed airway"),
    ),
    ProblemDefinition(
        kind="respiratory_distress",
        code="respiratory_distress",
        title="Respiratory Distress",
        default_march_category="R",
        synonyms=("breathing difficulty", "respiratory compromise", "shortness of breath"),
    ),
    ProblemDefinition(
        kind="tension_pneumothorax",
        code="tension_pneumothorax",
        title="Tension Pneumothorax",
        default_march_category="R",
        synonyms=("tension pneumo", "pneumothorax"),
    ),
    ProblemDefinition(
        kind="infectious_process",
        code="infectious_process",
        title="Infectious Process",
        default_march_category="C",
        synonyms=("infection", "infectious illness", "sepsis"),
    ),
    ProblemDefinition(
        kind="dehydration",
        code="dehydration",
        title="Dehydration",
        default_march_category="C",
        synonyms=("volume depletion", "heat dehydration"),
    ),
    ProblemDefinition(
        kind="heat_illness",
        code="heat_illness",
        title="Heat Illness",
        default_march_category="H1",
        synonyms=("heat exhaustion", "heat injury", "heat stress"),
    ),
    ProblemDefinition(
        kind="pain",
        code="pain",
        title="Pain",
        default_march_category="C",
        synonyms=("acute pain", "pain complaint"),
    ),
)


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


@lru_cache(maxsize=1)
def _problem_index() -> dict[str, ProblemDefinition]:
    index: dict[str, ProblemDefinition] = {}
    for definition in PROBLEM_DEFINITIONS:
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
                    f"Ambiguous problem dictionary token {candidate!r}: "
                    f"{existing.code!r} vs {definition.code!r}"
                )
            index[normalized] = definition
    return index


def normalize_problem_kind(value: Any) -> str:
    raw_value = value.value if hasattr(value, "value") else value
    if not isinstance(raw_value, str):
        raise ValueError("problem kind must be a string")
    normalized = _normalize_text(raw_value)
    if not normalized:
        raise ValueError("problem kind cannot be blank")
    definition = _problem_index().get(normalized)
    if definition is None:
        allowed = ", ".join(defn.kind for defn in PROBLEM_DEFINITIONS)
        raise ValueError(f"Invalid problem kind {raw_value!r}. Allowed values: {allowed}.")
    return definition.kind


def normalize_problem_code(value: Any) -> str:
    definition = get_problem_definition(value)
    return definition.code


def get_problem_definition(value: Any) -> ProblemDefinition:
    normalized_kind = normalize_problem_kind(value)
    for definition in PROBLEM_DEFINITIONS:
        if definition.kind == normalized_kind:
            return definition
    raise RuntimeError(f"Problem dictionary missing definition for {normalized_kind!r}")


def list_problem_definitions() -> tuple[ProblemDefinition, ...]:
    return PROBLEM_DEFINITIONS


def build_problem_dictionary_instruction() -> str:
    lines = [
        "### Problem Dictionary",
        "- Use canonical problem terms from this list when possible.",
        "- Problems are actionable clinical entities, not mechanisms or causes.",
    ]
    for definition in PROBLEM_DEFINITIONS:
        suffix = (
            f" (default MARCH `{definition.default_march_category}`)"
            if definition.default_march_category
            else ""
        )
        lines.append(f"- `{definition.kind}` / `{definition.code}`: {definition.title}{suffix}")
    return "\n".join(lines) + "\n"
