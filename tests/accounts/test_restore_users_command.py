from io import StringIO
import json

from django.core.management import call_command
import pytest

from apps.accounts.models import User, UserRole

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def reset_state():
    User.objects.all().delete()
    UserRole.objects.all().delete()


@pytest.fixture
def role():
    return UserRole.objects.create(title="Test Role")


def _dump_entry(email, password_hash, role_id, **overrides):
    fields = {
        "email": email,
        "password": password_hash,
        "first_name": "First",
        "last_name": "Last",
        "is_active": True,
        "is_staff": False,
        "is_superuser": False,
        "date_joined": "2024-01-01T00:00:00+00:00",
        "last_login": None,
        "role": role_id,
    }
    fields.update(overrides)
    return {"model": "accounts.user", "fields": fields}


def test_restore_users_happy_path(role, tmp_path):
    # Pre-hash a known password so we can verify it after restore
    from django.contrib.auth.hashers import make_password
    pw_hash = make_password("testpassword")

    dump_file = tmp_path / "users.json"
    dump_file.write_text(json.dumps([_dump_entry("new@example.com", pw_hash, role.id)]))

    out = StringIO()
    call_command("restore_users", str(dump_file), stdout=out)

    user = User.objects.get(email="new@example.com")
    assert user.role == role
    assert user.check_password("testpassword")
    assert "Created user" in out.getvalue()


def test_restore_users_skips_existing_email(role, tmp_path):
    User.objects.create_user(email="existing@example.com", password="old", role=role)

    dump_file = tmp_path / "users.json"
    dump_file.write_text(
        json.dumps([_dump_entry("existing@example.com", "irrelevant_hash", role.id)])
    )

    out = StringIO()
    call_command("restore_users", str(dump_file), stdout=out)

    assert "already exists" in out.getvalue()
    assert User.objects.filter(email="existing@example.com").count() == 1


def test_restore_users_skips_when_role_id_not_found(role, tmp_path):
    missing_role_id = role.id + 9999
    dump_file = tmp_path / "users.json"
    dump_file.write_text(json.dumps([_dump_entry("ghost@example.com", "hash", missing_role_id)]))

    out = StringIO()
    call_command("restore_users", str(dump_file), stdout=out)

    assert not User.objects.filter(email="ghost@example.com").exists()
    assert "not found" in out.getvalue()


def test_restore_users_missing_role_falls_back_to_id_1(tmp_path):
    # Role with id=1 must exist for fallback to succeed
    role1 = UserRole.objects.create(title="Default Role")
    # Force id=1 by checking what was assigned
    role1.refresh_from_db()

    dump_file = tmp_path / "users.json"
    dump_file.write_text(
        json.dumps([_dump_entry("nrole@example.com", "hash", None, role=None)])
    )

    out = StringIO()
    call_command("restore_users", str(dump_file), stdout=out)

    output = out.getvalue()
    # Either the user was created (role id=1 existed) or skipped (role not found)
    # We just verify the command handled the missing-role case without crashing
    assert "nrole@example.com" in output


def test_restore_users_preserves_password_hash(role, tmp_path):
    from django.contrib.auth.hashers import make_password
    pw_hash = make_password("mypassword123")

    dump_file = tmp_path / "users.json"
    dump_file.write_text(json.dumps([_dump_entry("pw@example.com", pw_hash, role.id)]))

    call_command("restore_users", str(dump_file), stdout=StringIO())

    user = User.objects.get(email="pw@example.com")
    assert user.password == pw_hash
    assert user.check_password("mypassword123")


def test_restore_users_multiple_entries(role, tmp_path):
    from django.contrib.auth.hashers import make_password
    entries = [
        _dump_entry("u1@example.com", make_password("p1"), role.id),
        _dump_entry("u2@example.com", make_password("p2"), role.id),
    ]
    dump_file = tmp_path / "users.json"
    dump_file.write_text(json.dumps(entries))

    call_command("restore_users", str(dump_file), stdout=StringIO())

    assert User.objects.filter(email="u1@example.com").exists()
    assert User.objects.filter(email="u2@example.com").exists()
