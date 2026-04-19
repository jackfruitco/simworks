"""Tests for feedback API endpoints.

Covers:
- POST /api/v1/feedback/           – create (auth, validation, sim/conv access)
- GET  /api/v1/feedback/categories/ – public category list
- GET  /api/v1/feedback/me/         – own submissions with pagination
- GET  /api/v1/feedback/staff/      – staff-only list with filters
"""

from django.test import Client
import pytest

from api.v1.auth import create_access_token


# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Test Role Feedback")


@pytest.fixture
def test_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="feedback_user@example.com",
        role=user_role,
    )


@pytest.fixture
def other_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="other_feedback@example.com",
        role=user_role,
    )


@pytest.fixture
def staff_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="staff_feedback@example.com",
        role=user_role,
        is_staff=True,
    )


@pytest.fixture
def auth_client(test_user):
    token = create_access_token(test_user)
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client


@pytest.fixture
def other_auth_client(other_user):
    token = create_access_token(other_user)
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client


@pytest.fixture
def staff_auth_client(staff_user):
    token = create_access_token(staff_user)
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client


@pytest.fixture
def simulation(test_user):
    from apps.simcore.models import Simulation

    return Simulation.objects.create(
        user=test_user,
        diagnosis="Pneumonia",
        chief_complaint="Cough",
        sim_patient_full_name="Alice Test",
    )


@pytest.fixture
def simulation_b(test_user):
    """A second simulation owned by test_user, used for mismatch tests."""
    from apps.simcore.models import Simulation

    return Simulation.objects.create(
        user=test_user,
        diagnosis="Fracture",
        chief_complaint="Pain",
        sim_patient_full_name="Bob Test",
    )


@pytest.fixture
def other_simulation(other_user):
    """A simulation owned by other_user; test_user has no access."""
    from apps.simcore.models import Simulation

    return Simulation.objects.create(
        user=other_user,
        diagnosis="Other Diagnosis",
        chief_complaint="Other Complaint",
        sim_patient_full_name="Charlie Test",
    )


@pytest.fixture
def conv_type(db):
    from apps.simcore.models import ConversationType

    ct, _ = ConversationType.objects.get_or_create(
        slug="simulated_patient_fb_test",
        defaults={
            "display_name": "Simulated Patient",
            "ai_persona": "patient",
            "locks_with_simulation": True,
            "available_in": ["chatlab"],
            "sort_order": 0,
        },
    )
    return ct


@pytest.fixture
def conversation(simulation, conv_type):
    """A conversation inside test_user's simulation."""
    from apps.simcore.models import Conversation

    return Conversation.objects.create(
        simulation=simulation,
        conversation_type=conv_type,
        display_name="Alice Test",
        display_initials="AT",
    )


@pytest.fixture
def conversation_in_b(simulation_b, conv_type):
    """A conversation inside simulation_b (also owned by test_user)."""
    from apps.simcore.models import Conversation

    return Conversation.objects.create(
        simulation=simulation_b,
        conversation_type=conv_type,
        display_name="Bob Test",
        display_initials="BT",
    )


@pytest.fixture
def other_conversation(other_simulation, conv_type):
    """A conversation inside other_user's simulation; test_user has no access."""
    from apps.simcore.models import Conversation

    return Conversation.objects.create(
        simulation=other_simulation,
        conversation_type=conv_type,
        display_name="Charlie Test",
        display_initials="CT",
    )


