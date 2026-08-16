import enum

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.inventory import InventoryItem
from app.models.mixins import TimestampMixin


class MovementType(str, enum.Enum):
    purchase_in = "purchase_in"           # raw material bought
    manufacturing_out = "manufacturing_out"  # gold issued to karigar
    manufacturing_in = "manufacturing_in"    # finished/intermediate received
    sale_out = "sale_out"                 # stock leaves on sale
    sale_return_in = "sale_return_in"
    approval_out = "approval_out"         # left for on-approval (tracked, but stock stays per business rule? we still record)
    approval_return_in = "approval_return_in"
    # Stock leaving one branch for another, and arriving. Kept apart from
    # `adjustment` because nothing was corrected — the same metal is still the
    # shop's, it has only moved — and a stock report that reads a transfer as
    # an adjustment shows every branch-to-branch move as an unexplained
    # write-off at one end and a windfall at the other.
    transfer_out = "transfer_out"
    transfer_in = "transfer_in"
    adjustment = "adjustment"             # manual correction


class StockMovement(Base, TimestampMixin):
    """
    Immutable ledger entry. Deltas are signed (positive = stock in, negative = stock out).
    The corresponding inventory_items snapshot is updated atomically by the service layer.
    """

    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[MovementType] = mapped_column(
        Enum(MovementType, name="stock_movement_type"),
        nullable=False,
        index=True,
    )
    inventory_item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    inventory_item: Mapped[InventoryItem] = relationship(lazy="joined")

    quantity_delta: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    weight_g_delta: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    weight_ct_delta: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)

    reference_type: Mapped[str | None] = mapped_column(String(50), index=True)  # 'manufacturing_job' | 'invoice' | etc.
    reference_id: Mapped[int | None] = mapped_column(Integer, index=True)

    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
    )
