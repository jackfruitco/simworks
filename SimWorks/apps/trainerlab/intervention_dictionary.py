from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

__all__ = [
    "InterventionDefinition",
    "InterventionFieldDefinition",
    "build_legacy_intervention_code",
    "get_intervention_definition",
    "get_intervention_detail_schema_metadata",
    "get_intervention_label",
    "get_intervention_site_choices",
    "get_intervention_site_label",
    "get_intervention_type_choices",
    "list_intervention_definitions",
    "normalize_intervention_site",
    "normalize_intervention_type",
    "normalize_tourniquet_application_mode",
    "validate_intervention_details",
]


@dataclass(frozen=True)
class InterventionFieldDefinition:
    name: str
    label: str
    input_type: str
    required: bool = True
    help_text: str = ""
    choices: tuple[tuple[str, str], ...] = ()


class InterventionDetailsBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    version: int = 1


class TourniquetDetails(InterventionDetailsBase):
    kind: Literal["tourniquet"] = "tourniquet"
    version: Literal[1] = 1
    application_mode: str

    @field_validator("application_mode")
    @classmethod
    def _normalize_application_mode(cls, value: str) -> str:
        return normalize_tourniquet_application_mode(value)


class WoundPackingDetails(InterventionDetailsBase):
    kind: Literal["wound_packing"] = "wound_packing"
    version: Literal[1] = 1


class PressureDressingDetails(InterventionDetailsBase):
    kind: Literal["pressure_dressing"] = "pressure_dressing"
    version: Literal[1] = 1


class NasopharyngealAirwayDetails(InterventionDetailsBase):
    kind: Literal["npa"] = "npa"
    version: Literal[1] = 1


class OropharyngealAirwayDetails(InterventionDetailsBase):
    kind: Literal["opa"] = "opa"
    version: Literal[1] = 1


class NeedleDecompressionDetails(InterventionDetailsBase):
    kind: Literal["needle_decompression"] = "needle_decompression"
    version: Literal[1] = 1


class SurgicalCricDetails(InterventionDetailsBase):
    kind: Literal["surgical_cric"] = "surgical_cric"
    version: Literal[1] = 1


@dataclass(frozen=True)
class InterventionDefinition:
    type_code: str
    label: str
    sites: tuple[tuple[str, str], ...]
    details_model: type[InterventionDetailsBase]
    ui_fields: tuple[InterventionFieldDefinition, ...] = ()
    details_schema_version: int = 1
    legacy_code_map: str | dict[str, str] = ""


TOURNIQUET_APPLICATION_MODE_CHOICES: tuple[tuple[str, str], ...] = (
    ("hasty", "Hasty"),
    ("deliberate", "Deliberate"),
)

