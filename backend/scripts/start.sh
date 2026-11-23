#!/usr/bin/env bash
# Start the deployed app (the Docker image runs this): bring the database up to date, then
# start the background worker and the API.
set -euo pipefail
cd "$(dirname "$0")/.."

bash scripts/prestart.sh
case "${DEMO_MODE:-}" in
  true | True | 1) python -m app.demo_data --refresh ;;
esac

server=(uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
  --proxy-headers --forwarded-allow-ips '*' --no-access-log)

if [ "${RUN_WORKER:-true}" != "true" ]; then
  exec "${server[@]}"
fi

# Stalled-deal checks, the morning pipeline review and the demo's daily reset, in one small
# process next to the API; it catches up on what came due while the host slept. Where the host
# offers background workers, set RUN_WORKER=false and run this command as a service of its own.
celery -A app.worker worker --beat --pool solo --loglevel=info &
worker=$!
"${server[@]}" &
api=$!

# The host stops the container with SIGTERM: pass it on to both and let them finish up.
stopping=false
trap 'stopping=true; kill -TERM "$api" "$worker" 2>/dev/null || true' TERM INT

# If either one stops by itself, stop the other and exit, so the host restarts the container.
# (Otherwise a crashed worker would leave the app up but with no background jobs at all.)
status=0
wait -n "$api" "$worker" || status=$?
if [ "$stopping" = false ]; then
  which=$(kill -0 "$api" 2>/dev/null && echo "background worker" || echo "API")
  echo "start.sh: the $which stopped (exit status $status), so the app is stopping too" >&2
  kill -TERM "$api" "$worker" 2>/dev/null || true
  status=$((status == 0 ? 1 : status)) # a restart is needed either way
else
  status=0
fi
wait || true
exit "$status"
