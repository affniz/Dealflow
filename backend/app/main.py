import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.agent import turns
from app.api.routes import (
    activities,
    board,
    client_errors,
    companies,
    contacts,
    copilot,
    dashboard,
    deals,
    login,
    meta,
    pipelines,
    settings,
    system,
    tokens,
    trash,
    usage,
    users,
)
from app.core.config import settings as config
from app.core.db import engine
from app.core.headers import SecurityHeaders
from app.core.logs import setup_logging
from app.core.monitoring import init_sentry
from app.core.requests import RequestLog, server_error
from app.mcp_server import route as mcp_route
from app.mcp_server import running as mcp_running


def operation_id(route: APIRoute) -> str:
    """Stable, readable names for the generated front-end client, e.g. deals-list_deals."""
    return f"{route.tags[0]}-{route.name}" if route.tags else route.name


setup_logging()
init_sentry("api")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with mcp_running():
        try:
            yield
        finally:
            turns.interrupt_all()  # Copilot replies this process won't get to finish


app = FastAPI(
    lifespan=lifespan,
    generate_unique_id_function=operation_id,
    title=config.PROJECT_NAME,
    openapi_url=f"{config.API_V1_STR}/openapi.json",
    docs_url="/docs",
)

app.add_middleware(SecurityHeaders)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestLog)  # outermost: it times and logs everything, CORS included
app.add_exception_handler(Exception, server_error)

api = APIRouter()
for module in (
    meta,
    login,
    users,
    tokens,
    companies,
    contacts,
    pipelines,
    board,
    deals,
    activities,
    dashboard,
    copilot,
    usage,
    settings,
    system,
    client_errors,
    trash,
):
    api.include_router(module.router)
app.include_router(api, prefix=config.API_V1_STR)
# Claude connects here over MCP (Streamable HTTP) with a personal access token
app.router.routes.append(mcp_route)


@app.get("/health", tags=["health"])
def health() -> JSONResponse:
    """For the host's health check: up, and able to reach the database."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        logging.getLogger(__name__).exception("Health check: can't reach the database")
        return JSONResponse({"status": "database unreachable"}, status_code=503)
    return JSONResponse({"status": "ok"})


def serve_front_end(app: FastAPI, directory: str) -> None:
    """Serve the built React app from the same address as the API: no CORS, and the MCP URL
    the Account page shows (this address + /mcp) is right wherever it's deployed."""
    static = Path(directory).resolve()
    app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def front_end(path: str) -> FileResponse:
        if path.split("/")[0] in ("api", "mcp", "docs"):
            raise HTTPException(404, "Not found")
        file = (static / path).resolve()
        if path and file.is_file() and file.is_relative_to(static):
            return FileResponse(file)  # favicon and other files in public/
        # Any other path is a page of the app: React Router renders it. Never cache this file,
        # so a new deploy's asset names are picked up at once.
        return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})


if config.STATIC_DIR:  # added last, so it only gets paths nothing above claimed
    serve_front_end(app, config.STATIC_DIR)
