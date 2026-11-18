from fastapi import APIRouter

from app.api.deps import AdminUser, CurrentUser, SessionDep
from app.models import AISettingsUpdate, AISettingsView, Budgets
from app.services.ai_settings import EFFORTS, get_ai_settings, model_options, update_ai_settings
from app.services.budgets import get_budgets, update_budgets

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/ai", response_model=AISettingsView)
def read_ai_settings(session: SessionDep, _: CurrentUser) -> AISettingsView:
    """Which model and effort each agent uses, and the models that can be chosen."""
    return AISettingsView(
        settings=get_ai_settings(session), models=model_options(), efforts=EFFORTS
    )


@router.patch("/ai", response_model=AISettingsView)
def change_ai_settings(
    session: SessionDep, user: AdminUser, body: AISettingsUpdate
) -> AISettingsView:
    """Change an agent's model or effort. Copilot chats already under way keep theirs."""
    return AISettingsView(
        settings=update_ai_settings(session, user, body), models=model_options(), efforts=EFFORTS
    )


@router.get("/budgets", response_model=Budgets)
def read_budgets(session: SessionDep, _: AdminUser) -> Budgets:
    """Monthly AI spending limits in USD; null means no limit."""
    return get_budgets(session)


@router.put("/budgets", response_model=Budgets)
def change_budgets(session: SessionDep, user: AdminUser, body: Budgets) -> Budgets:
    """Replace the limits; send null for no limit. They apply from the next model call."""
    return update_budgets(session, user, body)
