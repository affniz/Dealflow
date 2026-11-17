from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import col, select

from app.api.access import paginate, save
from app.api.deps import AdminUser, CurrentUser, SessionDep
from app.core.security import hash_password, verify_password
from app.models import (
    Message,
    Page,
    PasswordChange,
    Role,
    User,
    UserCreate,
    UserPublic,
    UserUpdate,
    UserUpdateMe,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserPublic)
def read_me(user: CurrentUser) -> User:
    return user


@router.patch("/me", response_model=UserPublic)
def update_me(session: SessionDep, user: CurrentUser, body: UserUpdateMe) -> User:
    user.sqlmodel_update(body.model_dump(exclude_unset=True))
    return save(session, user)


@router.post("/me/password", response_model=Message)
def change_password(session: SessionDep, user: CurrentUser, body: PasswordChange) -> Message:
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    user.hashed_password = hash_password(body.new_password)
    save(session, user)
    return Message(message="Password updated")


@router.get("", response_model=Page[UserPublic])
def list_users(
    session: SessionDep,
    _: AdminUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> Page[UserPublic]:
    return paginate(session, select(User).order_by(col(User.id)), UserPublic, skip, limit)


def _check_role_change(actor: User, target_role: Role, target: User | None = None) -> None:
    if actor.role != Role.owner and (
        target_role == Role.owner or (target is not None and target.role == Role.owner)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an owner can manage owners")


@router.post("", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def create_user(session: SessionDep, actor: AdminUser, body: UserCreate) -> User:
    _check_role_change(actor, body.role)
    email = body.email.lower()
    if session.exec(select(User).where(User.email == email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists")
    user = User.model_validate(
        body, update={"email": email, "hashed_password": hash_password(body.password)}
    )
    return save(session, user)


@router.patch("/{user_id}", response_model=UserPublic)
def update_user(session: SessionDep, actor: AdminUser, user_id: int, body: UserUpdate) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    data = body.model_dump(exclude_unset=True)
    _check_role_change(actor, data.get("role", user.role), user)
    if user.id == actor.id and (
        data.get("role", user.role) != user.role or data.get("is_active") is False
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't change your own role or status")
    if "email" in data:
        data["email"] = data["email"].lower()
        clash = session.exec(select(User).where(User.email == data["email"])).first()
        if clash and clash.id != user.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists")
    if "password" in data:
        data["hashed_password"] = hash_password(data.pop("password"))
    user.sqlmodel_update(data)
    return save(session, user)
