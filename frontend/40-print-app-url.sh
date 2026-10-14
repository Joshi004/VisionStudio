#!/bin/sh
# Runs when the frontend container starts (the nginx image runs every script in
# /docker-entrypoint.d/). This container starts last, once the backend is healthy, so the
# line appears at the end of the `docker compose up` output.
# APP_URL is set in docker-compose.yml from APP_PORT.
echo ""
echo "=============================================================="
echo "  Visio Studio is ready:  ${APP_URL:-http://localhost}"
echo "=============================================================="
echo ""
