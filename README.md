# Dealflow

A sales CRM: a FastAPI + PostgreSQL backend with Celery/Redis background jobs, and a React
front end. AI agents that work the pipeline alongside the team are on the way (see Roadmap).

## Features

**Core**
- Contacts, companies, deals and activities (calls, meetings, tasks, emails, notes), with
  search, filters and pagination
- Pipelines with ordered stages and win probabilities; deals move between stages and are
  marked won, lost (with a reason) or reopened
- Deal timeline: change history and activities in one list (`GET /deals/{id}/timeline`)
- Custom fields on contacts, companies and deals (stored as JSON)
- JWT login and four roles: **owner**, **admin** (all records, settings, users),
  **agent** (only their own records), **viewer** (read-only)

**Pipeline insight**
- **Rotting deals**: a Celery job flags open deals that have sat in one stage longer than
  the pipeline's `rotting_days` (default 14), logs it on the deal's timeline and creates a
  follow-up task for the owner. Moving or closing the deal clears the flag.
  Filter with `GET /deals?rotting=true`.
- **Kanban board** (`GET /pipelines/{id}/board`): one column per stage with its deals,
  total value, probability-weighted forecast and number of rotting deals
- **Lost-reason analytics** (`GET /dashboard/lost-reasons?days=90`): count, value and share
  of lost deals per reason
- **Pipeline summary** (`GET /dashboard/pipeline/{id}`): open, weighted, won and lost totals

Agents see only their own numbers everywhere; owners, admins and viewers see the whole team.

**Front end** (React, in progress)
- Sign in, role-aware navigation, and a pipeline board showing each stage's deals, totals,
  forecast and stalled deals; works on phones and follows the system light/dark setting

## Run it

You need Python 3.11+, [uv](https://docs.astral.sh/uv/) and Docker (for Postgres and Redis).

```bash
docker compose up -d          # Postgres (dealflow + dealflow_test databases) and Redis
cd backend
uv sync
cp .env.example .env          # then set SECRET_KEY
uv run bash scripts/prestart.sh    # migrate + create the first owner and default pipeline
uv run fastapi dev app/main.py
```

In a second terminal, start the background worker and its scheduler:

```bash
cd backend && uv run celery -A app.worker worker --beat --loglevel=info
```

Optionally load a demo sales team and pipeline (users `meera@`, `arjun@`, `sana@` and
`vikram@dealflow.dev`, password `demo-password`):

```bash
cd backend && uv run python -m app.demo_data
```

Then start the front end in a third terminal (needs Node 20+):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and sign in as `owner@example.com` / `changethis123` (from `.env`) or a
demo user. The API's interactive docs are at http://localhost:8000/docs.

## Develop

```bash
cd backend
uv run pytest                 # runs against the dealflow_test database
uv run ruff check . && uv run ruff format .
uv run alembic revision --autogenerate -m "describe change"   # after editing app/models.py
```

```bash
cd frontend
npm run build && npm run lint
# after changing the API, regenerate the typed client in src/client:
(cd ../backend && uv run python scripts/export_openapi.py) && npm run generate-client
```

## Layout

```
backend/app/
  models.py            tables + request/response schemas
  api/access.py        record-level access rules (who sees and edits what)
  api/deps.py          DB session, current user, role checks
  api/routes/          one file per resource
  services/rotting.py  stalled-deal check (run by the worker)
  services/stats.py    totals and weighted forecasts
  worker.py            Celery app and schedule
  initial_data.py      first owner, default "Sales" pipeline, lost reasons
  demo_data.py         demo sales team, companies, contacts and deals
backend/alembic/       migrations
backend/tests/
frontend/src/
  client/              generated API client and React Query hooks (don't edit by hand)
  lib/auth.ts          sign-in token, current user, role permissions
  components/          layout, route guards, UI building blocks
  pages/               one file per screen
```

## Roadmap

- [x] Phase 1: core backend
- [x] Phase 2: rotting deals, kanban board data, lost-reason analytics
- [ ] Phase 3: React front end and AI agents
  - [x] 3a: front-end skeleton, sign-in, generated API client, read-only board
  - [ ] 3b: drag-and-drop board, deal page with timeline
  - [ ] 3c: agent foundation: shared action layer, Copilot chat with approval of every change
  - [ ] 3d: pipeline agent that reviews stalled deals nightly, and an agent inbox
  - [ ] 3e: contacts, companies, my activities
  - [ ] 3f: dashboard charts, admin settings
  - [ ] 3g: end-to-end tests and CI; MCP server so Claude can work with Dealflow directly
- [ ] Phase 4: CSV import with dedupe, saved views, live board updates over WebSockets,
      WhatsApp messaging
