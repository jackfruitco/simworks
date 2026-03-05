"""Management command to export OpenAPI schema.

Usage:
    # Output to stdout
    python manage.py export_openapi

    # Save to file
    python manage.py export_openapi --output docs/openapi/v1.json

    # YAML format
    python manage.py export_openapi --format yaml
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Export the OpenAPI schema for API v1"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            "-o",
            type=str,
            help="Output file path. If not specified, outputs to stdout.",
        )
        parser.add_argument(
            "--format",
            "-f",
            type=str,
            choices=["json", "yaml"],
            default="json",
            help="Output format (default: json)",
        )
        parser.add_argument(
            "--indent",
            type=int,
            default=2,
            help="Indentation level for JSON output (default: 2)",
        )

    def handle(self, *args, **options):
        from api.v1.api import api

        # Get the OpenAPI schema
        schema = api.get_openapi_schema()

        # Format the output
        if options["format"] == "yaml":
            try:
                import yaml

                output = yaml.dump(schema, default_flow_style=False, sort_keys=False)
            except ImportError as err:
                raise CommandError(
                    "PyYAML is required for YAML output. Install with: uv add pyyaml"
                ) from err
        else:
            output = json.dumps(schema, indent=options["indent"])

        # Write to file or stdout
        if options["output"]:
            output_path = Path(options["output"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output)
            self.stdout.write(self.style.SUCCESS(f"OpenAPI schema exported to {options['output']}"))
        else:
            self.stdout.write(output)
