from fastapi import APIRouter

from app.api.deps import AdminUser, CurrentUser, SessionDep
from app.models import AISettingsUpdate, AISettingsView
from app.services.ai_settings import EFFORTS, get_ai_settings, model_options, update_ai_settings

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
