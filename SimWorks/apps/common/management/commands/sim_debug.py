"""Management command to toggle per-simulation debug logging.

Usage::

    # Enable debug logging for simulation 42 (default TTL: 1 hour)
    python manage.py sim_debug enable 42

    # Enable with a custom TTL in seconds
    python manage.py sim_debug enable 42 --ttl 300

    # Disable debug logging for simulation 42
    python manage.py sim_debug disable 42

    # Check current status
    python manage.py sim_debug status 42

When enabled, the task worker emits extra INFO-level logs tagged [SIM_DEBUG]
for every AI service call executed against that simulation. The flag is stored
in Django cache and expires automatically after the TTL.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.common.utils.sim_debug import (
    DEFAULT_TTL,
    disable_simulation_debug,
    enable_simulation_debug,
    is_simulation_debug,
)


class Command(BaseCommand):
    help = "Toggle verbose debug logging for a specific simulation."

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(dest="subcommand", required=True)

        enable_parser = subparsers.add_parser("enable", help="Enable debug logging")
        enable_parser.add_argument("simulation_id", type=int)
        enable_parser.add_argument(
            "--ttl",
            type=int,
            default=DEFAULT_TTL,
            help=f"Cache TTL in seconds (default: {DEFAULT_TTL})",
        )

        disable_parser = subparsers.add_parser("disable", help="Disable debug logging")
        disable_parser.add_argument("simulation_id", type=int)

        status_parser = subparsers.add_parser("status", help="Check debug logging status")
        status_parser.add_argument("simulation_id", type=int)

    def handle(self, *args, **options):
        subcommand = options["subcommand"]
        sim_id = options["simulation_id"]

        if subcommand == "enable":
            ttl = options["ttl"]
            enable_simulation_debug(sim_id, ttl=ttl)
            self.stdout.write(
                self.style.SUCCESS(
                    f"[sim_debug] Enabled debug logging for simulation {sim_id} (TTL: {ttl}s)"
                )
            )

        elif subcommand == "disable":
            disable_simulation_debug(sim_id)
            self.stdout.write(
                self.style.SUCCESS(f"[sim_debug] Disabled debug logging for simulation {sim_id}")
            )

        elif subcommand == "status":
            active = is_simulation_debug(sim_id)
            status_str = self.style.SUCCESS("ENABLED") if active else self.style.WARNING("disabled")
            self.stdout.write(f"[sim_debug] Simulation {sim_id}: {status_str}")

        else:
            raise CommandError(f"Unknown subcommand: {subcommand}")
