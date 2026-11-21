#!/usr/bin/env bash
# Start the deployed app (the Docker image runs this): bring the database up to date, then
# start the background worker and the API.
set -euo pipefail
cd "$(dirname "$0")/.."

bash scripts/prestart.sh
case "${DEMO_MODE:-}" in
  true | True | 1) python -m app.demo_data --if-missing ;;
esac

if [ "${RUN_WORKER:-true}" = "true" ]; then
  # Stalled-deal checks and the morning pipeline review, in one small process next to the
  # API. Where the host offers background workers, set RUN_WORKER=false and run this
  # command as a service of its own instead.
  celery -A app.worker worker --beat --pool solo --loglevel=info &
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips '*'
