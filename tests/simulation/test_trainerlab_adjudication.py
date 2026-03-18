from django.db import connection
from django.test.utils import CaptureQueriesContext
import pytest

from apps.trainerlab.adjudication import adjudicate_intervention
from apps.trainerlab.models import EventSource, Illness, Injury, Intervention, Problem
from apps.trainerlab.recommendations import validate_and_normalize_recommendation


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
        assert result.changed is True
        assert hemorrhage.status == Problem.Status.CONTROLLED
        assert hemorrhage.triggering_intervention_id == intervention.id
        assert hemorrhage.adjudication_rule_id == "intervention.tourniquet.targets.hemorrhage"
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
        assert result.changed is True
        assert open_chest_wound.status == Problem.Status.CONTROLLED
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
        assert result.changed is True
        assert infection.status == Problem.Status.TREATED
        assert infection.resolved_at is None
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

    def test_project_current_snapshot_does_not_regress_into_n_plus_one(self, simulation):
        from apps.trainerlab.recommendations import validate_and_normalize_recommendation
        from apps.trainerlab.services import create_session, project_current_snapshot

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
            snapshot = project_current_snapshot(session)

        assert snapshot["causes"]
        assert snapshot["problems"]
        assert snapshot["recommended_interventions"]
        assert len(context) <= 20
