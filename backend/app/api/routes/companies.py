from typing import Literal

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func
from sqlmodel import col, or_, select

from app.api.access import apply_update, get_visible, paginate, resolve_owner, save, scoped
from app.api.deps import CurrentUser, SessionDep, WriterUser
from app.models import (
    Company,
    CompanyCreate,
    CompanyPublic,
    CompanyUpdate,
    HistoryItem,
    Page,
)
from app.services.names import company_public, with_company_details
from app.services.trash import changes, history, log_record, snapshot, soft_delete

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=Page[CompanyPublic])
def list_companies(
    session: SessionDep,
    user: CurrentUser,
    q: str | None = Query(None, description="Search name, domain or industry"),
    owner_id: int | None = None,
    sort: Literal["name", "recent"] = Query("name", description="Name, or recently updated"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> Page[CompanyPublic]:
    stmt = scoped(select(Company), Company, user)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                col(Company.name).ilike(like),
                col(Company.domain).ilike(like),
                col(Company.industry).ilike(like),
            )
        )
    if owner_id is not None:
        stmt = stmt.where(Company.owner_id == owner_id)
    if sort == "recent":
        stmt = stmt.order_by(col(Company.updated_at).desc(), col(Company.id).desc())
    else:
        stmt = stmt.order_by(func.lower(Company.name), col(Company.id))
    page = paginate(session, stmt, CompanyPublic, skip, limit)
    with_company_details(session, user, page.data)
    return page


@router.post("", response_model=CompanyPublic, status_code=status.HTTP_201_CREATED)
def create_company(session: SessionDep, user: WriterUser, body: CompanyCreate) -> CompanyPublic:
    owner_id = resolve_owner(session, user, body.owner_id)
    company = Company.model_validate(body, update={"owner_id": owner_id})
    session.add(company)
    session.flush()
    log_record(session, "company", company.id, user, "created")  # type: ignore[arg-type]
    return company_public(session, user, save(session, company))


@router.get("/{company_id}", response_model=CompanyPublic)
def read_company(session: SessionDep, user: CurrentUser, company_id: int) -> CompanyPublic:
    return company_public(session, user, get_visible(session, Company, company_id, user))


@router.patch("/{company_id}", response_model=CompanyPublic)
def update_company(
    session: SessionDep, user: WriterUser, company_id: int, body: CompanyUpdate
) -> CompanyPublic:
    company = get_visible(session, Company, company_id, user)
    before = snapshot(company)
    apply_update(session, company, user, body.model_dump(exclude_unset=True))
    if diff := changes(before, snapshot(company)):
        log_record(session, "company", company_id, user, "updated", changes=diff)
    return company_public(session, user, save(session, company))


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company(session: SessionDep, user: WriterUser, company_id: int) -> Response:
    """Moves the company to the trash; its people, deals and activities keep the link, which
    comes back if it's restored."""
    soft_delete(session, user, "company", get_visible(session, Company, company_id, user))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{company_id}/history", response_model=list[HistoryItem])
def company_history(session: SessionDep, user: CurrentUser, company_id: int) -> list[HistoryItem]:
    """Who created, changed, deleted or restored this company, and what changed; newest first."""
    get_visible(session, Company, company_id, user)
    return history(session, "company", company_id)
