"""Modality-specific rendering of the canonical patient runtime context."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from .context import PatientRuntimeContext


@lru_cache(maxsize=1)
def _patient_yaml_instructions() -> dict[str, str]:
    path = Path(__file__).resolve().parents[1] / "orca" / "instructions" / "patient.yaml"
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return {
        item["name"]: str(item.get("instruction") or "").strip()
        for item in data.get("instructions", [])
        if isinstance(item, dict) and item.get("name")
    }


def _shared_static_instructions() -> list[str]:
    instructions = _patient_yaml_instructions()
    return [
        instructions[name]
        for name in (
            "PatientSafetyBoundariesInstruction",
            "PatientConversationBehaviorInstruction",
            "PatientInformationDisclosureInstruction",
        )
        if instructions.get(name)
    ]


def _dynamic_context(context: PatientRuntimeContext) -> str:
    lines = [
        "### Patient Runtime Context",
        f"- Patient identity: {context.patient_full_name}",
        f"- Chief complaint: {context.chief_complaint}",
        f"- Conversation persona: {context.persona}",
    ]
    if context.modifier_prompt:
        lines.extend(["### Scenario Modifier Constraints", context.modifier_prompt])
    return "\n".join(lines)


def render_text_patient_instructions(
    context: PatientRuntimeContext,
    *,
    include_shared: bool = True,
    include_schema: bool = True,
    include_reply_detail: bool = True,
) -> str:
    """Render shared patient behavior plus text-only schema requirements."""

    instructions = _patient_yaml_instructions()
    sections = [_dynamic_context(context)]
    if include_shared:
        sections.extend(_shared_static_instructions())
    text_only_names = []
    if include_schema:
        text_only_names.append("PatientSchemaContractInstruction")
    if include_reply_detail:
        text_only_names.append("PatientReplyDetailInstruction")
    for name in text_only_names:
        if instructions.get(name):
            sections.append(instructions[name])
    return "\n\n".join(section for section in sections if section)


def render_voice_patient_instructions(context: PatientRuntimeContext) -> str:
    """Render shared patient behavior plus a spoken-turn-only overlay."""

    sections = [
        _dynamic_context(context),
        *_shared_static_instructions(),
        (
            "### Voice Turn Behavior\n"
            "- Use concise, natural spoken turns that are easy to interrupt.\n"
            "- Do not verbalize schemas, JSON, tool mechanics, or hidden workflow details.\n"
            "- Remain in the patient's perspective and answer only what was asked."
        ),
    ]
    return "\n\n".join(section for section in sections if section)


__all__ = ["render_text_patient_instructions", "render_voice_patient_instructions"]
