from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    CurrentUser,
    DbSession,
    require_password_confirm,
    require_perm,
)
from app.core.permissions import USER_MANAGE
from app.core.security import hash_password
from app.models.role import Role
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter()

# All user management is admin-only — there is no fine-grained perm key for it
# because it controls who has *any* perms in the first place.
admin_only = Depends(require_perm(USER_MANAGE))


@router.get("", response_model=list[UserRead], dependencies=[admin_only])
async def list_users(db: DbSession) -> list[User]:
    result = await db.execute(select(User).order_by(User.id))
    return list(result.scalars().all())


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[admin_only],
)
async def create_user(payload: UserCreate, db: DbSession) -> User:
    role = await db.get(Role, payload.role_id)
    if role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid role_id")

    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        is_active=payload.is_active,
        role_id=payload.role_id,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already in use") from exc
    await db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserRead, dependencies=[admin_only])
async def get_user(user_id: int, db: DbSession) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.patch("/{user_id}", response_model=UserRead, dependencies=[admin_only])
async def update_user(user_id: int, payload: UserUpdate, db: DbSession) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    data = payload.model_dump(exclude_unset=True)
    if "password" in data:
        user.hashed_password = hash_password(data.pop("password"))
    if "role_id" in data:
        role = await db.get(Role, data["role_id"])
        if role is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid role_id")
    for k, v in data.items():
        setattr(user, k, v)

    await db.commit()
    await db.refresh(user)
    return user


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[admin_only, Depends(require_password_confirm)],
)
async def delete_user(user_id: int, current: CurrentUser, db: DbSession) -> None:
    if user_id == current.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot delete your own account")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    await db.delete(user)
    await db.commit()
