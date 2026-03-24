from io import StringIO

from django.core.management import call_command
import pytest

from apps.accounts.management.commands.create_dev_user import DEV_EMAIL, DEV_PASSWORD
from apps.accounts.models import User, UserRole

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def reset_user_state():
    User.objects.all().delete()
    UserRole.objects.all().delete()


@pytest.fixture
def user_role():
    return UserRole.objects.create(title="System")


def test_create_dev_user_skips_when_debug_disabled(monkeypatch):
    monkeypatch.delenv("DJANGO_DEBUG", raising=False)
    monkeypatch.setenv("DJANGO_CREATE_DEV_USER", "true")

    out = StringIO()
    call_command("create_dev_user", stdout=out)

    assert "Skipped: DJANGO_DEBUG is not enabled." in out.getvalue()
    assert not User.objects.filter(email=DEV_EMAIL).exists()


def test_create_dev_user_skips_when_create_flag_disabled(monkeypatch):
    monkeypatch.setenv("DJANGO_DEBUG", "true")
    monkeypatch.delenv("DJANGO_CREATE_DEV_USER", raising=False)

    out = StringIO()
    call_command("create_dev_user", stdout=out)

    assert "Skipped: DJANGO_CREATE_DEV_USER is not enabled." in out.getvalue()
    assert not User.objects.filter(email=DEV_EMAIL).exists()


def test_create_dev_user_force_bypasses_env_checks(monkeypatch, user_role):
    monkeypatch.delenv("DJANGO_DEBUG", raising=False)
    monkeypatch.delenv("DJANGO_CREATE_DEV_USER", raising=False)
    monkeypatch.delenv("DJANGO_DEV_USER_PASSWORD", raising=False)

    out = StringIO()
    call_command("create_dev_user", force=True, stdout=out)

    user = User.objects.get(email=DEV_EMAIL)
    assert "Created demo user" in out.getvalue()
    assert user.first_name == "Dev"
    assert user.last_name == "User"
    assert user.is_active is True
    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.role == user_role
    assert user.check_password(DEV_PASSWORD)


def test_create_dev_user_force_still_requires_role(monkeypatch):
    monkeypatch.delenv("DJANGO_DEBUG", raising=False)
    monkeypatch.delenv("DJANGO_CREATE_DEV_USER", raising=False)

    out = StringIO()
    call_command("create_dev_user", force=True, stdout=out)

    assert "No UserRole found" in out.getvalue()
    assert not User.objects.filter(email=DEV_EMAIL).exists()


def test_create_dev_user_force_preserves_existing_user(monkeypatch, user_role):
    monkeypatch.delenv("DJANGO_DEBUG", raising=False)
    monkeypatch.delenv("DJANGO_CREATE_DEV_USER", raising=False)

    existing_user = User.objects.create_user(
        email=DEV_EMAIL,
        password="existing-password",
        role=user_role,
    )

    out = StringIO()
    call_command("create_dev_user", force=True, stdout=out)

    existing_user.refresh_from_db()
    assert f"Dev user already exists: {DEV_EMAIL}" in out.getvalue()
    assert existing_user.check_password("existing-password")
