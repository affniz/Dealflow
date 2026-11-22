from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from app.core.config import settings
from app.core.db import get_session
from app.models import AuthSession, Role, User
from app.services.auth import resolve

# scripts and the API docs send the token as a bearer header; the browser app uses a cookie
oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token", auto_error=False
)
SESSION_COOKIE = "dealflow_session"
# A request signed in by the cookie must carry this header to change anything. Browsers only
# send the (SameSite=Strict) cookie from this site anyway; the header is a second lock, since
# another site can't add it without a CORS preflight that this API turns down.
CSRF_HEADER = "X-Dealflow-CSRF"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

SessionDep = Annotated[Session, Depends(get_session)]


def request_token(request: Request, bearer: str | None) -> tuple[str | None, bool]:
    """The sign-in token on this request, and whether it came from the cookie."""
    if bearer:
        return bearer, False
    cookie = request.cookies.get(SESSION_COOKIE)
    return cookie, cookie is not None


def get_current_session(
    request: Request,
    session: SessionDep,
    bearer: Annotated[str | None, Depends(oauth2)],
) -> AuthSession:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token, from_cookie = request_token(request, bearer)
    if token is None:
        raise unauthorized
    signed_in = resolve(session, token)
    if signed_in is None:
        raise unauthorized
    if from_cookie and request.method not in SAFE_METHODS and not request.headers.get(CSRF_HEADER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing the {CSRF_HEADER} header")
    request.state.user = signed_in.user
    return signed_in.auth_session


CurrentSession = Annotated[AuthSession, Depends(get_current_session)]


def get_current_user(request: Request, _: CurrentSession) -> User:
    return request.state.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role) -> Callable[[User], User]:
    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")
        return user

    return checker


# can create/edit records (viewers are read-only)
WriterUser = Annotated[User, Depends(require_roles(Role.owner, Role.admin, Role.agent))]
# can manage users, pipelines, lost reasons
AdminUser = Annotated[User, Depends(require_roles(Role.owner, Role.admin))]


def refuse_in_demo() -> None:
    if settings.DEMO_MODE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That's turned off in the public demo")


# for changes that would lock other demo visitors out or raise AI spending
NotInDemo = Depends(refuse_in_demo)
