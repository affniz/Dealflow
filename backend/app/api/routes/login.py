from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select

from app.api.deps import SessionDep
from app.core.security import create_access_token, verify_password
from app.models import Token, User

router = APIRouter(tags=["login"])


@router.post("/login/access-token", response_model=Token)
def login(session: SessionDep, form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Token:
    user = session.exec(select(User).where(User.email == form.username.lower())).first()
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Inactive user")
    return Token(access_token=create_access_token(user.id))  # type: ignore[arg-type]
