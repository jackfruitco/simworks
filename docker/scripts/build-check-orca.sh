#!/bin/bash
docker compose -f docker/compose.dev.yaml build --no-cache

docker compose -f docker/compose.dev.yaml run --rm server python manage.py check --deploy

docker compose -f docker/compose.dev.yaml run --rm server python manage.py ai_healthcheck