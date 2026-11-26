from datetime import timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.core.security import generate_api_token, hash_api_token
from app.models import (
    ApiToken,
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenPublic,
    Message,
    utcnow,
)

router = APIRouter(prefix="/users/me/tokens", tags=["tokens"])

MAX_TOKENS = 20


@router.get("", response_model=list[ApiTokenPublic])
def list_tokens(session: SessionDep, user: CurrentUser) -> list[ApiToken]:
    """Your personal access tokens (never the tokens themselves), expired ones included until
    you revoke them."""
    stmt = select(ApiToken).where(ApiToken.user_id == user.id)
    return list(session.exec(stmt.order_by(col(ApiToken.created_at).desc())).all())


@router.post("", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
def create_token(session: SessionDep, user: CurrentUser, body: ApiTokenCreate) -> ApiTokenCreated:
    """A new token that acts as you, with your role and access, narrowed by its scope, until it
    expires. It's shown only in this response."""
    now = utcnow()
    count = session.exec(  # expired tokens don't count
        select(func.count())
        .select_from(ApiToken)
        .where(ApiToken.user_id == user.id, col(ApiToken.expires_at) > now)
    ).one()
    if count >= MAX_TOKENS:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"You can have up to {MAX_TOKENS} tokens; revoke one first"
        )
    token = generate_api_token()
    row = ApiToken(
        user_id=user.id,  # type: ignore[arg-type]
        name=body.name.strip(),
        token_hash=hash_api_token(token),
        prefix=token[:10],
        scope=body.scope,
        created_at=now,
        expires_at=now + timedelta(days=body.expires_in_days),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return ApiTokenCreated.model_validate({**row.model_dump(), "token": token})


@router.delete("/{token_id}", response_model=Message)
def revoke_token(session: SessionDep, user: CurrentUser, token_id: int) -> Message:
    """Revoke a token straight away; anything using it stops working."""
    row = session.get(ApiToken, token_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found")
    session.delete(row)
    session.commit()
    return Message(message="Token revoked")
