# Dealflow

An agentic CRM for B2B sales teams: a FastAPI + PostgreSQL backend with Celery/Redis background
jobs, a React front end, and a Claude-powered Copilot that looks things up and prepares changes,
with a person approving every change.

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
- **Pipeline board**: drag deals between stages (the move shows instantly and is undone if the
  server refuses it); each column shows its count, total, weighted forecast and stalled deals;
  "My deals" and "Stalled only" filters; add a deal from the board
- **Deal page**: clickable stage bar; Won, Lost (with a reason), Reopen, Edit and Delete; the
  deal's timeline of changes and activities; log a note, call or meeting, or schedule a task
- Sign-in and role-aware screens: viewers get no edit controls, agents see only their own deals;
  works on phones and follows the system light/dark setting

**Copilot (AI)**
- A chat panel on every page. Ask "what's stalled and what should I do?" or "log a call with
  Priya and move it to Proposal"; it knows which deal you're looking at
- It reads with your access (agents' Copilot sees only their deals) and **proposes** changes as
  cards you approve or reject, in the chat or on the deal page; approved changes show
  "via Copilot" on the timeline
- Viewers can ask questions but can't change anything

**Pipeline agent (AI)**
- Every morning (07:00 in the team's time zone) it reviews each stalled deal as the deal's owner:
  reads the history, proposes at most two concrete next steps (usually a specific follow-up
  task) and leaves the owner a short note
- Suggestions land in the **agent inbox** (sidebar badge shows how many are waiting), next to
  the agent's notes; approve or reject there or on the deal page. Admins can see everyone's and
  start a review on demand
- Bounded by design: a cap on deals per run and model calls per deal, deals with pending
  suggestions or a review in the last 3 days are skipped, one failed deal doesn't stop the run,
  and a database lock stops two workers reviewing at once

**AI model settings**
- Admins choose the Claude model (Opus 5.5, Sonnet 5.5 or Haiku 5.5) and effort for each agent
  in Settings; both default to Sonnet 5.5 at medium effort (`COPILOT_MODEL`, `PIPELINE_MODEL`,
  ... in `.env`)
- A Copilot chat keeps the model and effort it started with, so its prompt cache and earlier
  reasoning stay valid; changes apply to new chats and the next pipeline review

**AI usage tracking**
- Every Claude call is recorded with its model, token counts (input, cache reads, cache writes,
  output) and cost in USD from a dated price table (`app/agent/pricing.py`); a call that falls
  back to another model is billed per model. Calls made before a failed turn are still recorded
- Admins get an **AI usage** page: month spend, cost per Copilot question and per deal review,
  daily spend, and breakdowns by feature, person and model. Everyone sees their own Copilot
  spend in the Copilot panel

### How the Copilot works

- **Loop** (`app/agent/copilot.py`): a tool-use loop on the Claude Messages API, run in the
  backend. Each user message runs up to `COPILOT_MAX_STEPS` model calls: Claude asks for tools,
  Dealflow runs them and sends back the results, until Claude answers.
- **Tools** (`app/agent/tools.py`): six read tools (search deals, read a deal and its history,
  contacts, activities, pipeline overview, lost-deal report) and six change tools. Each tool's
  input is a Pydantic model, sent as a `strict` schema and re-validated before it runs.
- **Human approval**: change tools never change anything. They create an `AgentProposal`; when
  a person approves it, it runs through the same action layer as the REST API
  (`app/services/actions.py`), with the approver's access checked at that moment. If the deal
  changed meanwhile (say it was closed), the proposal is marked failed with the reason.
- **Access**: tools run as the signed-in user, so the Copilot can't see or touch what the user
  couldn't. Text inside CRM records is treated as data, never as instructions.
- **History**: conversations are stored exactly as sent to the API and only appended to; the
  model's thinking blocks are only valid in an unedited history. The system prompt and tool
  list never change, and per-turn facts (current time, the user, the deal on screen) go in a
  system message after the user's message, so prompt caching keeps working.
- **Safety nets**: a step limit per message, server-side model fallback if a safety classifier
  declines, and a polite reply on refusal.
- **Pipeline agent** (`app/agent/pipeline.py`) uses the same loop and tools with its own
  prompt, as the deal owner, with a hard cap of two proposals per deal. Each review is stored as
  an `AgentRun` (note, tokens, full message history) for the inbox and for auditing.
- **Tests** (`tests/test_copilot.py`, `tests/test_pipeline_agent.py`) use a scripted stand-in for
  Claude: no network or API key.

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

In a second terminal, start the background worker and its scheduler (stalled-deal checks every
hour, pipeline agent every morning):

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

To turn on the AI features, put an Anthropic API key in `backend/.env` (`ANTHROPIC_API_KEY=...`)
or sign in with `ant auth login`, then restart the API. Everything else works without it.

To try the agents against the real models and see what each question costs (on a demo database):

```bash
cd backend && uv run python scripts/live_check.py                            # the app's settings
cd backend && uv run python scripts/live_check.py --model claude-opus-5-5    # try another model
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
npm run format                # Prettier
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
  agent/               AI agents: shared tool-use loop, tools, Copilot, pipeline agent,
                       proposal approval, usage ledger and prices
  services/actions.py  every change to deals and activities (used by the API and the agents)
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
  - [x] 3b: drag-and-drop board, deal page with timeline
  - [x] 3c: agent foundation: shared action layer, Copilot chat with approval of every change
  - [x] 3d: pipeline agent that reviews stalled deals every morning, and an agent inbox
  - [ ] 3e: contacts, companies, my activities
  - [ ] 3f: dashboard charts, admin settings
  - [ ] 3g: end-to-end tests and CI; MCP server so Claude can work with Dealflow directly
- [ ] Phase 4: CSV import with dedupe, saved views, live board updates over WebSockets,
      WhatsApp messaging
