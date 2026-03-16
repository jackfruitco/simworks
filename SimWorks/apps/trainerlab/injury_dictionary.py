from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "build_injury_codebook_instruction",
    "get_injury_dictionary_choices",
    "get_injury_mapping_warnings",
    "normalize_injury_category",
    "normalize_injury_kind",
    "normalize_injury_location",
]


@dataclass(frozen=True)
class _ChoiceIndex:
    field_name: str
    code_to_label: dict[str, str]
    normalized_to_code: dict[str, str]
    codes: tuple[str, ...]
    labels: tuple[str, ...]


@dataclass(frozen=True)
class _InjuryMappingBundle:
    category: _ChoiceIndex
    location: _ChoiceIndex
    kind: _ChoiceIndex
    warnings: tuple[str, ...]


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def _build_choice_index(*, field_name: str, choices: list[tuple[str, str]]) -> _ChoiceIndex:
    code_to_label: dict[str, str] = {}
    normalized_to_code: dict[str, str] = {}
    codes: list[str] = []
    labels: list[str] = []

    for raw_code, raw_label in choices:
        code = str(raw_code).strip()
        label = " ".join(str(raw_label).strip().split())

        if not code:
            msg = f"Empty code in {field_name} choices"
            raise RuntimeError(msg)
        if code in code_to_label:
            msg = f"Duplicate code {code!r} in {field_name} choices"
            raise RuntimeError(msg)

        code_to_label[code] = label
        codes.append(code)
        labels.append(label)

        for normalized in (_normalize_text(code), _normalize_text(label)):
            previous = normalized_to_code.get(normalized)
            if previous and previous != code:
                msg = (
                    f"Ambiguous normalized token {normalized!r} in {field_name}: "
                    f"{previous!r} vs {code!r}"
                )
                raise RuntimeError(msg)
            normalized_to_code[normalized] = code

    return _ChoiceIndex(
        field_name=field_name,
        code_to_label=code_to_label,
        normalized_to_code=normalized_to_code,
        codes=tuple(codes),
        labels=tuple(labels),
    )


def _build_integrity_warnings() -> tuple[str, ...]:
    from apps.trainerlab.models import Problem

    warnings: list[str] = []
    for member in Problem.MARCHCategory:
        if "_" in member.name:
            continue
        if len(member.name) <= 4 and member.name != member.value:
            warnings.append(
                "MARCHCategory member "
                f"{member.name!r} maps to code {member.value!r}; review intent."
            )
    return tuple(warnings)


@lru_cache(maxsize=1)
def _build_bundle() -> _InjuryMappingBundle:
    from apps.trainerlab.models import Injury, Problem

    category = _build_choice_index(
        field_name="march_category",
        choices=[(str(code), str(label)) for code, label in Problem.MARCHCategory.choices],
    )
    location = _build_choice_index(
        field_name="injury_location",
        choices=[(str(code), str(label)) for code, label in Injury.InjuryLocation.choices],
    )
    kind = _build_choice_index(
        field_name="injury_kind",
        choices=[(str(code), str(label)) for code, label in Injury.InjuryKind.choices],
    )
    warnings = _build_integrity_warnings()
    for warning in warnings:
        logger.warning("TrainerLab injury mapping integrity warning: %s", warning)

    return _InjuryMappingBundle(
        category=category,
        location=location,
        kind=kind,
        warnings=warnings,
    )


def _resolve_choice(index: _ChoiceIndex, value: Any) -> str:
    raw_value = value.value if hasattr(value, "value") else value
    if not isinstance(raw_value, str):
        raise ValueError(f"{index.field_name} must be a string")

    normalized = _normalize_text(raw_value)
    if not normalized:
        raise ValueError(f"{index.field_name} cannot be blank")

    code = index.normalized_to_code.get(normalized)
    if code:
        return code

    allowed_codes = ", ".join(index.codes)
    allowed_labels = "; ".join(index.labels)
    raise ValueError(
        f"Invalid {index.field_name!r} value {raw_value!r}. "
        f"Allowed codes: {allowed_codes}. "
        f"Allowed labels: {allowed_labels}."
    )


def normalize_injury_category(value: Any) -> str:
    return _resolve_choice(_build_bundle().category, value)


def normalize_injury_location(value: Any) -> str:
    return _resolve_choice(_build_bundle().location, value)


def normalize_injury_kind(value: Any) -> str:
    return _resolve_choice(_build_bundle().kind, value)


def get_injury_dictionary_choices() -> dict[str, list[tuple[str, str]]]:
    bundle = _build_bundle()
    return {
        "categories": list(bundle.category.code_to_label.items()),
        "regions": list(bundle.location.code_to_label.items()),
        "kinds": list(bundle.kind.code_to_label.items()),
    }


def get_injury_mapping_warnings() -> tuple[str, ...]:
    return _build_bundle().warnings


def _format_codebook_pairs(pairs: list[tuple[str, str]]) -> str:
    return ", ".join(f"{code}={label}" for code, label in pairs)


def build_injury_codebook_instruction() -> str:
    choices = get_injury_dictionary_choices()
    categories = _format_codebook_pairs(choices["categories"])
    regions = _format_codebook_pairs(choices["regions"])
    kinds = _format_codebook_pairs(choices["kinds"])
    return (
        "### Injury Codebook\n"
        "- Return canonical codes for `march_category`, `injury_location`, and `injury_kind`.\n"
        "- You may reason with friendly labels, but your final output must use codes.\n"
        f"- `march_category` codes: {categories}\n"
        f"- `injury_location` codes: {regions}\n"
        f"- `injury_kind` codes: {kinds}\n"
    )
