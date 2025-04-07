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

# Start server
echo
echo "Starting daphne server..."
daphne -b 0.0.0.0 -p 8000 SimWorks.asgi:application
