#!/bin/bash

# cd SimWorks

# Set Django settings module
export DJANGO_SETTINGS_MODULE=SimWorks.settings

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

# Create AppDev superuser if it doesn't exist,
# and only if DJANGO_DEBUG is set to True in .env
if [ "${DJANGO_DEBUG:-}" = "True" ]; then
  echo
  echo "Checking for Developer superuser if not exists..."
  python manage.py shell -c "\
from django.contrib.auth import get_user_model; \
User = get_user_model(); \
User.objects.filter(username='appDev').exists() or \
User.objects.create_superuser('appDev', 'dev@example.com', 'appDev')"
else
  echo "Skipping dev superuser setup — DJANGO_DEBUG is not set to 'True'."
fi

# Start server
echo
echo "Starting daphne server..."
daphne -b 0.0.0.0 -p 8000 SimWorks.asgi:application
