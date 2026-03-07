#!/bin/bash

set -euo pipefail

export DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE:-config.settings}

cd /app/SimWorks

if [ "${DJANGO_COLLECTSTATIC:-0}" = "1" ]; then
  echo
  echo "Collecting static files..."
  python manage.py collectstatic --noinput --clear
else
  echo
  echo "Skipping collectstatic; using baked assets."
fi

if [ "${DJANGO_MIGRATE:-0}" = "1" ]; then
  echo
  echo "Applying database migrations..."
  python manage.py migrate
else
  echo
  echo "Skipping database migrations."
fi

if [ "${DJANGO_CREATE_DEFAULT_ROLES:-0}" = "1" ]; then
  echo
  echo "Seeding default roles..."
  python manage.py seed_roles
else
  echo
  echo "Skipping default role creation."
fi

exec "$@"