INTERVENTION_DEFINITIONS: tuple[InterventionDefinition, ...] = (
    InterventionDefinition(
        type_code="tourniquet",
        label="Tourniquet",
        sites=(
            ("TQ-L-ARM", "Left Arm"),
            ("TQ-R-ARM", "Right Arm"),
            ("TQ-L-LEG", "Left Leg"),
            ("TQ-R-LEG", "Right Leg"),
        ),
        details_model=TourniquetDetails,
        ui_fields=(
            InterventionFieldDefinition(
                name="application_mode",
                label="Application Mode",
                input_type="select",
                choices=TOURNIQUET_APPLICATION_MODE_CHOICES,
            ),
        ),
        legacy_code_map={
            "hasty": "M-TQ-H",
            "deliberate": "M-TQ-D",
        },
    ),
    InterventionDefinition(
        type_code="wound_packing",
        label="Wound Packing",
        sites=(
            ("WP-L-AX", "Left Axilla"),
            ("WP-R-AX", "Right Axilla"),
            ("WP-L-ING", "Left Inguinal"),
            ("WP-R-ING", "Right Inguinal"),
            ("WP-L-NECK", "Left Neck"),
            ("WP-R-NECK", "Right Neck"),
        ),
        details_model=WoundPackingDetails,
        legacy_code_map="M-WPK",
    ),
    InterventionDefinition(
        type_code="pressure_dressing",
        label="Pressure Dressing",
        sites=(
            ("PD-L-ARM", "Left Arm"),
            ("PD-R-ARM", "Right Arm"),
            ("PD-L-LEG", "Left Leg"),
            ("PD-R-LEG", "Right Leg"),
        ),
        details_model=PressureDressingDetails,
        legacy_code_map="M-PD",
    ),
    InterventionDefinition(
        type_code="npa",
        label="Nasopharyngeal Airway",
        sites=(("NPA-NARES", "Nares"),),
        details_model=NasopharyngealAirwayDetails,
        legacy_code_map="A-NPA",
    ),
    InterventionDefinition(
        type_code="opa",
        label="Oropharyngeal Airway",
        sites=(("OPA-ORAL", "Oral Airway"),),
        details_model=OropharyngealAirwayDetails,
        legacy_code_map="A-OPA",
    ),
    InterventionDefinition(
        type_code="needle_decompression",
        label="Needle Decompression",
        sites=(
            ("NCD-L-ANT", "Left Anterior Chest"),
            ("NCD-R-ANT", "Right Anterior Chest"),
            ("NCD-L-LAT", "Left Lateral Chest"),
            ("NCD-R-LAT", "Right Lateral Chest"),
        ),
        details_model=NeedleDecompressionDetails,
        legacy_code_map="R-NCD",
    ),
    InterventionDefinition(
        type_code="surgical_cric",
        label="Surgical Cricothyrotomy",
        sites=(("CRIC-MIDLINE", "Anterior Neck"),),
        details_model=SurgicalCricDetails,
        legacy_code_map="A-SURG-CRIC",
    ),
)


@dataclass(frozen=True)
class _ChoiceIndex:
    field_name: str
    code_to_label: dict[str, str]
    normalized_to_code: dict[str, str]
    codes: tuple[str, ...]
    labels: tuple[str, ...]


@dataclass(frozen=True)
class _InterventionBundle:
    intervention_types: _ChoiceIndex
    definitions_by_type: dict[str, InterventionDefinition]
    sites_by_type: dict[str, _ChoiceIndex]
    field_choices_by_type: dict[str, dict[str, _ChoiceIndex]]


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def _build_choice_index(*, field_name: str, choices: tuple[tuple[str, str], ...]) -> _ChoiceIndex:
    code_to_label: dict[str, str] = {}
    normalized_to_code: dict[str, str] = {}
    codes: list[str] = []
    labels: list[str] = []

    for raw_code, raw_label in choices:
        code = str(raw_code).strip()
        label = " ".join(str(raw_label).strip().split())
        if not code:
            raise RuntimeError(f"Empty code in {field_name} choices")
        if code in code_to_label:
            raise RuntimeError(f"Duplicate code {code!r} in {field_name} choices")

        code_to_label[code] = label
        codes.append(code)
        labels.append(label)

        for normalized in (_normalize_text(code), _normalize_text(label)):
            previous = normalized_to_code.get(normalized)
            if previous and previous != code:
                raise RuntimeError(
                    f"Ambiguous normalized token {normalized!r} in {field_name}: "
                    f"{previous!r} vs {code!r}"
                )
            normalized_to_code[normalized] = code

    return _ChoiceIndex(
        field_name=field_name,
        code_to_label=code_to_label,
        normalized_to_code=normalized_to_code,
        codes=tuple(codes),
        labels=tuple(labels),
    )


