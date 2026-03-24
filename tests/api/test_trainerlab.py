"""Tests for TrainerLab API v1 endpoints."""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.test import Client
import pytest

from api.v1.auth import create_access_token
from apps.common.outbox.event_types import SIMULATION_STATUS_UPDATED


class FakeClock:
    def __init__(self):
        self.current = 0.0

    def monotonic(self) -> float:
        return self.current

    async def sleep(self, seconds: float) -> None:
        self.current += seconds


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Test Role TrainerLab")


@pytest.fixture
def instructor_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="trainer-instructor@example.com",
        role=user_role,
    )


@pytest.fixture
def viewer_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="trainer-viewer@example.com",
        role=user_role,
    )


@pytest.fixture
def non_member_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="trainer-none@example.com",
        role=user_role,
    )


@pytest.fixture
def other_instructor_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="trainer-other@example.com",
        role=user_role,
    )


@pytest.fixture
def billing_admin_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="trainer-billing@example.com",
        role=user_role,
    )


@pytest.fixture
def trainerlab_lab(db):
    from apps.accounts.models import Lab

    lab, _ = Lab.objects.get_or_create(
        slug="trainerlab",
        defaults={"display_name": "TrainerLab", "is_active": True},
    )
    return lab


@pytest.fixture
def instructor_membership(instructor_user, trainerlab_lab):
    from apps.accounts.models import LabMembership

    return LabMembership.objects.create(
        user=instructor_user,
        lab=trainerlab_lab,
        access_level=LabMembership.AccessLevel.INSTRUCTOR,
    )


@pytest.fixture
def other_instructor_membership(other_instructor_user, trainerlab_lab):
    from apps.accounts.models import LabMembership

    return LabMembership.objects.create(
        user=other_instructor_user,
        lab=trainerlab_lab,
        access_level=LabMembership.AccessLevel.INSTRUCTOR,
    )


@pytest.fixture
def viewer_membership(viewer_user, trainerlab_lab):
    from apps.accounts.models import LabMembership

    return LabMembership.objects.create(
        user=viewer_user,
        lab=trainerlab_lab,
        access_level=LabMembership.AccessLevel.VIEWER,
    )


@pytest.fixture
def auth_client_factory():
    def _build(user):
        token = create_access_token(user)
        client = Client()
        client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return client

    return _build


