"""
Tests for Django 6.0 template partials integration with simulation tools.
"""

from django.template import Context, TemplateDoesNotExist
from django.template.loader import get_template
import pytest


@pytest.mark.django_db
class TestToolPartials:
    """Test that Django 6.0 partials work correctly for tool rendering."""

    def test_tool_wrapper_partial_exists(self):
        """Verify tool_wrapper partial can be loaded."""
        template = get_template("simcore/tools.html#tool_wrapper")
        assert template is not None
        assert hasattr(template, "template")

    def test_tool_panel_partial_exists(self):
        """Verify tool_panel partial can be loaded."""
        template = get_template("simcore/tools.html#tool_panel")
        assert template is not None

    def test_tool_generic_partial_exists(self):
        """Verify tool_generic partial can be loaded."""
        template = get_template("simcore/tools.html#tool_generic")
        assert template is not None

    def test_tool_patient_history_partial_exists(self):
        """Verify tool_patient_history partial can be loaded."""
        template = get_template("simcore/tools.html#tool_patient_history")
        assert template is not None

    def test_tool_patient_results_partial_exists(self):
        """Verify tool_patient_results partial can be loaded."""
        template = get_template("simcore/tools.html#tool_patient_results")
        assert template is not None

    def test_tool_simulation_feedback_partial_exists(self):
        """Verify tool_simulation_feedback partial can be loaded."""
        template = get_template("simcore/tools.html#tool_simulation_feedback")
        assert template is not None

    def test_tool_fallback_partial_exists(self):
        """Verify tool_fallback partial can be loaded."""
        template = get_template("simcore/tools.html#tool_fallback")
        assert template is not None

    def test_nonexistent_partial_raises_error(self):
        """Verify that loading a non-existent partial raises TemplateDoesNotExist."""
        with pytest.raises(TemplateDoesNotExist):
            get_template("simcore/tools.html#tool_nonexistent")

    def test_tool_partial_can_be_rendered(self):
        """Test that tool partials can be rendered with minimal context."""
        # Load a simple partial
        template = get_template("simcore/tools.html#tool_generic")

        # Create minimal context that satisfies template requirements
        tool_dict = {
            "name": "test_tool",
            "display_name": "Test Tool",
            "data": [],
            "is_generic": True,
            "checksum": "abc123",
        }

        # Render with proper Django Context object
        context = Context({"tool": tool_dict})
        rendered = template.template.render(context)

        # Verify rendered output contains expected elements
        assert "tool-empty-state" in rendered or "tool-item-list" in rendered
        assert "No data available" in rendered or "tool-item" in rendered