# ── POST /api/v1/feedback/ ────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateFeedback:
    """Tests for POST /api/v1/feedback/."""

    def test_create_no_simulation_succeeds(self, auth_client, test_user):
        """Authenticated user can submit general feedback without a simulation."""
        response = auth_client.post(
            "/api/v1/feedback/",
            data={"category": "other", "body": "Great app overall"},
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.json()
        assert data["category"] == "other"
        assert data["body"] == "Great app overall"
        assert data["status"] == "new"
        assert data["source"] == "in_app"
        assert data["simulation_id"] is None
        assert data["user_id"] == test_user.pk

    def test_create_with_own_simulation_succeeds(self, auth_client, simulation):
        """Authenticated user can submit feedback scoped to their own simulation."""
        response = auth_client.post(
            "/api/v1/feedback/",
            data={
                "category": "simulation_content",
                "body": "The patient dialog felt off",
                "simulation_id": simulation.pk,
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.json()
        assert data["simulation_id"] == simulation.pk

    def test_create_fails_unauthorized_simulation(self, auth_client, other_simulation):
        """Submitting feedback for another user's simulation returns 403."""
        response = auth_client.post(
            "/api/v1/feedback/",
            data={
                "category": "bug_report",
                "body": "Trying to attach to someone else's sim",
                "simulation_id": other_simulation.pk,
            },
            content_type="application/json",
        )

        assert response.status_code == 403

    def test_create_fails_nonexistent_simulation(self, auth_client):
        """Referencing a simulation that does not exist returns 404."""
        response = auth_client.post(
            "/api/v1/feedback/",
            data={
                "category": "other",
                "body": "Some feedback",
                "simulation_id": 999999,
            },
            content_type="application/json",
        )

        assert response.status_code == 404

    def test_create_fails_blank_body(self, auth_client):
        """Empty body is rejected with 400 (Pydantic min_length)."""
        response = auth_client.post(
            "/api/v1/feedback/",
            data={"category": "other", "body": ""},
            content_type="application/json",
        )

        assert response.status_code == 422

    def test_create_fails_whitespace_only_body(self, auth_client):
        """Whitespace-only body is rejected with 400 by endpoint validation."""
        response = auth_client.post(
            "/api/v1/feedback/",
            data={"category": "other", "body": "   \t\n  "},
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_create_fails_inaccessible_conversation(self, auth_client, other_conversation):
        """Referencing a conversation in another user's simulation returns 403."""
        response = auth_client.post(
            "/api/v1/feedback/",
            data={
                "category": "ux_issue",
                "body": "Attempted cross-user conversation reference",
                "conversation_id": other_conversation.pk,
            },
            content_type="application/json",
        )

        assert response.status_code == 403

    def test_create_fails_mismatched_conversation_simulation(
        self, auth_client, simulation, conversation_in_b
    ):
        """When both simulation_id and conversation_id are given, they must match."""
        response = auth_client.post(
            "/api/v1/feedback/",
            data={
                "category": "other",
                "body": "Mismatched IDs",
                "simulation_id": simulation.pk,
                "conversation_id": conversation_in_b.pk,
            },
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_create_succeeds_conversation_alone_inherits_simulation(
        self, auth_client, conversation
    ):
        """Providing conversation_id without simulation_id inherits the simulation."""
        response = auth_client.post(
            "/api/v1/feedback/",
            data={
                "category": "simulation_content",
                "body": "Feedback via conversation only",
                "conversation_id": conversation.pk,
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.json()
        assert data["conversation_id"] == conversation.pk
        assert data["simulation_id"] == conversation.simulation_id

    def test_create_unauthenticated_returns_401(self):
        """Unauthenticated request is rejected."""
        client = Client()
        response = client.post(
            "/api/v1/feedback/",
            data={"category": "other", "body": "Hello"},
            content_type="application/json",
        )

        assert response.status_code == 401

    def test_create_nonexistent_conversation_returns_404(self, auth_client):
        """Referencing a conversation that does not exist returns 404."""
        response = auth_client.post(
            "/api/v1/feedback/",
            data={"category": "other", "body": "Some feedback", "conversation_id": 999999},
            content_type="application/json",
        )

        assert response.status_code == 404


# ── Request metadata ──────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreateFeedbackMetadata:
    """Tests that structured metadata fields are captured correctly."""

    def test_structured_fields_populated_from_headers(self, test_user):
        """Custom request headers populate the model's structured metadata columns."""
        from apps.feedback.models import UserFeedback

        token = create_access_token(test_user)
        client = Client()
        client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"

        response = client.post(
            "/api/v1/feedback/",
            data={"category": "bug_report", "body": "Crash on load"},
            content_type="application/json",
            HTTP_X_APP_VERSION="2.4.1",
            HTTP_X_PLATFORM="ios",
            HTTP_X_OS_VERSION="17.2",
            HTTP_X_DEVICE_MODEL="iPhone16,1",
            HTTP_X_SESSION_ID="sess-abc-xyz",
        )

        assert response.status_code == 201
        fb = UserFeedback.objects.get(user=test_user)
        assert fb.client_version == "2.4.1"
        assert fb.client_platform == "ios"
        assert fb.os_version == "17.2"
        assert fb.device_model == "iPhone16,1"
        assert fb.session_identifier == "sess-abc-xyz"

    def test_unknown_platform_header_falls_back_to_unknown(self, auth_client, test_user):
        """An unrecognised X-Platform value is stored as 'unknown'."""
        from apps.feedback.models import UserFeedback

        response = auth_client.post(
            "/api/v1/feedback/",
            data={"category": "other", "body": "Platform test"},
            content_type="application/json",
            HTTP_X_PLATFORM="smartwatch",
        )

        assert response.status_code == 201
        fb = UserFeedback.objects.get(user=test_user)
        assert fb.client_platform == UserFeedback.ClientPlatform.UNKNOWN

    def test_context_json_contains_server_meta_and_client_context(self, auth_client, test_user):
        """context_json merges both server-side metadata and client-provided context."""
        from apps.feedback.models import UserFeedback

        response = auth_client.post(
            "/api/v1/feedback/",
            data={
                "category": "feature_request",
                "body": "Please add dark mode",
                "context": {"screen": "settings", "theme": "light"},
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        fb = UserFeedback.objects.get(user=test_user)
        # Server-populated keys are present.
        assert "request_path" in fb.context_json
        # Client-provided keys are preserved.
        assert fb.context_json.get("screen") == "settings"
        assert fb.context_json.get("theme") == "light"

    def test_admin_fields_not_accepted_from_client(self, auth_client):
        """status and source are always server-set; client values are ignored."""
        response = auth_client.post(
            "/api/v1/feedback/",
            # status and source are not in FeedbackCreate — Pydantic ignores extras.
            data={
                "category": "other",
                "body": "Test",
                "status": "resolved",
                "source": "admin",
                "severity": "critical",
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "new"
        assert data["source"] == "in_app"


# ── GET /api/v1/feedback/categories/ ─────────────────────────────────────────


@pytest.mark.django_db
class TestFeedbackCategories:
    def test_returns_all_category_choices(self):
        """Returns one entry per UserFeedback.Category choice, no auth required."""
        from apps.feedback.models import UserFeedback

        client = Client()
        response = client.get("/api/v1/feedback/categories/")

        assert response.status_code == 200
        data = response.json()
        expected_values = {v for v, _ in UserFeedback.Category.choices}
        returned_values = {item["value"] for item in data}
        assert returned_values == expected_values

    def test_each_category_has_value_and_label(self):
        """Every item in the response has value and label keys."""
        client = Client()
        response = client.get("/api/v1/feedback/categories/")

        assert response.status_code == 200
        for item in response.json():
            assert "value" in item
            assert "label" in item
            assert item["label"]  # non-empty label


# ── GET /api/v1/feedback/me/ ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestMyFeedback:
    """Tests for GET /api/v1/feedback/me/."""

    def test_returns_own_submissions_only(self, auth_client, test_user, other_user):
        """Only the authenticated user's submissions are returned."""
        from apps.feedback.models import UserFeedback

        UserFeedback.objects.create(
            user=test_user,
            category=UserFeedback.Category.OTHER,
            body="My feedback",
        )
        UserFeedback.objects.create(
            user=other_user,
            category=UserFeedback.Category.BUG_REPORT,
            body="Other user's feedback",
        )

        response = auth_client.get("/api/v1/feedback/me/")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["body"] == "My feedback"

    def test_pagination_basics(self, auth_client, test_user):
        """offset and limit control which records are returned."""
        from apps.feedback.models import UserFeedback

        for i in range(5):
            UserFeedback.objects.create(
                user=test_user,
                category=UserFeedback.Category.OTHER,
                body=f"Feedback {i}",
            )

        response = auth_client.get("/api/v1/feedback/me/?limit=2&offset=0")
        assert response.status_code == 200
        first_page = response.json()
        assert first_page["count"] == 2
        assert first_page["total"] == 5

        response = auth_client.get("/api/v1/feedback/me/?limit=2&offset=4")
        last_page = response.json()
        assert last_page["count"] == 1
        assert last_page["total"] == 5

    def test_unauthenticated_returns_401(self):
        client = Client()
        response = client.get("/api/v1/feedback/me/")
        assert response.status_code == 401


# ── GET /api/v1/feedback/staff/ ──────────────────────────────────────────────


@pytest.mark.django_db
class TestStaffFeedback:
    """Tests for GET /api/v1/feedback/staff/."""

    def test_non_staff_gets_403(self, auth_client):
        response = auth_client.get("/api/v1/feedback/staff/")
        assert response.status_code == 403

    def test_unauthenticated_returns_401(self):
        client = Client()
        response = client.get("/api/v1/feedback/staff/")
        assert response.status_code == 401

    def test_staff_sees_all_users_feedback(self, staff_auth_client, test_user, other_user):
        """Staff endpoint returns feedback from all users."""
        from apps.feedback.models import UserFeedback

        UserFeedback.objects.create(
            user=test_user, category=UserFeedback.Category.OTHER, body="User A"
        )
        UserFeedback.objects.create(
            user=other_user, category=UserFeedback.Category.BUG_REPORT, body="User B"
        )

        response = staff_auth_client.get("/api/v1/feedback/staff/")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2

    def test_filter_by_status(self, staff_auth_client, test_user):
        """status filter returns only matching records."""
        from apps.feedback.models import UserFeedback

        UserFeedback.objects.create(
            user=test_user,
            category=UserFeedback.Category.OTHER,
            body="New item",
            status=UserFeedback.Status.NEW,
        )
        UserFeedback.objects.create(
            user=test_user,
            category=UserFeedback.Category.OTHER,
            body="Triaged item",
            status=UserFeedback.Status.TRIAGED,
        )

        response = staff_auth_client.get("/api/v1/feedback/staff/?status=new")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["status"] == "new"

    def test_filter_by_category(self, staff_auth_client, test_user):
        """category filter returns only matching records."""
        from apps.feedback.models import UserFeedback

        UserFeedback.objects.create(
            user=test_user, category=UserFeedback.Category.BUG_REPORT, body="A bug"
        )
        UserFeedback.objects.create(
            user=test_user, category=UserFeedback.Category.FEATURE_REQUEST, body="A feature"
        )

        response = staff_auth_client.get("/api/v1/feedback/staff/?category=bug_report")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["category"] == "bug_report"

    def test_invalid_date_from_returns_400(self, staff_auth_client):
        """Unparseable date_from returns 400, not a silent no-op filter."""
        response = staff_auth_client.get("/api/v1/feedback/staff/?date_from=not-a-date")
        assert response.status_code == 400

    def test_invalid_date_to_returns_400(self, staff_auth_client):
        """Unparseable date_to returns 400, not a silent no-op filter."""
        response = staff_auth_client.get("/api/v1/feedback/staff/?date_to=bad_date")
        assert response.status_code == 400

    def test_valid_date_from_filters_correctly(self, staff_auth_client, test_user):
        """A valid ISO 8601 date_from filters out earlier records."""
        from apps.feedback.models import UserFeedback
        from django.utils import timezone
        from datetime import timedelta

        old = UserFeedback.objects.create(
            user=test_user, category=UserFeedback.Category.OTHER, body="Old entry"
        )
        # Back-date the old entry
        UserFeedback.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=30)
        )
        UserFeedback.objects.create(
            user=test_user, category=UserFeedback.Category.OTHER, body="Recent entry"
        )

        cutoff = (timezone.now() - timedelta(days=7)).isoformat()
        response = staff_auth_client.get(f"/api/v1/feedback/staff/?date_from={cutoff}")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["body"] == "Recent entry"

    def test_staff_response_includes_internal_notes(self, staff_auth_client, test_user):
        """Staff list response exposes internal_notes field."""
        from apps.feedback.models import UserFeedback

        UserFeedback.objects.create(
            user=test_user,
            category=UserFeedback.Category.BUG_REPORT,
            body="A bug report",
            internal_notes="Investigated, looks like a race condition",
        )

        response = staff_auth_client.get("/api/v1/feedback/staff/")
        assert response.status_code == 200
        data = response.json()
        assert data["items"][0]["internal_notes"] == "Investigated, looks like a race condition"
