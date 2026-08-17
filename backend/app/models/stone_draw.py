from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.purchase import StonePurchaseItem


class StoneDraw(Base, TimestampMixin):
    """
    Carats taken out of one purchased parcel for one job.

    Stone stock is reported as a single running figure per grade — "120ct of 12
    PTR commercial" — because that is the question the counter asks. But the
    120 is rarely one purchase: fifty carats bought in January at Rs 8,000 and
    seventy in March at Rs 9,200 are the same stone at two different costs, and
    a piece made from them cost what its parcel cost, not what the mean of the
    two happens to be.

    Averaging is the alternative and it hides the thing worth seeing. A parcel
    bought dear disappears into the mean, every piece looks equally profitable,
    and the buying mistake never surfaces on any report. Drawing oldest-first
    keeps each piece's cost tied to metal and stones the shop actually paid
    for, in the order it paid for them.

    A draw with no `purchase_item_id` is stone the system never saw arrive —
    opening stock, or a parcel bought before this shop was on the system. It is
    costed at the stone master's rate and recorded rather than refused, because
    refusing would mean a shop cannot issue its own stones until every historic
    purchase has been keyed in.
    """

    __tablename__ = "stone_draws"

    id: Mapped[int] = mapped_column(primary_key=True)
    leg_stone_id: Mapped[int] = mapped_column(
        ForeignKey("leg_stones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # RESTRICT: a purchase line that has been drawn from is part of a piece's
    # cost. Deleting it would leave that cost unexplainable.
    purchase_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("stone_purchase_items.id", ondelete="RESTRICT"), index=True
    )
    purchase_item: Mapped[StonePurchaseItem | None] = relationship(lazy="joined")

    weight_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    # Landed rupees per carat: the parcel's rate, converted at the exchange rate
    # of the day it was bought and loaded with that bill's freight and
    # certification percentage. Snapshotted, because all three of those can be
    # edited afterwards and a piece's cost must not move when they are.
    rate_per_ct_pkr: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
