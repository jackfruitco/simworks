from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
import pytest


@pytest.fixture
def fake_app_structure(tmp_path):
    """Create a fake apps directory tree with migration files.

    The command resolves project_root = Path(__file__).resolve().parent * 4,
    so we put a fake command file 4 levels below tmp_path and patch __file__
    to point to it so project_root resolves to tmp_path.
    """
    # Fake apps under project root
    app1 = tmp_path / "myapp" / "migrations"
    app1.mkdir(parents=True)
    (app1 / "__init__.py").write_text("")
    (app1 / "0001_initial.py").write_text("# migration")
    (app1 / "0002_add_field.py").write_text("# migration")

    app2 = tmp_path / "otherapp" / "migrations"
    app2.mkdir(parents=True)
    (app2 / "__init__.py").write_text("")
    (app2 / "0001_initial.py").write_text("# migration")

    # App without migrations dir — should be skipped
    (tmp_path / "noapp").mkdir()

    # Fake command file 3 levels below project root so parent*4 == tmp_path
    # Path(__file__).resolve().parent.parent.parent.parent:
    #   parent1 = tmp_path/a/b/c, parent2 = tmp_path/a/b, parent3 = tmp_path/a, parent4 = tmp_path
    fake_cmd = tmp_path / "a" / "b" / "c" / "reset_migrations.py"
    fake_cmd.parent.mkdir(parents=True)
    fake_cmd.write_text("")

    return tmp_path, fake_cmd


def test_reset_migrations_deletes_migration_files(fake_app_structure):
    """Migration .py files are deleted; __init__.py files survive."""
    project_root, fake_cmd = fake_app_structure

    from apps.common.management.commands import reset_migrations as cmd_mod

    out = StringIO()
    with patch.object(cmd_mod, "__file__", str(fake_cmd)):
        call_command("reset_migrations", stdout=out)

    output = out.getvalue()
    assert "Deleted migration files" in output
    assert "0001_initial.py" in output

    # __init__.py files must still exist
    for init in project_root.rglob("__init__.py"):
        assert init.exists(), f"__init__.py was deleted: {init}"

    # Migration files must be gone
    assert not (project_root / "myapp" / "migrations" / "0001_initial.py").exists()
    assert not (project_root / "myapp" / "migrations" / "0002_add_field.py").exists()
    assert not (project_root / "otherapp" / "migrations" / "0001_initial.py").exists()


def test_reset_migrations_no_files_prints_warning(tmp_path):
    """If no migration files exist, prints a warning."""
    app = tmp_path / "emptyapp" / "migrations"
    app.mkdir(parents=True)
    (app / "__init__.py").write_text("")

    fake_cmd = tmp_path / "a" / "b" / "c" / "reset_migrations.py"
    fake_cmd.parent.mkdir(parents=True)
    fake_cmd.write_text("")

    from apps.common.management.commands import reset_migrations as cmd_mod

    out = StringIO()
    with patch.object(cmd_mod, "__file__", str(fake_cmd)):
        call_command("reset_migrations", stdout=out)

    assert "No migration files found" in out.getvalue()


def test_reset_migrations_makemigrations_flag(fake_app_structure):
    """--makemigrations calls the makemigrations management command after deletion."""
    _project_root, fake_cmd = fake_app_structure

    from apps.common.management.commands import reset_migrations as cmd_mod

    out = StringIO()
    with patch.object(cmd_mod, "__file__", str(fake_cmd)), patch(
        "apps.common.management.commands.reset_migrations.call_command"
    ) as mock_cc:
        call_command("reset_migrations", makemigrations=True, stdout=out)
        mock_cc.assert_called_once_with("makemigrations")
