#!/bin/bash

# Set Django settings module
export DJANGO_SETTINGS_MODULE=SimWorks.settings

# Collect static files
echo
echo "Collecting static files..."
python manage.py collectstatic -v 1 --no-input

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
    UserRole(name='EMT (NREMT-B)'), \
    UserRole(name='Paramedic (NRP)'), \
    UserRole(name='Military Medic'), \
    UserRole(name='SOF Medic'), \
    UserRole(name='RN'), \
    UserRole(name='RN, BSN'), \
    UserRole(name='Physician') \
])"

# Start server
echo
echo "Starting daphne server..."
daphne -b 0.0.0.0 -p 8000 SimWorks.asgi:application
