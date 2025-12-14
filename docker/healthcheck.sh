#!/bin/bash
export DJANGO_SKIP_READY=1

# Check if Django server is responding
if curl -fs --max-time 3 http://localhost:8000/health > /dev/null; then
    echo "Healthcheck passed."
    exit 0
else
    echo "Healthcheck failed."
    exit 1
fi