def _create_session(
    client: Client,
    *,
    idempotency_key: str = "sess-create-1",
    ready: bool = True,
    stub_enqueue: bool = True,
) -> dict:
    from apps.trainerlab.services import complete_initial_scenario_generation

    context = (
        patch(
            "apps.trainerlab.services.enqueue_initial_scenario_generation",
            return_value="test-call-id",
        )
        if stub_enqueue
        else nullcontext()
    )
    with context:
        response = client.post(
            "/api/v1/trainerlab/simulations/",
            data={
                "scenario_spec": {
                    "diagnosis": "Heat stroke",
                    "chief_complaint": "Altered mental status",
                    "tick_interval_seconds": 10,
                },
                "directives": "Initial directives",
                "modifiers": ["altitude", "dehydration"],
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
    assert response.status_code in (200, 201)
    payload = response.json()
    if ready:
        session = complete_initial_scenario_generation(simulation_id=payload["simulation_id"])
        assert session is not None
        payload["status"] = session.status
    return payload


def _post_injury_event(
    client: Client,
    *,
    simulation_id: int,
    idempotency_key: str,
    injury_location: str = "LUA",
    injury_kind: str = "LAC",
    injury_description: str = "Initial laceration",
    description: str = "",
    supersedes_event_id: int | None = None,
):
    data = {
        "injury_location": injury_location,
        "injury_kind": injury_kind,
        "injury_description": injury_description,
        "description": description,
    }
    if supersedes_event_id is not None:
        data["supersedes_event_id"] = supersedes_event_id
    return client.post(
        f"/api/v1/trainerlab/simulations/{simulation_id}/events/injuries/",
        data=data,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def _post_problem_event(
    client: Client,
    *,
    simulation_id: int,
    idempotency_key: str,
    cause_kind: str,
    cause_id: int,
    kind: str,
    title: str,
    march_category: str,
    severity: str = "moderate",
    description: str = "",
    anatomical_location: str = "",
    supersedes_event_id: int | None = None,
):
    data = {
        "cause_kind": cause_kind,
        "cause_id": cause_id,
        "kind": kind,
        "title": title,
        "march_category": march_category,
        "severity": severity,
        "description": description,
        "anatomical_location": anatomical_location,
    }
    if supersedes_event_id is not None:
        data["supersedes_event_id"] = supersedes_event_id
    return client.post(
        f"/api/v1/trainerlab/simulations/{simulation_id}/events/problems/",
        data=data,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )


def _inline_runtime_payload(
    *,
    intervention_event_id: int | None = None,
    target_event_id: int | None = None,
    cause_id: int | None = None,
) -> dict:
    return {
        "state_changes": {
            "problem_observations": [
                {
                    "observation": "new_problem",
                    "cause_kind": "injury",
                    "cause_id": cause_id,
                    "description": "Progressive shortness of breath from a worsening chest injury.",
                    "problem_kind": "respiratory_distress",
                    "title": "Respiratory distress",
                    "march_category": "R",
                    "severity": "high",
                    "anatomical_location": "Left Anterior Chest",
                },
                {
                    "observation": "worsening",
                    "target_problem_id": target_event_id,
                    "problem_kind": "open_chest_wound",
                    "title": "Open chest wound",
                    "march_category": "R",
                    "description": "Chest GSW with worsening respiratory compromise",
                    "anatomical_location": "Left Anterior Chest",
                    "severity": "high",
                },
            ]
            if target_event_id and cause_id
            else [],
            "vital_updates": [
                {
                    "vital_type": "respiratory_rate",
                    "min_value": 28,
                    "max_value": 34,
                    "lock_value": False,
                    "trend": "up",
                },
                {
                    "vital_type": "spo2",
                    "min_value": 84,
                    "max_value": 89,
                    "lock_value": False,
                    "trend": "down",
                },
            ],
            "finding_updates": [
                {
                    "action": "create",
                    "finding_kind": "diminished_breath_sounds",
                    "title": "Diminished breath sounds",
                    "description": "Reduced left-sided breath sounds on reassessment.",
                    "status": "worsening",
                    "severity": "high",
                    "target_problem_id": target_event_id,
                    "anatomical_location": "Left anterior chest",
                    "laterality": "left",
                }
            ]
            if target_event_id
            else [],
            "recommendation_suggestions": [
                {
                    "intervention_kind": "chest_seal",
                    "title": "Chest seal to left anterior chest",
                    "target_problem_id": target_event_id,
                    "rationale": "Open chest wound remains active and worsening.",
                    "priority": 1,
                    "site": "left_anterior_chest",
                }
            ]
            if target_event_id
            else [],
            "intervention_assessments": (
                [
                    {
                        "intervention_event_id": intervention_event_id,
                        "status": "effective",
                        "effectiveness": "effective",
                        "clinical_effect": "Bleeding control improved after proper placement.",
                        "notes": "Continue monitoring for re-bleed.",
                    }
                ]
                if intervention_event_id
                else []
            ),
        },
        "patient_status": {
            "respiratory_distress": True,
            "impending_pneumothorax": True,
            "narrative": "Breathing is worsening and the patient is moving toward a pneumothorax.",
            "teaching_flags": ["watch chest rise", "prepare decompression"],
        },
        "instructor_intent": {
            "summary": "Expect worsening breathing over the next minute.",
            "rationale": "The untreated chest injury is progressing despite recent interventions.",
            "trigger": "elapsed time with thoracic trauma",
            "eta_seconds": 45,
            "confidence": 0.82,
            "upcoming_changes": [
                "Higher respiratory distress",
                "Potential pneumothorax progression",
            ],
            "monitoring_focus": ["respiratory rate", "oxygen saturation"],
        },
        "rationale_notes": [
            "Monitor for asymmetric chest rise.",
            "Thoracic trauma is driving the current deterioration.",
        ],
        "llm_conditions_check": [{"key": "runtime_complete", "value": "true"}],
    }


@pytest.mark.django_db
class TestTrainerLabAccess:
    def test_access_requires_jwt(self):
        response = Client().get("/api/v1/trainerlab/access/me/")
        assert response.status_code == 401

    def test_access_rejects_session_auth(self, instructor_user, instructor_membership):
        client = Client()
        client.force_login(instructor_user)

        response = client.get("/api/v1/trainerlab/access/me/")
        assert response.status_code == 401

    def test_access_denies_non_member(self, auth_client_factory, non_member_user):
        client = auth_client_factory(non_member_user)
        response = client.get("/api/v1/trainerlab/access/me/")
        assert response.status_code == 403

    def test_access_denies_viewer(self, auth_client_factory, viewer_user, viewer_membership):
        client = auth_client_factory(viewer_user)
        response = client.get("/api/v1/trainerlab/access/me/")
        assert response.status_code == 403

    def test_access_allows_instructor(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        response = client.get("/api/v1/trainerlab/access/me/")

        assert response.status_code == 200
        body = response.json()
        assert body["lab_slug"] == "trainerlab"
        assert body["access_level"] == "instructor"

    @pytest.mark.parametrize(
        "product_code",
        (
            "trainerlab_go",
            "trainerlab_plus",
            "medsim_one",
            "medsim_one_plus",
        ),
    )
    def test_access_allows_catalog_backed_products(
        self,
        auth_client_factory,
        instructor_user,
        other_instructor_user,
        product_code,
    ):
        from apps.accounts.models import AccountMembership
        from apps.accounts.services import create_organization_account
        from apps.billing.models import Entitlement

        org_account = create_organization_account(
            name=f"Trainer Product {product_code}",
            owner_user=other_instructor_user,
        )
        AccountMembership.objects.create(
            account=org_account,
            user=instructor_user,
            invite_email=instructor_user.email,
            role=AccountMembership.Role.INSTRUCTOR,
            status=AccountMembership.Status.ACTIVE,
        )
        Entitlement.objects.create(
            account=org_account,
            source_type=Entitlement.SourceType.MANUAL,
            source_ref=f"manual:{product_code}",
            scope_type=Entitlement.ScopeType.ACCOUNT,
            product_code=product_code,
            status=Entitlement.Status.ACTIVE,
        )

        client = auth_client_factory(instructor_user)
        response = client.get(
            "/api/v1/trainerlab/access/me/",
            HTTP_X_ACCOUNT_UUID=str(org_account.uuid),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["lab_slug"] == "trainerlab"
        assert body["access_level"] == "instructor"

    def test_access_denies_billing_admin_account_member(
        self,
        auth_client_factory,
        instructor_user,
        billing_admin_user,
    ):
        from apps.accounts.models import AccountMembership
        from apps.accounts.services import create_organization_account
        from apps.billing.catalog import ProductCode
        from apps.billing.models import Entitlement

        org_account = create_organization_account(
            name="Trainer Billing Org", owner_user=instructor_user
        )
        AccountMembership.objects.create(
            account=org_account,
            user=billing_admin_user,
            invite_email=billing_admin_user.email,
            role=AccountMembership.Role.BILLING_ADMIN,
            status=AccountMembership.Status.ACTIVE,
        )
        Entitlement.objects.create(
            account=org_account,
            source_type=Entitlement.SourceType.MANUAL,
            source_ref="manual:trainerlab",
            scope_type=Entitlement.ScopeType.ACCOUNT,
            product_code=ProductCode.TRAINERLAB_GO.value,
            status=Entitlement.Status.ACTIVE,
        )

        client = auth_client_factory(billing_admin_user)
        response = client.get(
            "/api/v1/trainerlab/access/me/",
            HTTP_X_ACCOUNT_UUID=str(org_account.uuid),
        )

        assert response.status_code == 403


@pytest.mark.django_db
class TestTrainerLabSessionLifecycle:
    def test_create_session_requires_idempotency_key(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)

        response = client.post(
            "/api/v1/trainerlab/simulations/",
            data={"scenario_spec": {}, "directives": "", "modifiers": []},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_create_session_and_idempotent_retry(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.trainerlab.models import TrainerCommand, TrainerSession

        client = auth_client_factory(instructor_user)

        first = _create_session(
            client,
            idempotency_key="session-create-a",
            ready=False,
            stub_enqueue=False,
        )
        assert first["status"] == "seeding"

        second_response = client.post(
            "/api/v1/trainerlab/simulations/",
            data={
                "scenario_spec": {
                    "diagnosis": "Heat stroke",
                    "chief_complaint": "Altered mental status",
                    "tick_interval_seconds": 10,
                },
                "directives": "Initial directives",
                "modifiers": ["altitude", "dehydration"],
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="session-create-a",
        )

        assert second_response.status_code == 200
        second = second_response.json()
        assert second["simulation_id"] == first["simulation_id"]

        assert TrainerSession.objects.count() == 1
        assert TrainerCommand.objects.filter(idempotency_key="session-create-a").count() == 1

    def test_create_session_conflicting_retry_returns_409(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        _create_session(client, idempotency_key="session-create-conflict")

        response = client.post(
            "/api/v1/trainerlab/simulations/",
            data={
                "scenario_spec": {
                    "diagnosis": "Anaphylaxis",
                    "chief_complaint": "Shortness of breath",
                },
                "directives": "Different directives",
                "modifiers": ["rain"],
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="session-create-conflict",
        )

        assert response.status_code == 409

    def test_create_session_enqueues_initial_generation(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
        monkeypatch,
    ):
        captured: dict[str, int] = {}

        def _fake_enqueue(*, session, correlation_id=None, retryable=None):
            captured["simulation_id"] = session.simulation_id
            return "call-test-123"

        monkeypatch.setattr(
            "apps.trainerlab.services.enqueue_initial_scenario_generation",
            _fake_enqueue,
        )

        client = auth_client_factory(instructor_user)
        created = _create_session(
            client,
            idempotency_key="session-create-enqueue",
            ready=False,
            stub_enqueue=False,
        )

        assert captured["simulation_id"] == created["simulation_id"]

    def test_create_session_returns_seeding_and_blocks_mutations_until_ready(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        session = _create_session(
            client,
            idempotency_key="session-create-seeding-blocked",
            ready=False,
        )
        simulation_id = session["simulation_id"]

        start = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/run/start/",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="session-create-seeding-start",
        )
        assert start.status_code == 409
        assert "still generating" in start.content.decode("utf-8")

        note = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/notes/",
            data={"content": "Blocked until initial seeding completes."},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="session-create-seeding-note",
        )
        assert note.status_code == 409
        assert "still generating" in note.content.decode("utf-8")

    def test_retry_initial_endpoint_requeues_failed_trainerlab_session(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
        monkeypatch,
    ):
        from apps.trainerlab.models import TrainerSession
        from apps.trainerlab.services import fail_initial_scenario_generation

        captured: dict[str, int | None] = {"simulation_id": None}

        def _fake_enqueue(*, session, correlation_id=None, retryable=None):
            captured["simulation_id"] = session.simulation_id
            return "retry-call-123"

        monkeypatch.setattr(
            "apps.trainerlab.services.enqueue_initial_scenario_generation",
            _fake_enqueue,
        )

        client = auth_client_factory(instructor_user)
        session = _create_session(
            client,
            idempotency_key="session-create-initial-failure",
            ready=False,
            stub_enqueue=False,
        )
        simulation_id = session["simulation_id"]

        fail_initial_scenario_generation(
            simulation_id=simulation_id,
            reason_code="provider_timeout",
            reason_text="Timed out waiting for initial scenario generation.",
            retryable=True,
        )

        failed = client.get(f"/api/v1/trainerlab/simulations/{simulation_id}/")
        assert failed.status_code == 200
        assert failed.json()["status"] == "failed"
        assert failed.json()["retryable"] is True

        response = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/retry-initial/",
            content_type="application/json",
        )

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "seeding"
        assert captured["simulation_id"] == simulation_id

        trainer_session = TrainerSession.objects.get(simulation_id=simulation_id)
        trainer_session.simulation.refresh_from_db()
        assert trainer_session.status == "seeding"
        assert trainer_session.runtime_state_json["phase"] == "seeding"
        assert trainer_session.simulation.initial_retry_count == 1
        assert trainer_session.simulation.terminal_reason_code == ""

    def test_retry_initial_endpoint_rejects_non_retryable_initial_failure(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.trainerlab.services import fail_initial_scenario_generation

        client = auth_client_factory(instructor_user)
        session = _create_session(
            client,
            idempotency_key="session-create-non-retryable-failure",
            ready=False,
        )
        simulation_id = session["simulation_id"]

        fail_initial_scenario_generation(
            simulation_id=simulation_id,
            reason_code="provider_auth_or_request_error",
            reason_text="Provider rejected the request.",
            retryable=False,
        )

        failed = client.get(f"/api/v1/trainerlab/simulations/{simulation_id}/")
        assert failed.status_code == 200
        assert failed.json()["status"] == "failed"
        assert failed.json()["retryable"] is False

        retry = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/retry-initial/",
            content_type="application/json",
        )
        assert retry.status_code == 409

    def test_create_session_returns_failed_payload_when_enqueue_fails(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
        monkeypatch,
    ):
        from apps.trainerlab.services import fail_initial_scenario_generation

        def _fail_enqueue(*, session, correlation_id=None, retryable=None):
            fail_initial_scenario_generation(
                simulation_id=session.simulation_id,
                reason_code="provider_auth_or_request_error",
                reason_text="Provider rejected the request.",
                retryable=False,
                correlation_id=correlation_id,
            )
            return None

        monkeypatch.setattr(
            "apps.trainerlab.services.enqueue_initial_scenario_generation",
            _fail_enqueue,
        )

        client = auth_client_factory(instructor_user)
        response = client.post(
            "/api/v1/trainerlab/simulations/",
            data={
                "scenario_spec": {
                    "diagnosis": "Heat stroke",
                    "chief_complaint": "Altered mental status",
                    "tick_interval_seconds": 10,
                },
                "directives": "Initial directives",
                "modifiers": ["altitude", "dehydration"],
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="session-create-inline-enqueue-failure",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "failed"
        assert body["retryable"] is False
        assert (
            body["terminal_reason_code"]
            == "trainerlab_initial_generation_provider_auth_or_request_error"
        )

    def test_run_state_machine_and_summary(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="session-state-machine")
        simulation_id = session["simulation_id"]

        start = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/run/start/",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="run-start-1",
        )
        assert start.status_code == 200
        assert start.json()["status"] == "running"

        pause = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/run/pause/",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="run-pause-1",
        )
        assert pause.status_code == 200
        assert pause.json()["status"] == "paused"

        resume = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/run/resume/",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="run-resume-1",
        )
        assert resume.status_code == 200
        assert resume.json()["status"] == "running"

        stop = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/run/stop/",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="run-stop-1",
        )
        assert stop.status_code == 200
        assert stop.json()["status"] == "completed"

        summary = client.get(f"/api/v1/trainerlab/simulations/{simulation_id}/summary/")
        assert summary.status_code == 200
        body = summary.json()
        assert body["simulation_id"] == simulation_id
        assert body["status"] == "completed"

    def test_summary_returns_404_until_generated(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="summary-not-ready-session")
        simulation_id = session["simulation_id"]

        before_stop = client.get(f"/api/v1/trainerlab/simulations/{simulation_id}/summary/")
        assert before_stop.status_code == 404
        assert "Summary not generated" in before_stop.content.decode("utf-8")

        start = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/run/start/",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="summary-not-ready-start",
        )
        assert start.status_code == 200

        stop = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/run/stop/",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="summary-not-ready-stop",
        )
        assert stop.status_code == 200

        after_stop = client.get(f"/api/v1/trainerlab/simulations/{simulation_id}/summary/")
        assert after_stop.status_code == 200
        assert after_stop.json()["simulation_id"] == simulation_id

    def test_stop_clears_runtime_work_and_ignores_late_runtime_output(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.trainerlab.models import Illness, SessionStatus, TrainerSession
        from apps.trainerlab.services import apply_runtime_turn_output

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="session-stop-runtime-cleanup")
        simulation_id = session["simulation_id"]
        trainer_session = TrainerSession.objects.get(simulation_id=simulation_id)

        state = dict(trainer_session.runtime_state_json or {})
        state["state_revision"] = 4
        state["pending_runtime_reasons"] = [
            {"reason_kind": "adjustment", "payload": {"note": "Queued before stop"}}
        ]
        state["currently_processing_reasons"] = [
            {"reason_kind": "tick", "payload": {"tick_nonce": 1}}
        ]
        state["runtime_processing"] = True
        trainer_session.status = SessionStatus.RUNNING
        trainer_session.runtime_state_json = state
        trainer_session.save(update_fields=["status", "runtime_state_json", "modified_at"])

        stop = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/run/stop/",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="run-stop-runtime-cleanup",
        )
        assert stop.status_code == 200

        trainer_session.refresh_from_db()
        assert trainer_session.status == "completed"
        assert trainer_session.runtime_state_json["pending_runtime_reasons"] == []
        assert trainer_session.runtime_state_json["currently_processing_reasons"] == []
        assert trainer_session.runtime_state_json["runtime_processing"] is False
        assert len(trainer_session.runtime_state_json["last_discarded_runtime_reasons"]) == 2

        revision_before = trainer_session.runtime_state_json["state_revision"]
        apply_runtime_turn_output(
            session_id=trainer_session.id,
            output_payload=_inline_runtime_payload(),
            service_context={
                "session_id": trainer_session.id,
                "simulation_id": simulation_id,
                "correlation_id": "late-runtime-output",
            },
        )

        trainer_session.refresh_from_db()
        assert trainer_session.runtime_state_json["state_revision"] == revision_before
        assert not Illness.objects.filter(
            simulation_id=simulation_id,
            name="Respiratory distress",
            is_active=True,
        ).exists()

    def test_invalid_transition_returns_409(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="session-invalid-transition")

        response = client.post(
            f"/api/v1/trainerlab/simulations/{session['simulation_id']}/run/pause/",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="invalid-pause-before-start",
        )
        assert response.status_code == 409

    def test_run_command_rejects_same_key_for_different_session(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        first_session = _create_session(client, idempotency_key="session-run-target-a")
        second_session = _create_session(client, idempotency_key="session-run-target-b")

        first = client.post(
            f"/api/v1/trainerlab/simulations/{first_session['simulation_id']}/run/start/",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="run-start-conflict",
        )
        assert first.status_code == 200

        second = client.post(
            f"/api/v1/trainerlab/simulations/{second_session['simulation_id']}/run/start/",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="run-start-conflict",
        )
        assert second.status_code == 409


@pytest.mark.django_db
class TestTrainerLabEvents:
    def test_event_injection_superseding_and_cursor_list(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.trainerlab.models import Injury

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="event-session-1")
        simulation_id = session["simulation_id"]

        start = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/run/start/",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="event-run-start",
        )
        assert start.status_code == 200

        first_event = _post_injury_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="injury-1",
            injury_description="Initial laceration",
        )
        assert first_event.status_code == 200

        from apps.trainerlab.models import Problem

        first_injury = Injury.objects.get(injury_description="Initial laceration")
        first_problem_event = _post_problem_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="problem-1",
            cause_kind="injury",
            cause_id=first_injury.id,
            kind="hemorrhage",
            title="Left arm hemorrhage",
            march_category="M",
            severity="moderate",
            anatomical_location=first_injury.anatomical_location,
        )
        assert first_problem_event.status_code == 200
        first_problem = Problem.objects.get(cause_injury=first_injury)
        assert first_injury.is_active is True
        assert first_problem.is_active is True

        second_event = _post_injury_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="injury-2",
            injury_description="Corrected laceration",
            supersedes_event_id=first_injury.id,
        )
        assert second_event.status_code == 200

        corrected_injury = Injury.objects.get(injury_description="Corrected laceration")
        corrected_problem_event = _post_problem_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="problem-2",
            cause_kind="injury",
            cause_id=corrected_injury.id,
            kind="hemorrhage",
            title="Corrected left arm hemorrhage",
            march_category="M",
            severity="moderate",
            anatomical_location=corrected_injury.anatomical_location,
            supersedes_event_id=first_problem.id,
        )
        assert corrected_problem_event.status_code == 200

        first_injury.refresh_from_db()
        first_problem.refresh_from_db()
        corrected_problem = Problem.objects.get(cause_injury=corrected_injury)
        assert first_injury.is_active is False
        assert first_problem.is_active is False
        assert corrected_injury.supersedes_id == first_injury.id
        assert corrected_problem.supersedes_id == first_problem.id

        page_one = client.get(f"/api/v1/trainerlab/simulations/{simulation_id}/events/?limit=1")
        assert page_one.status_code == 200
        page_one_data = page_one.json()
        assert len(page_one_data["items"]) == 1
        assert page_one_data["has_more"] is True

        cursor = page_one_data["next_cursor"]
        page_two = client.get(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/?cursor={cursor}"
        )
        assert page_two.status_code == 200
        page_two_data = page_two.json()

        first_page_event_id = page_one_data["items"][0]["event_id"]
        second_page_ids = {item["event_id"] for item in page_two_data["items"]}
        assert first_page_event_id not in second_page_ids

    def test_problem_status_route_uses_problem_path_and_returns_status_fields(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.trainerlab.models import Injury, Problem

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="problem-status-session")
        simulation_id = session["simulation_id"]

        injury_response = _post_injury_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="problem-status-injury",
            injury_description="Left thigh gunshot wound",
            injury_location="LUL",
        )
        assert injury_response.status_code == 200

        injury = Injury.objects.get(injury_description="Left thigh gunshot wound")
        problem_response = _post_problem_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="problem-status-problem",
            cause_kind="injury",
            cause_id=injury.id,
            kind="hemorrhage",
            title="Left thigh hemorrhage",
            march_category="M",
            severity="critical",
            anatomical_location=injury.anatomical_location,
        )
        assert problem_response.status_code == 200

        problem = Problem.objects.get(title="Left thigh hemorrhage", is_active=True)
        response = client.patch(
            f"/api/v1/trainerlab/simulations/{simulation_id}/problems/{problem.id}/",
            data={"is_treated": True},
            content_type="application/json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["problem_id"] != problem.id
        assert body["is_treated"] is True
        assert body["is_controlled"] is False
        assert body["is_resolved"] is False
        assert body["status"] == "treated"
        assert body["label"] == "Left thigh hemorrhage"

    def test_steer_prompt_idempotent(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.trainerlab.models import TrainerCommand

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="steer-session")

        first = client.post(
            f"/api/v1/trainerlab/simulations/{session['simulation_id']}/steer/prompt/",
            data={"prompt": "Worsen airway patency over next 3 ticks"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="steer-1",
        )
        assert first.status_code == 200

        second = client.post(
            f"/api/v1/trainerlab/simulations/{session['simulation_id']}/steer/prompt/",
            data={"prompt": "Worsen airway patency over next 3 ticks"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="steer-1",
        )
        assert second.status_code == 200
        assert second.json()["command_id"] == first.json()["command_id"]

        assert TrainerCommand.objects.filter(idempotency_key="steer-1").count() == 1

    def test_steer_prompt_conflicting_retry_returns_409(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="steer-session-conflict")

        first = client.post(
            f"/api/v1/trainerlab/simulations/{session['simulation_id']}/steer/prompt/",
            data={"prompt": "Worsen airway patency over next 3 ticks"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="steer-conflict",
        )
        assert first.status_code == 200

        second = client.post(
            f"/api/v1/trainerlab/simulations/{session['simulation_id']}/steer/prompt/",
            data={"prompt": "Use a different instruction"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="steer-conflict",
        )
        assert second.status_code == 409

    def test_event_injection_conflicting_retry_returns_409(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="event-conflict-session")
        simulation_id = session["simulation_id"]

        first = _post_injury_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="injury-conflict",
            injury_description="Initial laceration",
        )
        assert first.status_code == 200

        second = _post_injury_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="injury-conflict",
            injury_location="RUA",
            injury_description="Different injury",
        )
        assert second.status_code == 409

    def test_note_event_persists_and_streams_without_ai_dispatch(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.common.models import OutboxEvent
        from apps.common.outbox.event_types import SIMULATION_NOTE_CREATED
        from apps.trainerlab.models import SimulationNote, TrainerSession

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="note-session")
        simulation_id = session["simulation_id"]

        anchor = (
            OutboxEvent.objects.filter(simulation_id=simulation_id)
            .order_by("created_at", "id")
            .last()
        )
        assert anchor is not None

        response = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/notes/",
            data={"content": "Instructor note for the timeline."},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="note-event-1",
        )

        assert response.status_code == 200

        note = SimulationNote.objects.get(content="Instructor note for the timeline.")
        assert note.source == "instructor"

        trainer_session = TrainerSession.objects.get(simulation_id=simulation_id)
        assert trainer_session.runtime_state_json.get("pending_runtime_reasons", []) == []

        outbox_event = OutboxEvent.objects.get(
            simulation_id=simulation_id,
            event_type=SIMULATION_NOTE_CREATED,
        )
        assert outbox_event.payload["content"] == "Instructor note for the timeline."
        assert outbox_event.payload["created_by_role"] == "instructor"

        listed = client.get(f"/api/v1/trainerlab/simulations/{simulation_id}/events/")
        assert listed.status_code == 200
        assert any(
            item["event_type"] == SIMULATION_NOTE_CREATED
            and item["payload"]["content"] == "Instructor note for the timeline."
            for item in listed.json()["items"]
        )

        from tests.helpers.sse import collect_streaming_chunks

        streamed = client.get(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/stream/?cursor={anchor.id}"
        )
        chunks = collect_streaming_chunks(streamed, 8)
        payload = "".join(chunks)
        assert SIMULATION_NOTE_CREATED in payload
        assert '"created_by_role": "instructor"' in payload

    def test_note_event_send_to_ai_queues_runtime_reason(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.trainerlab.models import TrainerSession

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="note-send-ai-session")
        simulation_id = session["simulation_id"]

        response = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/notes/",
            data={"content": "Send this note to the runtime AI.", "send_to_ai": True},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="note-send-ai-1",
        )

        assert response.status_code == 200

        trainer_session = TrainerSession.objects.get(simulation_id=simulation_id)
        pending = trainer_session.runtime_state_json.get("pending_runtime_reasons", [])
        assert len(pending) == 1
        assert pending[0]["reason_kind"] == "note_recorded"
        assert pending[0]["payload"]["event_kind"] == "note"
        assert pending[0]["payload"]["content"] == "Send this note to the runtime AI."
        assert pending[0]["payload"]["send_to_ai"] is True
        assert pending[0]["payload"]["note_id"] == pending[0]["payload"]["domain_event_id"]

    def test_note_event_idempotent_and_conflicting_retry_returns_409(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.trainerlab.models import SimulationNote

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="note-idempotent-session")
        simulation_id = session["simulation_id"]

        first = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/notes/",
            data={"content": "Repeated instructor note."},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="note-idempotent-1",
        )
        assert first.status_code == 200

        second = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/notes/",
            data={"content": "Repeated instructor note."},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="note-idempotent-1",
        )
        assert second.status_code == 200
        assert second.json()["command_id"] == first.json()["command_id"]
        assert SimulationNote.objects.filter(content="Repeated instructor note.").count() == 1

        conflict = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/notes/",
            data={"content": "Conflicting instructor note."},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="note-idempotent-1",
        )
        assert conflict.status_code == 409

    def test_note_event_rejects_blank_content(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="note-validation-session")

        response = client.post(
            f"/api/v1/trainerlab/simulations/{session['simulation_id']}/events/notes/",
            data={"content": "   "},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="note-validation-1",
        )

        assert response.status_code == 422
        assert "content" in response.content.decode("utf-8")

    def test_intervention_event_requires_target_problem_id_and_details(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.trainerlab.models import Injury, Problem

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="intervention-required-fields-session")
        simulation_id = session["simulation_id"]

        response = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/interventions/",
            data={
                "intervention_type": "tourniquet",
                "site_code": "left_arm",
                "status": "applied",
                "effectiveness": "unknown",
                "notes": "Missing required contract fields",
                "initiated_by_type": "user",
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="intervention-required-fields-1",
        )

        assert response.status_code == 422
        content = response.content.decode("utf-8")
        assert "target_problem_id" in content

        injury_resp = _post_injury_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="intervention-required-fields-injury",
            injury_location="LUL",
            injury_kind="GSW",
            injury_description="GSW to the left thigh",
        )
        assert injury_resp.status_code == 200
        cause = Injury.objects.get(injury_description="GSW to the left thigh")
        problem_resp = _post_problem_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="intervention-required-fields-problem",
            cause_kind="injury",
            cause_id=cause.id,
            kind="hemorrhage",
            title="Massive hemorrhage from left thigh",
            march_category="M",
            severity="critical",
            anatomical_location=cause.anatomical_location,
        )
        assert problem_resp.status_code == 200
        problem = Problem.objects.filter(simulation_id=simulation_id).latest("timestamp")

        missing_details = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/interventions/",
            data={
                "intervention_type": "tourniquet",
                "site_code": "left_arm",
                "target_problem_id": problem.id,
                "status": "applied",
                "effectiveness": "unknown",
                "notes": "Missing details payload",
                "initiated_by_type": "user",
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="intervention-required-fields-2",
        )

        assert missing_details.status_code == 422
        assert "details" in missing_details.content.decode("utf-8")

    def test_completed_session_allows_post_stop_notes_and_rejects_other_mutations(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.trainerlab.models import TrainerSession
        from apps.trainerlab.services import apply_debrief_output

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="post-stop-note-session")
        simulation_id = session["simulation_id"]

        stop = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/run/stop/",
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="post-stop-note-stop",
        )
        assert stop.status_code == 200

        trainer_session = TrainerSession.objects.get(simulation_id=simulation_id)
        apply_debrief_output(
            session_id=trainer_session.id,
            output_payload={
                "narrative_summary": "Baseline review before adding post-stop notes.",
                "strengths": ["Maintained scene control."],
                "misses": [],
                "deterioration_timeline": [],
                "teaching_points": ["Continue verbalizing reassessments."],
                "overall_assessment": "Baseline assessment",
                "llm_conditions_check": [],
            },
            correlation_id="post-stop-note-baseline",
        )

        note = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/notes/",
            data={"content": "Post-stop instructor note.", "send_to_ai": True},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="post-stop-note-1",
        )
        assert note.status_code == 200

        trainer_session.refresh_from_db()
        assert trainer_session.runtime_state_json["pending_runtime_reasons"] == []

        summary = client.get(f"/api/v1/trainerlab/simulations/{simulation_id}/summary/")
        assert summary.status_code == 200
        summary_body = summary.json()
        assert any(
            item["content"] == "Post-stop instructor note." for item in summary_body["notes"]
        )
        assert summary_body["ai_debrief"]["overall_assessment"] == "Baseline assessment"

        injury = _post_injury_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="post-stop-injury",
            injury_description="Should be rejected after stop",
        )
        assert injury.status_code == 409

        steer = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/steer/prompt/",
            data={"prompt": "This should not be accepted after stop"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="post-stop-steer",
        )
        assert steer.status_code == 409

        adjust = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/adjust/",
            data={"target": "note", "direction": "add", "note": "Rejected after stop"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="post-stop-adjust",
        )
        assert adjust.status_code == 409

    def test_adjust_simulation_conflicting_retry_returns_409(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="adjust-conflict-session")
        simulation_id = session["simulation_id"]

        first = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/adjust/",
            data={
                "target": "note",
                "direction": "add",
                "note": "Increase confusion over the next minute",
                "metadata": {"severity": "moderate"},
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="adjust-conflict",
        )
        assert first.status_code == 200

        second = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/adjust/",
            data={
                "target": "note",
                "direction": "add",
                "note": "Use a different adjustment",
                "metadata": {"severity": "high"},
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="adjust-conflict",
        )
        assert second.status_code == 409

    def test_injury_event_accepts_friendly_labels(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.trainerlab.models import Injury

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="event-friendly-label-session")
        simulation_id = session["simulation_id"]

        response = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/injuries/",
            data={
                "injury_location": "left upper arm",
                "injury_kind": "laceration",
                "injury_description": "Friendly label injury",
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="injury-friendly-1",
        )
        assert response.status_code == 200

        injury = Injury.objects.get(injury_description="Friendly label injury")
        assert injury.injury_location == "LUA"
        assert injury.injury_kind == "LAC"

    def test_injury_event_rejects_unknown_label(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="event-invalid-label-session")
        simulation_id = session["simulation_id"]

        response = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/injuries/",
            data={
                "injury_location": "not-a-real-location",
                "injury_kind": "laceration",
                "injury_description": "Should fail",
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="injury-invalid-1",
        )
        assert response.status_code == 422
        assert "injury_location" in response.content.decode("utf-8")

    def test_sse_stream_endpoint_responds(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.common.models import OutboxEvent

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="sse-session")
        simulation_id = session["simulation_id"]

        anchor = (
            OutboxEvent.objects.filter(simulation_id=simulation_id)
            .order_by("created_at", "id")
            .last()
        )
        if anchor is None:
            anchor = OutboxEvent.objects.create(
                event_type="stream.anchor",
                simulation_id=simulation_id,
                payload={"status": "anchored"},
                idempotency_key=f"stream.anchor:{simulation_id}",
            )

        streamed = OutboxEvent.objects.create(
            event_type=SIMULATION_STATUS_UPDATED,
            simulation_id=simulation_id,
            payload={"status": "seeded", "phase": "seeded"},
            idempotency_key=f"{SIMULATION_STATUS_UPDATED}:{simulation_id}:streamed",
        )

        response = client.get(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/stream/?cursor={anchor.id}"
        )
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/event-stream")
        assert response["Cache-Control"] == "no-cache, no-transform"
        assert response["X-Accel-Buffering"] == "no"

        from tests.helpers.sse import collect_streaming_chunks

        chunks = collect_streaming_chunks(response, 8)
        payload = "".join(chunks)

        assert f"id: {streamed.id}\n" in payload
        assert "event: sim\n" in payload
        assert SIMULATION_STATUS_UPDATED in payload
        assert '"status": "seeded"' in payload

    def test_sse_stream_endpoint_emits_idle_keep_alive(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
        monkeypatch,
    ):
        from apps.common.models import OutboxEvent
        from tests.helpers.sse import collect_streaming_chunks

        def _fake_enqueue(*, session, correlation_id=None, retryable=None):
            return "call-test-idle-keepalive"

        monkeypatch.setattr(
            "apps.trainerlab.services.enqueue_initial_scenario_generation",
            _fake_enqueue,
        )

        clock = FakeClock()
        monkeypatch.setattr("api.v1.sse.time.monotonic", clock.monotonic)
        monkeypatch.setattr("api.v1.sse.asyncio.sleep", clock.sleep)

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="sse-idle-session")
        simulation_id = session["simulation_id"]

        anchor = (
            OutboxEvent.objects.filter(simulation_id=simulation_id)
            .order_by("created_at", "id")
            .last()
        )
        if anchor is None:
            anchor = OutboxEvent.objects.create(
                event_type="stream.anchor",
                simulation_id=simulation_id,
                payload={"status": "anchored"},
                idempotency_key=f"stream.anchor.idle:{simulation_id}",
            )

        response = client.get(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/stream/?cursor={anchor.id}"
        )

        chunks = collect_streaming_chunks(response, 1)
        first_chunk = chunks[0]

        assert first_chunk == ": keep-alive\n\n"
        assert "event:" not in first_chunk
        assert clock.current == pytest.approx(0.0)


