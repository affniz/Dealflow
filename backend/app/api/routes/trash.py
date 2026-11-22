from fastapi import APIRouter, status

from app.api.deps import CurrentUser, SessionDep, WriterUser
from app.models import Message, TrashItem
from app.services import trash as service
from app.services.trash import RecordType

router = APIRouter(prefix="/trash", tags=["trash"])


@router.get("", response_model=list[TrashItem])
def list_trash(session: SessionDep, user: CurrentUser) -> list[TrashItem]:
    """Deleted deals, contacts, companies and activities, restorable until `purge_after`.
    Agents see their own; everyone else sees the team's."""
    return service.trash(session, user)


@router.post("/{record_type}/{record_id}/restore", response_model=Message)
def restore(
    session: SessionDep, user: WriterUser, record_type: RecordType, record_id: int
) -> Message:
    """Put a deleted record back, with its history and links."""
    service.restore(session, user, record_type, record_id)
    return Message(message="Restored")


@router.delete("/{record_type}/{record_id}", status_code=status.HTTP_200_OK, response_model=Message)
def delete_for_good(
    session: SessionDep, user: WriterUser, record_type: RecordType, record_id: int
) -> Message:
    """Admins: delete a record in the trash for good, now. Its history goes with it, and
    other records lose the link."""
    service.purge_one(session, user, record_type, record_id)
    return Message(message="Deleted for good")
