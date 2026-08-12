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
from app.models.currency import Currency
from app.models.customer import Customer
from app.models.mixins import TimestampMixin
from app.models.stone import Stone


class Supplier(Base, TimestampMixin):
    """
    A party the shop buys stones from.

    Kept apart from workers: a supplier is owed money for goods, a worker is
    owed labour and may be holding the shop's metal. They post to different
    control accounts and their statements answer different questions.
    """

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(Text)
    opening_balance: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class GoldKind(str, enum.Enum):
    """
    What the shop is buying back. The distinction matters commercially: pure
    metal goes straight into stock at its stated purity, while used jewellery is
    bought below rate because it has to be melted and assayed before it is
    worth anything.
    """

    pure = "pure"
    used = "used"


class OldGoldPurchase(Base, TimestampMixin):
    """
    Buying metal back over the counter.

    A real channel, not an edge case — a customer trading in old jewellery is
    how a large share of a shop's gold arrives, and it is bought at a spread
    below the day's rate. Recorded separately from a sale's gold-exchange
    payment because this one is a standalone purchase with cash going out,
    not a settlement against a bill.
    """

    __tablename__ = "old_gold_purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), index=True
    )
    customer: Mapped[Customer | None] = relationship(lazy="joined")
    # Walk-ins often decline to be recorded at all, so a name is enough.
    walk_in_name: Mapped[str | None] = mapped_column(String(150))

    kind: Mapped[GoldKind] = mapped_column(
        Enum(GoldKind, name="gold_kind"), nullable=False, default=GoldKind.used, index=True
    )
    weight_g: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    purity: Mapped[int | None] = mapped_column(Integer)
    # What the shop paid per gram — deliberately its own column rather than the
    # day's rate, because the spread below rate is where the margin is.
    rate_per_g: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    inventory_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="SET NULL")
    )
    journal_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="RESTRICT"), index=True
    )

    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class StonePurchase(Base, TimestampMixin):
    """A bill from a stone supplier, with its lines."""

    __tablename__ = "stone_purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    supplier: Mapped[Supplier] = relationship(lazy="joined")

    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120))

    subtotal: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    # Freight, certification, the supplier's own loading — quoted as a
    # percentage on top rather than a figure, which is how these bills arrive.
    extra_cost_pct: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    journal_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="RESTRICT"), index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    items: Mapped[list["StonePurchaseItem"]] = relationship(
        back_populates="purchase",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="StonePurchaseItem.id",
    )


class StonePurchaseItem(Base, TimestampMixin):
    """
    One graded lot on a stone bill.

    The grading columns are snapshots, not links: a lot is bought as "12 PTR
    commercial, VS1, round" and that description has to stay true on the bill
    even if the shop later renames a grade in its option lists.
    """

    __tablename__ = "stone_purchase_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(
        ForeignKey("stone_purchases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purchase: Mapped[StonePurchase] = relationship(back_populates="items")

    stone_id: Mapped[int] = mapped_column(
        ForeignKey("stones.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    stone: Mapped[Stone] = relationship(lazy="joined")

    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weight_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    rate_per_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    # A rate without its currency is a number, not a price. Both are snapshotted
    # here rather than read back off the stone master, which can be edited — and
    # editing it would otherwise retroactively change what this row meant.
    currency: Mapped[Currency] = mapped_column(
        Enum(Currency, name="currency"), nullable=False, default=Currency.PKR
    )
    # Rupees per unit of `currency` when this row was written. 1 for PKR.
    fx_rate_to_pkr: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    quality: Mapped[str | None] = mapped_column(String(60))
    cut: Mapped[str | None] = mapped_column(String(40))
    color: Mapped[str | None] = mapped_column(String(40))
    clarity: Mapped[str | None] = mapped_column(String(40))

    inventory_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
