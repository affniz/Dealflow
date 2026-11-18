"""Which Claude model and effort each agent uses.

Defaults come from the environment (COPILOT_MODEL, PIPELINE_MODEL, ...); admins override them in
the app, stored in the `appsetting` table.
"""

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status
from sqlmodel import Session

from app.agent.pricing import price_for
from app.core.config import settings
from app.models import AISettings, AISettingsUpdate, AppSetting, ModelOption, User, utcnow

KEY = "ai"
EFFORTS = ["low", "medium", "high", "xhigh", "max"]


@dataclass(frozen=True)
class ModelInfo:
    name: str
    note: str
    # Haiku 5.5 has no server-side refusal fallback, so don't send the parameter for it
    server_fallback: bool = True


SUPPORTED_MODELS: dict[str, ModelInfo] = {
    "claude-opus-5-5": ModelInfo(
        "Claude Opus 5.5", "Most capable; best for long, open-ended questions"
    ),
    "claude-sonnet-5-5": ModelInfo(
        "Claude Sonnet 5.5", "Fast and capable; handles most CRM work at half Opus's price"
    ),
    "claude-haiku-5-5": ModelInfo(
        "Claude Haiku 5.5",
        "Cheapest; fine for narrow, repetitive jobs like routine deal reviews",
        server_fallback=False,
    ),
}


def model_info(model: str) -> ModelInfo:
    # a model set in the environment but not listed here still works, with the defaults
    return SUPPORTED_MODELS.get(model, ModelInfo(model, ""))


def _defaults() -> dict[str, Any]:
    return {
        "copilot_model": settings.COPILOT_MODEL,
        "copilot_effort": settings.COPILOT_EFFORT,
        "pipeline_model": settings.PIPELINE_MODEL,
        "pipeline_effort": settings.PIPELINE_EFFORT,
    }


def get_ai_settings(session: Session) -> AISettings:
    stored = session.get(AppSetting, KEY)
    return AISettings(**{**_defaults(), **(stored.value if stored else {})})


def update_ai_settings(session: Session, user: User, body: AISettingsUpdate) -> AISettings:
    changes = body.model_dump(exclude_none=True)
    for key in ("copilot_model", "pipeline_model"):
        if key in changes and changes[key] not in SUPPORTED_MODELS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{changes[key]} isn't one of the supported models",
            )
    stored = session.get(AppSetting, KEY) or AppSetting(key=KEY, value={})
    stored.value = {**stored.value, **changes}  # a new dict, so the JSON column is saved
    stored.updated_at = utcnow()
    stored.updated_by_id = user.id
    session.add(stored)
    session.commit()
    return get_ai_settings(session)


def model_options() -> list[ModelOption]:
    out = []
    for model_id, info in SUPPORTED_MODELS.items():
        price = price_for(model_id)
        assert price is not None, f"no price for {model_id}"
        out.append(
            ModelOption(
                id=model_id,
                name=info.name,
                note=info.note,
                input_usd_per_mtok=price.input,
                output_usd_per_mtok=price.output,
            )
        )
    return out
