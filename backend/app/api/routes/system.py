from typing import Annotated

from fastapi import APIRouter, Depends

from app.agent import copilot
from app.api.deps import AdminUser, SessionDep
from app.models import SystemStatus
from app.services.jobs import system_status

router = APIRouter(prefix="/system", tags=["system"])

ClientDep = Annotated[copilot.MessagesClient | None, Depends(copilot.get_client)]


@router.get("/status", response_model=SystemStatus)
def read_status(session: SessionDep, _: AdminUser, client: ClientDep) -> SystemStatus:
    """Admins: when each background job last ran and whether it worked, and anything that
    needs attention (`problems`, which the app shows as a banner)."""
    return system_status(session, ai_configured=client is not None)
