# tests/accounts/managment/commands/test_demo_user_commands.py

import getpass
from io import StringIO

from allauth.account.models import EmailAddress
from django.core.management import call_command
from django.core.management.base import CommandError
import pytest

from apps.accounts.models import User, UserRole
from apps.accounts.services import get_personal_account_for_user
from apps.billing.models import Entitlement

pytestmark = pytest.mark.django_db


@pytest.fixture
def system_role() -> UserRole:
    role, _ = UserRole.objects.get_or_create(title="System")
    return role


def _run_command(name: str, *args, **kwargs) -> tuple[str, str]:
    stdout = kwargs.pop("stdout", StringIO())
    stderr = kwargs.pop("stderr", StringIO())
    call_command(name, *args, stdout=stdout, stderr=stderr, **kwargs)
    return stdout.getvalue(), stderr.getvalue()


def _entitlement_for_user(user: User, product_code: str) -> Entitlement:
    account = get_personal_account_for_user(user)
    return Entitlement.objects.get(account=account, product_code=product_code)


def test_create_demo_user_creates_default_user_with_explicit_password(system_role: UserRole):
    stdout, stderr = _run_command("create_demo_user", password="Sup3rS3cret!234")

    user = User.objects.get(email="demo@medsim.local")
    email_address = EmailAddress.objects.get(user=user, email=user.email)
    entitlement = _entitlement_for_user(user, "medsim_one")

    assert user.first_name == "Demo"
    assert user.last_name == "User"
    assert user.is_active is True
    assert user.is_staff is True
    assert user.is_superuser is False
    assert user.role == system_role
    assert user.check_password("Sup3rS3cret!234") is True
    assert user.has_usable_password() is True

    assert email_address.verified is True
    assert email_address.primary is True

    assert entitlement.source_type == "grant"
    assert entitlement.source_ref == "manual-entitlement"

    assert "Created demo user: demo@medsim.local" in stdout
    assert stderr == ""


def test_create_demo_user_updates_existing_user_and_demotes_other_primary_email(
    system_role: UserRole,
):
    old_role = UserRole.objects.create(title="Old Role")
    user = User.objects.create(
        email="demo@medsim.local",
        first_name="Old",
        last_name="Name",
        is_active=False,
        is_staff=False,
        is_superuser=True,
        role=old_role,
    )
    user.set_password("old-password")
    user.save()

    EmailAddress.objects.create(
        user=user,
        email="other@medsim.local",
        verified=True,
        primary=True,
    )

    stdout, stderr = _run_command(
        "create_demo_user",
        password="N3wS3cret!234",
        first_name="Demo",
        last_name="User",
    )

    user.refresh_from_db()
    current_email = EmailAddress.objects.get(user=user, email=user.email)
    other_email = EmailAddress.objects.get(user=user, email="other@medsim.local")

    assert user.first_name == "Demo"
    assert user.last_name == "User"
    assert user.is_active is True
    assert user.is_staff is True
    assert user.is_superuser is False
    assert user.role == system_role
    assert user.check_password("N3wS3cret!234") is True

    assert current_email.verified is True
    assert current_email.primary is True
    assert other_email.primary is False

    assert "Updated existing user: demo@medsim.local" in stdout
    assert stderr == ""


def test_create_demo_user_supports_explicit_email_password_and_product(system_role: UserRole):
    stdout, stderr = _run_command(
        "create_demo_user",
        email="anything@medsim.local",
        password="Train3rPass!234",
        product="trainerlab_go",
    )

    user = User.objects.get(email="anything@medsim.local")
    entitlement = _entitlement_for_user(user, "trainerlab_go")

    assert user.check_password("Train3rPass!234") is True
    assert entitlement.product_code == "trainerlab_go"
    assert "Created demo user: anything@medsim.local" in stdout
    assert stderr == ""


