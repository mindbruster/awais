import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.location import City
from app.models.mixins import TimestampMixin


class Branch(Base, TimestampMixin):
    """
    A place the business trades from.

    Stock, sales and staff all belong somewhere once there is more than one
    shop, and "somewhere" has to be a record rather than a string typed into
    `inventory_items.location` — a branch is a party you transfer goods to and
    report on separately, and neither works against free text.

    Exactly one branch carries `is_default`. It is what existing rows were
    backfilled onto when branches were introduced, and what a user without a
    branch of their own falls back to, so that no code path has to invent an
    answer to "which shop did this happen at".
    """

    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Short and human — it prefixes transfer numbers and prints on labels,
    # where "MAIN" fits and "Main Showroom, Anarkali" does not.
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)

    phone: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(Text)
    city_id: Mapped[int | None] = mapped_column(
        ForeignKey("cities.id", ondelete="SET NULL"), index=True
    )
    city: Mapped[City | None] = relationship(lazy="joined")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    # --- what the customer's copy says at the top ---
    # `name` is what staff pick from a dropdown ("Main Shop"); this is what the
    # shop is called on paper ("MARKAZ-E-HEERA"). They are rarely the same word,
    # and a bill headed with the internal name looks like a system printed it.
    # NULL falls back to `name`, so a shop that never fills this in still gets a
    # letterhead rather than a blank.
    letterhead_name: Mapped[str | None] = mapped_column(String(120))
    # The line under the name — "DIAMOND JEWELLERY & WATCHES".
    tagline: Mapped[str | None] = mapped_column(String(160))
    logo_url: Mapped[str | None] = mapped_column(String(500))

    notes: Mapped[str | None] = mapped_column(Text)

    @property
    def print_name(self) -> str:
        """The name to head a document with."""
        return self.letterhead_name or self.name

    @property
    def city_name(self) -> str | None:
        return self.city.name if self.city else None


class TransferStatus(str, enum.Enum):
    """
    Where the goods are.

    `sent` is not a formality. Metal that has left one shop and not yet
    arrived at the other is real stock in a real van, and it belongs to
    neither branch's shelf count — which is precisely the moment a shop
    loses track of it, so it gets a state of its own rather than being
    collapsed into an instantaneous move.
    """

    draft = "draft"
    sent = "sent"
    received = "received"
    cancelled = "cancelled"


class BranchTransfer(Base, TimestampMixin):
    """
    Goods moving from one branch to another.

    Modelled as a send and a receive rather than a single hop, for the same
    reason a job leg is: the shop needs to be able to say what is in transit
    and who signed for it. Nothing here touches the ledger — moving your own
    stock between your own shops changes no balance, only where the metal
    sits. Posting a journal entry for it would inflate turnover with movements
    that never earned a rupee.
    """

    __tablename__ = "branch_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)

    from_branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    from_branch: Mapped[Branch] = relationship(foreign_keys=[from_branch_id], lazy="joined")
    to_branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    to_branch: Mapped[Branch] = relationship(foreign_keys=[to_branch_id], lazy="joined")

    status: Mapped[TransferStatus] = mapped_column(
        Enum(TransferStatus, name="transfer_status"),
        nullable=False,
        default=TransferStatus.draft,
        index=True,
    )

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sent_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    received_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    notes: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["BranchTransferItem"]] = relationship(
        back_populates="transfer",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BranchTransferItem.id",
    )


class BranchTransferItem(Base, TimestampMixin):
    """
    One line on a transfer: either a finished piece or a weight of raw stock.

    Both go on the same document because a van carries both, and the shop
    signs for the lot in one go. Exactly one of `product_id` and
    `inventory_item_id` is set; the API refuses a line that names neither or
    both, because a line that cannot say what moved cannot be received.
    """

    __tablename__ = "branch_transfer_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_id: Mapped[int] = mapped_column(
        ForeignKey("branch_transfers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transfer: Mapped[BranchTransfer] = relationship(back_populates="items")

    # A finished piece. It moves whole, so there is no weight to state — the
    # product carries its own.
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )

    # Raw stock. The source row is at the sending branch; receiving creates or
    # tops up the mirror row at the destination.
    inventory_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    weight_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    weight_ct: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    purity: Mapped[int | None] = mapped_column(Integer)
    # Fineness in percent, preferred over the karat integer above. Metal moving
    # between branches has to arrive as the same asset it left as, so the
    # transfer note carries the sending branch's own reading. See
    # `Product.gold_tunch_pct`.
    tunch_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))

    # Where the received goods landed, so a receive is idempotent and auditable.
    received_inventory_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="SET NULL")
    )

    notes: Mapped[str | None] = mapped_column(Text)
