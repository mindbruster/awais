from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.branch import Branch
from app.models.mixins import TimestampMixin
from app.models.role import Role


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False)
    role: Mapped[Role] = relationship(back_populates="users", lazy="joined")

    # The shop this user works at, used as the default branch on everything
    # they record. Nullable on purpose: an owner or accountant belongs to the
    # business rather than to one counter, and forcing them onto a branch
    # would quietly file head-office work under whichever shop was listed
    # first.
    branch_id: Mapped[int | None] = mapped_column(
        ForeignKey("branches.id", ondelete="SET NULL"), index=True
    )
    branch: Mapped[Branch | None] = relationship(lazy="joined")
