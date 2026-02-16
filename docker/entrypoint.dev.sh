#!/bin/bash

set -euo pipefail

# Allow bypassing all entrypoint behavior (useful for debugging / running one-off manage.py commands)
# Example:
#   docker compose run --rm -e DJANGO_ENTRYPOINT_SKIP=1 --entrypoint bash server -lc "python manage.py migrate --plan"
if [ "${DJANGO_ENTRYPOINT_SKIP:-0}" = "1" ]; then
  exec "$@"
fi

# Allow selectively skipping heavy startup steps
DJANGO_RUN_MAKEMIGRATIONS_CHECK="${DJANGO_RUN_MAKEMIGRATIONS_CHECK:-1}"
DJANGO_RUN_MIGRATE="${DJANGO_RUN_MIGRATE:-1}"
DJANGO_RUN_SEED_ROLES="${DJANGO_RUN_SEED_ROLES:-1}"
DJANGO_RUN_DEV_SUPERUSER="${DJANGO_RUN_DEV_SUPERUSER:-1}"

# If running as root, fix perms on mounted volumes then drop to appuser.
if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/static /app/media /app/logs
  chown -R appuser:appuser /app/static /app/media /app/logs || true
  exec gosu appuser "$0" "$@"
fi

echo "Entrypoint running as: $(id)"

# Set Django settings module
export DJANGO_SETTINGS_MODULE=config.settings

# Collect static files
echo
echo "Collecting static files..."
if [ "${DJANGO_COLLECTSTATIC:-0}" = "1" ]; then
  python manage.py collectstatic --noinput --clear
fi

echo
echo "Checking for pending migrations (dry-run)..."
if [ "$DJANGO_RUN_MAKEMIGRATIONS_CHECK" = "1" ] && ! python manage.py makemigrations --check --dry-run; then
  echo "Migrations are pending; generate them locally with 'python manage.py makemigrations' if desired."
fi

# Apply database migrations
echo
echo "Applying database migrations..."
if [ "$DJANGO_RUN_MIGRATE" = "1" ]; then
  python manage.py migrate
else
  echo "Skipping migrate — DJANGO_RUN_MIGRATE=$DJANGO_RUN_MIGRATE"
fi

# Create default UserRole objects
if [ "$DJANGO_RUN_SEED_ROLES" = "1" ]; then
  echo
  echo "Creating default user roles if not already exists..."
  python manage.py shell -c "\
from apps.accounts.models import UserRole; \
UserRole.objects.exists() or UserRole.objects.bulk_create([ \
    UserRole(title='EMT (NREMT-B)'), \
    UserRole(title='Paramedic (NRP)'), \
    UserRole(title='Military Medic'), \
    UserRole(title='SOF Medic'), \
    UserRole(title='RN'), \
    UserRole(title='RN, BSN'), \
    UserRole(title='Physician') \
])"
else
  echo "Skipping role seeding — DJANGO_RUN_SEED_ROLES=$DJANGO_RUN_SEED_ROLES"
fi

# Create AppDev superuser if it doesn't exist,
# and only if DJANGO_DEBUG is set to True in .env
if [ "$DJANGO_RUN_DEV_SUPERUSER" = "1" ] && [ "${DJANGO_DEBUG:-}" = "True" ]; then
  echo
  echo "Creating developer superuser if not exists..."
  python manage.py shell -c "\
from django.contrib.auth import get_user_model; \
User = get_user_model(); \
role, created = UserRole.objects.get_or_create(title='SOF Medic')
User.objects.filter(email='dev@jkfrt.com').exists() or \
User.objects.create_superuser(email='dev@jkfrt.com', password='dev', role=role)"
else
  echo "Skipping dev superuser setup — DJANGO_DEBUG is not set to 'True'."
fi

# Start server
echo
echo "Starting daphne server..."
exec daphne -b 0.0.0.0 -p 8000 --access-log /dev/null config.asgi:application
