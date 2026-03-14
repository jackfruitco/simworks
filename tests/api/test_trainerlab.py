"""Tests for TrainerLab API v1 endpoints."""

from itertools import islice

from django.test import Client
import pytest

from api.v1.auth import create_access_token


class FakeClock:
    def __init__(self):
        self.current = 0.0

    def monotonic(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.current += seconds


def decode_chunk(chunk) -> str:
    return chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk


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


def _create_session(client: Client, *, idempotency_key: str = "sess-create-1") -> dict:
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
    return response.json()


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

        first = _create_session(client, idempotency_key="session-create-a")
        assert first["status"] == "seeded"

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

        def _fake_enqueue(*, simulation):
            captured["simulation_id"] = simulation.id
            return "call-test-123"

        monkeypatch.setattr(
            "apps.trainerlab.services.enqueue_initial_scenario_generation",
            _fake_enqueue,
        )

        client = auth_client_factory(instructor_user)
        created = _create_session(client, idempotency_key="session-create-enqueue")

        assert captured["simulation_id"] == created["simulation_id"]

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

        first_event = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/injuries/",
            data={
                "injury_category": "M",
                "injury_location": "LUA",
                "injury_kind": "LAC",
                "injury_description": "Initial laceration",
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="injury-1",
        )
        assert first_event.status_code == 200

        first_injury = Injury.objects.get(injury_description="Initial laceration")
        assert first_injury.is_active is True

        second_event = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/injuries/",
            data={
                "injury_category": "M",
                "injury_location": "LUA",
                "injury_kind": "LAC",
                "injury_description": "Corrected laceration",
                "supersedes_event_id": first_injury.id,
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="injury-2",
        )
        assert second_event.status_code == 200

        first_injury.refresh_from_db()
        corrected = Injury.objects.get(injury_description="Corrected laceration")
        assert first_injury.is_active is False
        assert corrected.supersedes_event_id == first_injury.id

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

        first = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/injuries/",
            data={
                "injury_category": "M",
                "injury_location": "LUA",
                "injury_kind": "LAC",
                "injury_description": "Initial laceration",
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="injury-conflict",
        )
        assert first.status_code == 200

        second = client.post(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/injuries/",
            data={
                "injury_category": "M",
                "injury_location": "RUA",
                "injury_kind": "LAC",
                "injury_description": "Different injury",
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="injury-conflict",
        )
        assert second.status_code == 409

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
                "injury_category": "massive hemorrhage",
                "injury_location": "left upper arm",
                "injury_kind": "laceration",
                "injury_description": "Friendly label injury",
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="injury-friendly-1",
        )
        assert response.status_code == 200

        injury = Injury.objects.get(injury_description="Friendly label injury")
        assert injury.injury_category == "M"
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
                "injury_category": "massive hemorrhage",
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
            OutboxEvent.objects.filter(
                simulation_id=simulation_id,
                event_type__startswith="trainerlab.",
            )
            .order_by("created_at", "id")
            .last()
        )
        if anchor is None:
            anchor = OutboxEvent.objects.create(
                event_type="trainerlab.stream.anchor",
                simulation_id=simulation_id,
                payload={"status": "anchored"},
                idempotency_key=f"trainerlab.anchor:{simulation_id}",
            )

        streamed = OutboxEvent.objects.create(
            event_type="trainerlab.session.seeded",
            simulation_id=simulation_id,
            payload={"status": "seeded"},
            idempotency_key=f"trainerlab.seeded:{simulation_id}",
        )

        response = client.get(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/stream/?cursor={anchor.id}"
        )
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/event-stream")
        assert response["Cache-Control"] == "no-cache, no-transform"
        assert response["X-Accel-Buffering"] == "no"

        chunks = [decode_chunk(chunk) for chunk in islice(response.streaming_content, 3)]
        payload = "".join(chunks)

        assert chunks[0] == f"id: {streamed.id}\n"
        assert chunks[1] == "event: trainerlab\n"
        assert "trainerlab.session.seeded" in payload
        assert '"status": "seeded"' in payload

    def test_sse_stream_endpoint_emits_idle_keep_alive(
        self,
        auth_client_factory,
        instructor_user,
        instructor_membership,
        monkeypatch,
    ):
        from apps.common.models import OutboxEvent

        clock = FakeClock()
        monkeypatch.setattr("api.v1.sse.time.monotonic", clock.monotonic)
        monkeypatch.setattr("api.v1.sse.time.sleep", clock.sleep)

        client = auth_client_factory(instructor_user)
        session = _create_session(client, idempotency_key="sse-idle-session")
        simulation_id = session["simulation_id"]

        anchor = (
            OutboxEvent.objects.filter(
                simulation_id=simulation_id,
                event_type__startswith="trainerlab.",
            )
            .order_by("created_at", "id")
            .last()
        )
        if anchor is None:
            anchor = OutboxEvent.objects.create(
                event_type="trainerlab.stream.anchor",
                simulation_id=simulation_id,
                payload={"status": "anchored"},
                idempotency_key=f"trainerlab.idle.anchor:{simulation_id}",
            )

        response = client.get(
            f"/api/v1/trainerlab/simulations/{simulation_id}/events/stream/?cursor={anchor.id}"
        )

        first_chunk = decode_chunk(next(response.streaming_content))

        assert first_chunk == ": keep-alive\n\n"
        assert "event:" not in first_chunk
        assert clock.current == pytest.approx(10.0)


@pytest.mark.django_db
class TestTrainerLabDictionaries:
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
        data = response.json()
        group_names = {group["group"] for group in data}
        assert "Airway" in group_names
        airway_group = next(group for group in data if group["group"] == "Airway")
        airway_codes = {item["code"] for item in airway_group["items"]}
        assert "A-NPA" in airway_codes

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
