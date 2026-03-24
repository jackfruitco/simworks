from io import StringIO
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest

MINIMAL_SCHEMA = {"openapi": "3.1.0", "info": {"title": "Test API", "version": "1"}, "paths": {}}

_PATCH_TARGET = "apps.common.management.commands.export_openapi"


@pytest.fixture(autouse=True)
def mock_api():
    mock = MagicMock()
    mock.get_openapi_schema.return_value = MINIMAL_SCHEMA
    with patch(f"{_PATCH_TARGET}.Command.handle", wraps=None) as _:
        pass
    # Patch the import of api inside handle()
    with patch.dict("sys.modules", {"api.v1.api": MagicMock(api=mock)}):
        yield mock


def test_export_openapi_stdout_is_valid_json(mock_api):
    out = StringIO()
    call_command("export_openapi", stdout=out)
    output = out.getvalue()
    parsed = json.loads(output)
    assert parsed["openapi"] == "3.1.0"


def test_export_openapi_to_file(mock_api, tmp_path):
    output_file = str(tmp_path / "schema.json")
    out = StringIO()
    call_command("export_openapi", output=output_file, stdout=out)

    assert Path(output_file).exists()
    data = json.loads(Path(output_file).read_text())
    assert "openapi" in data
    assert "exported to" in out.getvalue()


def test_export_openapi_creates_parent_dirs(mock_api, tmp_path):
    output_file = str(tmp_path / "nested" / "dir" / "schema.json")
    call_command("export_openapi", output=output_file, stdout=StringIO())
    assert Path(output_file).exists()


def test_export_openapi_indent_option(mock_api, tmp_path):
    output_file = str(tmp_path / "schema.json")
    call_command("export_openapi", output=output_file, indent=4, stdout=StringIO())
    content = Path(output_file).read_text()
    # 4-space indent means lines start with "    "
    assert "    " in content


def test_export_openapi_yaml_missing_pyyaml(mock_api):
    """CommandError raised when PyYAML is not installed."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("No module named 'yaml'")
        return real_import(name, *args, **kwargs)

    out = StringIO()
    with patch("builtins.__import__", side_effect=fake_import), pytest.raises(
        (CommandError, SystemExit)
    ):
        call_command("export_openapi", format="yaml", stdout=out)


def test_export_openapi_yaml_format(mock_api, tmp_path):
    """YAML format produces valid YAML when PyYAML is available."""
    yaml = pytest.importorskip("yaml")
    output_file = str(tmp_path / "schema.yaml")
    call_command("export_openapi", format="yaml", output=output_file, stdout=StringIO())
    content = Path(output_file).read_text()
    parsed = yaml.safe_load(content)
    assert parsed["openapi"] == "3.1.0"
