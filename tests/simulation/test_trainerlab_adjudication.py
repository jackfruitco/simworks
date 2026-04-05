from django.db import connection
from django.test.utils import CaptureQueriesContext
import pytest

from apps.trainerlab.adjudication import adjudicate_intervention
from apps.trainerlab.models import (
    EventSource,
    HeartRate,
    Illness,
    Injury,
    Intervention,
    PatientStatusState,
    Problem,
    PulseAssessment,
    RecommendedIntervention,
    RuntimeEvent,
    ScenarioBrief,
)
from apps.trainerlab.recommendations import validate_and_normalize_recommendation
from apps.trainerlab.runtime_llm import build_runtime_llm_context, compact_runtime_reasons
from apps.trainerlab.services import create_session, get_runtime_state
from apps.trainerlab.viewmodels import (
    build_scenario_snapshot,
    build_trainer_rest_view_model,
    build_trainer_watch_view_model,
    load_trainer_engine_aggregate,
)


@pytest.fixture
def simulation(db):
    from apps.accounts.models import User, UserRole
    from apps.simcore.models import Simulation

    role = UserRole.objects.create(title="TrainerLab Rule Tests")
    user = User.objects.create_user(
        email="trainerlab-rules@example.com",
        password="testpass123",
        role=role,
    )
    return Simulation.objects.create(user=user)


def _injury(simulation, *, description: str, location: str, kind: str) -> Injury:
    return Injury.objects.create(
        simulation=simulation,
        source=EventSource.SYSTEM,
        injury_location=location,
        injury_kind=kind,
        injury_description=description,
    )


def _problem(
    simulation,
    *,
    cause_injury: Injury | None = None,
    cause_illness: Illness | None = None,
    kind: str,
    title: str,
    march_category: str,
    anatomical_location: str = "",
) -> Problem:
    return Problem.objects.create(
        simulation=simulation,
        source=EventSource.SYSTEM,
        cause_injury=cause_injury,
        cause_illness=cause_illness,
        problem_kind=Problem.ProblemKind.INJURY if cause_injury else Problem.ProblemKind.ILLNESS,
        kind=kind,
        code=kind,
        title=title,
        display_name=title,
        description=title,
        march_category=march_category,
        severity=Problem.Severity.HIGH,
        anatomical_location=anatomical_location,
    )


def _intervention(
    simulation,
    *,
    problem: Problem,
    intervention_type: str,
    site_code: str,
    details: dict,
) -> Intervention:
    return Intervention.objects.create(
        simulation=simulation,
        source=EventSource.INSTRUCTOR,
        target_problem=problem,
        intervention_type=intervention_type,
        site_code=site_code,
        details_json=details,
        initiated_by_type=Intervention.InitiatedByType.USER,
        notes="Explicit intervention event",
    )


