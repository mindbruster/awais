"""
Schemas for the chart of accounts, the journal, and the reports read off it.

Every money and weight field is a Decimal — gold is measured to four decimal
places and a float would drift a statement by paisas that the shop notices.
Quantities are signed the way `JournalLine` stores them (positive debits,
negative credits); only the statement and trial balance split them into the
debit/credit columns a human expects to read.
"""
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.account import AccountType
from app.models.journal import Commodity, PartyType
from app.schemas.common import ORMModel, TimestampedRead


# --------------------------------------------------------------------------
# Chart of accounts
# --------------------------------------------------------------------------
class AccountBase(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=120)
    type: AccountType
    parent_id: int | None = None
    is_postable: bool = True
    is_active: bool = True
    notes: str | None = None


class AccountCreate(AccountBase):
    # A new account always hangs off an existing head — a second root would
    # leave the tree with two tops and no report knows which to walk.
    parent_id: int


class AccountUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=20)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: int | None = None
    is_postable: bool | None = None
    is_active: bool | None = None
    is_system: bool | None = None
    notes: str | None = None


class AccountRead(TimestampedRead, AccountBase):
    is_system: bool
    parent_name: str | None = None


# --------------------------------------------------------------------------
# Journal
# --------------------------------------------------------------------------
class JournalLineRead(ORMModel):
    id: int
    account_id: int
    account_code: str
    account_name: str
    commodity: Commodity
    quantity: Decimal
    rate: Decimal
    value_pkr: Decimal
    native_weight_g: Decimal | None = None
    native_purity: int | None = None
    party_type: PartyType | None = None
    party_id: int | None = None
    memo: str | None = None


class JournalEntryRead(ORMModel):
    id: int
    entry_no: str
    entry_date: date
    memo: str | None = None
    source_type: str | None = None
    source_id: int | None = None
    reverses_entry_id: int | None = None
    posted_at: datetime
    created_by_user_id: int | None = None
    total_debit: Decimal
    total_credit: Decimal
    lines: list[JournalLineRead]


class PostingCreate(BaseModel):
    """
    One side of a manual entry, as the voucher screen sends it.

    For GOLD, `quantity` is the weight **as weighed at the counter** and
    `native_purity` is its karat — the router converts to the fine grams the
    ledger stores. A human writing a voucher has a scale reading and a karat
    stamp, not a 24k equivalent, and asking them to do that arithmetic is how
    22k gets banked as if it were pure: the entry still balances, because both
    sides are valued off the same wrong quantity, so nothing ever catches it.
    """

    account_code: str = Field(min_length=1, max_length=20)
    # Signed: positive debits, negative credits.
    quantity: Decimal
    commodity: Commodity = Commodity.PKR
    # PKR per unit — per *fine* gram for GOLD, the FX rate for USD.
    rate: Decimal = Decimal("1")
    party_type: PartyType | None = None
    party_id: int | None = None
    # Karat of the weight above. Defaults to pure, which is how bullion is
    # entered; anything else must be stated.
    native_purity: int | None = Field(default=None, ge=1, le=24)
    memo: str | None = None

    @model_validator(mode="after")
    def rate_required_off_pkr(self) -> "PostingCreate":
        # A rate of zero values the line at nothing, so the entry would balance
        # against itself and silently post gold worth nothing.
        if self.commodity is not Commodity.PKR and self.rate <= 0:
            raise ValueError(f"A {self.commodity.value} line needs a rate above zero.")
        if self.commodity is not Commodity.GOLD and self.native_purity is not None:
            raise ValueError("native_purity only applies to GOLD lines.")
        return self


class ManualEntryCreate(BaseModel):
    memo: str = Field(min_length=1)
    entry_date: date | None = None
    # Capped, not just floored. The posting service absorbs rounding up to half
    # a paisa per line, so an unbounded line count would let a caller widen that
    # tolerance until a genuine imbalance fitted inside it. Fifty lines is far
    # beyond any real voucher.
    postings: list[PostingCreate] = Field(min_length=2, max_length=50)


class EntryReverseRequest(BaseModel):
    memo: str | None = None


# --------------------------------------------------------------------------
# Statement
# --------------------------------------------------------------------------
class StatementRow(BaseModel):
    line_id: int
    entry_id: int
    entry_no: str
    entry_date: date
    memo: str | None = None
    # The other accounts on the same entry — "what this movement was against".
    counter_accounts: list[str]
    debit: Decimal
    credit: Decimal
    running_balance: Decimal
    native_weight_g: Decimal | None = None
    native_purity: int | None = None


class StatementReport(BaseModel):
    account_id: int
    account_code: str
    account_name: str
    commodity: Commodity
    party_type: PartyType | None = None
    party_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    opening_balance: Decimal
    rows: list[StatementRow]
    # Totals for the whole period, not for the page of rows above — a control
    # account's month routinely runs past any page size.
    period_debit: Decimal
    period_credit: Decimal
    closing_balance: Decimal
    total_rows: int = 0
    # True when `rows` is only part of the period. The totals are still complete.
    truncated: bool = False


