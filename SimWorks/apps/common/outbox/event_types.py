"""Canonical outbox event type registry.

Every canonical event type must follow the strict contract:
``domain.subject.action``.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

CANONICAL_ACTIONS = (
    "created",
    "updated",
    "removed",
    "triggered",
    "completed",
    "failed",
)
CANONICAL_DOMAINS = (
    "simulation",
    "patient",
    "message",
    "feedback",
    "guard",
)
EVENT_TYPE_PATTERN = re.compile(
    r"^[a-z]+\.[a-z]+\.(created|updated|removed|triggered|completed|failed)$"
)


@dataclass(frozen=True, slots=True)
class EventTypeSpec:
    """Definition for a canonical event type and any internal aliases."""

    name: str
    description: str
    aliases: tuple[str, ...] = ()


MESSAGE_CREATED = "message.item.created"
MESSAGE_DELIVERY_UPDATED = "message.delivery.updated"
PATIENT_METADATA_CREATED = "patient.metadata.created"
METADATA_CREATED = PATIENT_METADATA_CREATED
PATIENT_RESULTS_UPDATED = "patient.results.updated"
FEEDBACK_CREATED = "feedback.item.created"
FEEDBACK_GENERATION_FAILED = "feedback.generation.failed"
FEEDBACK_GENERATION_UPDATED = "feedback.generation.updated"
SIMULATION_STATUS_UPDATED = "simulation.status.updated"
SIMULATION_BRIEF_CREATED = "simulation.brief.created"
SIMULATION_BRIEF_UPDATED = "simulation.brief.updated"
SIMULATION_SNAPSHOT_UPDATED = "simulation.snapshot.updated"
SIMULATION_PLAN_UPDATED = "simulation.plan.updated"
SIMULATION_PATCH_EVALUATION_COMPLETED = "simulation.patch.completed"
SIMULATION_TICK_TRIGGERED = "simulation.tick.triggered"
SIMULATION_SUMMARY_UPDATED = "simulation.summary.updated"
SIMULATION_SUMMARY_READY = SIMULATION_SUMMARY_UPDATED
SIMULATION_RUNTIME_FAILED = "simulation.runtime.failed"
SIMULATION_PRESET_APPLIED = "simulation.preset.updated"
SIMULATION_COMMAND_ACCEPTED = "simulation.command.updated"
SIMULATION_ADJUSTMENT_ACCEPTED = "simulation.adjustment.updated"
SIMULATION_ADJUSTMENT_APPLIED = SIMULATION_ADJUSTMENT_ACCEPTED
SIMULATION_NOTE_CREATED = "simulation.note.created"
SIMULATION_ANNOTATION_CREATED = "simulation.annotation.created"
PATIENT_INJURY_CREATED = "patient.injury.created"
PATIENT_INJURY_UPDATED = "patient.injury.updated"
PATIENT_ILLNESS_CREATED = "patient.illness.created"
PATIENT_ILLNESS_UPDATED = "patient.illness.updated"
PATIENT_PROBLEM_CREATED = "patient.problem.created"
PATIENT_PROBLEM_UPDATED = "patient.problem.updated"
PATIENT_RECOMMENDED_INTERVENTION_CREATED = "patient.recommendedintervention.created"
PATIENT_RECOMMENDED_INTERVENTION_UPDATED = "patient.recommendedintervention.updated"
PATIENT_RECOMMENDED_INTERVENTION_REMOVED = "patient.recommendedintervention.removed"
PATIENT_INTERVENTION_CREATED = "patient.intervention.created"
PATIENT_INTERVENTION_UPDATED = "patient.intervention.updated"
PATIENT_INTERVENTION_ASSESSMENT_COMPLETED = PATIENT_INTERVENTION_UPDATED
PATIENT_ASSESSMENT_FINDING_CREATED = "patient.assessmentfinding.created"
PATIENT_ASSESSMENT_FINDING_UPDATED = "patient.assessmentfinding.updated"
PATIENT_ASSESSMENT_FINDING_REMOVED = "patient.assessmentfinding.removed"
PATIENT_DIAGNOSTIC_RESULT_CREATED = "patient.diagnosticresult.created"
PATIENT_DIAGNOSTIC_RESULT_UPDATED = "patient.diagnosticresult.updated"
PATIENT_RESOURCE_UPDATED = "patient.resource.updated"
PATIENT_DISPOSITION_UPDATED = "patient.disposition.updated"
PATIENT_RECOMMENDATION_EVALUATION_CREATED = "patient.recommendationevaluation.created"
PATIENT_VITAL_CREATED = "patient.vital.created"
PATIENT_VITAL_UPDATED = "patient.vital.updated"
PATIENT_PULSE_CREATED = "patient.pulse.created"
PATIENT_PULSE_UPDATED = "patient.pulse.updated"
GUARD_STATE_UPDATED = "guard.state.updated"
GUARD_WARNING_UPDATED = "guard.warning.updated"


EVENT_TYPE_SPECS: tuple[EventTypeSpec, ...] = (
    EventTypeSpec(
        MESSAGE_CREATED,
        "A durable message was created.",
        aliases=(),
    ),
    EventTypeSpec(
        MESSAGE_DELIVERY_UPDATED,
        "A durable message delivery state changed.",
        aliases=(),
    ),
    EventTypeSpec(
        METADATA_CREATED,
        "Structured patient metadata was persisted.",
        aliases=(),
    ),
    EventTypeSpec(
        PATIENT_RESULTS_UPDATED,
        "A patient results panel payload was refreshed.",
        aliases=(),
    ),
    EventTypeSpec(
        FEEDBACK_CREATED,
        "A feedback item was created.",
        aliases=(),
    ),
    EventTypeSpec(
        FEEDBACK_GENERATION_FAILED,
        "Feedback generation failed.",
        aliases=(),
    ),
    EventTypeSpec(
        FEEDBACK_GENERATION_UPDATED,
        "Feedback generation state changed.",
        aliases=(),
    ),
    EventTypeSpec(
        SIMULATION_STATUS_UPDATED,
        "Simulation or session status changed.",
        aliases=(
            "simulation.state_changed",
            "simulation.ended",
            "run.started",
            "run.paused",
            "run.resumed",
            "run.stopped",
            "session.seeded",
            "session.failed",
        ),
    ),
    EventTypeSpec(
        SIMULATION_BRIEF_CREATED,
        "The scenario brief was created.",
        aliases=("trainerlab.scenario_brief.created",),
    ),
    EventTypeSpec(
        SIMULATION_BRIEF_UPDATED,
        "The scenario brief was updated.",
        aliases=("trainerlab.scenario_brief.updated",),
    ),
    EventTypeSpec(
        SIMULATION_SNAPSHOT_UPDATED,
        "The projected runtime snapshot changed.",
        aliases=("state.updated",),
    ),
    EventTypeSpec(
        SIMULATION_PLAN_UPDATED,
        "The AI runtime plan changed.",
        aliases=("ai.intent.updated",),
    ),
    EventTypeSpec(
        SIMULATION_PATCH_EVALUATION_COMPLETED,
        "A runtime patch evaluation completed.",
        aliases=(
            "trainerlab.control_plane.patch_evaluated",
            "simulation.patch_evaluation.completed",
        ),
    ),
    EventTypeSpec(
        SIMULATION_TICK_TRIGGERED,
        "A manual or system tick was triggered.",
        aliases=("trainerlab.tick.triggered",),
    ),
    EventTypeSpec(
        SIMULATION_SUMMARY_UPDATED,
        "A simulation summary changed.",
        aliases=("summary.ready", "summary.updated", "simulation.summary.ready"),
    ),
    EventTypeSpec(
        SIMULATION_RUNTIME_FAILED,
        "Runtime processing failed.",
        aliases=("runtime.failed",),
    ),
    EventTypeSpec(
        SIMULATION_PRESET_APPLIED,
        "A preset state changed.",
        aliases=("preset.applied",),
    ),
    EventTypeSpec(
        SIMULATION_COMMAND_ACCEPTED,
        "A command state changed.",
        aliases=("command.accepted",),
    ),
    EventTypeSpec(
        SIMULATION_ADJUSTMENT_ACCEPTED,
        "An adjustment state changed.",
        aliases=("adjustment.accepted", "adjustment.applied"),
    ),
    EventTypeSpec(
        SIMULATION_NOTE_CREATED,
        "A simulation note was created.",
        aliases=("note.created",),
    ),
    EventTypeSpec(
        SIMULATION_ANNOTATION_CREATED,
        "A debrief annotation was created.",
        aliases=("trainerlab.annotation.created",),
    ),
    EventTypeSpec(
        PATIENT_INJURY_CREATED,
        "A patient injury was created.",
        aliases=("injury.created",),
    ),
    EventTypeSpec(
        PATIENT_INJURY_UPDATED,
        "A patient injury was updated.",
        aliases=("injury.updated",),
    ),
    EventTypeSpec(
        PATIENT_ILLNESS_CREATED,
        "A patient illness was created.",
        aliases=("illness.created",),
    ),
    EventTypeSpec(
        PATIENT_ILLNESS_UPDATED,
        "A patient illness was updated.",
        aliases=("illness.updated",),
    ),
    EventTypeSpec(
        PATIENT_PROBLEM_CREATED,
        "A patient problem was created.",
        aliases=("problem.created",),
    ),
    EventTypeSpec(
        PATIENT_PROBLEM_UPDATED,
        "A patient problem changed.",
        aliases=("problem.updated", "problem.resolved"),
    ),
    EventTypeSpec(
        PATIENT_RECOMMENDED_INTERVENTION_CREATED,
        "A recommended intervention was created.",
        aliases=("recommended_intervention.created", "patient.recommended_intervention.created"),
    ),
    EventTypeSpec(
        PATIENT_RECOMMENDED_INTERVENTION_UPDATED,
        "A recommended intervention was updated.",
        aliases=("recommended_intervention.updated", "patient.recommended_intervention.updated"),
    ),
    EventTypeSpec(
        PATIENT_RECOMMENDED_INTERVENTION_REMOVED,
        "A recommended intervention was removed.",
        aliases=("recommended_intervention.removed", "patient.recommended_intervention.removed"),
    ),
    EventTypeSpec(
        PATIENT_INTERVENTION_CREATED,
        "A patient intervention was created.",
        aliases=("intervention.created",),
    ),
    EventTypeSpec(
        PATIENT_INTERVENTION_UPDATED,
        "A patient intervention changed.",
        aliases=("intervention.updated", "trainerlab.intervention.assessed"),
    ),
    EventTypeSpec(
        PATIENT_ASSESSMENT_FINDING_CREATED,
        "An assessment finding was created.",
        aliases=("trainerlab.assessment_finding.created", "patient.assessment_finding.created"),
    ),
    EventTypeSpec(
        PATIENT_ASSESSMENT_FINDING_UPDATED,
        "An assessment finding was updated.",
        aliases=("trainerlab.assessment_finding.updated", "patient.assessment_finding.updated"),
    ),
    EventTypeSpec(
        PATIENT_ASSESSMENT_FINDING_REMOVED,
        "An assessment finding was removed.",
        aliases=("trainerlab.assessment_finding.removed", "patient.assessment_finding.removed"),
    ),
    EventTypeSpec(
        PATIENT_DIAGNOSTIC_RESULT_CREATED,
        "A diagnostic result was created.",
        aliases=("trainerlab.diagnostic_result.created", "patient.diagnostic_result.created"),
    ),
    EventTypeSpec(
        PATIENT_DIAGNOSTIC_RESULT_UPDATED,
        "A diagnostic result was updated.",
        aliases=("trainerlab.diagnostic_result.updated", "patient.diagnostic_result.updated"),
    ),
    EventTypeSpec(
        PATIENT_RESOURCE_UPDATED,
        "A patient resource state changed.",
        aliases=("trainerlab.resource.updated",),
    ),
    EventTypeSpec(
        PATIENT_DISPOSITION_UPDATED,
        "A patient disposition changed.",
        aliases=("trainerlab.disposition.updated",),
    ),
    EventTypeSpec(
        PATIENT_RECOMMENDATION_EVALUATION_CREATED,
        "A recommendation evaluation was created.",
        aliases=(
            "trainerlab.recommendation_evaluation.created",
            "patient.recommendation_evaluation.created",
        ),
    ),
    EventTypeSpec(
        PATIENT_VITAL_CREATED,
        "A vital record was created.",
        aliases=("trainerlab.vital.created",),
    ),
    EventTypeSpec(
        PATIENT_VITAL_UPDATED,
        "A vital record changed.",
        aliases=("trainerlab.vital.updated",),
    ),
    EventTypeSpec(
        PATIENT_PULSE_CREATED,
        "A pulse assessment was created.",
        aliases=("trainerlab.pulse.created",),
    ),
    EventTypeSpec(
        PATIENT_PULSE_UPDATED,
        "A pulse assessment changed.",
        aliases=("trainerlab.pulse.updated",),
    ),
    EventTypeSpec(
        GUARD_STATE_UPDATED,
        "Guard state changed (pause, resume, lock, unlock).",
        aliases=("guard.state_changed",),
    ),
    EventTypeSpec(
        GUARD_WARNING_UPDATED,
        "Guard warning issued (inactivity warning, nearing limit).",
        aliases=("guard.warning_sent",),
    ),
)


EVENT_TYPE_BY_NAME = {spec.name: spec for spec in EVENT_TYPE_SPECS}
LEGACY_EVENT_TYPE_TO_CANONICAL = {
    alias: spec.name for spec in EVENT_TYPE_SPECS for alias in spec.aliases
}
ALL_EVENT_TYPES = tuple(spec.name for spec in EVENT_TYPE_SPECS)
ALL_DOCUMENTED_EVENT_TYPES = tuple(
    list(ALL_EVENT_TYPES) + list(LEGACY_EVENT_TYPE_TO_CANONICAL.keys())
)


def canonical_event_type(event_type: str) -> str:
    """Return the canonical event type for a canonical or legacy name."""

    return LEGACY_EVENT_TYPE_TO_CANONICAL.get(event_type, event_type)


def legacy_aliases_for(event_type: str) -> tuple[str, ...]:
    """Return deprecated aliases for a canonical event type."""

    canonical = canonical_event_type(event_type)
    spec = EVENT_TYPE_BY_NAME.get(canonical)
    return spec.aliases if spec is not None else ()


def is_known_event_type(event_type: str, *, allow_aliases: bool = True) -> bool:
    """Return True when the event type exists in the registry."""

    if event_type in EVENT_TYPE_BY_NAME:
        return True
    return allow_aliases and event_type in LEGACY_EVENT_TYPE_TO_CANONICAL


def is_valid_canonical_event_type(event_type: str) -> bool:
    """Return True when the event type is canonical and matches the naming contract."""

    if event_type not in EVENT_TYPE_BY_NAME:
        return False
    if not EVENT_TYPE_PATTERN.fullmatch(event_type):
        return False
    domain, _subject, action = event_type.split(".")
    return domain in CANONICAL_DOMAINS and action in CANONICAL_ACTIONS


def canonical_event_types() -> tuple[str, ...]:
    """Return canonical event types in registry order."""

    return ALL_EVENT_TYPES


def deprecated_event_types() -> tuple[str, ...]:
    """Return all legacy aliases still accepted for internal compatibility."""

    return tuple(LEGACY_EVENT_TYPE_TO_CANONICAL.keys())


def specs_by_name() -> dict[str, EventTypeSpec]:
    """Expose a copy of the canonical registry keyed by canonical name."""

    return dict(EVENT_TYPE_BY_NAME)


def event_type_examples(*, include_aliases: bool = False) -> list[str]:
    """Return representative event type examples for API schema docs."""

    values = list(ALL_EVENT_TYPES)
    if include_aliases:
        values.extend(LEGACY_EVENT_TYPE_TO_CANONICAL.keys())
    return values[:10]


def event_type_description(*, include_aliases: bool = False) -> str:
    """Build a compact description string for the API schema."""

    values = list(ALL_EVENT_TYPES)
    if include_aliases:
        values.extend(LEGACY_EVENT_TYPE_TO_CANONICAL.keys())
    return (
        "Canonical event types use the strict domain.subject.action contract with "
        "lowercase dot-separated segments. Supported canonical types: " + ", ".join(values)
    )
