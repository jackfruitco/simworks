#!/bin/bash
set -euo pipefail

# Updated to align with the Makefile's dev compose path and conventions.
# You can override these via env vars if needed.
DEV_COMPOSE_FILE="${DEV_COMPOSE:-docker/compose.dev.yaml}"
SERVER_SERVICE="${SERVER_SERVICE:-server}"

# Usage:
#   ./build-run_service.sh [service_identity] [sim_context_json]
# Example:
#   ./build-run_service.sh chatlab.standardized_patient.initial '{"simulation_id": 1}'
SERVICE_IDENTITY="${1:-chatlab.standardized_patient.initial}"
SIM_CONTEXT_JSON="${2:-{\"simulation_id\": 1}}"

echo ">>> Building images (no cache) using ${DEV_COMPOSE_FILE}..."
docker compose -f "${DEV_COMPOSE_FILE}" build --no-cache "${SERVER_SERVICE}"

echo ">>> Bringing up ${SERVER_SERVICE} (detached) with --build..."
docker compose -f "${DEV_COMPOSE_FILE}" up -d --build "${SERVER_SERVICE}"

echo ">>> Running manage.py run_service inside ${SERVER_SERVICE}..."
docker compose -f "${DEV_COMPOSE_FILE}" exec "${SERVER_SERVICE}" \
  python manage.py run_service "${SERVICE_IDENTITY}" -c "${SIM_CONTEXT_JSON}"

echo ">>> Done."