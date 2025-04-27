#!/bin/bash

# Set Django settings module
export DJANGO_SETTINGS_MODULE=config.settings

# Collect static files
echo
echo "Collecting static files..."
python manage.py collectstatic -v 1 --no-input

echo
echo "Making migrations..."
python manage.py makemigrations

# Apply database migrations
echo
echo "Applying database migrations..."
python manage.py migrate

# Create default UserRole objects
echo
echo "Creating default user roles if not already exists..."
python manage.py shell -c "\
from accounts.models import UserRole; \
UserRole.objects.exists() or UserRole.objects.bulk_create([ \
    UserRole(title='EMT (NREMT-B)'), \
    UserRole(title='Paramedic (NRP)'), \
    UserRole(title='Military Medic'), \
    UserRole(title='SOF Medic'), \
    UserRole(title='RN'), \
    UserRole(title='RN, BSN'), \
    UserRole(title='Physician') \
])"

# Create AppDev superuser if it doesn't exist,
# and only if DJANGO_DEBUG is set to True in .env
if [ "${DJANGO_DEBUG:-}" = "True" ]; then
  echo
  echo "Creating developer superuser if not exists..."
  python manage.py shell -c "\
from django.contrib.auth import get_user_model; \
User = get_user_model(); \
role, created = UserRole.objects.get_or_create(title='SOF Medic')
User.objects.filter(username='appDev').exists() or \
User.objects.create_superuser(username='appDev', password='appDev', role=role)"
else
  echo "Skipping dev superuser setup — DJANGO_DEBUG is not set to 'True'."
fi

# Start server
echo
echo "Starting daphne server..."
daphne -b 0.0.0.0 -p 8000 config.asgi:application
