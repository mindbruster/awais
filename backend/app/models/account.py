import enum

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class AccountType(str, enum.Enum):
    asset = "asset"
    liability = "liability"
    equity = "equity"
    income = "income"
    expense = "expense"


# Codes the posting service looks up by name. Renaming or deleting one breaks
# automatic posting, which is why rows carrying these codes are flagged
# `is_system` and refused deletion.
class SystemAccount(str, enum.Enum):
    CASH_IN_HAND = "1110"
    BANK = "1120"
    GOLD_IN_HAND = "1130"
    STONE_INVENTORY = "1140"
    FINISHED_GOODS = "1150"
    GOLD_WITH_WORKERS = "1160"
    CUSTOMERS = "1210"
    SUPPLIERS = "2110"
    WORKERS_PAYABLE = "2120"
    CAPITAL = "3100"
    OPENING_BALANCE_EQUITY = "3200"
    SALES = "4100"
    WASTAGE_RECOVERED = "4200"
    LABOUR_COST = "5100"
    WASTAGE_EXPENSE = "5200"
    COST_OF_GOODS_SOLD = "5400"
    OTHER_EXPENSES = "5300"


class Account(Base, TimestampMixin):
    """
    A node in the chart of accounts.

    The tree is self-referencing: headers (Assets, Current Assets) carry no
    postings, leaves do. `code` is the stable identifier the posting service
    resolves against — names are for humans and the shop will rename them.

    Per-counterparty balances are *not* modelled as one account per customer.
    Customers and workers post to a single control account each, and the
    identity travels on the journal line's `party_type`/`party_id`. That keeps
    the chart small and readable while still giving a per-customer or
    per-worker statement from one indexed query.
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    type: Mapped[AccountType] = mapped_column(
        Enum(AccountType, name="account_type"), nullable=False, index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    parent: Mapped["Account | None"] = relationship(remote_side="Account.id", lazy="joined")

    # True for the heads the posting service depends on. Blocks deletion and
    # code changes so automatic posting can't be broken from the settings UI.
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    # Header accounts group their children and are never posted to directly.
    is_postable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    @property
    def parent_name(self) -> str | None:
        return self.parent.name if self.parent else None
