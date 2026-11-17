from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from app.core.config import settings
from app.core.db import get_session
from app.core.security import ALGORITHM
from app.models import Role, User

oauth2 = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/login/access-token")

SessionDep = Annotated[Session, Depends(get_session)]
TokenDep = Annotated[str, Depends(oauth2)]


def get_current_user(session: SessionDep, token: TokenDep) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise unauthorized from None
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


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
