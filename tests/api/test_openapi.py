"""Tests for OpenAPI schema export functionality."""

from io import StringIO
import json
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest

from tests.helpers.assertions import assert_schema_has_paths


class TestOpenAPIExport:
    """Tests for the export_openapi management command."""

    def test_export_to_stdout(self):
        """Test that the command outputs valid JSON to stdout."""
        out = StringIO()
        call_command("export_openapi", stdout=out)
        output = out.getvalue()

        # Should be valid JSON
        schema = json.loads(output)

        # Should have required OpenAPI fields
        assert "openapi" in schema
        assert schema["openapi"].startswith("3.")
        assert "info" in schema
        assert "paths" in schema

    def test_export_to_file(self, tmp_path):
        """Test that the command writes to a file when --output is specified."""
        output_file = tmp_path / "schema.json"

        out = StringIO()
        call_command("export_openapi", output=str(output_file), stdout=out)

        # File should exist and contain valid JSON
        assert output_file.exists()
        schema = json.loads(output_file.read_text())
        assert "openapi" in schema

        # Stdout should contain success message
        assert "exported to" in out.getvalue()

    def test_export_creates_parent_directories(self, tmp_path):
        """Test that the command creates parent directories if needed."""
        output_file = tmp_path / "nested" / "dir" / "schema.json"

        call_command("export_openapi", output=str(output_file), stdout=StringIO())

        assert output_file.exists()
        assert output_file.parent.exists()

    def test_export_with_custom_indent(self, tmp_path):
        """Test that the --indent option controls JSON formatting."""
        output_file = tmp_path / "schema.json"

        # Export with indent=4
        call_command("export_openapi", output=str(output_file), indent=4, stdout=StringIO())

        content = output_file.read_text()
        # With indent=4, should have 4-space indentation
        assert "    " in content

    def test_yaml_format_without_pyyaml(self):
        """Test that YAML format fails gracefully without PyYAML."""
        try:
            import yaml  # noqa: F401

            pytest.skip("PyYAML is installed, cannot test missing dependency")
        except ImportError:
            pass

        with pytest.raises(CommandError) as exc_info:
            call_command("export_openapi", format="yaml", stdout=StringIO())

        assert "PyYAML is required" in str(exc_info.value)

    def test_yaml_format_with_pyyaml(self):
        """Test that YAML format works correctly when PyYAML is installed."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML is not installed")

        out = StringIO()
        call_command("export_openapi", format="yaml", stdout=out)
        output = out.getvalue()

        # Should be valid YAML
        schema = yaml.safe_load(output)

        # Should have required OpenAPI fields
        assert "openapi" in schema
        assert schema["openapi"].startswith("3.")
        assert "info" in schema
        assert "paths" in schema


class TestOpenAPISchemaContent:
    """Tests for the content of the exported OpenAPI schema."""

    @pytest.fixture
    def schema(self):
        """Get the exported OpenAPI schema."""
        out = StringIO()
        call_command("export_openapi", stdout=out)
        return json.loads(out.getvalue())

    def test_schema_has_api_info(self, schema):
        """Test that the schema contains API metadata."""
        assert schema["info"]["title"] == "SimWorks API"
        assert schema["info"]["version"] == "0.10.2"
        assert "description" in schema["info"]

    def test_schema_has_health_endpoints(self, schema):
        """Test that health check endpoints are documented."""
        assert_schema_has_paths(
            schema,
            required_paths=[
                "/api/v1/health",
                "/api/v1/health/auth",
                "/api/v1/health/jwt",
            ],
        )

    def test_schema_has_auth_endpoints(self, schema):
        """Test that authentication endpoints are documented."""
        paths = schema["paths"]

        # Check for auth endpoints
        auth_paths = [p for p in paths if "/auth/" in p]
        assert len(auth_paths) > 0

    def test_schema_has_simulations_endpoints(self, schema):
        """Test that simulation endpoints are documented."""
        paths = schema["paths"]

        # Check for simulation endpoints
        sim_paths = [p for p in paths if "/simulations" in p]
        assert len(sim_paths) > 0

    def test_schema_has_modifiers_endpoint(self, schema):
        """Test that modifier groups endpoint is documented."""
        paths = schema["paths"]

        assert "/api/v1/config/modifier-groups/" in paths

    def test_schema_has_trainerlab_and_guard_contract_paths(self, schema):
        """TrainerLab mobile contract endpoints stay explicitly documented."""
        assert_schema_has_paths(
            schema,
            required_paths=[
                "/api/v1/trainerlab/simulations/",
                "/api/v1/trainerlab/simulations/{simulation_id}/",
                "/api/v1/trainerlab/simulations/{simulation_id}/state/",
                "/api/v1/trainerlab/simulations/{simulation_id}/summary/",
                "/api/v1/trainerlab/simulations/{simulation_id}/run/start/",
                "/api/v1/trainerlab/simulations/{simulation_id}/run/pause/",
                "/api/v1/trainerlab/simulations/{simulation_id}/run/resume/",
                "/api/v1/trainerlab/simulations/{simulation_id}/run/stop/",
                "/api/v1/trainerlab/simulations/{simulation_id}/events/injuries/",
                "/api/v1/trainerlab/simulations/{simulation_id}/events/illnesses/",
                "/api/v1/trainerlab/simulations/{simulation_id}/events/problems/",
                "/api/v1/trainerlab/simulations/{simulation_id}/events/interventions/",
                "/api/v1/trainerlab/simulations/{simulation_id}/events/assessment-findings/",
                "/api/v1/trainerlab/simulations/{simulation_id}/events/diagnostic-results/",
                "/api/v1/trainerlab/simulations/{simulation_id}/events/resources/",
                "/api/v1/trainerlab/simulations/{simulation_id}/events/disposition/",
                "/api/v1/trainerlab/simulations/{simulation_id}/events/notes/",
                "/api/v1/trainerlab/simulations/{simulation_id}/events/vitals/",
                "/api/v1/trainerlab/simulations/{simulation_id}/annotations/",
                "/api/v1/trainerlab/dictionaries/injuries/",
                "/api/v1/trainerlab/dictionaries/interventions/",
                "/api/v1/simulations/{simulation_id}/guard-state/",
                "/api/v1/simulations/{simulation_id}/heartbeat/",
            ],
        )
        assert "/api/v1/trainerlab/simulations/{simulation_id}/events/annotations/" not in schema[
            "paths"
        ]

    def test_schema_defines_response_schemas(self, schema):
        """Test that response schemas are defined."""
        components = schema.get("components", {})
        schemas = components.get("schemas", {})

        # Should have key response schemas
        schema_names = list(schemas.keys())
        assert "HealthResponse" in schema_names
        assert "SimulationOut" in schema_names
        assert "MessageOut" in schema_names

    def test_endpoints_have_tags(self, schema):
        """Test that endpoints are organized with tags."""
        for path, methods in schema["paths"].items():
            for method, details in methods.items():
                if method in ("get", "post", "put", "patch", "delete"):
                    assert "tags" in details, f"{method.upper()} {path} missing tags"

    def test_lab_order_request_schemas_share_constraints(self, schema):
        """Tools and canonical lab-order routes should expose matching validation constraints."""
        lab_orders_schema = schema["components"]["schemas"]["LabOrderSubmit"]
        tools_schema = schema["components"]["schemas"]["SignOrdersIn"]

        assert lab_orders_schema["required"] == ["orders"]
        assert tools_schema["required"] == ["submitted_orders"]

        lab_orders_property = lab_orders_schema["properties"]["orders"]
        submitted_orders_property = tools_schema["properties"]["submitted_orders"]

        assert lab_orders_property["minItems"] == 1
        assert submitted_orders_property["minItems"] == 1
        assert lab_orders_property["maxItems"] == 50
        assert submitted_orders_property["maxItems"] == 50
        assert lab_orders_property["items"]["maxLength"] == 255
        assert submitted_orders_property["items"]["maxLength"] == 255


class TestCommittedSchema:
    """Tests to verify the committed schema matches the current API."""

    def test_committed_schema_is_up_to_date(self):
        """Test that docs/openapi/v1.json matches the current API."""
        committed_schema_path = Path("docs/openapi/v1.json")

        if not committed_schema_path.exists():
            pytest.skip("Committed schema does not exist yet")

        # Export current schema
        out = StringIO()
        call_command("export_openapi", stdout=out)
        current_schema = json.loads(out.getvalue())

        # Load committed schema
        committed_schema = json.loads(committed_schema_path.read_text())

        # Compare (excluding timestamps or other dynamic fields if needed)
        assert current_schema == committed_schema, (
            "Committed OpenAPI schema is out of date. "
            "Run 'uv run python SimWorks/manage.py export_openapi --output docs/openapi/v1.json' "
            "to update it."
        )