def test_create_demo_user_supports_role_id(system_role: UserRole):
    stdout, stderr = _run_command(
        "create_demo_user",
        password="Sup3rS3cret!234",
        role=str(system_role.id),
    )

    user = User.objects.get(email="demo@medsim.local")

    assert user.role == system_role
    assert "Created demo user: demo@medsim.local" in stdout
    assert stderr == ""


def test_create_demo_user_raises_when_role_is_missing():
    with pytest.raises(CommandError, match='No UserRole found with title or id "Missing Role"'):
        _run_command(
            "create_demo_user",
            password="Sup3rS3cret!234",
            role="Missing Role",
        )


def test_create_demo_user_non_interactive_requires_explicit_allow_for_random_password(
    system_role: UserRole,
):
    with pytest.raises(
        CommandError,
        match=r"Under --no-input, pass --allow-random-password to generate one\.",
    ):
        _run_command("create_demo_user", interactive=False)

    assert User.objects.filter(email="demo@medsim.local").exists() is False


def test_create_demo_user_non_interactive_can_generate_random_password_when_explicitly_allowed(
    system_role: UserRole,
):
    stdout, stderr = _run_command(
        "create_demo_user",
        interactive=False,
        allow_random_password=True,
    )

    user = User.objects.get(email="demo@medsim.local")

    assert user.has_usable_password() is True
    assert "Created demo user: demo@medsim.local" in stdout
    assert "Generated random password for demo user." in stderr


def test_create_demo_user_interactive_can_collect_manual_password(
    monkeypatch: pytest.MonkeyPatch,
    system_role: UserRole,
):
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    responses = iter(["ManualPass!234", "ManualPass!234"])
    monkeypatch.setattr(getpass, "getpass", lambda prompt: next(responses))

    stdout, stderr = _run_command("create_demo_user")

    user = User.objects.get(email="demo@medsim.local")
    assert user.check_password("ManualPass!234") is True
    assert "Created demo user: demo@medsim.local" in stdout
    assert stderr == ""


def test_create_demo_user_interactive_can_generate_random_password(
    monkeypatch: pytest.MonkeyPatch,
    system_role: UserRole,
):
    responses = iter(["n", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))

    stdout, stderr = _run_command("create_demo_user")

    user = User.objects.get(email="demo@medsim.local")
    assert user.has_usable_password() is True
    assert "Created demo user: demo@medsim.local" in stdout
    assert "Generated random password for demo user." in stderr


def test_create_demo_user_uses_env_password_when_present(
    monkeypatch: pytest.MonkeyPatch,
    system_role: UserRole,
):
    monkeypatch.setenv("DEMO_USER_PASSWORD", "EnvPass!234")

    stdout, stderr = _run_command("create_demo_user")

    user = User.objects.get(email="demo@medsim.local")

    assert user.check_password("EnvPass!234") is True
    assert "Using password from DEMO_USER_PASSWORD." in stdout
    assert stderr == ""


def test_create_dev_user_skips_when_env_flags_are_disabled(system_role: UserRole):
    stdout, stderr = _run_command("create_dev_user")

    assert "Skipped: DJANGO_DEBUG is not enabled." in stdout
    assert User.objects.filter(email="dev@medsim.local").exists() is False
    assert stderr == ""


def test_create_dev_user_force_delegates_to_create_demo_user(system_role: UserRole):
    stdout, stderr = _run_command("create_dev_user", force=True)

    user = User.objects.get(email="dev@medsim.local")
    entitlement = _entitlement_for_user(user, "medsim_one")
    email_address = EmailAddress.objects.get(user=user, email=user.email)

    assert user.first_name == "Dev"
    assert user.last_name == "User"
    assert user.is_active is True
    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.role == system_role
    assert user.check_password("dev") is True

    assert email_address.verified is True
    assert email_address.primary is True
    assert entitlement.product_code == "medsim_one"

    assert "Created demo user: dev@medsim.local" in stdout
    assert "Granted manual entitlement:" in stdout
    assert stderr == ""
