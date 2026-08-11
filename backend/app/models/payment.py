import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.bank import BankAccount
from app.models.mixins import TimestampMixin


class PaymentMethod(str, enum.Enum):
    cash = "cash"
    bank = "bank"
    # The customer hands over old jewellery against the bill. It is a payment,
    # not a purchase: the metal settles part of what they owe, valued at the
    # rate agreed on the day.
    gold_exchange = "gold_exchange"
    # Money taken before the bill exists, applied when it does.
    advance = "advance"


class PaymentDirection(str, enum.Enum):
    # Money or metal coming to the shop.
    received = "received"
    # Going out — the change owed when a customer's old gold is worth more than
    # the piece they are buying, which happens often enough to need its own path.
    paid = "paid"


class Payment(Base, TimestampMixin):
    """
    A settlement against an invoice, or an advance held before one exists.

    The old model had no payments at all — `mark-paid` flipped a status flag, so
    there was no record of how much was taken, when, by what method, or what was
    still outstanding. A shop cannot chase a balance it never wrote down.

    Every row posts a journal entry, so a customer's balance is derived from the
    ledger rather than stored here and trusted.
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    # Null while the money is an unapplied advance — the customer has paid
    # before the bill exists, which is normal for a commissioned piece.
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"), index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, name="payment_method"), nullable=False, index=True
    )
    direction: Mapped[PaymentDirection] = mapped_column(
        Enum(PaymentDirection, name="payment_direction"),
        nullable=False,
        default=PaymentDirection.received,
        index=True,
    )

    # Always the rupee value, whatever the method — gold handed over is valued
    # at `gold_rate_per_g` so a balance is one number, not two.
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    # Only for gold_exchange: what came across the counter, as weighed.
    gold_weight_g: Mapped[float | None] = mapped_column(Numeric(14, 4))
    gold_purity: Mapped[int | None] = mapped_column(Integer)
    gold_rate_per_g: Mapped[float | None] = mapped_column(Numeric(14, 4))

    bank_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="RESTRICT"), index=True
    )
    bank_account: Mapped[BankAccount | None] = relationship(lazy="joined")

    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)

    journal_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="RESTRICT"), index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
