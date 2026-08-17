"""
Counting the safe, and recording what the scale said.

A stock-take is a *document*, not an edit. Everywhere else in this system a
balance changes only because something happened and was written down; a count
is no different, and the sheet is what happened. Posting it moves stock through
`post_movement` and the books through `post_entry`, exactly as a purchase does.

The alternative — an editable stock figure with an "adjust" button — is the one
thing that would make every other guarantee in this system worthless. A balance
you can type over is a balance nobody can audit.
"""
import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.branch import Branch
from app.models.inventory import InventoryItem
from app.models.metal import Metal
from app.models.mixins import TimestampMixin


class StockCountStatus(str, enum.Enum):
    draft = "draft"
    # Counting is finished and a decision is wanted. Without this there is no
    # difference between a sheet half-filled and one ready to sign, and the
    # person who has to accept the loss would have to guess which is which.
    submitted = "submitted"
    posted = "posted"
    # A sheet abandoned rather than posted — miscounted, or the shop decided to
    # recount. Kept rather than deleted: "we counted and threw the sheet away"
    # is itself something an auditor wants to be able to see.
    cancelled = "cancelled"


class StockCount(Base, TimestampMixin):
    """
    One stock-take of one metal at one branch.

    Per metal because gold and silver are weighed on different days by
    different people, and a sheet covering both invites a variance on one to be
    signed off by somebody who only counted the other.
    """

    __tablename__ = "stock_counts"

    id: Mapped[int] = mapped_column(primary_key=True)
    count_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    branch: Mapped[Branch] = relationship(lazy="joined")

    metal: Mapped[Metal] = mapped_column(Enum(Metal, name="metal"), nullable=False)
    status: Mapped[StockCountStatus] = mapped_column(
        Enum(StockCountStatus, name="stock_count_status"),
        nullable=False,
        default=StockCountStatus.draft,
        index=True,
    )

    counted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    # Why the books were wrong. Required before posting — a write-off with no
    # explanation is the first thing an auditor asks about, so the system asks
    # first instead.
    reason: Mapped[str | None] = mapped_column(Text)

    journal_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="RESTRICT"), index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Deliberately separate from the creator. Counting the metal and accepting
    # the loss are different acts; a shop that wants two people on them can now
    # see whether it got two.
    posted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Who asserted the figures are what the scale said. Usually the person who
    # opened the sheet, not always — one opened in the morning and finished by
    # whoever is on at six is ordinary — and the two-person check is against
    # whoever asserted the numbers, not whoever clicked "new".
    submitted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["StockCountLine"]] = relationship(
        back_populates="count",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="StockCountLine.id",
    )


class StockCountLine(Base, TimestampMixin):
    """
    One melt pot on the sheet: what the books said, and what the scale said.

    `book_weight_g` is a snapshot taken when the sheet was opened, never read
    again at posting time. A count that took an hour while the counter was
    still selling would otherwise produce a variance made partly of real sales,
    and the shop would go hunting for metal that legitimately walked out of the
    door.
    """

    __tablename__ = "stock_count_lines"
    __table_args__ = (
        UniqueConstraint("count_id", "inventory_item_id", name="uq_stock_count_line_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    count_id: Mapped[int] = mapped_column(
        ForeignKey("stock_counts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    count: Mapped[StockCount] = relationship(back_populates="lines")

    inventory_item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    item: Mapped[InventoryItem] = relationship(lazy="joined")

    book_weight_g: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    # NULL means "not weighed yet", which is not the same as weighing nothing.
    # Treating an unweighed pot as zero would write the whole pot off.
    counted_weight_g: Mapped[float | None] = mapped_column(Numeric(14, 4))
    notes: Mapped[str | None] = mapped_column(Text)
