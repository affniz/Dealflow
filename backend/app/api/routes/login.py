from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import (
    SESSION_COOKIE,
    CurrentSession,
    NotInDemo,
    SessionDep,
    oauth2,
    request_token,
)
from app.core.config import settings
from app.models import Message, Token
from app.services.auth import authenticate, end_session, end_sessions, start_session

router = APIRouter(tags=["login"])
COOKIE_PATH = settings.API_V1_STR


def client_ip(request: Request) -> str:
    # behind a proxy, uvicorn --proxy-headers has already put the visitor's address here
    return request.client.host if request.client else "unknown"


@router.post("/login/access-token", response_model=Token)
def login(
    request: Request,
    response: Response,
    session: SessionDep,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """Sign in. Sets the session cookie the web app uses, and returns the same token for
    scripts and the API docs to send as a bearer header.

    Too many failed tries from one address answer 429 with a Retry-After header."""
    user = authenticate(session, form.username, form.password, client_ip(request))
    token, expires = start_session(session, user, request.headers.get("user-agent"))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        expires=expires,
        path=COOKIE_PATH,
        httponly=True,  # page scripts can't read it, so an injected script can't steal it
        secure=settings.ENVIRONMENT == "production",
        samesite="strict",
    )
    return Token(access_token=token)


@router.post("/logout", response_model=Message)
def logout(
    request: Request,
    response: Response,
    session: SessionDep,
    bearer: Annotated[str | None, Depends(oauth2)],
) -> Message:
    """End this session. Works (and clears the cookie) even if it had already ended."""
    token, _ = request_token(request, bearer)
    if token:
        end_session(session, token)
    response.delete_cookie(SESSION_COOKIE, path=COOKIE_PATH)
    return Message(message="Signed out")


@router.post(
    "/logout/everywhere",
    response_model=Message,
    status_code=status.HTTP_200_OK,
    dependencies=[NotInDemo],  # demo visitors share accounts
)
def logout_everywhere(response: Response, session: SessionDep, auth: CurrentSession) -> Message:
    """End every session of the signed-in person, this one included."""
    end_sessions(session, auth.user_id)
    session.commit()
    response.delete_cookie(SESSION_COOKIE, path=COOKIE_PATH)
    return Message(message="Signed out everywhere")
