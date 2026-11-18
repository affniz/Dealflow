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
    usage,
    users,
)
from app.core.config import settings


def operation_id(route: APIRoute) -> str:
    """Stable, readable names for the generated front-end client, e.g. deals-list_deals."""
    return f"{route.tags[0]}-{route.name}" if route.tags else route.name


app = FastAPI(
    generate_unique_id_function=operation_id,
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter()
for module in (
    login,
    users,
    companies,
    contacts,
    pipelines,
    board,
    deals,
    activities,
    dashboard,
    copilot,
    usage,
):
    api.include_router(module.router)
app.include_router(api, prefix=settings.API_V1_STR)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
