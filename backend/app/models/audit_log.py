from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class AuditLog(Base, TimestampMixin):
    """
    Append-only record of sensitive actions: who did what, on what, when.
    Created lazily by `app.services.audit.log` from the relevant endpoints —
    the stock_movements table covers stock-level audit; this one covers
    everything else (issue, void, complete, cancel, deletes, etc.).
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor_email: Mapped[str | None] = mapped_column(String(255), index=True)

    # e.g. "invoice.issue", "manufacturing.complete", "product.delete"
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    # e.g. "invoice", "product", "stone"
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    resource_id: Mapped[int | None] = mapped_column(Integer, index=True)

    # Free-form context. JSON so we don't have to migrate every time we add a key.
    details: Mapped[dict | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(40))
