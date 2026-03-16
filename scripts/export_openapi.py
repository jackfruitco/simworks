#!/usr/bin/env python
"""Export the OpenAPI schema for API v1.

Usage from the repo root:
    uv run python scripts/export_openapi.py
    uv run python scripts/export_openapi.py --output docs/openapi/v1.json
    uv run python scripts/export_openapi.py --output /tmp/current-schema.json
"""

import os
from pathlib import Path
import sys

# Ensure manage.py can be found regardless of working directory
REPO_ROOT = Path(__file__).resolve().parent.parent
SIMWORKS_DIR = REPO_ROOT / "SimWorks"

sys.path.insert(0, str(SIMWORKS_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
from django.core.management import call_command  # noqa: E402

os.environ["DJANGO_SKIP_READY"] = "1"

django.setup()

if __name__ == "__main__":
    # Forward all args to the management command
    args = sys.argv[1:]
    call_command("export_openapi", *args)