# --------------------------------------------------------------------------
# Party statement — the wholesale account, in metal and money at once
# --------------------------------------------------------------------------
class PartyStatementRow(BaseModel):
    """
    One document's effect on a trade party's account, in both units.

    A row carries a metal side and a cash side because a single document
    routinely moves both and moves them by unrelated amounts: a bill for twelve
    rings adds fine grams to what the jeweller owes in metal and rupees to what
    he owes in making. Splitting that across two statements would mean reading
    two pages to find out where one document left the account.

    Either side may be zero. Metal-only rows are ordinary — a jeweller dropping
    off 500g for job work moves no money at all — and so are cash-only ones.
    """

    entry_id: int
    entry_no: str
    entry_date: date
    memo: str | None = None
    # What kind of document this was — 'invoice', 'payment', 'gold_purchase'.
    # Taken from the entry's own source_type so the statement names the
    # document rather than describing the posting.
    source_type: str | None = None
    source_id: int | None = None

    # Fine grams. Positive is metal the party has taken on — it increases what
    # they owe. Negative is metal received from them.
    metal_in_g: Decimal = Decimal("0")
    metal_out_g: Decimal = Decimal("0")
    metal_balance_g: Decimal = Decimal("0")
    # As weighed, when the document said. Display only.
    native_weight_g: Decimal | None = None
    native_purity: int | None = None
    native_tunch_pct: Decimal | None = None

    cash_debit: Decimal = Decimal("0")
    cash_credit: Decimal = Decimal("0")
    cash_balance: Decimal = Decimal("0")


class PartyStatementReport(BaseModel):
    """
    A trade party's whole position: what they owe in gold, and what in rupees.

    The two balances are reported separately and are never netted. Converting
    the metal side to money to produce a single figure would price grams the
    party has not agreed to sell yet — the entire point of settling in metal is
    that the rate is decided on the day the metal moves, not on the day the
    bill was written.
    """

    party_type: PartyType
    party_id: int
    party_name: str | None = None
    date_from: date | None = None
    date_to: date | None = None

    opening_metal_g: Decimal = Decimal("0")
    opening_cash: Decimal = Decimal("0")

    rows: list[PartyStatementRow]

    metal_in_total_g: Decimal = Decimal("0")
    metal_out_total_g: Decimal = Decimal("0")
    cash_debit_total: Decimal = Decimal("0")
    cash_credit_total: Decimal = Decimal("0")

    # Positive means the party owes the shop. Negative on the metal side means
    # the shop is holding their gold, which is the normal state during job work.
    closing_metal_g: Decimal = Decimal("0")
    closing_cash: Decimal = Decimal("0")

    total_rows: int = 0
    truncated: bool = False


# --------------------------------------------------------------------------
# Trial balance / position
# --------------------------------------------------------------------------
class TrialBalanceRow(BaseModel):
    account_id: int
    account_code: str
    account_name: str
    account_type: AccountType
    commodity: Commodity
    # In the commodity's own unit: rupees, dollars, or fine grams.
    debit: Decimal
    credit: Decimal
    balance: Decimal


class TrialBalanceReport(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    rows: list[TrialBalanceRow]
    total_debit_pkr: Decimal
    total_credit_pkr: Decimal
    balanced: bool


class PositionReport(BaseModel):
    as_of: date
    cash_in_hand: Decimal
    gold_in_hand_g: Decimal
    gold_with_workers_g: Decimal
    customer_receivable: Decimal
    # Payables are shown as the shop reads them: positive means money owed out,
    # even though a liability carries a credit (negative) balance in the ledger.
    supplier_payable: Decimal
    worker_payable: Decimal


# --------------------------------------------------------------------------
# Opening balances
# --------------------------------------------------------------------------
class OpeningBalancePosted(BaseModel):
    party_type: str
    party_id: int
    party_name: str
    entry_id: int
    entry_no: str


class OpeningBalanceSkipped(BaseModel):
    party_type: str
    party_id: int
    party_name: str
    reason: str


class OpeningBalanceResult(BaseModel):
    gold_rate_per_g: Decimal
    posted: list[OpeningBalancePosted]
    skipped: list[OpeningBalanceSkipped]


__all__ = [
    "AccountCreate", "AccountUpdate", "AccountRead",
    "JournalLineRead", "JournalEntryRead",
    "PostingCreate", "ManualEntryCreate", "EntryReverseRequest",
    "StatementRow", "StatementReport",
    "TrialBalanceRow", "TrialBalanceReport",
    "PositionReport",
    "OpeningBalancePosted", "OpeningBalanceSkipped", "OpeningBalanceResult",
]
