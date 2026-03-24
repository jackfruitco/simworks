from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
import pytest

from apps.common.utils.sim_debug import is_simulation_debug

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_sim_debug_enable_sets_flag():
    out = StringIO()
    call_command("sim_debug", "enable", "42", stdout=out)

    assert is_simulation_debug(42)
    assert "Enabled" in out.getvalue()
    assert "42" in out.getvalue()


def test_sim_debug_enable_custom_ttl():
    out = StringIO()
    call_command("sim_debug", "enable", "99", "--ttl", "60", stdout=out)

    assert is_simulation_debug(99)
    assert "60" in out.getvalue()


def test_sim_debug_disable_clears_flag():
    call_command("sim_debug", "enable", "7", stdout=StringIO())
    assert is_simulation_debug(7)

    out = StringIO()
    call_command("sim_debug", "disable", "7", stdout=out)

    assert not is_simulation_debug(7)
    assert "Disabled" in out.getvalue()


def test_sim_debug_status_when_enabled():
    call_command("sim_debug", "enable", "5", stdout=StringIO())

    out = StringIO()
    call_command("sim_debug", "status", "5", stdout=out)

    assert "ENABLED" in out.getvalue()


def test_sim_debug_status_when_disabled():
    out = StringIO()
    call_command("sim_debug", "status", "5", stdout=out)

    assert "disabled" in out.getvalue().lower()


def test_sim_debug_disable_nonexistent_is_noop():
    """Disabling a simulation that was never enabled should not raise."""
    out = StringIO()
    call_command("sim_debug", "disable", "9999", stdout=out)
    assert not is_simulation_debug(9999)
