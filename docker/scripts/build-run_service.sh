#!/bin/bash
set -euo pipefail

COMPOSE_FILE="docker/compose.dev.yaml"
SERVICE_NAME="server"
SIM_CONTEXT='{"simulation_id": 1}'

echo ">>> Building images (no cache) using ${COMPOSE_FILE}..."
docker compose -f "${COMPOSE_FILE}" build --no-cache

echo ">>> Bringing up ${SERVICE_NAME} with --build..."
docker compose -f "${COMPOSE_FILE}" up --build -d "${SERVICE_NAME}"

echo ">>> Running manage.py run_service inside ${SERVICE_NAME}..."
docker compose -f "${COMPOSE_FILE}" exec "${SERVICE_NAME}" \
  python manage.py run_service chatlab.standardized_patient.initial -c "${SIM_CONTEXT}"

echo ">>> Done."