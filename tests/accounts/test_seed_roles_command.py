from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
import pytest

from apps.accounts.management.commands.seed_roles import LEARNER_ROLES, SYSTEM_USERS
from apps.accounts.models import UserRole

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture(autouse=True)
def reset_state():
    User.objects.all().delete()
    UserRole.objects.all().delete()


def test_seed_roles_creates_system_roles():
    call_command("seed_roles", stdout=StringIO())
    system_role_titles = {entry["role_title"] for entry in SYSTEM_USERS}
    for title in system_role_titles:
        assert UserRole.objects.filter(title=title).exists(), f"Missing system role: {title}"


def test_seed_roles_creates_system_users():
    call_command("seed_roles", stdout=StringIO())
    for entry in SYSTEM_USERS:
        user = User.objects.filter(email=entry["email"]).first()
        assert user is not None, f"Missing system user: {entry['email']}"
        assert user.is_active is False, f"System user {entry['email']} should be inactive"


def test_seed_roles_creates_learner_roles():
    call_command("seed_roles", stdout=StringIO())
    for title in LEARNER_ROLES:
        assert UserRole.objects.filter(title=title).exists(), f"Missing learner role: {title}"


def test_seed_roles_idempotent():
    call_command("seed_roles", stdout=StringIO())
    call_command("seed_roles", stdout=StringIO())

    expected_roles = len(SYSTEM_USERS) + len(LEARNER_ROLES)
    assert UserRole.objects.count() == expected_roles

    expected_users = len(SYSTEM_USERS)
    assert User.objects.count() == expected_users


def test_seed_roles_reports_created(capsys):
    out = StringIO()
    call_command("seed_roles", stdout=out)
    output = out.getvalue()
    assert "Created role" in output or "Created system user" in output


def test_seed_roles_silent_on_existing():
    call_command("seed_roles", stdout=StringIO())
    out = StringIO()
    call_command("seed_roles", stdout=out)
    # Second run should produce no "Created" output
    assert "Created" not in out.getvalue()
