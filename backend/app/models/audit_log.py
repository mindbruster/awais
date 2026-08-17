from sqlalchemy import ForeignKey, Integer, String, Text
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
    # Kept alongside before/after because plenty of actions are not field
    # changes at all — how many lots were on a bill, which entry a reversal
    # produced — and forcing those into a diff shape would lose them.
    details: Mapped[dict | None] = mapped_column(JSONB)

    # What the changed fields held before and after, and *only* the changed
    # ones. A full snapshot of both sides buries the one number that moved in
    # forty that did not, and on a wide table makes the log larger than the
    # data it describes.
    #
    # NULL rather than `{}` when an action was not recorded this way: an empty
    # object would claim nothing changed, which is a different statement from
    # "this was never captured".
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)

    # Why. Its own column rather than a key in `details` because it is the
    # field somebody actually searches, and JSON cannot be filtered on cheaply.
    reason: Mapped[str | None] = mapped_column(Text)

    request_id: Mapped[str | None] = mapped_column(String(40))
