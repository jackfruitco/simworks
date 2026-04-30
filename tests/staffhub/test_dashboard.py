from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
import pytest

from apps.accounts.models import UserRole
from apps.staffhub.services import (
    get_staff_dashboard_links,
    get_staff_dashboard_status,
)

pytestmark = pytest.mark.django_db

User = get_user_model()


def _dashboard_section(body: str) -> str:
    """Return only the staffhub dashboard markup, excluding the base nav."""
    start = body.find('id="staffhub-dashboard"')
    if start < 0:
        return ""
    end = body.find("</main>", start)
    return body[start:end] if end > 0 else body[start:]


@pytest.fixture
def role():
    return UserRole.objects.create(title="Staffhub Test Role")


@pytest.fixture
def regular_user(role):
    return User.objects.create_user(
        email="regular@example.com",
        password="password",
        role=role,
    )


@pytest.fixture
def staff_user(role):
    return User.objects.create_user(
        email="staff@example.com",
        password="password",
        role=role,
        is_staff=True,
    )


@pytest.fixture
def superuser(role):
    return User.objects.create_user(
        email="super@example.com",
        password="password",
        role=role,
        is_staff=True,
        is_superuser=True,
    )


def test_anonymous_redirects_to_login(client):
    response = client.get(reverse("staffhub:dashboard"))
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_authenticated_non_staff_is_forbidden(client, regular_user):
    client.force_login(regular_user)
    response = client.get(reverse("staffhub:dashboard"))
    assert response.status_code == 403


def test_staff_user_can_view_dashboard(client, staff_user):
    client.force_login(staff_user)
    response = client.get(reverse("staffhub:dashboard"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "Staff Dashboard" in body


def test_staff_non_superuser_does_not_see_admin_links(client, staff_user):
    client.force_login(staff_user)
    response = client.get(reverse("staffhub:dashboard"))
    assert response.status_code == 200
    section = _dashboard_section(response.content.decode())
    assert section, "staffhub dashboard section not found in response"
    assert "Django Admin" not in section
    assert "API Docs" not in section
    assert "OpenAPI Schema" not in section
    assert "Invitations" not in section
    assert "Billing" not in section


def test_superuser_sees_admin_and_api_links(client, superuser):
    client.force_login(superuser)
    response = client.get(reverse("staffhub:dashboard"))
    assert response.status_code == 200
    section = _dashboard_section(response.content.decode())
    assert "Django Admin" in section
    assert "API Docs" in section
    assert "OpenAPI Schema" in section
    assert "Invitations" in section


def test_dashboard_renders_without_external_links_setting(client, staff_user, settings):
    if hasattr(settings, "STAFFHUB_EXTERNAL_LINKS"):
        del settings.STAFFHUB_EXTERNAL_LINKS
    client.force_login(staff_user)
    response = client.get(reverse("staffhub:dashboard"))
    assert response.status_code == 200


def test_external_links_appear_only_for_superuser(client, staff_user, superuser, settings):
    settings.STAFFHUB_EXTERNAL_LINKS = {
        "github_repo": "https://github.com/jackfruitco/simworks",
        "empty_one": "",
    }

    client.force_login(staff_user)
    section = _dashboard_section(client.get(reverse("staffhub:dashboard")).content.decode())
    assert "Github Repo" not in section

    client.force_login(superuser)
    section = _dashboard_section(client.get(reverse("staffhub:dashboard")).content.decode())
    assert "Github Repo" in section
    assert "https://github.com/jackfruitco/simworks" in section


def test_dashboard_status_returns_dict_safely():
    status = get_staff_dashboard_status()
    assert isinstance(status, dict)
    for key in (
        "environment",
        "version",
        "commit",
        "build_time",
        "debug",
        "database",
        "redis",
        "openai_configured",
    ):
        assert key in status
    assert isinstance(status["debug"], bool)
    assert isinstance(status["openai_configured"], bool)


def test_get_staff_dashboard_links_filters_superuser_only(staff_user, superuser):
    staff_links = get_staff_dashboard_links(staff_user)
    assert all(not link.superuser_only for link in staff_links)

    superuser_links = get_staff_dashboard_links(superuser)
    assert any(link.superuser_only for link in superuser_links)
    assert any(link.label == "Django Admin" for link in superuser_links)


@override_settings(STAFFHUB_EXTERNAL_LINKS=None)
def test_dashboard_renders_when_external_links_is_none(client, staff_user):
    client.force_login(staff_user)
    response = client.get(reverse("staffhub:dashboard"))
    assert response.status_code == 200