@lru_cache(maxsize=1)
def _build_bundle() -> _InterventionBundle:
    intervention_type_choices = tuple(
        (definition.type_code, definition.label) for definition in INTERVENTION_DEFINITIONS
    )
    definitions_by_type = {
        definition.type_code: definition for definition in INTERVENTION_DEFINITIONS
    }

    return _InterventionBundle(
        intervention_types=_build_choice_index(
            field_name="intervention_type",
            choices=intervention_type_choices,
        ),
        definitions_by_type=definitions_by_type,
        sites_by_type={
            definition.type_code: _build_choice_index(
                field_name=f"{definition.type_code}.site_code",
                choices=definition.sites,
            )
            for definition in INTERVENTION_DEFINITIONS
        },
        field_choices_by_type={
            definition.type_code: {
                field.name: _build_choice_index(
                    field_name=f"{definition.type_code}.{field.name}",
                    choices=field.choices,
                )
                for field in definition.ui_fields
                if field.choices
            }
            for definition in INTERVENTION_DEFINITIONS
        },
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


def _format_validation_error(error: dict[str, Any]) -> str:
    location = ".".join(str(part) for part in error.get("loc", ()))
    message = error.get("msg", "Invalid value")
    return f"{location}: {message}" if location else message


def list_intervention_definitions() -> tuple[InterventionDefinition, ...]:
    return INTERVENTION_DEFINITIONS


def normalize_intervention_type(value: Any) -> str:
    return _resolve_choice(_build_bundle().intervention_types, value)


def get_intervention_definition(intervention_type: str) -> InterventionDefinition:
    normalized_type = normalize_intervention_type(intervention_type)
    return _build_bundle().definitions_by_type[normalized_type]


def normalize_intervention_site(intervention_type: str, value: Any) -> str:
    normalized_type = normalize_intervention_type(intervention_type)
    index = _build_bundle().sites_by_type[normalized_type]
    return _resolve_choice(index, value)


def normalize_tourniquet_application_mode(value: Any) -> str:
    index = _build_bundle().field_choices_by_type["tourniquet"]["application_mode"]
    return _resolve_choice(index, value)


def get_intervention_type_choices() -> list[tuple[str, str]]:
    bundle = _build_bundle()
    return list(bundle.intervention_types.code_to_label.items())


def get_intervention_site_choices() -> dict[str, list[tuple[str, str]]]:
    bundle = _build_bundle()
    return {
        intervention_type: list(index.code_to_label.items())
        for intervention_type, index in bundle.sites_by_type.items()
    }


def get_intervention_label(intervention_type: str) -> str:
    definition = get_intervention_definition(intervention_type)
    return definition.label


def get_intervention_site_label(intervention_type: str, site_code: str) -> str:
    normalized_type = normalize_intervention_type(intervention_type)
    normalized_site = normalize_intervention_site(normalized_type, site_code)
    return _build_bundle().sites_by_type[normalized_type].code_to_label[normalized_site]


def get_intervention_detail_schema_metadata(
    intervention_type: str,
) -> dict[str, Any]:
    definition = get_intervention_definition(intervention_type)
    required_fields = [field.name for field in definition.ui_fields if field.required]
    optional_fields = [field.name for field in definition.ui_fields if not field.required]
    return {
        "kind": definition.type_code,
        "version": definition.details_schema_version,
        "required_fields": required_fields,
        "optional_fields": optional_fields,
        "allows_extra": False,
    }


def validate_intervention_details(intervention_type: str, details: Any) -> dict[str, Any]:
    definition = get_intervention_definition(intervention_type)
    if isinstance(details, BaseModel):
        raw_details = details.model_dump(exclude_none=True)
    elif isinstance(details, dict):
        raw_details = details
    else:
        raise ValueError("details must be an object")

    try:
        validated = definition.details_model.model_validate(raw_details)
    except ValidationError as exc:
        messages = "; ".join(_format_validation_error(error) for error in exc.errors())
        raise ValueError(f"Invalid details for {definition.type_code!r}: {messages}") from None

    return validated.model_dump(exclude_none=True)


def build_legacy_intervention_code(
    intervention_type: str,
    details: dict[str, Any] | None = None,
) -> str:
    definition = get_intervention_definition(intervention_type)
    legacy_code = definition.legacy_code_map
    if isinstance(legacy_code, str):
        return legacy_code

    normalized_details = validate_intervention_details(definition.type_code, details or {})
    application_mode = normalized_details.get("application_mode")
    if not isinstance(application_mode, str):
        raise ValueError("application_mode is required for tourniquet legacy code")
    return legacy_code[application_mode]
