from io import StringIO
import json
from pathlib import Path

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


@pytest.fixture
def users(role):
    u1 = User.objects.create_user(email="alice@example.com", password="pass1", role=role)
    u2 = User.objects.create_user(email="bob@example.com", password="pass2", role=role)
    return u1, u2


def test_dump_users_default_exports_all(users, tmp_path):
    output_file = str(tmp_path / "out.json")
    out = StringIO()
    call_command("dump_users", output=output_file, stdout=out)

    data = json.loads(Path(output_file).read_text())
    assert len(data) == 2
    emails = {entry["fields"]["email"] for entry in data}
    assert emails == {"alice@example.com", "bob@example.com"}
    assert "2 user(s) dumped" in out.getvalue()


def test_dump_users_filter_by_email(users, tmp_path):
    output_file = str(tmp_path / "out.json")
    out = StringIO()
    call_command("dump_users", emails=["alice@example.com"], output=output_file, stdout=out)

    data = json.loads(Path(output_file).read_text())
    assert len(data) == 1
    assert data[0]["fields"]["email"] == "alice@example.com"


def test_dump_users_filter_multiple_emails(users, tmp_path):
    output_file = str(tmp_path / "out.json")
    call_command(
        "dump_users",
        emails=["alice@example.com", "bob@example.com"],
        output=output_file,
        stdout=StringIO(),
    )
    data = json.loads(Path(output_file).read_text())
    assert len(data) == 2


def test_dump_users_no_match_prints_error(role, tmp_path):
    output_file = str(tmp_path / "out.json")
    out = StringIO()
    call_command(
        "dump_users",
        emails=["nobody@example.com"],
        output=output_file,
        stdout=out,
    )
    assert "No matching users found" in out.getvalue()
    assert not Path(output_file).exists()


def test_dump_users_output_schema(users, tmp_path):
    """Output entries must have 'model' and 'fields' keys with expected field names."""
    output_file = str(tmp_path / "out.json")
    call_command("dump_users", output=output_file, stdout=StringIO())

    data = json.loads(Path(output_file).read_text())
    entry = data[0]
    assert "model" in entry
    assert "fields" in entry
    fields = entry["fields"]
    for key in ("email", "password", "first_name", "last_name", "is_active", "is_staff", "is_superuser", "role"):
        assert key in fields, f"Missing field: {key}"


def test_dump_users_password_hash_preserved(role, tmp_path):
    user = User.objects.create_user(email="carol@example.com", password="secretpass", role=role)
    output_file = str(tmp_path / "out.json")
    call_command(
        "dump_users",
        emails=["carol@example.com"],
        output=output_file,
        stdout=StringIO(),
    )
    data = json.loads(Path(output_file).read_text())
    assert data[0]["fields"]["password"] == user.password