@pytest.mark.django_db
class TestTrainerLabDictionaries:
    def test_state_endpoint_returns_structured_defaults(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="state-defaults-session")

        response = client.get(f"/api/v1/trainerlab/simulations/{session['simulation_id']}/state/")

        assert response.status_code == 200
        body = response.json()
        assert body["simulation_id"] == session["simulation_id"]
        assert body["state_revision"] == 0
        assert body["current_snapshot"]["causes"] == []
        assert body["current_snapshot"]["problems"] == []
        assert body["current_snapshot"]["recommended_interventions"] == []
        assert body["current_snapshot"]["interventions"] == []
        assert body["current_snapshot"]["assessment_findings"] == []
        assert body["current_snapshot"]["diagnostic_results"] == []
        assert body["current_snapshot"]["resources"] == []
        assert body["current_snapshot"]["disposition"] is None
        assert body["current_snapshot"]["vitals"] == []
        assert body["pending_runtime_reasons"] == []

    def test_control_plane_debug_endpoint_returns_defaults(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="control-plane-defaults-session")
        response = client.get(
            f"/api/v1/trainerlab/simulations/{session['simulation_id']}/control-plane/"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["execution_plan"] == ["core_runtime", "vitals", "recommendation", "narrative"]
        assert body["current_step_index"] == 0
        assert body["queued_reasons"] == []
        assert body["currently_processing_reasons"] == []
        assert body["last_processed_reasons"] == []

    def test_intervention_event_captures_structured_fields_and_queues_reason(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.common.models import OutboxEvent
        from apps.trainerlab.models import Injury, Intervention, Problem, TrainerSession

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="intervention-runtime-fields")
        simulation_id = session["simulation_id"]
        injury_resp = _post_injury_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="intervention-runtime-fields-injury",
            injury_location="LUL",
            injury_kind="GSW",
            injury_description="GSW to the left thigh",
        )
        assert injury_resp.status_code == 200
        cause = Injury.objects.get(injury_description="GSW to the left thigh")
        problem_resp = _post_problem_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="intervention-runtime-fields-problem",
            cause_kind="injury",
            cause_id=cause.id,
            kind="hemorrhage",
            title="Massive hemorrhage from left thigh",
            march_category="M",
            severity="critical",
            anatomical_location=cause.anatomical_location,
        )
        assert problem_resp.status_code == 200
        problem_id = Problem.objects.filter(simulation_id=simulation_id).latest("timestamp").id

        response = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/interventions/",
            data={
                "intervention_type": "tourniquet",
                "site_code": "left_arm",
                "target_problem_id": problem_id,
                "status": "applied",
                "effectiveness": "unknown",
                "notes": "Tourniquet placed high and tight",
                "details": {"kind": "tourniquet", "version": 1, "application_mode": "deliberate"},
                "initiated_by_type": "user",
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="intervention-runtime-fields-1",
        )

        assert response.status_code == 200

        intervention = Intervention.objects.get(intervention_type="tourniquet")
        assert intervention.site_code == "LEFT_ARM"
        assert intervention.effectiveness == "unknown"
        assert intervention.initiated_by_type == "user"
        assert intervention.code == "M-TQ-D"

        trainer_session = TrainerSession.objects.get(simulation_id=simulation_id)
        pending = trainer_session.runtime_state_json.get("pending_runtime_reasons", [])
        assert pending
        assert pending[-1]["reason_kind"] == "intervention_recorded"

        state = client.get(f"/api/v1/trainerlab/simulations/{simulation_id}/state/").json()
        assert state["pending_runtime_reasons"][-1]["reason_kind"] == "intervention_recorded"

        # Verify the outbox event payload from _inject_event_core has structured fields
        outbox_event = OutboxEvent.objects.filter(
            simulation_id=simulation_id,
            event_type="patient.intervention.created",
        ).first()
        assert outbox_event is not None
        assert outbox_event.payload["kind"] == "tourniquet"
        assert outbox_event.payload["site_code"] == "LEFT_ARM"
        assert outbox_event.payload["effectiveness"] == "unknown"
        assert "effective" not in outbox_event.payload

    def test_tourniquet_details_require_application_mode(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.trainerlab.models import Injury, Problem

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="tourniquet-detail-validation")
        simulation_id = session["simulation_id"]

        injury_resp = _post_injury_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="tourniquet-detail-validation-injury",
            injury_location="LUL",
            injury_kind="GSW",
            injury_description="GSW to the left thigh",
        )
        assert injury_resp.status_code == 200
        cause = Injury.objects.get(injury_description="GSW to the left thigh")
        problem_resp = _post_problem_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="tourniquet-detail-validation-problem",
            cause_kind="injury",
            cause_id=cause.id,
            kind="hemorrhage",
            title="Massive hemorrhage from left thigh",
            march_category="M",
            severity="critical",
            anatomical_location=cause.anatomical_location,
        )
        assert problem_resp.status_code == 200
        problem = Problem.objects.filter(simulation_id=simulation_id).latest("timestamp")

        response = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/interventions/",
            data={
                "intervention_type": "tourniquet",
                "site_code": "left_arm",
                "target_problem_id": problem.id,
                "status": "applied",
                "effectiveness": "unknown",
                "notes": "Missing tourniquet application mode",
                "details": {"kind": "tourniquet", "version": 1},
                "initiated_by_type": "user",
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="tourniquet-mode-required",
        )

        assert response.status_code == 422
        assert "application_mode" in response.content.decode("utf-8")

    def test_intervention_dictionary_endpoint_returns_structured_definitions(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)

        response = client.get("/api/v1/trainerlab/dictionaries/interventions/")

        assert response.status_code == 200
        definitions = response.json()
        assert isinstance(definitions, list)
        assert len(definitions) >= 18

        types = [d["intervention_type"] for d in definitions]
        assert "tourniquet" in types
        assert "chest_seal" in types
        assert "needle_decompression" in types
        assert "antibiotics" in types

        tq = next(d for d in definitions if d["intervention_type"] == "tourniquet")
        assert tq["label"] == "Tourniquet"
        assert {"code": "LEFT_ARM", "label": "Left Arm"} in tq["sites"]

    def test_runtime_worker_applies_mock_ai_output_and_emits_state_update(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
        monkeypatch,
    ):
        from apps.common.models import OutboxEvent
        from apps.trainerlab.models import (
            AssessmentFinding,
            Injury,
            Intervention,
            Problem,
            TrainerSession,
        )
        from apps.trainerlab.services import apply_runtime_turn_output, process_runtime_turn_queue

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="runtime-worker-session")
        simulation_id = session["simulation_id"]

        injury_resp = _post_injury_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="runtime-worker-injury",
            injury_location="TLA",
            injury_kind="GSW",
            injury_description="GSW to the left chest",
        )
        assert injury_resp.status_code == 200

        injury = Injury.objects.get(injury_description="GSW to the left chest")
        problem_resp = _post_problem_event(
            client,
            simulation_id=simulation_id,
            idempotency_key="runtime-worker-problem",
            cause_kind="injury",
            cause_id=injury.id,
            kind="open_chest_wound",
            title="Open chest wound",
            march_category="R",
            severity="moderate",
            anatomical_location=injury.anatomical_location,
        )
        assert problem_resp.status_code == 200
        problem = Problem.objects.get(cause_injury=injury, simulation_id=simulation_id)

        intervention_resp = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/interventions/",
            data={
                "intervention_type": "tourniquet",
                "site_code": "left_arm",
                "target_problem_id": problem.id,
                "status": "applied",
                "effectiveness": "unknown",
                "notes": "Tourniquet placed high and tight",
                "details": {"kind": "tourniquet", "version": 1, "application_mode": "deliberate"},
                "initiated_by_type": "user",
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="runtime-worker-intervention",
        )
        assert intervention_resp.status_code == 200

        trainer_session = TrainerSession.objects.get(simulation_id=simulation_id)
        intervention = Intervention.objects.filter(
            simulation_id=simulation_id, intervention_type="tourniquet"
        ).latest("timestamp")
        captured_batch: dict[str, object] = {}

        def _inline_enqueue(batch):
            captured_batch.update(batch)
            apply_runtime_turn_output(
                session_id=batch["session_id"],
                output_payload=_inline_runtime_payload(
                    intervention_event_id=intervention.id,
                    target_event_id=problem.id,
                    cause_id=injury.id,
                ),
                service_context={
                    "session_id": batch["session_id"],
                    "simulation_id": batch["simulation_id"],
                    "correlation_id": batch.get("correlation_id"),
                },
            )
            return "inline-runtime-call"

        monkeypatch.setattr(
            "apps.trainerlab.services.enqueue_runtime_turn_service_call", _inline_enqueue
        )

        class _FakeEncoding:
            def encode(self, text: str) -> list[int]:
                return list(range(max(1, len(text) // 4)))

        monkeypatch.setattr(
            "apps.trainerlab.runtime_llm._encoding_for_model",
            lambda model_name: _FakeEncoding(),
        )

        call_id = process_runtime_turn_queue(session_id=trainer_session.id)

        assert call_id == "inline-runtime-call"
        assert captured_batch["runtime_request_metrics"]["previous_response_id_present"] is False
        assert "runtime_llm_context" in captured_batch
        assert "current_snapshot" in captured_batch
        assert "pending_runtime_reasons" in captured_batch["runtime_llm_context"]
        assert "read_aloud_brief" not in str(captured_batch["runtime_llm_context"])

        trainer_session.refresh_from_db()
        current_snapshot = trainer_session.runtime_state_json["current_snapshot"]
        assert trainer_session.runtime_state_json["state_revision"] >= 4
        assert current_snapshot["patient_status"]["respiratory_distress"] is True
        assert current_snapshot["patient_status"]["impending_pneumothorax"] is True
        assert trainer_session.runtime_state_json["ai_plan"]["eta_seconds"] == 45
        assert trainer_session.runtime_state_json["pending_runtime_reasons"] == []
        assert trainer_session.runtime_state_json["currently_processing_reasons"] == []
        assert Problem.objects.filter(
            simulation_id=simulation_id,
            kind="respiratory_distress",
            is_active=True,
        ).exists()
        assert AssessmentFinding.objects.filter(
            simulation_id=simulation_id,
            kind="diminished_breath_sounds",
            is_active=True,
        ).exists()
        assert current_snapshot["recommended_interventions"]
        assert OutboxEvent.objects.filter(
            simulation_id=simulation_id,
            event_type="simulation.snapshot.updated",
        ).exists()

        intervention_recorded = OutboxEvent.objects.filter(
            simulation_id=simulation_id,
            event_type="patient.intervention.created",
        ).first()
        assert intervention_recorded is not None
        assert "effectiveness" in intervention_recorded.payload
        assert "effective" not in intervention_recorded.payload
        assert intervention_recorded.payload["kind"] == "tourniquet"
        assert intervention_recorded.payload["site_code"] == "LEFT_ARM"

    def test_active_elapsed_seconds_freeze_while_paused(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.trainerlab.models import SessionStatus, TrainerSession
        from apps.trainerlab.services import (
            _freeze_active_elapsed,
            _set_active_elapsed_anchor,
            get_active_elapsed_seconds,
            get_runtime_state,
        )

        start_at = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)
        pause_at = start_at + timedelta(seconds=30)
        much_later = pause_at + timedelta(minutes=3)

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="elapsed-paused-session")
        trainer_session = TrainerSession.objects.get(simulation_id=session["simulation_id"])
        trainer_session.status = SessionStatus.RUNNING
        anchored = _set_active_elapsed_anchor(
            trainer_session,
            state=get_runtime_state(trainer_session),
            now=start_at,
        )
        frozen = _freeze_active_elapsed(
            trainer_session,
            state=anchored,
            now=pause_at,
        )
        trainer_session.status = SessionStatus.PAUSED

        assert frozen["active_elapsed_seconds"] == 30
        assert (
            get_active_elapsed_seconds(
                trainer_session,
                state=frozen,
                now=much_later,
            )
            == 30
        )

    def test_apply_debrief_output_updates_summary(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.common.models import OutboxEvent
        from apps.trainerlab.models import TrainerRunSummary, TrainerSession
        from apps.trainerlab.services import apply_debrief_output, build_summary

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="debrief-output-session")
        trainer_session = TrainerSession.objects.get(simulation_id=session["simulation_id"])

        build_summary(session=trainer_session, generated_by=instructor_user)
        apply_debrief_output(
            session_id=trainer_session.id,
            output_payload={
                "narrative_summary": "The scenario progressed from thoracic trauma to respiratory compromise.",
                "strengths": ["Recognized the chest wound quickly."],
                "misses": ["Did not anticipate the pneumothorax early enough."],
                "deterioration_timeline": [
                    {
                        "title": "Breathing worsened",
                        "timestamp_label": "00:45",
                        "significance": "The patient entered respiratory distress.",
                    }
                ],
                "teaching_points": ["Discuss when needle decompression becomes appropriate."],
                "overall_assessment": "Strong initial recognition, but deterioration cues were missed.",
                "llm_conditions_check": [],
            },
            correlation_id="corr-debrief-1",
        )

        summary = TrainerRunSummary.objects.get(session=trainer_session)
        assert summary.summary_json["ai_debrief"]["overall_assessment"].startswith("Strong initial")

        trainer_session.refresh_from_db()
        assert trainer_session.runtime_state_json["summary_feedback"]["teaching_points"] == [
            "Discuss when needle decompression becomes appropriate."
        ]
        assert OutboxEvent.objects.filter(
            simulation_id=trainer_session.simulation_id,
            event_type="simulation.summary.updated",
        ).exists()

    def test_apply_debrief_output_emits_new_outbox_event_for_each_revision(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.common.models import OutboxEvent
        from apps.trainerlab.models import TrainerRunSummary, TrainerSession
        from apps.trainerlab.services import apply_debrief_output, build_summary

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="debrief-revision-session")
        trainer_session = TrainerSession.objects.get(simulation_id=session["simulation_id"])

        build_summary(session=trainer_session, generated_by=instructor_user)
        apply_debrief_output(
            session_id=trainer_session.id,
            output_payload={
                "narrative_summary": "First pass summary.",
                "strengths": ["Strong first look."],
                "misses": [],
                "deterioration_timeline": [],
                "teaching_points": ["Keep scanning vitals."],
                "overall_assessment": "First assessment",
                "llm_conditions_check": [],
            },
            correlation_id="debrief-revision-1",
        )
        apply_debrief_output(
            session_id=trainer_session.id,
            output_payload={
                "narrative_summary": "Second pass summary with updated context.",
                "strengths": ["Strong first look."],
                "misses": ["Delayed reassessment."],
                "deterioration_timeline": [],
                "teaching_points": ["Reassess sooner after interventions."],
                "overall_assessment": "Updated assessment",
                "llm_conditions_check": [],
            },
            correlation_id="debrief-revision-2",
        )

        summary = TrainerRunSummary.objects.get(session=trainer_session)
        assert summary.summary_json["ai_debrief_revision"] == 2
        assert summary.summary_json["ai_debrief"]["overall_assessment"] == "Updated assessment"

        events = list(
            OutboxEvent.objects.filter(
                simulation_id=trainer_session.simulation_id,
                event_type="simulation.summary.updated",
            ).order_by("created_at", "id")
        )
        assert len(events) >= 2
        assert events[-2].payload["ai_debrief_revision"] == 1
        assert events[-1].payload["ai_debrief_revision"] == 2

    def test_build_summary_preserves_notes_beyond_timeline_window(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.trainerlab.models import TrainerRunSummary, TrainerSession
        from apps.trainerlab.services import build_summary

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="note-summary-session")
        simulation_id = session["simulation_id"]

        for index in range(11):
            response = client.post(
                f"/api/v1/trainerlab/simulations/{simulation_id}/events/notes/",
                data={"content": f"Instructor note {index + 1}"},
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=f"note-summary-{index + 1}",
            )
            assert response.status_code == 200

        trainer_session = TrainerSession.objects.get(simulation_id=simulation_id)
        build_summary(session=trainer_session, generated_by=instructor_user)

        summary = TrainerRunSummary.objects.get(session=trainer_session)
        assert len(summary.summary_json["timeline_highlights"]) == 10
        assert len(summary.summary_json["notes"]) == 11
        assert summary.summary_json["notes"][0]["content"] == "Instructor note 1"
        assert summary.summary_json["notes"][-1]["content"] == "Instructor note 11"

        summary_response = client.get(f"/api/v1/trainerlab/simulations/{simulation_id}/summary/")
        assert summary_response.status_code == 200
        assert len(summary_response.json()["notes"]) == 11

    def test_debrief_context_instruction_includes_summary_notes(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from asgiref.sync import async_to_sync

        from apps.trainerlab.models import TrainerSession
        from apps.trainerlab.orca.instructions.debrief import TrainerDebriefContextInstruction
        from apps.trainerlab.orca.services.debrief import GenerateTrainerRunDebrief
        from apps.trainerlab.services import build_summary

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="note-debrief-session")
        simulation_id = session["simulation_id"]

        response = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/notes/",
            data={"content": "Remember the trainee verbalized concern about breathing."},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="note-debrief-1",
        )
        assert response.status_code == 200

        trainer_session = TrainerSession.objects.get(simulation_id=simulation_id)
        build_summary(session=trainer_session, generated_by=instructor_user)

        service = GenerateTrainerRunDebrief(
            context={
                "simulation_id": simulation_id,
                "session_id": trainer_session.id,
            }
        )
        async_to_sync(service._aprepare_context)()

        assert service.context["notes"][0]["content"] == (
            "Remember the trainee verbalized concern about breathing."
        )
        rendered = TrainerDebriefContextInstruction.render_instruction(service)
        assert "Instructor notes JSON" in rendered
        assert "Remember the trainee verbalized concern about breathing." in rendered

    def test_injury_dictionary_contains_curated_regions(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        response = client.get("/api/v1/trainerlab/dictionaries/injuries/")
        assert response.status_code == 200
        data = response.json()
        region_codes = {item["code"] for item in data["regions"]}
        assert "LHA" in region_codes
        assert "RFT" in region_codes

    def test_intervention_dictionary_contains_airway_group(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        client = auth_client_factory(instructor_user)
        response = client.get("/api/v1/trainerlab/dictionaries/interventions/")
        assert response.status_code == 200
        interventions = response.json()
        assert isinstance(interventions, list)
        types = {item["intervention_type"] for item in interventions}
        assert "npa" in types
        npa = next(item for item in interventions if item["intervention_type"] == "npa")
        assert npa["label"]
        assert isinstance(npa["sites"], list)

    def test_injury_dictionary_matches_shared_mapping(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        from apps.trainerlab.injury_dictionary import get_injury_dictionary_choices

        client = auth_client_factory(instructor_user)
        response = client.get("/api/v1/trainerlab/dictionaries/injuries/")
        assert response.status_code == 200
        data = response.json()
        expected = get_injury_dictionary_choices()

        for key in ("categories", "regions", "kinds"):
            expected_pairs = {(code, label) for code, label in expected[key]}
            actual_pairs = {(item["code"], item["label"]) for item in data[key]}
            assert actual_pairs == expected_pairs


@pytest.mark.django_db
class TestTrainerLabPresets:
    def test_preset_crud_share_duplicate_and_apply(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
        other_instructor_user,
        other_instructor_membership,
    ):
        from apps.trainerlab.models import TrainerSession

        owner_client = auth_client_factory(instructor_user)
        other_client = auth_client_factory(other_instructor_user)

        created = owner_client.post(
            "/api/v1/trainerlab/presets/",
            data={
                "title": "Massive bleed baseline",
                "description": "Initial preset",
                "instruction_text": "Start with moderate hemorrhage",
                "injuries": ["LUA"],
                "severity": "high",
                "metadata": {"source": "test"},
            },
            content_type="application/json",
        )
        assert created.status_code == 201
        preset = created.json()
        preset_id = preset["id"]

        listed = owner_client.get("/api/v1/trainerlab/presets/")
        assert listed.status_code == 200
        assert any(item["id"] == preset_id for item in listed.json()["items"])

        shared = owner_client.post(
            f"/api/v1/trainerlab/presets/{preset_id}/share/",
            data={"user_id": other_instructor_user.id, "can_read": True, "can_duplicate": True},
            content_type="application/json",
        )
        assert shared.status_code == 200
        assert shared.json()["user_id"] == other_instructor_user.id

        accessible = other_client.get(f"/api/v1/trainerlab/presets/{preset_id}/")
        assert accessible.status_code == 200

        duplicate = other_client.post(f"/api/v1/trainerlab/presets/{preset_id}/duplicate/")
        assert duplicate.status_code == 201
        assert duplicate.json()["owner_id"] == other_instructor_user.id

        session = _create_session(owner_client, idempotency_key="preset-apply-session")
        applied = owner_client.post(
            f"/api/v1/trainerlab/presets/{preset_id}/apply/",
            data={"simulation_id": session["simulation_id"]},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="preset-apply-1",
        )
        assert applied.status_code == 200

        trainer_session = TrainerSession.objects.get(simulation_id=session["simulation_id"])
        applied_presets = trainer_session.runtime_state_json.get("applied_presets", [])
        assert any(item["preset_id"] == preset_id for item in applied_presets)

    def test_unshare_removes_access(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
        other_instructor_user,
        other_instructor_membership,
    ):
        owner_client = auth_client_factory(instructor_user)
        other_client = auth_client_factory(other_instructor_user)

        created = owner_client.post(
            "/api/v1/trainerlab/presets/",
            data={"title": "Share test"},
            content_type="application/json",
        )
        preset_id = created.json()["id"]

        owner_client.post(
            f"/api/v1/trainerlab/presets/{preset_id}/share/",
            data={"user_id": other_instructor_user.id, "can_read": True},
            content_type="application/json",
        )
        assert other_client.get(f"/api/v1/trainerlab/presets/{preset_id}/").status_code == 200

        unshared = owner_client.post(
            f"/api/v1/trainerlab/presets/{preset_id}/unshare/",
            data={"user_id": other_instructor_user.id},
            content_type="application/json",
        )
        assert unshared.status_code == 204
        assert other_client.get(f"/api/v1/trainerlab/presets/{preset_id}/").status_code == 404

    def test_apply_preset_conflicting_retry_returns_409(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
    ):
        owner_client = auth_client_factory(instructor_user)

        first_preset = owner_client.post(
            "/api/v1/trainerlab/presets/",
            data={"title": "Preset A"},
            content_type="application/json",
        ).json()
        second_preset = owner_client.post(
            "/api/v1/trainerlab/presets/",
            data={"title": "Preset B"},
            content_type="application/json",
        ).json()

        session = _create_session(owner_client, idempotency_key="preset-apply-conflict-session")

        first = owner_client.post(
            f"/api/v1/trainerlab/presets/{first_preset['id']}/apply/",
            data={"simulation_id": session["simulation_id"]},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="preset-apply-conflict",
        )
        assert first.status_code == 200

        second = owner_client.post(
            f"/api/v1/trainerlab/presets/{second_preset['id']}/apply/",
            data={"simulation_id": session["simulation_id"]},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="preset-apply-conflict",
        )
        assert second.status_code == 409
