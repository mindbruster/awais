from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255))
    # A role the shop created can be renamed and deleted. The ones the system
    # seeds by name cannot, or an upgrade lands on a database whose roles no
    # longer answer to the names the code looks for.
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    users: Mapped[list["User"]] = relationship(back_populates="role")  # noqa: F821
    # Eager, and deliberately so: every authenticated request checks at least
    # one permission, and a lazy load there would be a query per endpoint —
    # worse, an async lazy load, which SQLAlchemy refuses outright.
    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def permission_names(self) -> set[str]:
        return {p.permission for p in self.permissions}


class RolePermission(Base, TimestampMixin):
    """
    One permission granted to one role.

    A row per grant rather than a JSON column, so a permission can be searched
    for — "who can post a revaluation" is a question somebody asks after
    something has gone wrong, and it should be answerable with a query.
    """

    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission", name="uq_role_permission"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[Role] = relationship(back_populates="permissions")
    permission: Mapped[str] = mapped_column(String(60), nullable=False)
