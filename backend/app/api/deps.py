from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import role_has
from app.core.security import decode_token, verify_password
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_v1_prefix}/auth/login")

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError, TypeError) as exc:
        raise credentials_exc from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exc
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_perm(perm: str):
    """Dependency-factory: require the current user to hold `<resource>:<action>`."""

    async def _checker(user: CurrentUser) -> User:
        if not role_has(user.role.name, perm):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {perm}",
            )
        return user

    return _checker


def require_roles(*role_names: str):
    """Legacy convenience for routes that still want a hard role list."""

    async def _checker(user: CurrentUser) -> User:
        if user.role.name not in role_names:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(role_names)}",
            )
        return user

    return _checker


async def require_password_confirm(
    user: CurrentUser,
    x_confirm_password: Annotated[str | None, Header(alias="X-Confirm-Password")] = None,
) -> User:
    """
    Require the caller to re-enter their password via the `X-Confirm-Password`
    header. Use this on destructive / irreversible actions (void invoice,
    cancel a job mid-flow, delete a user, etc.).
    """
    if not x_confirm_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password confirmation required (X-Confirm-Password header)",
        )
    if not verify_password(x_confirm_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password confirmation failed",
        )
    return user
