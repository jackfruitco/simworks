#!/bin/bash

set -euo pipefail

# Kept as a dev alias for compatibility; use the shared generic entrypoint logic.
exec /app/docker/entrypoint.sh "$@"
