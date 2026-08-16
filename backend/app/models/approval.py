import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.branch import Branch
from app.models.customer import Customer
from app.models.mixins import TimestampMixin


class ApprovalStatus(str, enum.Enum):
    """
    Where the memo stands.

    `partly_returned` is its own state rather than a derived one because it is
    what the shop chases: a memo with four pieces out and one back is not open
    in the same way as one nothing has come back from, and collapsing the two
    hides which customers are sitting on stock.
    """

    out = "out"
    partly_returned = "partly_returned"
    closed = "closed"
    cancelled = "cancelled"


class ApprovalLineStatus(str, enum.Enum):
    out = "out"
    returned = "returned"
    sold = "sold"


class Approval(Base, TimestampMixin):
    """
    Goods let out on approval — a memo.

    The piece has left the shop and has not been sold. That is the whole
    difficulty: it is neither on the shelf nor in anyone's sales figures, and a
    shop without a record of it discovers the gap at stock-take, months later,
    with no idea who has it.

    Nothing here posts to the ledger. No sale has happened and no money has
    changed hands — the goods are still the shop's asset, merely somewhere
    else. Posting revenue when a memo goes out would book a sale that may never
    occur, and reversing it later is how turnover figures become fiction. When
    a piece is actually bought, the ordinary invoice does the ordinary thing.
    """

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    approval_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    customer: Mapped[Customer] = relationship(lazy="joined")

    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    branch: Mapped[Branch] = relationship(lazy="joined")

    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="approval_status"),
        nullable=False,
        default=ApprovalStatus.out,
        index=True,
    )

    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When the pieces are expected back. The single most useful column here:
    # a memo with no return date is one nobody ever chases.
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    issued_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    notes: Mapped[str | None] = mapped_column(Text)
    cancelled_reason: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["ApprovalItem"]] = relationship(
        back_populates="approval",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ApprovalItem.id",
    )


class ApprovalItem(Base, TimestampMixin):
    """
    One piece on a memo.

    Tracked per line, not per document, because a customer keeps two of the
    five and returns three — and the shop needs to know which two, by serial,
    to bill for.
    """

    __tablename__ = "approval_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    approval_id: Mapped[int] = mapped_column(
        ForeignKey("approvals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    approval: Mapped[Approval] = relationship(back_populates="items")

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    status: Mapped[ApprovalLineStatus] = mapped_column(
        Enum(ApprovalLineStatus, name="approval_line_status"),
        nullable=False,
        default=ApprovalLineStatus.out,
        index=True,
    )

    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when the customer keeps the piece and it is billed. The link that
    # turns a memo line into a sale without either document guessing.
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), index=True
    )

    notes: Mapped[str | None] = mapped_column(Text)
