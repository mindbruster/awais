from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.cash import CashDirection, CashMethod
from app.models.currency import Currency
from app.schemas.common import TimestampedRead


class CashCategoryBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # Which way this heading is normally used. Null means either.
    direction: CashDirection | None = None
    # The ledger head this category posts to. Left empty, expenses fall to 5300
    # Other Expenses and receipts to 4400 Other Income.
    account_code: str | None = Field(default=None, max_length=20)
    is_active: bool = True
    notes: str | None = None


class CashCategoryCreate(CashCategoryBase):
    pass


class CashCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    direction: CashDirection | None = None
    account_code: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None
    notes: str | None = None


class CashCategoryRead(TimestampedRead, CashCategoryBase):
    pass


class CashEntryCreate(BaseModel):
    """
    Money in or out that no other document explains.

    `occurred_on` is the day the money actually moved, not the day it was
    keyed — a cash book filed by typing date cannot be reconciled against a
    drawer count.
    """

    direction: CashDirection
    method: CashMethod
    category_id: int | None = None
    occurred_on: date | None = None
    amount: Decimal = Field(gt=0)
    currency: Currency = Currency.PKR
    fx_rate_to_pkr: Decimal = Field(default=Decimal("1"), gt=0)
    # Required for a bank entry, refused for a cash one — see
    # `app.services.cash.validate_method`.
    bank_account_id: int | None = None
    counterparty: str | None = Field(default=None, max_length=150)
    reference: str | None = Field(default=None, max_length=120)
    branch_id: int | None = None
    notes: str | None = None


class CashEntryRead(TimestampedRead):
    entry_no: str
    direction: CashDirection
    method: CashMethod
    category_id: int | None = None
    category_name: str | None = None
    occurred_on: date
    amount: Decimal
    currency: Currency
    fx_rate_to_pkr: Decimal
    # The rupee value that reached the books, which is the amount converted.
    # Shown because a dollar expense and its rupee cost are both worth seeing.
    amount_pkr: Decimal
    bank_account_id: int | None = None
    bank_account_label: str | None = None
    counterparty: str | None = None
    reference: str | None = None
    branch_id: int | None = None
    journal_entry_id: int | None = None
    entry_no_journal: str | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Cash flow report
# ---------------------------------------------------------------------------
class CashFlowLine(BaseModel):
    """One movement of money through the drawer or the bank."""

    entry_date: date
    entry_no: str
    account_code: str
    account_name: str
    # What the money moved through, so a day can be split into drawer and bank
    # without reading every line twice.
    side: str
    memo: str | None = None
    # Signed: positive is money arriving, negative is money leaving.
    amount: Decimal
    source_type: str | None = None
    source_id: int | None = None


class CashFlowHead(BaseModel):
    account_code: str
    account_name: str
    money_in: Decimal
    money_out: Decimal
    net: Decimal


class CashFlowReport(BaseModel):
    """
    Every rupee that moved through the drawer and the bank, and what moved it.

    Read off the journal rather than off the cash entries, which is the whole
    point: a day's money is invoices settled, suppliers paid, wages, rent and
    the till float, and a report that only knew about one of those would answer
    a question nobody asked.
    """

    date_from: date
    date_to: date
    opening_cash: Decimal
    opening_bank: Decimal
    closing_cash: Decimal
    closing_bank: Decimal
    money_in: Decimal
    money_out: Decimal
    net: Decimal
    by_head: list[CashFlowHead]
    lines: list[CashFlowLine]
