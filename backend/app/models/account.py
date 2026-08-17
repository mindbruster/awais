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
    # Silver's own pair, mirroring 1130 and 1160.
    #
    # Not a sub-balance of the gold accounts. "How much metal is in the safe"
    # is not a question with an answer — grams of gold and grams of silver are
    # different assets at a hundredfold difference in value, and one account
    # holding both reports a number in no unit at all.
    SILVER_IN_HAND = "1135"
    STONE_INVENTORY = "1140"
    FINISHED_GOODS = "1150"
    GOLD_WITH_WORKERS = "1160"
    SILVER_WITH_WORKERS = "1165"
    # Carats a worker owes the shop, per worker via the line's party columns.
    #
    # Separate from 1160 because grams and carats cannot share a balance and
    # the two settle separately: a setter can be 2.2g of gold short and
    # simultaneously owe 0.20ct of stones, and netting them would produce a
    # number in no unit at all.
    STONES_WITH_WORKERS = "1170"
    CUSTOMERS = "1210"
    # The running metal account with a trade party, in fine grams.
    #
    # Deliberately one account that swings both ways rather than an asset for
    # metal owed to the shop and a liability for metal the shop is holding. In
    # this trade the same jeweller is on both sides of that line in the same
    # week — he settles a bill in bullion on Tuesday and drops off 500g for job
    # work on Thursday — and a split would need reclassifying constantly. The
    # bazaar itself keeps one running account with a direction, so the ledger
    # does too: positive means they owe the shop metal, negative means the shop
    # is holding theirs.
    PARTY_METAL = "1215"
    SUPPLIERS = "2110"
    WORKERS_PAYABLE = "2120"
    CAPITAL = "3100"
    OPENING_BALANCE_EQUITY = "3200"
    SALES = "4100"
    WASTAGE_RECOVERED = "4200"
    # What the shop charges for making a piece, as income.
    #
    # `5100 Labour Cost` is what the karigar is paid; this is its opposite and
    # there was no account for it, so making charges billed to a customer fell
    # into `4100 Sales` alongside the metal. For a retailer that is untidy. For
    # a wholesaler it hides the business: making and wastage *are* the margin,
    # the metal largely passes through at cost, and a profit report that cannot
    # separate the two cannot say whether the month was any good.
    MAKING_INCOME = "4300"
    # Money in that is not a sale: capital put into the till, a supplier
    # refund, scrap sold off the bench. It has its own head so that revenue
    # means revenue — a margin report that counts the owner topping up the
    # drawer as a sale reports a month that never happened.
    OTHER_INCOME = "4400"
    # What the market did to metal the shop was already holding.
    #
    # One account swinging both ways rather than a gain and a loss head. A
    # falling rate books a real loss in a month the shop may have traded well,
    # and that is the truth of holding metal — splitting it across two heads
    # would make the same phenomenon read as two unrelated events, and a month
    # with both a rise and a fall would show income and expense for what was
    # one position moving.
    METAL_REVALUATION = "4500"
    LABOUR_COST = "5100"
    WASTAGE_EXPENSE = "5200"
    COST_OF_GOODS_SOLD = "5400"
    OTHER_EXPENSES = "5300"
    # What a stock-take found that the books did not. One account swinging both
    # ways rather than a shrinkage head and a windfall head: it is one
    # phenomenon — the count did not match — and splitting it would make a
    # month holding a gold loss and a silver gain read as two unrelated events.
    #
    # A credit balance here deserves a hard look. Finding more metal than the
    # books show does not mean the shop got richer; it means something arrived
    # that was never recorded.
    STOCK_VARIANCE = "5500"


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
