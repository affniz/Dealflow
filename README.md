# CRM

A sales CRM built with FastAPI, following the plan in the "Open-Source CRM Projects on GitHub" doc.

**Phase 1 (done): core backend**
- Contacts, companies, deals, activities, with search, filters and pagination
- Pipelines with ordered stages and win probabilities; lost reasons
- Deals: move between stages, mark won / lost (with a reason) / reopen
- Deal timeline: change history + activities in one list (`GET /deals/{id}/timeline`)
- Dashboard: per-stage counts, totals and probability-weighted forecast
- JWT login and four roles: **owner**, **admin** (all records, settings, users),
  **agent** (only their own records), **viewer** (read-only)
- Custom fields on contacts, companies and deals (stored as JSON)
- Alembic migrations (tested on Postgres and sqlite), 22 pytest tests

## Run it

```bash
cd backend
uv sync                      # installs dependencies into .venv
cp .env.example .env         # then set SECRET_KEY
uv run bash scripts/prestart.sh   # migrate + create the first owner and default pipeline
uv run fastapi dev app/main.py
```

Open http://localhost:8000/docs, click **Authorize**, and log in as `owner@example.com` /
`changethis123` (from `.env`).

To use Postgres instead of sqlite: `docker compose up -d db`, then set
`DATABASE_URL=postgresql+psycopg://crm:crm@localhost:5432/crm` in `backend/.env` and rerun the
prestart script.

## Develop

```bash
cd backend
uv run pytest                 # tests (in-memory sqlite)
uv run ruff check . && uv run ruff format .
uv run alembic revision --autogenerate -m "describe change"   # after editing app/models.py
```

## Layout

```
backend/app/
  models.py          tables + request/response schemas
  api/access.py      record-level access rules (who sees and edits what)
  api/deps.py        DB session, current user, role checks
  api/routes/        one file per resource
  initial_data.py    first owner, default "Sales" pipeline, lost reasons
backend/alembic/     migrations
backend/tests/
```

## Roadmap

- **Phase 2, standout features:** rotting-deal flags (Celery + Redis job using
  `stage_changed_at` and `pipeline.rotting_days`), lost-reason analytics endpoint, weighted
  totals per kanban column
- **Phase 3, front end:** React kanban board, deal workspace page with the timeline
- **Phase 4, extras:** CSV import with dedupe, saved views, live board updates over
  WebSockets, WhatsApp or AI-drafted replies
