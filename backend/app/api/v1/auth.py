from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.services.audit import log_action
from app.schemas.auth import ChangePasswordRequest, LoginRequest, TokenResponse
from app.schemas.user import UserRead

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, payload: LoginRequest, db: DbSession) -> TokenResponse:
    """
    Throttled to 10 attempts/minute per source IP. The `request` arg is required
    by slowapi to read the IP — it isn't used in the body. Behind a reverse proxy,
    make sure uvicorn is started with `--proxy-headers` so the real IP shows up.
    """
    result = await db.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    token = create_access_token(subject=user.id, extra_claims={"role": user.role.name})
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserRead)
async def me(current: CurrentUser) -> User:
    return current


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    db: DbSession,
    current: CurrentUser,
) -> None:
    """
    Change your own password.

    Every account needs this and only an admin had it: the password lived on
    `PATCH /users/{id}`, behind `user:manage`, which a salesman will never hold.
    So a shopkeeper who suspected somebody had watched them type had to ask the
    owner to change it for them, which means saying the new one out loud.

    It also unfreezes the seeded accounts. The seeder skips a user that already
    exists, so changing `SEED_ADMIN_PASSWORD` and redeploying does nothing —
    before this, the password chosen on the day the shop was set up could never
    be changed by anyone without a database console.

    Throttled like the login it guards, and rejecting a wrong current password
    with the same 401 the login gives.
    """
    if not verify_password(payload.current_password, current.hashed_password):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Your current password is not right."
        )
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The new password is the same as the old one."
        )
    user = await db.get(User, current.id)
    user.hashed_password = hash_password(payload.new_password)
    await log_action(
        db,
        user=current,
        action="user.change_password",
        resource_type="user",
        resource_id=user.id,
        details={"email": user.email},
    )
    await db.commit()
