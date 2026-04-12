"""Integration tests for post-adjudication domain event emission.

Verifies that after a trainer injects an intervention:
  1. patient.intervention.created is emitted immediately
  2. patient.recommendedintervention.removed is emitted for any stale recs
  3. patient.problem.updated is emitted with a complete payload that includes
     the post-adjudication recommended_interventions list
  4. /state/ reflects the adjudicated problem status without a further round-trip
"""

from unittest.mock import patch

from django.test import Client
import pytest

from api.v1.auth import create_access_token

# ---------------------------------------------------------------------------
# Fixtures — minimal copies of the shared set from tests/api/test_trainerlab.py
# ---------------------------------------------------------------------------


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Intervention Events Test Role")


@pytest.fixture
def instructor_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="intervention-events-instructor@example.com",
        role=user_role,
    )


@pytest.fixture
def instructor_membership(instructor_user):
    from apps.accounts.services import get_personal_account_for_user
    from apps.billing.catalog import ProductCode
    from apps.billing.models import Entitlement

    account = get_personal_account_for_user(instructor_user)
    return Entitlement.objects.create(
        account=account,
        source_type=Entitlement.SourceType.MANUAL,
        source_ref="manual:trainerlab-go",
        scope_type=Entitlement.ScopeType.USER,
        subject_user=instructor_user,
        product_code=ProductCode.TRAINERLAB_GO.value,
        status=Entitlement.Status.ACTIVE,
        portable_across_accounts=True,
    )


@pytest.fixture
def auth_client(instructor_user, instructor_membership):
    token = create_access_token(instructor_user)
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client


# ---------------------------------------------------------------------------
# Shared request helpers
# ---------------------------------------------------------------------------


