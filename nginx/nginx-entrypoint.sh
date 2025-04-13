#!/bin/sh
set -e

# Substitute env vars in template
envsubst '${DJANGO_UPSTREAM_HOST}' < /etc/nginx/nginx.template.conf > /etc/nginx/nginx.conf

# Optional: view the output
echo "----- Rendered nginx.conf -----"
cat /etc/nginx/nginx.conf
echo "-------------------------------"

# Start nginx
exec nginx -g 'daemon off;'