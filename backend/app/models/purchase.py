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
    # Fineness in percent, preferred over the karat integer above. Scrap is
    # bought on a touchstone or acid reading, which lands on a decimal and not
    # on a karat band. See `Product.gold_tunch_pct`.
    tunch_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))
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


class GoldPaymentMode(str, enum.Enum):
    """
    How the bullion was paid for.

    The distinction is the whole reason this is not just another old-gold row.
    A counter buy-back is cash across the table; a dealer's bill for half a kilo
    is settled by transfer, or not at all that day — and metal taken on account
    is a debt the shop owes, which has to be on the books as one.
    """

    cash = "cash"
    bank = "bank"
    credit = "credit"


class GoldPurchase(Base, TimestampMixin):
    """
    Raw gold bought in from a dealer — the metal the workshop makes from.

    Distinct from `OldGoldPurchase`, which is a customer walking in with their
    own jewellery. That is a buy-back, priced below the day's rate because the
    spread is the margin, paid in cash, one lot at a time. This is a trade
    purchase: a supplier, a bill with several bars on it, possibly on credit,
    and no spread to speak of. Filing one as the other makes the buy-back
    margin report meaningless and hides a payable the shop genuinely owes.

    Money is held in rupees like every other money column in the system.
    `currency` and `fx_rate_to_pkr` on the line are the snapshot of what the
    dealer quoted, kept so the bill still reads the way it was agreed.
    """

    __tablename__ = "gold_purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    supplier: Mapped[Supplier] = relationship(lazy="joined")

    # Which safe the metal landed in. Metal bought at one shop must not top up
    # another's melt pot, or both branches' stock reports are wrong at once.
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120))

    payment_mode: Mapped[GoldPaymentMode] = mapped_column(
        Enum(GoldPaymentMode, name="gold_payment_mode"),
        nullable=False,
        default=GoldPaymentMode.cash,
        index=True,
    )
    # Which account the transfer left from. Reference only — the ledger posts to
    # the one Bank control account, as every other payment in the system does.
    bank_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="SET NULL"), index=True
    )

    subtotal: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    # Carriage, assay, the dealer's own loading — quoted as a percentage on top,
    # which is how these bills arrive. Capitalised into the metal rather than
    # expensed: it is part of what the gold cost.
    extra_cost_pct: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    journal_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="RESTRICT"), index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    items: Mapped[list["GoldPurchaseItem"]] = relationship(
        back_populates="purchase",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="GoldPurchaseItem.id",
    )


class GoldPurchaseItem(Base, TimestampMixin):
    """
    One lot of metal on a dealer's bill: a bar, or a parcel of one purity.

    `rate_per_g` is quoted against the *actual* weight, not the fine weight —
    which is how the trade quotes it, and matches how a buy-back is recorded.
    The conversion to fine grams happens once, at posting time, from `purity`.
    """

    __tablename__ = "gold_purchase_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(
        ForeignKey("gold_purchases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purchase: Mapped[GoldPurchase] = relationship(back_populates="items")

    # What the dealer called it — "TT bar 10 tola", "biscuit 100g". Free text:
    # bullion has no master list in this shop, and inventing one would mean a
    # counter hand cannot record a bar until somebody sets it up.
    description: Mapped[str | None] = mapped_column(String(150))
    purity: Mapped[int] = mapped_column(Integer, nullable=False)
    # Fineness in percent, preferred over the karat integer above. A bullion
    # dealer sells on an assayed tunch — 99.5, 99.9 — and karat cannot say
    # either. See `Product.gold_tunch_pct`.
    tunch_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))
    weight_g: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    rate_per_g: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)

    # What the dealer quoted in, and what it was worth in rupees at the time.
    # A rate without its currency is a number, not a price.
    currency: Mapped[Currency] = mapped_column(
        Enum(Currency, name="currency"), nullable=False, default=Currency.PKR
    )
    fx_rate_to_pkr: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    # Rupees, always — so the line, the bill total, the stock value and the
    # journal entry are one number rather than four that resemble each other.
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    # The melt pot this landed in, so a reversal knows what to take back out.
    inventory_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
