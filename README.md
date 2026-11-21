# Dealflow

[![CI](https://github.com/affniz/Dealflow/actions/workflows/ci.yml/badge.svg)](https://github.com/affniz/Dealflow/actions/workflows/ci.yml)

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

**Front end** (React)
- **Pipeline board**: drag deals between stages (the move shows instantly and is undone if the
  server refuses it); each column shows its count, total, weighted forecast and stalled deals;
  "My deals" and "Stalled only" filters; add a deal from the board
- **Deal page**: clickable stage bar; Won, Lost (with a reason), Reopen, Edit and Delete; the
  deal's timeline of changes and activities; log a note, call or meeting, or schedule a task
- **Contacts and companies**: searchable, sortable lists (search covers full names, email, phone
  and company name; admins can filter by owner), kept in the URL so they survive reloads and
  links. Each record has a page with its activities (to-dos first, then history), deals, people
  (for a company) and details, and is added or edited in a side panel without leaving the page
- **My activities**: open tasks, calls, meetings and emails grouped into Overdue, Today (in your
  own time zone), Upcoming and No due date; a "Done & notes" history; tick things off, edit them
  in a side panel, or add one linked to a deal, contact and company
- **Dashboard**: open pipeline, weighted forecast, won value and win rate for a period; open value
  by stage and lost deals by reason as bar charts (each with a table view); the stalled deals.
  Filter by pipeline, period and (for admins) person; agents see their own numbers
- **Settings** (admins): add people, change roles, deactivate and reactivate; rename, reorder,
  add and delete stages and set their win chance and the stalled-deal limit; add, rename and
  retire lost reasons; AI models and budgets
- **Your account** (everyone): change your name and password, and create tokens for
  connecting Claude
- Sign-in and role-aware screens: viewers get no edit controls, agents see only their own deals;
  works on phones and follows the system light/dark setting

**Copilot (AI)**
- A chat panel on every page. Ask "what's stalled and what should I do?" or "log a call with
  Priya and move it to Proposal"; it knows which deal you're looking at
- It reads with your access (agents' Copilot sees only their deals) and **proposes** changes as
  cards you approve or reject, in the chat or on the deal page; approved changes show
  "via Copilot" on the timeline
- Viewers can ask questions but can't change anything

**Claude over MCP**
- Dealflow is an [MCP](https://modelcontextprotocol.io) server at `/mcp`, so Claude Code,
  Claude Desktop or any MCP client can work with the CRM directly: "which of my deals are
  stalled?", "draft follow-up tasks for everything in Negotiation"
- It serves the Copilot's own twelve tools, as the person whose personal access token connects
  it: same access rules (an agent's Claude sees only their deals), and every change it wants to
  make lands in that person's **agent inbox** for approval, marked "Claude (MCP)"
- Create and revoke tokens under **Your account**, which also prints the `claude mcp add`
  command. Only a SHA-256 hash of each token is stored, and a deactivated person's tokens stop
  working at once

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

**AI budgets**
- Monthly limits in USD: one per person for the Copilot (default $10) and one for the whole
  team's pipeline agent (default $20); admins change them in Settings, or set no limit
- Checked before every model call, so a question or review can go over by at most one call. Past
  the limit, new Copilot questions are refused with the reset date, an answer in progress stops
  with a note, and the pipeline agent stops reviewing deals for the month
- Everyone sees their own spend against their limit in the Copilot panel (highlighted from 80%);
  the AI usage page shows each budget's use

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
- **Caching**: the tools and system prompt get their own cache point, shared by every chat and
  deal review; automatic caching covers each conversation's growing history.
- **Prompt versions**: a chat keeps the Copilot prompt version it started with (like its model),
  since editing the system prompt of a chat under way would invalidate its earlier reasoning.
  To change the prompt, add a version in `app/agent/copilot.py`; don't edit an old one.
- **Safety nets**: a step limit per message, server-side model fallback if a safety classifier
  declines, and a polite reply on refusal.
- **Pipeline agent** (`app/agent/pipeline.py`) uses the same loop and tools with its own
  prompt, as the deal owner, with a hard cap of two proposals per deal. Each review is stored as
  an `AgentRun` (note, tokens, full message history) for the inbox and for auditing.
- **Tests** (`tests/test_copilot.py`, `tests/test_pipeline_agent.py`) use a scripted stand-in for
  Claude: no network or API key.

### Connect Claude to Dealflow (MCP)

1. In Dealflow, open **Your account** (your name at the bottom of the sidebar) and create a token.
2. Run the command it shows, for example:

   ```bash
   claude mcp add --transport http dealflow http://localhost:5173/mcp --header "Authorization: Bearer dfp_…"
   ```

3. Ask Claude about your pipeline. Approve or reject what it suggests in the agent inbox.

Other MCP clients connect to the same URL over Streamable HTTP with that header. The server
(`app/mcp_server.py`) is mounted in the API, stateless with JSON responses, so it needs no
extra process and works behind several API workers.

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

## Deploy

The whole app is one Docker image (`Dockerfile`): it builds the React app, and the API serves
it from the same address, so there's no CORS to set up and the MCP address is simply the site's
address + `/mcp`. On start (`backend/scripts/start.sh`) it migrates the database, creates the
first owner, starts the background worker next to the API (`RUN_WORKER=false` turns that off,
for hosts where the worker runs as its own service) and serves on `$PORT`.

```bash
docker build -t dealflow .
docker run -p 8000:8000 -e SECRET_KEY=... -e FIRST_OWNER_PASSWORD=... \
  -e DATABASE_URL=postgresql://... -e REDIS_URL=redis://... dealflow
```

It refuses to start in production with the development `SECRET_KEY` or owner password, and it
accepts the `postgres://` URLs hosts hand out.

**Render**: `render.yaml` is a Blueprint for the web service, Postgres and Redis, on free plans
in Singapore. In Render, choose **New > Blueprint**, pick this repository and paste an Anthropic
API key when asked (or leave it empty to run without the AI). It redeploys when `main` passes
CI. The owner account's password is generated: find `FIRST_OWNER_PASSWORD` under the service's
Environment. Free plans suit a demo: the service sleeps after 15 idle minutes (the next visit
takes about a minute) and the free database expires after 30 days.

**Public demo** (`DEMO_MODE=true`, on in `render.yaml`): loads the sample team on first start and
puts one-click sign-in for each role on the sign-in page. Visitors share one database, so it
refuses the changes that would spoil it for the next person or raise the AI bill: passwords,
adding or changing people, AI models and budgets. That makes the budgets a hard ceiling; the
Blueprint sets $2 a month per person for the Copilot and $3 for the pipeline agent.

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

End-to-end tests (Playwright) drive the real app in Chromium: signing in, the board (including
drag and drop), deals won and lost, contacts, activities, role access, the dashboard, settings,
and connecting Claude over MCP. They start their own API and front end on ports 8010 and 5174,
on a `dealflow_e2e` database that is reset to the demo data on every run, with AI turned off:

```bash
cd frontend
npx playwright install chromium   # once
npm run e2e
```

**CI** (`.github/workflows/ci.yml`) runs on every pull request and push to `main`: backend lint,
migrations applied and checked against the models, the test suite on Postgres, a check that the
generated API schema and client are up to date, front-end formatting, lint and build, and the
end-to-end tests. CI sets `AI_ENABLED=false`, so it never calls Claude.

## Product decisions

- **The AI proposes; a person approves.** CRM data feeds forecasts and commissions, so a wrong
  write costs more than a slow one. Every change the Copilot, the pipeline agent or Claude over
  MCP wants to make is a proposal, applied through the same action layer as the app's own
  buttons, with the approver's access checked at the moment they approve.
- **The AI has exactly the user's access.** Tools run as the signed-in person, so an agent's
  Copilot can't read a colleague's deals, and a viewer's can't propose anything. Access rules
  live in one place (`api/access.py`) instead of being repeated in prompts.
- **Stalled deals are the agent's job.** Pipelines rarely leak because of one bad call; they
  leak because deals sit untouched. The worker flags deals that have overstayed their stage and
  the pipeline agent turns each into at most two concrete next steps, every morning, before the
  team starts.
- **Spending has a ceiling.** Monthly budgets per person and for the team are checked before
  every model call, and every call is recorded with its cost, so an admin can answer "what does
  the AI cost us per deal reviewed?" from the AI usage page.
- **Built for Indian B2B teams.** Rupees by default with lakh and crore, the team's time zone
  (default Asia/Kolkata) for "today" and the morning review, and the agent writes amounts the
  way the team says them.
- **One set of tools, three ways in.** The Copilot, the pipeline agent and the MCP server share
  the same twelve tools, so Claude Code or Claude Desktop gets the same abilities and limits as
  the in-app Copilot. MCP uses personal access tokens (stored hashed, revocable) rather than
  OAuth: simpler for a team tool, and enough until there's a need for third-party apps.
- **Cache-friendly by construction.** Conversation history is append-only and the system
  prompt never changes inside a chat (new prompt versions apply to new chats), so prompt
  caching keeps working and long chats stay cheap.
- **Left out on purpose (for now)**: email and calendar sync, WhatsApp, CSV import and live
  updates. They're the next phase; the core loop of deals, stalls, suggestions and approvals
  came first.

## Layout

```
backend/app/
  models.py            tables + request/response schemas
  api/access.py        record-level access rules (who sees and edits what)
  api/deps.py          DB session, current user, role checks
  api/routes/          one file per resource
  agent/               AI agents: shared tool-use loop, tools, Copilot, pipeline agent,
                       proposal approval, usage ledger and prices
  mcp_server.py        the MCP server at /mcp (the Copilot's tools, for Claude via a token)
  services/actions.py  every change to deals and activities (used by the API and the agents)
  services/rotting.py  stalled-deal check (run by the worker)
  services/stats.py    totals and weighted forecasts
  worker.py            Celery app and schedule
  initial_data.py      first owner, default "Sales" pipeline, lost reasons
  demo_data.py         demo sales team, companies, contacts and deals
backend/alembic/       migrations
backend/scripts/       start (Docker), OpenAPI export, live AI check, e2e database and server
backend/tests/
frontend/src/
  client/              generated API client and React Query hooks (don't edit by hand)
  lib/auth.ts          sign-in token, current user, role permissions
  components/          layout, route guards, UI building blocks
  pages/               one file per screen
frontend/e2e/          Playwright end-to-end tests
.github/workflows/     CI
Dockerfile             the deployable image (API + React app + worker)
render.yaml            Render Blueprint: web service, Postgres, Redis
```

## Roadmap

- [x] Phase 1: core backend
- [x] Phase 2: rotting deals, kanban board data, lost-reason analytics
- [x] Phase 3: React front end and AI agents
  - [x] 3a: front-end skeleton, sign-in, generated API client, read-only board
  - [x] 3b: drag-and-drop board, deal page with timeline
  - [x] 3c: agent foundation: shared action layer, Copilot chat with approval of every change
  - [x] 3d: pipeline agent that reviews stalled deals every morning, and an agent inbox
  - [x] 3e: contacts, companies, my activities
  - [x] 3f: dashboard charts, admin settings
  - [x] 3g: end-to-end tests and CI; MCP server so Claude can work with Dealflow directly
- [ ] Ship
  - [x] One Docker image, a Render Blueprint and a public demo mode
  - [x] Product decisions in this README
  - [ ] Live demo link and a GIF
- [ ] Phase 4: CSV import with dedupe, saved views, live board updates over WebSockets,
      WhatsApp messaging