def _create_session(client: Client, *, idempotency_key: str) -> dict:
    from apps.trainerlab.services import complete_initial_scenario_generation

    with patch(
        "apps.trainerlab.services.enqueue_initial_scenario_generation",
        return_value="test-call-id",
    ):
        response = client.post(
            "/api/v1/trainerlab/simulations/",
            data={
                "scenario_spec": {"diagnosis": "GSW", "tick_interval_seconds": 60},
                "directives": "",
                "modifiers": [],
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
    assert response.status_code in (200, 201), response.content
    payload = response.json()
    complete_initial_scenario_generation(simulation_id=payload["simulation_id"])
    return payload


def _post_injury(client: Client, *, simulation_id: int, idempotency_key: str):
    resp = client.post(
        f"/api/v1/trainerlab/simulations/{simulation_id}/events/injuries/",
        data={
            "injury_location": "LUL",
            "injury_kind": "GSW",
            "injury_description": "GSW left thigh",
            "description": "",
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )
    assert resp.status_code == 200, resp.content
    return resp


def _post_problem(
    client: Client,
    *,
    simulation_id: int,
    cause_id: int,
    idempotency_key: str,
):
    resp = client.post(
        f"/api/v1/trainerlab/simulations/{simulation_id}/events/problems/",
        data={
            "cause_kind": "injury",
            "cause_id": cause_id,
            "kind": "hemorrhage",
            "title": "Massive hemorrhage left thigh",
            "march_category": "M",
            "severity": "critical",
            "anatomical_location": "Left thigh",
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )
    assert resp.status_code == 200, resp.content
    return resp


def _post_tourniquet(
    client: Client,
    *,
    simulation_id: int,
    target_problem_id: int,
    idempotency_key: str,
    site_code: str = "LEFT_LEG",
):
    return client.post(
        f"/api/v1/trainerlab/simulations/{simulation_id}/events/interventions/",
        data={
            "intervention_type": "tourniquet",
            "site_code": site_code,
            "target_problem_id": target_problem_id,
            "status": "applied",
            "effectiveness": "unknown",
            "notes": "",
            "details": {"kind": "tourniquet", "version": 1, "application_mode": "deliberate"},
            "initiated_by_type": "user",
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


# ---------------------------------------------------------------------------
# Shared setup helper — creates session → injury → hemorrhage problem
# and returns (simulation_id, injury, problem)
# ---------------------------------------------------------------------------


def _setup_hemorrhage(client: Client, *, prefix: str):
    from apps.trainerlab.models import Injury, Problem

    session = _create_session(client, idempotency_key=f"{prefix}-session")
    sim_id = session["simulation_id"]

    _post_injury(client, simulation_id=sim_id, idempotency_key=f"{prefix}-injury")
    injury = Injury.objects.get(injury_description="GSW left thigh", simulation_id=sim_id)

    _post_problem(
        client, simulation_id=sim_id, cause_id=injury.id, idempotency_key=f"{prefix}-problem"
    )
    problem = Problem.objects.filter(simulation_id=sim_id, kind="hemorrhage").latest("timestamp")

    return sim_id, injury, problem


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestInterventionAdjudicationEvents:
    """Verify post-adjudication domain event emission for TrainerLab interventions."""

    def test_effective_intervention_emits_intervention_created(self, auth_client):
        """patient.intervention.created must be emitted for every successful intervention POST."""
        from apps.common.models import OutboxEvent

        sim_id, _injury, problem = _setup_hemorrhage(auth_client, prefix="tq-created")

        resp = _post_tourniquet(
            auth_client,
            simulation_id=sim_id,
            target_problem_id=problem.id,
            idempotency_key="tq-created-tq",
        )
        assert resp.status_code == 200

        event = OutboxEvent.objects.filter(
            simulation_id=sim_id,
            event_type="patient.intervention.created",
        ).first()
        assert event is not None
        assert event.payload["kind"] == "tourniquet"
        assert event.payload["site_code"] == "LEFT_LEG"
        assert event.payload["target_problem_previous_status"] == "active"
        assert event.payload["target_problem_current_status"] == "controlled"
        assert event.payload["adjudication_reason"] == "intervention_adjudicated"

    def test_effective_intervention_emits_problem_updated_with_controlled_status(self, auth_client):
        """patient.problem.updated must reflect the adjudicated (controlled) status."""
        from apps.common.models import OutboxEvent

        sim_id, _injury, problem = _setup_hemorrhage(auth_client, prefix="tq-prob-updated")
        original_problem_id = problem.id

        resp = _post_tourniquet(
            auth_client,
            simulation_id=sim_id,
            target_problem_id=problem.id,
            idempotency_key="tq-prob-updated-tq",
        )
        assert resp.status_code == 200

        event = OutboxEvent.objects.filter(
            simulation_id=sim_id,
            event_type="patient.problem.updated",
        ).first()
        assert event is not None, "patient.problem.updated event must be emitted"

        payload = event.payload
        assert payload["status"] == "controlled"
        assert payload["previous_status"] == "active"
        assert payload["adjudication_reason"] == "intervention_adjudicated"
        assert payload["triggering_intervention_id"] is not None
        # The superseding problem has a new ID — the original problem is now inactive
        assert payload["problem_id"] != original_problem_id

    def test_problem_updated_payload_includes_recommended_interventions(self, auth_client):
        """patient.problem.updated payload must contain a complete recommended_interventions
        list — not an empty array — so the iOS overlay can render it without guessing.

        The payload is emitted AFTER recompute_active_recommendations(), so the
        superseding problem's new recommendation rows are already in the DB when
        serialize_problem_snapshot() runs.
        """
        from apps.common.models import OutboxEvent
        from apps.trainerlab.models import Problem

        sim_id, _injury, problem = _setup_hemorrhage(auth_client, prefix="tq-recs-in-payload")

        resp = _post_tourniquet(
            auth_client,
            simulation_id=sim_id,
            target_problem_id=problem.id,
            idempotency_key="tq-recs-in-payload-tq",
        )
        assert resp.status_code == 200

        event = OutboxEvent.objects.filter(
            simulation_id=sim_id,
            event_type="patient.problem.updated",
        ).first()
        assert event is not None

        recs = event.payload.get("recommended_interventions")
        assert isinstance(recs, list), "recommended_interventions must be a list in the payload"
        assert len(recs) > 0, (
            "recommended_interventions must not be empty — payload is emitted after recompute"
        )

        # Every nested recommendation must target the NEW superseding problem
        new_problem = Problem.objects.get(pk=event.payload["problem_id"])
        for rec in recs:
            assert rec["target_problem_id"] == new_problem.id, (
                "nested recommendations must reference the superseding problem, not the old one"
            )

    def test_effective_intervention_emits_recommendation_removed_for_old_problem(self, auth_client):
        """After adjudication, recommendations for the deactivated problem are removed.

        patient.recommendedintervention.removed must be emitted for each stale
        recommendation whose target_problem is now inactive.
        """
        from apps.common.models import OutboxEvent
        from apps.trainerlab.models import RecommendedIntervention

        sim_id, _injury, problem = _setup_hemorrhage(auth_client, prefix="tq-rec-removed")
        original_problem_id = problem.id

        # After posting the problem, recompute_active_recommendations was already called
        # and created rule-based recommendations (tourniquet + pressure_dressing for hemorrhage).
        assert RecommendedIntervention.objects.filter(
            simulation_id=sim_id, target_problem_id=original_problem_id, is_active=True
        ).exists(), "rule-based recs must exist before the intervention"

        resp = _post_tourniquet(
            auth_client,
            simulation_id=sim_id,
            target_problem_id=problem.id,
            idempotency_key="tq-rec-removed-tq",
        )
        assert resp.status_code == 200

        removed_events = OutboxEvent.objects.filter(
            simulation_id=sim_id,
            event_type="patient.recommendedintervention.removed",
        )
        assert removed_events.exists(), (
            "patient.recommendedintervention.removed must be emitted for old recs"
        )
        # All removal events must reference the original (now-inactive) problem
        for ev in removed_events:
            assert ev.payload["target_problem_id"] == original_problem_id

    def test_intervention_event_emitted_before_problem_event(self, auth_client):
        """patient.intervention.created must appear in the event stream before
        patient.problem.updated — causal ordering must be preserved.
        """
        from apps.trainerlab.models import RuntimeEvent

        sim_id, _injury, problem = _setup_hemorrhage(auth_client, prefix="tq-ordering")

        resp = _post_tourniquet(
            auth_client,
            simulation_id=sim_id,
            target_problem_id=problem.id,
            idempotency_key="tq-ordering-tq",
        )
        assert resp.status_code == 200

        events = list(
            RuntimeEvent.objects.filter(
                simulation_id=sim_id,
                event_type__in=[
                    "patient.intervention.created",
                    "patient.problem.updated",
                ],
            ).order_by("created_at")
        )
        event_types = [e.event_type for e in events]
        assert "patient.intervention.created" in event_types
        assert "patient.problem.updated" in event_types

        intervention_pos = event_types.index("patient.intervention.created")
        problem_pos = [i for i, t in enumerate(event_types) if t == "patient.problem.updated"][-1]
        assert intervention_pos < problem_pos, (
            "patient.intervention.created must precede patient.problem.updated in stream order"
        )

    def test_ineffective_intervention_does_not_emit_problem_updated(self, auth_client):
        """When adjudication does not change the problem (wrong type), no
        patient.problem.updated event should be emitted.
        """
        from apps.common.models import OutboxEvent

        sim_id, _injury, problem = _setup_hemorrhage(auth_client, prefix="tq-no-effect")

        # chest_seal does not apply to hemorrhage — adjudication_reason will be
        # "intervention_not_applicable_to_problem_kind", changed=False
        resp = auth_client.post(
            f"/api/v1/trainerlab/simulations/{sim_id}/events/interventions/",
            data={
                "intervention_type": "chest_seal",
                "site_code": "LEFT_ANTERIOR_CHEST",
                "target_problem_id": problem.id,
                "status": "applied",
                "effectiveness": "unknown",
                "notes": "",
                "details": {"kind": "chest_seal", "version": 1},
                "initiated_by_type": "user",
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="tq-no-effect-chest-seal",
        )
        assert resp.status_code == 200

        assert OutboxEvent.objects.filter(
            simulation_id=sim_id, event_type="patient.intervention.created"
        ).exists()
        assert not OutboxEvent.objects.filter(
            simulation_id=sim_id, event_type="patient.problem.updated"
        ).exists(), "patient.problem.updated must NOT be emitted when adjudication has no effect"

    def test_state_reflects_controlled_problem_immediately_after_intervention(self, auth_client):
        """/state/ must show the superseding (controlled) problem immediately after
        the intervention POST — without requiring a second runtime tick.
        """
        sim_id, _injury, problem = _setup_hemorrhage(auth_client, prefix="tq-state")

        resp = _post_tourniquet(
            auth_client,
            simulation_id=sim_id,
            target_problem_id=problem.id,
            idempotency_key="tq-state-tq",
        )
        assert resp.status_code == 200

        state = auth_client.get(f"/api/v1/trainerlab/simulations/{sim_id}/state/").json()

        problems = state["scenario_snapshot"]["problems"]
        problem_statuses = {p["problem_id"]: p["status"] for p in problems}

        # The original active problem must be gone (it is now inactive)
        assert problem.id not in problem_statuses, (
            "The original hemorrhage problem must no longer appear in /state/ (it is now inactive)"
        )

        # A controlled hemorrhage problem must exist
        controlled = [p for p in problems if p["status"] == "controlled"]
        assert controlled, "/state/ must contain a controlled hemorrhage problem"
        assert controlled[0]["kind"] == "hemorrhage"

    def test_recommendation_created_for_superseding_problem(self, auth_client):
        """After adjudication, a new recommendation must be created that targets the
        superseding problem (not the original deactivated one).

        patient.recommendedintervention.created is emitted as part of
        recompute_active_recommendations() before the problem.updated event fires.
        """
        from apps.common.models import OutboxEvent

        sim_id, _injury, problem = _setup_hemorrhage(auth_client, prefix="tq-rec-created")
        original_problem_id = problem.id

        resp = _post_tourniquet(
            auth_client,
            simulation_id=sim_id,
            target_problem_id=problem.id,
            idempotency_key="tq-rec-created-tq",
        )
        assert resp.status_code == 200

        # Retrieve the new superseding problem ID from the problem.updated event
        problem_event = OutboxEvent.objects.filter(
            simulation_id=sim_id, event_type="patient.problem.updated"
        ).first()
        assert problem_event is not None
        new_problem_id = problem_event.payload["problem_id"]
        assert new_problem_id != original_problem_id

        # There must be at least one created event targeting the NEW superseding problem
        # (separate from the initial recommendation events emitted when the problem was first added)
        created_for_new_problem = OutboxEvent.objects.filter(
            simulation_id=sim_id,
            event_type="patient.recommendedintervention.created",
            payload__target_problem_id=new_problem_id,
        )
        assert created_for_new_problem.exists(), (
            "patient.recommendedintervention.created must be emitted targeting the "
            "superseding (controlled) problem after adjudication"
        )
