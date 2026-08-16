import enum
from datetime import date, datetime

from sqlalchemy import (
    Date,
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
from app.models.account import Account
from app.models.mixins import TimestampMixin


class Commodity(str, enum.Enum):
    """
    What a journal line is denominated in.

    Gold is a commodity the shop banks in, not merely stock: workers, customers
    and the shop itself all carry running gold balances that settle
    independently of cash. Recording it as a ledger commodity is what makes
    "how much metal does Zahid owe me" a balance rather than a guess.
    """

    PKR = "PKR"
    USD = "USD"
    GOLD = "GOLD"


class PartyType(str, enum.Enum):
    customer = "customer"
    worker = "worker"
    supplier = "supplier"
    # Staff who carry stock out to jewellers and sell on the road. A fourth
    # party rather than a kind of worker: a karigar is given metal to transform
    # and owes it back as pieces, a salesman is given finished pieces and owes
    # them back as either goods or money. Both hold the firm's assets, but the
    # obligations settle in different units, so they cannot share a sub-ledger.
    salesman = "salesman"


class JournalEntry(Base, TimestampMixin):
    """
    One balanced accounting event.

    Entries are append-only. A mistake is corrected by posting a reversal that
    points back at the original, never by editing — an edited ledger cannot be
    trusted and cannot explain itself.
    """

    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    memo: Mapped[str | None] = mapped_column(Text)

    # What caused this entry — 'job_leg', 'design_stock', 'invoice', 'payment',
    # 'old_gold_purchase', 'stone_purchase', 'manual', 'opening_balance'. Lets
    # any business record show its accounting effect, and lets a reversal find
    # everything a cancelled document posted. Keep this list and the journal
    # screen's filter honest: a value that appears in one and not the other is a
    # filter that quietly returns nothing.
    source_type: Mapped[str | None] = mapped_column(String(50), index=True)
    source_id: Mapped[int | None] = mapped_column(Integer, index=True)

    reverses_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="RESTRICT"), index=True
    )

    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    lines: Mapped[list["JournalLine"]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="JournalLine.id",
    )


class JournalLine(Base, TimestampMixin):
    """
    A single posting.

    Amounts are **signed**: positive is a debit, negative is a credit. Separate
    debit/credit columns read more like a paper ledger but make every balance
    query a CASE expression and let a line carry both by mistake; the stock
    ledger in this codebase already uses signed deltas, so this matches.

    Multi-commodity balancing works the way plain-text accounting systems do
    it: `quantity` is in the line's own commodity (rupees, dollars, or *fine*
    grams of gold), and `value_pkr` is that quantity converted at `rate`. An
    entry must net to zero on `value_pkr`, not on quantity — otherwise taking
    old gold in part-payment for a rupee invoice could never balance.

    Gold quantity is always fine (24k-equivalent) grams. Storing "10g" without
    a purity makes 10g of 22k and 10g of 24k look identical, and they are not
    the same asset. The weight and purity as actually entered are kept
    alongside so statements can show what the counter saw.
    """

    __tablename__ = "journal_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry: Mapped[JournalEntry] = relationship(back_populates="lines")

    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    account: Mapped[Account] = relationship(lazy="joined")

    commodity: Mapped[Commodity] = mapped_column(
        Enum(Commodity, name="commodity"), nullable=False, default=Commodity.PKR, index=True
    )
    # Signed. Rupees/dollars for cash commodities, fine grams for GOLD.
    quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    # Conversion applied to reach value_pkr: 1 for PKR, the FX rate for USD,
    # PKR per fine gram for GOLD. Snapshotted so historic entries never move.
    rate: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=1)
    # Signed PKR valuation. SUM over an entry must be exactly zero.
    value_pkr: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    # Gold as the counter entered it, for display only — never used in maths.
    native_weight_g: Mapped[float | None] = mapped_column(Numeric(14, 4))
    native_purity: Mapped[int | None] = mapped_column(Integer)
    # And the tunch it was weighed at, when the document carried one. Display
    # only, like the two columns above it — `quantity` is already fine grams
    # and remains the only figure any balance is computed from.
    native_tunch_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))

    # Subsidiary identity behind a control account. A customer statement is
    # (account = Customers, party_type = customer, party_id = N).
    party_type: Mapped[PartyType | None] = mapped_column(
        Enum(PartyType, name="party_type"), index=True
    )
    party_id: Mapped[int | None] = mapped_column(Integer, index=True)

    memo: Mapped[str | None] = mapped_column(Text)
