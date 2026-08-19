from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    CurrentUser,
    DbSession,
    require_password_confirm,
    require_perm,
)
from app.core.permissions import SUPERADMIN, USER_MANAGE
from app.core.security import hash_password, verify_password
from app.models.role import Role
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.audit import changes, log_action, snapshot

router = APIRouter()

# All user management is admin-only — there is no fine-grained perm key for it
# because it controls who has *any* perms in the first place.
admin_only = Depends(require_perm(USER_MANAGE))


def _is_superadmin(user: User) -> bool:
    return getattr(getattr(user, "role", None), "name", None) == SUPERADMIN


def _guard_target(target: User, current: User) -> None:
    """
    Who may act on this account.

    **Only a super admin may touch a super admin.** Without this the tier is
    decorative: an admin holds `user:manage`, so it could reset the super
    admin's password and sign in as them — verified against a running server
    before this guard existed, and it returned 200 twice. Every restriction the
    tier exists to impose is one PATCH away from an admin who wants around it.

    **Nobody may demote or deactivate themselves.** An admin who removes their
    own role loses `user:manage` in the same request that removed it, and there
    is then no account left that can put it back — the shop is locked out of
    its own user list and the only way in is the database.
    """
    if _is_superadmin(target) and not _is_superadmin(current):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a super admin can change a super admin's account. That tier "
            "exists to sit above this one, and it would not if an admin could "
            "reset its password.",
        )


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
async def create_user(payload: UserCreate, db: DbSession, current: CurrentUser) -> User:
    role = await db.get(Role, payload.role_id)
    if role is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid role_id")
    if role.name == SUPERADMIN and not _is_superadmin(current):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a super admin can create another super admin.",
        )

    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        is_active=payload.is_active,
        role_id=payload.role_id,
    )
    db.add(user)
    try:
        await db.flush()
        await log_action(
            db,
            user=current,
            action="user.create",
            resource_type="user",
            resource_id=user.id,
            details={"email": user.email, "role": role.name},
            after=snapshot(user),
        )
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
async def update_user(
    user_id: int,
    payload: UserUpdate,
    db: DbSession,
    current: CurrentUser,
    x_confirm_password: Annotated[str | None, Header(alias="X-Confirm-Password")] = None,
) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    _guard_target(user, current)

    data = payload.model_dump(exclude_unset=True)
    before = snapshot(user)

    if user.id == current.id:
        # Self-lockout, in the two shapes it actually takes.
        if data.get("is_active") is False:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "You cannot deactivate your own account — ask another admin to do it.",
            )
        if "role_id" in data and data["role_id"] != user.role_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "You cannot change your own role. Moving yourself off an admin role "
                "removes the permission that let you do it, and no account would be "
                "left that could put it back.",
            )

    if "password" in data:
        # Setting somebody else's password is an account takeover in intent
        # even when it is a favour — a locked-out shopkeeper on the phone. The
        # person doing it re-enters their own password, so the audit line names
        # somebody who was present rather than whoever left a session open.
        if not x_confirm_password or not verify_password(
            x_confirm_password, current.hashed_password
        ):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Confirm your own password to set somebody else's.",
            )
        user.hashed_password = hash_password(data.pop("password"))

    if "role_id" in data:
        role = await db.get(Role, data["role_id"])
        if role is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid role_id")
        if role.name == SUPERADMIN and not _is_superadmin(current):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only a super admin can grant the super admin role.",
            )
    for k, v in data.items():
        setattr(user, k, v)

    await log_action(
        db,
        user=current,
        action="user.update",
        resource_type="user",
        resource_id=user.id,
        details={"email": user.email},
        before=before,
        after=snapshot(user),
    )
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
    _guard_target(user, current)
    await log_action(
        db,
        user=current,
        action="user.delete",
        resource_type="user",
        resource_id=user.id,
        details={"email": user.email, "role": getattr(user.role, "name", None)},
        before=snapshot(user),
    )
    await db.delete(user)
    await db.commit()
