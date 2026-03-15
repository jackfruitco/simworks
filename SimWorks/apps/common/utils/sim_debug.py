"""Per-simulation debug logging toggle.

Allows temporarily enabling verbose DEBUG-level log output for a specific
simulation without changing global log levels. Backed by Django cache so
it works across multiple worker processes.

Usage (programmatic)::

    from apps.common.utils.sim_debug import enable_simulation_debug, disable_simulation_debug
    enable_simulation_debug(42, ttl=300)   # enable for 5 minutes
    disable_simulation_debug(42)

Usage (management command)::

    python manage.py sim_debug enable 42 --ttl 300
    python manage.py sim_debug disable 42
    python manage.py sim_debug status 42
"""

from django.core.cache import cache

_CACHE_KEY = "orca:sim_debug:{}"
DEFAULT_TTL = 3600  # 1 hour


def is_simulation_debug(simulation_id) -> bool:
    """Return True if debug logging is enabled for this simulation."""
    if not simulation_id:
        return False
    return bool(cache.get(_CACHE_KEY.format(simulation_id)))


def enable_simulation_debug(simulation_id, ttl: int = DEFAULT_TTL) -> None:
    """Enable verbose debug logging for a simulation (TTL in seconds)."""
    cache.set(_CACHE_KEY.format(simulation_id), True, timeout=ttl)


def disable_simulation_debug(simulation_id) -> None:
    """Disable verbose debug logging for a simulation."""
    cache.delete(_CACHE_KEY.format(simulation_id))
