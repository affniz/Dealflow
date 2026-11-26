#!/usr/bin/env bash
# The API for the Playwright tests: a fresh copy of the demo data, and a scripted stand-in
# for Claude (app/agent/scripted.py), so the Copilot works without calling it.
# Playwright starts this itself (see frontend/playwright.config.ts).
set -euo pipefail
cd "$(dirname "$0")/.."
DATABASE_URL="$(python scripts/e2e_db.py --url)"
export DATABASE_URL
export AI_ENABLED=true AI_SCRIPTED=true
python scripts/e2e_db.py --reset
exec uvicorn app.main:app --port "${E2E_API_PORT:-8010}"