@pytest.mark.django_db
class TestTrainerLabAdjudication:
    def test_tourniquet_controls_hemorrhage_without_resolving_separate_wound_problem(
        self, simulation
    ):
        cause = _injury(
            simulation,
            description="GSW left thigh",
            location=Injury.InjuryLocation.LEG_LEFT_UPPER,
            kind=Injury.InjuryKind.GSW,
        )
        hemorrhage = _problem(
            simulation,
            cause_injury=cause,
            kind="hemorrhage",
            title="Massive hemorrhage from left thigh",
            march_category=Problem.MARCHCategory.M,
            anatomical_location="Left thigh",
        )
        open_wound = _problem(
            simulation,
            cause_injury=cause,
            kind="open_wound",
            title="Open wound left thigh",
            march_category=Problem.MARCHCategory.M,
            anatomical_location="Left thigh",
        )
        intervention = _intervention(
            simulation,
            problem=hemorrhage,
            intervention_type="tourniquet",
            site_code="LEFT_LEG",
            details={"kind": "tourniquet", "version": 1, "application_mode": "deliberate"},
        )

        result = adjudicate_intervention(intervention)

        hemorrhage.refresh_from_db()
        open_wound.refresh_from_db()
        intervention.refresh_from_db()
        adjudicated_problem = Problem.objects.get(pk=intervention.target_problem_id)
        assert result.changed is True
        assert hemorrhage.is_active is False
        assert adjudicated_problem.status == Problem.Status.CONTROLLED
        assert adjudicated_problem.triggering_intervention_id == intervention.id
        assert (
            adjudicated_problem.adjudication_rule_id == "intervention.tourniquet.targets.hemorrhage"
        )
        assert adjudicated_problem.supersedes_id == hemorrhage.id
        assert open_wound.status == Problem.Status.ACTIVE
        assert intervention.target_problem_previous_status == Problem.Status.ACTIVE
        assert intervention.target_problem_current_status == Problem.Status.CONTROLLED

    def test_wrong_site_or_wrong_intervention_does_not_change_problem(self, simulation):
        cause = _injury(
            simulation,
            description="GSW left thigh",
            location=Injury.InjuryLocation.LEG_LEFT_UPPER,
            kind=Injury.InjuryKind.GSW,
        )
        hemorrhage = _problem(
            simulation,
            cause_injury=cause,
            kind="hemorrhage",
            title="Massive hemorrhage from left thigh",
            march_category=Problem.MARCHCategory.M,
            anatomical_location="Left thigh",
        )
        wrong_site = _intervention(
            simulation,
            problem=hemorrhage,
            intervention_type="tourniquet",
            site_code="RIGHT_ARM",
            details={"kind": "tourniquet", "version": 1, "application_mode": "deliberate"},
        )
        wrong_type = _intervention(
            simulation,
            problem=hemorrhage,
            intervention_type="chest_seal",
            site_code="LEFT_ANTERIOR_CHEST",
            details={"kind": "chest_seal", "version": 1},
        )

        first = adjudicate_intervention(wrong_site)
        second = adjudicate_intervention(wrong_type)

        hemorrhage.refresh_from_db()
        assert first.changed is False
        assert second.changed is False
        assert hemorrhage.status == Problem.Status.ACTIVE

    def test_chest_seal_controls_open_chest_wound_without_resolving_respiratory_downstream_problem(
        self, simulation
    ):
        cause = _injury(
            simulation,
            description="GSW left chest",
            location=Injury.InjuryLocation.THORAX_LEFT_ANTERIOR,
            kind=Injury.InjuryKind.GSW,
        )
        open_chest_wound = _problem(
            simulation,
            cause_injury=cause,
            kind="open_chest_wound",
            title="Open chest wound",
            march_category=Problem.MARCHCategory.R,
            anatomical_location="Left anterior chest",
        )
        respiratory_distress = _problem(
            simulation,
            cause_injury=cause,
            kind="respiratory_distress",
            title="Respiratory distress",
            march_category=Problem.MARCHCategory.R,
            anatomical_location="Left chest",
        )
        intervention = _intervention(
            simulation,
            problem=open_chest_wound,
            intervention_type="chest_seal",
            site_code="LEFT_ANTERIOR_CHEST",
            details={"kind": "chest_seal", "version": 1},
        )

        result = adjudicate_intervention(intervention)

        open_chest_wound.refresh_from_db()
        respiratory_distress.refresh_from_db()
        adjudicated_problem = Problem.objects.get(pk=intervention.target_problem_id)
        assert result.changed is True
        assert open_chest_wound.is_active is False
        assert adjudicated_problem.status == Problem.Status.CONTROLLED
        assert respiratory_distress.status == Problem.Status.ACTIVE

    def test_antibiotics_mark_infectious_problem_treated_but_not_resolved(self, simulation):
        illness = Illness.objects.create(
            simulation=simulation,
            source=EventSource.SYSTEM,
            name="Sepsis",
            description="Suspected bacterial sepsis",
        )
        infection = _problem(
            simulation,
            cause_illness=illness,
            kind="infectious_process",
            title="Infectious process",
            march_category=Problem.MARCHCategory.C,
        )
        antibiotics = _intervention(
            simulation,
            problem=infection,
            intervention_type="antibiotics",
            site_code="SYSTEMIC",
            details={"kind": "antibiotics", "version": 1},
        )

        result = adjudicate_intervention(antibiotics)

        infection.refresh_from_db()
        antibiotics.refresh_from_db()
        adjudicated_problem = Problem.objects.get(pk=antibiotics.target_problem_id)
        assert result.changed is True
        assert infection.is_active is False
        assert adjudicated_problem.status == Problem.Status.TREATED
        assert adjudicated_problem.resolved_at is None
        assert antibiotics.target_problem_current_status == Problem.Status.TREATED

    def test_recommendation_normalization_accepts_free_text_and_rejects_invalid_kind(
        self, simulation
    ):
        cause = _injury(
            simulation,
            description="GSW left thigh",
            location=Injury.InjuryLocation.LEG_LEFT_UPPER,
            kind=Injury.InjuryKind.GSW,
        )
        hemorrhage = _problem(
            simulation,
            cause_injury=cause,
            kind="hemorrhage",
            title="Massive hemorrhage from left thigh",
            march_category=Problem.MARCHCategory.M,
            anatomical_location="Left thigh",
        )

        normalized = validate_and_normalize_recommendation(
            problem=hemorrhage,
            raw_kind="pressure dressing",
            raw_title="Pressure dressing to left thigh",
            raw_site="left_leg",
            rationale="Suggested by AI",
        )
        rejected = validate_and_normalize_recommendation(
            problem=hemorrhage,
            raw_kind="magic healing beam",
            raw_title="Magic healing beam",
        )

        assert normalized.accepted is True
        assert normalized.kind == "pressure_dressing"
        assert normalized.validation_status == "normalized"
        assert rejected.accepted is False
        assert rejected.validation_status == "rejected"

    def test_hypoperfusion_shock_accepts_access_recommendations_and_rejects_unrelated_kind(
        self, simulation
    ):
        cause = _injury(
            simulation,
            description="GSW left thigh",
            location=Injury.InjuryLocation.LEG_LEFT_UPPER,
            kind=Injury.InjuryKind.GSW,
        )
        shock = _problem(
            simulation,
            cause_injury=cause,
            kind="hypoperfusion_shock",
            title="Progressive hypoperfusion / shock",
            march_category=Problem.MARCHCategory.C,
            anatomical_location="Left thigh",
        )

        iv_access = validate_and_normalize_recommendation(
            problem=shock,
            raw_kind="IV Access",
            raw_title="Establish IV access",
        )
        io_access = validate_and_normalize_recommendation(
            problem=shock,
            raw_kind="io_access",
            raw_title="Establish IO access",
        )
        rejected = validate_and_normalize_recommendation(
            problem=shock,
            raw_kind="tourniquet",
            raw_title="Tourniquet for shock",
        )

        assert iv_access.accepted is True
        assert iv_access.kind == "iv_access"
        assert io_access.accepted is True
        assert io_access.kind == "io_access"
        assert rejected.accepted is False
        assert rejected.validation_status == "rejected"
        assert (
            rejected.metadata["rejection_reason"]
            == "'tourniquet' is not a valid recommendation for 'hypoperfusion_shock'"
        )

    def test_scenario_snapshot_builder_does_not_regress_into_n_plus_one(self, simulation):
        from apps.trainerlab.recommendations import validate_and_normalize_recommendation

        session = create_session(
            user=simulation.user,
            scenario_spec={},
            directives=None,
            modifiers=[],
        )
        cause = _injury(
            session.simulation,
            description="GSW left thigh",
            location=Injury.InjuryLocation.LEG_LEFT_UPPER,
            kind=Injury.InjuryKind.GSW,
        )
        for index in range(3):
            problem = _problem(
                session.simulation,
                cause_injury=cause,
                kind="hemorrhage" if index == 0 else "open_wound",
                title=f"Problem {index}",
                march_category=Problem.MARCHCategory.M,
                anatomical_location="Left thigh",
            )
            normalized = validate_and_normalize_recommendation(
                problem=problem,
                raw_kind="tourniquet" if index == 0 else "pressure dressing",
                raw_title=f"Recommendation {index}",
                raw_site="left_leg",
            )
            from apps.trainerlab.models import RecommendedIntervention

            RecommendedIntervention.objects.create(
                simulation=session.simulation,
                source=EventSource.AI,
                kind=normalized.kind,
                code=normalized.code,
                slug=normalized.slug,
                title=normalized.title,
                display_name=normalized.display_name,
                target_problem=problem,
                target_injury=cause,
                recommendation_source=normalized.recommendation_source,
                validation_status=normalized.validation_status,
                normalized_kind=normalized.kind,
                normalized_code=normalized.code,
                site_code=normalized.site_code,
                site_label=normalized.site_label,
            )

        with CaptureQueriesContext(connection) as context:
            aggregate = load_trainer_engine_aggregate(session=session)
            snapshot = build_scenario_snapshot(aggregate).model_dump(mode="json")

        assert snapshot["causes"]
        assert snapshot["problems"]
        assert snapshot["recommended_interventions"]
        assert len(context) <= 20

    def test_patient_status_state_persists_only_structured_clinical_flags(self):
        field_names = {field.name for field in PatientStatusState._meta.fields}

        assert "avpu" in field_names
        assert "respiratory_distress" in field_names
        assert "hemodynamic_instability" in field_names
        assert "impending_pneumothorax" in field_names
        assert "tension_pneumothorax" in field_names
        assert "narrative" not in field_names
        assert "teaching_flags" not in field_names

    def test_scenario_snapshot_patient_status_uses_canonical_state_plus_problem_derivation(
        self, simulation
    ):
        session = create_session(
            user=simulation.user,
            scenario_spec={},
            directives="",
            modifiers=[],
        )
        cause = _injury(
            session.simulation,
            description="GSW left thigh",
            location=Injury.InjuryLocation.LEG_LEFT_UPPER,
            kind=Injury.InjuryKind.GSW,
        )
        _problem(
            session.simulation,
            cause_injury=cause,
            kind="hemorrhage",
            title="Massive hemorrhage",
            march_category=Problem.MARCHCategory.M,
            anatomical_location="Left thigh",
        )
        PatientStatusState.objects.create(
            simulation=session.simulation,
            source=EventSource.SYSTEM,
            avpu="verbal",
            respiratory_distress=False,
            hemodynamic_instability=False,
            impending_pneumothorax=False,
            tension_pneumothorax=False,
        )

        snapshot = build_scenario_snapshot(load_trainer_engine_aggregate(session=session))

        assert snapshot.patient_status.avpu == "verbal"
        assert snapshot.patient_status.hemodynamic_instability is True
        assert snapshot.patient_status.respiratory_distress is False

    def test_load_trainer_engine_aggregate_and_builders_stay_query_bounded(self, simulation):
        session = create_session(
            user=simulation.user,
            scenario_spec={},
            directives="",
            modifiers=[],
        )
        cause = _injury(
            session.simulation,
            description="GSW left thigh",
            location=Injury.InjuryLocation.LEG_LEFT_UPPER,
            kind=Injury.InjuryKind.GSW,
        )
        problem = _problem(
            session.simulation,
            cause_injury=cause,
            kind="hemorrhage",
            title="Massive hemorrhage",
            march_category=Problem.MARCHCategory.M,
            anatomical_location="Left thigh",
        )
        normalized = validate_and_normalize_recommendation(
            problem=problem,
            raw_kind="tourniquet",
            raw_title="Tourniquet",
            raw_site="left_leg",
        )
        RecommendedIntervention.objects.create(
            simulation=session.simulation,
            source=EventSource.SYSTEM,
            kind=normalized.kind,
            code=normalized.code,
            slug=normalized.slug,
            title=normalized.title,
            display_name=normalized.display_name,
            target_problem=problem,
            target_injury=cause,
            recommendation_source=normalized.recommendation_source,
            validation_status=normalized.validation_status,
            normalized_kind=normalized.kind,
            normalized_code=normalized.code,
            site_code=normalized.site_code,
            site_label=normalized.site_label,
        )
        HeartRate.objects.create(
            simulation=session.simulation,
            source=EventSource.SYSTEM,
            min_value=120,
            max_value=128,
        )
        ScenarioBrief.objects.create(
            simulation=session.simulation,
            source=EventSource.SYSTEM,
            read_aloud_brief="Casualty is bleeding from the left thigh in an exposed alley.",
        )

        with CaptureQueriesContext(connection) as context:
            aggregate = load_trainer_engine_aggregate(session=session)

        assert len(context) <= 21

        with CaptureQueriesContext(connection) as context:
            rest_view_model = build_trainer_rest_view_model(aggregate)
        assert len(context) == 0
        assert rest_view_model.scenario_snapshot.causes

        with CaptureQueriesContext(connection) as context:
            watch_view_model = build_trainer_watch_view_model(aggregate)
        assert len(context) == 0
        assert watch_view_model.scenario_snapshot.problems

    def test_runtime_event_timeline_window_is_chronological_with_true_total_count(self, simulation):
        from datetime import UTC, datetime, timedelta

        session = create_session(
            user=simulation.user,
            scenario_spec={},
            directives="",
            modifiers=[],
        )
        base_time = datetime(2030, 1, 1, tzinfo=UTC)
        total_events = 105
        baseline_events = RuntimeEvent.objects.filter(session=session).count()

        for sequence in range(total_events):
            runtime_event = RuntimeEvent.objects.create(
                session=session,
                simulation=session.simulation,
                event_type="trainerlab.runtime.note",
                payload={"sequence": sequence},
            )
            RuntimeEvent.objects.filter(pk=runtime_event.pk).update(
                created_at=base_time + timedelta(seconds=sequence)
            )

        aggregate = load_trainer_engine_aggregate(session=session, event_limit=100)

        with CaptureQueriesContext(connection) as context:
            rest_view_model = build_trainer_rest_view_model(aggregate)
        assert len(context) == 0

        sequences = [
            entry.payload["sequence"]
            for entry in rest_view_model.event_timeline.events
            if "sequence" in entry.payload
        ]
        assert len(sequences) == 100
        assert sequences == list(range(5, 105))
        assert rest_view_model.event_timeline.total_events == baseline_events + total_events

    def test_scenario_snapshot_patient_status_derives_from_active_problems_without_backfill(
        self, simulation
    ):
        session = create_session(
            user=simulation.user,
            scenario_spec={},
            directives="",
            modifiers=[],
        )
        cause = _injury(
            session.simulation,
            description="GSW left chest",
            location=Injury.InjuryLocation.THORAX_LEFT_ANTERIOR,
            kind=Injury.InjuryKind.GSW,
        )
        _problem(
            session.simulation,
            cause_injury=cause,
            kind="open_chest_wound",
            title="Open chest wound",
            march_category=Problem.MARCHCategory.R,
            anatomical_location="Left chest",
        )

        aggregate = load_trainer_engine_aggregate(session=session)
        snapshot = build_scenario_snapshot(aggregate)

        assert aggregate.patient_status is None
        assert snapshot.patient_status.impending_pneumothorax is True
        assert snapshot.patient_status.respiratory_distress is False
        assert snapshot.patient_status.narrative == "Patient status is being actively reassessed."

    def test_scenario_snapshot_patient_status_ignores_legacy_runtime_blobs(self, simulation):
        session = create_session(
            user=simulation.user,
            scenario_spec={},
            directives="",
            modifiers=[],
        )
        cause = _injury(
            session.simulation,
            description="GSW left chest",
            location=Injury.InjuryLocation.THORAX_LEFT_ANTERIOR,
            kind=Injury.InjuryKind.GSW,
        )
        _problem(
            session.simulation,
            cause_injury=cause,
            kind="open_chest_wound",
            title="Open chest wound",
            march_category=Problem.MARCHCategory.R,
            anatomical_location="Left chest",
        )
        state = get_runtime_state(session)
        state["snapshot_annotations"] = {
            "patient_status": {
                "avpu": "verbal",
                "narrative": "Legacy cached narrative from a pre-refactor session.",
                "teaching_flags": ["watch chest rise"],
            }
        }

        aggregate = load_trainer_engine_aggregate(session=session, runtime_state_override=state)
        snapshot = build_scenario_snapshot(aggregate)

        assert PatientStatusState.objects.filter(simulation=session.simulation).count() == 0
        assert aggregate.runtime_state == get_runtime_state(session)
        assert snapshot.patient_status.avpu is None
        assert snapshot.patient_status.impending_pneumothorax is True
        assert snapshot.patient_status.narrative == "Patient status is being actively reassessed."
        assert snapshot.patient_status.teaching_flags == []

    def test_runtime_llm_context_keeps_relevant_state_but_excludes_raw_snapshot_noise(
        self, simulation
    ):
        session = create_session(
            user=simulation.user,
            scenario_spec={},
            directives="",
            modifiers=[],
        )
        session.status = "running"
        session.save(update_fields=["status", "modified_at"])

        cause = _injury(
            session.simulation,
            description="GSW left thigh",
            location=Injury.InjuryLocation.LEG_LEFT_UPPER,
            kind=Injury.InjuryKind.GSW,
        )
        problem = _problem(
            session.simulation,
            cause_injury=cause,
            kind="hemorrhage",
            title="Massive hemorrhage",
            march_category=Problem.MARCHCategory.M,
            anatomical_location="Left thigh",
        )
        intervention = _intervention(
            session.simulation,
            problem=problem,
            intervention_type="tourniquet",
            site_code="LEFT_LEG",
            details={"kind": "tourniquet", "application_mode": "deliberate"},
        )

        old_hr = HeartRate.objects.create(
            simulation=session.simulation,
            source=EventSource.SYSTEM,
            min_value=92,
            max_value=96,
        )
        old_hr.is_active = False
        old_hr.save(update_fields=["is_active"])
        HeartRate.objects.create(
            simulation=session.simulation,
            source=EventSource.SYSTEM,
            supersedes=old_hr,
            min_value=128,
            max_value=136,
        )
        PulseAssessment.objects.create(
            simulation=session.simulation,
            source=EventSource.SYSTEM,
            location=PulseAssessment.Location.PEDAL_LEFT,
            present=False,
            description=PulseAssessment.Description.ABSENT,
            color_normal=False,
            color_description=PulseAssessment.ColorDescription.PALE,
            condition_normal=False,
            condition_description=PulseAssessment.ConditionDescription.CLAMMY,
            temperature_normal=False,
            temperature_description=PulseAssessment.TemperatureDescription.COOL,
        )

        state = get_runtime_state(session)
        state["intervention_effects"] = {
            str(intervention.id): {
                "status": "active",
                "clinical_effect": "Bleeding is slowing but shock risk remains.",
                "notes": "Observe distal perfusion.",
            }
        }
        snapshot = build_scenario_snapshot(
            load_trainer_engine_aggregate(session=session, runtime_state_override=state)
        ).model_dump(mode="json")
        context = build_runtime_llm_context(
            session,
            scenario_snapshot=snapshot,
            runtime_reasons=[
                {
                    "reason_kind": "intervention_recorded",
                    "payload": {
                        "event_kind": "intervention",
                        "domain_event_id": intervention.id,
                    },
                    "created_at": "2026-03-22T00:00:00Z",
                }
            ],
            active_elapsed_seconds=120,
        )

        context_json = str(context)
        assert context["active_elapsed_seconds"] == 120
        assert context["patient_status"]["hemodynamic_instability"] is True
        assert context["vitals_summary"]["heart_rate"]["trend"] == "up"
        assert context["interventions"][0]["clinical_effect"].startswith("Bleeding is slowing")
        assert context["pulse_summary"][0]["location"] == "pedal_left"
        assert "details" not in context_json
        assert "timestamp" not in context_json
        assert "source" not in context_json
        assert "display_name" not in context_json
        assert "slug" not in context_json

    def test_runtime_reason_compaction_deduplicates_and_prioritizes(self):
        reasons = [
            {
                "reason_kind": "tick",
                "payload": {"tick_nonce": 1},
                "created_at": "2026-03-22T00:00:00Z",
            }
            for _ in range(12)
        ]
        reasons.extend(
            [
                {
                    "reason_kind": "manual_tick",
                    "payload": {"triggered_at": "2026-03-22T00:01:00Z"},
                    "created_at": "2026-03-22T00:01:00Z",
                }
                for _ in range(4)
            ]
        )
        reasons.extend(
            [
                {
                    "reason_kind": "note_recorded",
                    "payload": {
                        "event_kind": "note",
                        "domain_event_id": 44,
                        "send_to_ai": True,
                        "content": "Need to reassess breathing after intervention.",
                    },
                    "created_at": "2026-03-22T00:01:05Z",
                },
                {
                    "reason_kind": "intervention_recorded",
                    "payload": {
                        "event_kind": "intervention",
                        "domain_event_id": 55,
                    },
                    "created_at": "2026-03-22T00:01:10Z",
                },
                {
                    "reason_kind": "steer_prompt",
                    "payload": {"command_id": "cmd-1", "prompt": "Focus on deterioration."},
                    "created_at": "2026-03-22T00:01:15Z",
                },
            ]
        )

        compacted = compact_runtime_reasons(reasons, max_reasons=8)

        assert len(compacted) <= 8
        assert sum(1 for item in compacted if item["reason_kind"] == "tick") == 1
        assert next(item for item in compacted if item["reason_kind"] == "tick")["count"] == 12
        assert sum(1 for item in compacted if item["reason_kind"] == "manual_tick") == 1
        assert any(item["reason_kind"] == "note_recorded" for item in compacted)
        assert any(item["reason_kind"] == "intervention_recorded" for item in compacted)
