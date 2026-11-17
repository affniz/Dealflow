#!/usr/bin/env bash
# Bring the database schema up to date and make sure the first owner + default pipeline exist.
set -euo pipefail
cd "$(dirname "$0")/.."
alembic upgrade head
python -m app.initial_data
