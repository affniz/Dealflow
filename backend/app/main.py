from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.api.routes import (
    activities,
    board,
    companies,
    contacts,
    copilot,
    dashboard,
    deals,
    login,
    pipelines,
    settings,
    tokens,
    usage,
    users,
)
from app.core.config import settings as config
from app.mcp_server import route as mcp_route
from app.mcp_server import running as mcp_running


def operation_id(route: APIRoute) -> str:
    """Stable, readable names for the generated front-end client, e.g. deals-list_deals."""
    return f"{route.tags[0]}-{route.name}" if route.tags else route.name


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with mcp_running():
        yield


app = FastAPI(
    lifespan=lifespan,
    generate_unique_id_function=operation_id,
    title=config.PROJECT_NAME,
    openapi_url=f"{config.API_V1_STR}/openapi.json",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter()
for module in (
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
):
    api.include_router(module.router)
app.include_router(api, prefix=config.API_V1_STR)
# Claude connects here over MCP (Streamable HTTP) with a personal access token
app.router.routes.append(mcp_route)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
