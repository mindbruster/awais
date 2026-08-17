import enum
from datetime import date

from sqlalchemy import Boolean, Date, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.bank import BankAccount
from app.models.branch import Branch
from app.models.currency import Currency
from app.models.mixins import TimestampMixin


class CashDirection(str, enum.Enum):
    """Which way the money went."""

    # Out: rent, wages, tea, freight, a bank charge.
    paid = "paid"
    # In, and not against an invoice: capital put in, a refund from a supplier,
    # scrap sold off the bench. Customer settlements are payments and belong to
    # that module, which knows what they are settling.
    received = "received"


class CashMethod(str, enum.Enum):
    cash = "cash"
    bank = "bank"


class CashCategory(Base, TimestampMixin):
    """
    A heading the shop files its own money movements under.

    Editable, because every shop's list is different and a fixed enum would
    mean a code change to record a kind of expense the shop already has. What
    is *not* editable from here is which ledger account the heading posts to:
    that is a chart-of-accounts decision, and letting the counter repoint a
    category at another account would silently restate history.

    `account_code` is optional. Left empty, an expense falls to 5300 Other
    Expenses and a receipt to 4400 Other Income — which is honest rather than
    precise, and better than refusing to record the money at all because
    nobody has set up a chart yet.
    """

    __tablename__ = "cash_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    # Which way this heading is normally used. `None` means either — "bank
    # charges" is only ever paid, but "adjustment" goes both ways.
    direction: Mapped[CashDirection | None] = mapped_column(
        Enum(CashDirection, name="cash_direction"), index=True
    )
    account_code: Mapped[str | None] = mapped_column(String(20), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class CashEntry(Base, TimestampMixin):
    """
    Money in or out that no other document explains.

    Everything else in this system moves money as a *consequence*: an invoice
    bills, a payment settles, a purchase owes. What was missing was the rest of
    a shop's day — rent, the electricity bill, tea, a courier, cash put into the
    till from the owner's pocket. None of it had anywhere to go, so the cash
    figure on the dashboard was only ever the part of the shop's money that
    happened to pass through a sale.

    Every row posts a balanced journal entry, so the cash and bank balances stay
    derived from the ledger rather than from a column somebody has to remember
    to update.

    `bank_account_id` is required when the method is bank and refused when it is
    cash. A "bank" movement with no account is a figure that cannot be
    reconciled against a statement, which is the only thing it exists for.
    """

    __tablename__ = "cash_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    direction: Mapped[CashDirection] = mapped_column(
        Enum(CashDirection, name="cash_direction"), nullable=False, index=True
    )
    method: Mapped[CashMethod] = mapped_column(
        Enum(CashMethod, name="cash_method"), nullable=False, index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("cash_categories.id", ondelete="RESTRICT"), index=True
    )
    category: Mapped[CashCategory | None] = relationship(lazy="joined")

    # The day the money actually moved, which is not always the day it was
    # keyed. A cash book that files an entry under the day someone got round to
    # typing it cannot be reconciled against a drawer count.
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    currency: Mapped[Currency] = mapped_column(
        Enum(Currency, name="currency"), nullable=False, default=Currency.PKR
    )
    # Rupees per unit of `currency` on the day. 1 for PKR.
    fx_rate_to_pkr: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=1)

    bank_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="RESTRICT"), index=True
    )
    bank_account: Mapped[BankAccount | None] = relationship(lazy="joined")

    # Who it was paid to or received from, as free text. Deliberately not a
    # foreign key: most of these are a landlord, a courier or the tea shop, and
    # forcing every one of them into the supplier master would fill it with
    # rows nobody wants to see when raising a purchase.
    counterparty: Mapped[str | None] = mapped_column(String(150), index=True)
    reference: Mapped[str | None] = mapped_column(String(120))

    branch_id: Mapped[int | None] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), index=True
    )
    branch: Mapped[Branch | None] = relationship(lazy="joined")

    journal_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="RESTRICT"), index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
