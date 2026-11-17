from fastapi import APIRouter, Query, Response, status
from sqlmodel import col, or_, select

from app.api.access import apply_update, get_visible, paginate, resolve_owner, save, scoped
from app.api.deps import CurrentUser, SessionDep, WriterUser
from app.models import (
    Activity,
    Company,
    CompanyCreate,
    CompanyPublic,
    CompanyUpdate,
    Contact,
    Deal,
    Page,
)

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=Page[CompanyPublic])
def list_companies(
    session: SessionDep,
    user: CurrentUser,
    q: str | None = Query(None, description="Search name or domain"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> Page[CompanyPublic]:
    stmt = scoped(select(Company), Company, user)
    if q:
        stmt = stmt.where(
            or_(col(Company.name).ilike(f"%{q}%"), col(Company.domain).ilike(f"%{q}%"))
        )
    return paginate(session, stmt.order_by(col(Company.name)), CompanyPublic, skip, limit)


@router.post("", response_model=CompanyPublic, status_code=status.HTTP_201_CREATED)
def create_company(session: SessionDep, user: WriterUser, body: CompanyCreate) -> Company:
    owner_id = resolve_owner(session, user, body.owner_id)
    return save(session, Company.model_validate(body, update={"owner_id": owner_id}))


@router.get("/{company_id}", response_model=CompanyPublic)
def read_company(session: SessionDep, user: CurrentUser, company_id: int) -> Company:
    return get_visible(session, Company, company_id, user)


@router.patch("/{company_id}", response_model=CompanyPublic)
def update_company(
    session: SessionDep, user: WriterUser, company_id: int, body: CompanyUpdate
) -> Company:
    company = get_visible(session, Company, company_id, user)
    apply_update(session, company, user, body.model_dump(exclude_unset=True))
    return save(session, company)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company(session: SessionDep, user: WriterUser, company_id: int) -> Response:
    company = get_visible(session, Company, company_id, user)
    # keep the linked people, deals and activities; just unlink them
    for model in (Contact, Deal, Activity):
        for row in session.exec(select(model).where(model.company_id == company_id)):
            row.company_id = None
            session.add(row)
    session.delete(company)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
