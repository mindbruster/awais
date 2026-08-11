from sqlalchemy import Boolean, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.currency import Currency
from app.models.mixins import TimestampMixin


class Bank(Base, TimestampMixin):
    """
    A bank the shop holds accounts with.

    `deduction_rate` is the charge that bank takes on a transaction, as a
    percentage. It is held per-bank because the rates differ and the shop needs
    to know what actually lands in the account when a customer pays by
    transfer — the invoice total and the settled amount are not the same number.
    """

    __tablename__ = "banks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    deduction_rate: Mapped[float] = mapped_column(Numeric(6, 3), default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class BankAccount(Base, TimestampMixin):
    """
    An account held at a bank.

    `opening_balance` records the cash already in the account when the shop
    starts using the system. It is stored here for now; once the ledger lands
    it becomes the source of an opening journal entry rather than a standalone
    number, and this column becomes the historical record of what was declared.
    """

    __tablename__ = "bank_accounts"
    __table_args__ = (
        UniqueConstraint("bank_id", "account_no", name="uq_bank_accounts_bank_account_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[int] = mapped_column(
        ForeignKey("banks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    bank: Mapped[Bank] = relationship(lazy="joined")

    account_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(150))
    currency: Mapped[Currency] = mapped_column(
        Enum(Currency, name="currency"), nullable=False, default=Currency.PKR, index=True
    )
    opening_balance: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
