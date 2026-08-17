"""
The opening screen, as one response.

Deliberately a single endpoint rather than the six it could have been. A
dashboard that fires six requests renders in six stages, and the shop reads a
half-drawn screen as a broken one — the cash figure arriving a beat after the
gold figure is exactly when somebody acts on a number that is not there yet.
"""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class DashboardToday(BaseModel):
    """What is true right now. Numbers, not trends."""

    # None when nobody has set a rate today. That is not cosmetic: the routing
    # engine refuses to issue metal without one, so it is the first thing the
    # screen has to be able to say.
    gold_rate_per_g: Decimal | None = None
    gold_rate_date: date | None = None
    gold_rate_is_stale: bool = False

    cash_in_hand: Decimal
    # Kept apart from cash. A drawer is counted and a bank account is agreed
    # against a statement; one "money" figure covering both cannot be
    # reconciled against either.
    bank_balance: Decimal = Decimal("0")
    # Everything that moved through the drawer or the bank today, whatever
    # produced it — a bill settled, a supplier paid, the rent. Read off the
    # journal, so it is the whole day and not just what was typed by hand.
    money_in_today: Decimal = Decimal("0")
    money_out_today: Decimal = Decimal("0")

    gold_in_hand_g: Decimal
    gold_with_workers_g: Decimal
    # Silver and stones alongside, never added to the gold. They are different
    # assets and a combined figure is a number in no unit at all.
    silver_in_hand_g: Decimal = Decimal("0")
    silver_with_workers_g: Decimal = Decimal("0")
    stones_with_workers_ct: Decimal = Decimal("0")

    customer_receivable: Decimal
    supplier_payable: Decimal
    # What the shop owes its workers in cash for labour, and in metal to the
    # makers who worked on their own gold. The second only exists because the
    # shop can now take that deal at all, and it is the one obligation nothing
    # else in the day would raise.
    worker_payable: Decimal = Decimal("0")
    metal_owed_to_makers_g: Decimal = Decimal("0")

    sold_today_count: int
    sold_today_value: Decimal


class DashboardFloorRow(BaseModel):
    """One department, and what is sitting in it."""

    department_id: int | None = None
    department: str
    pieces: int
    # How long the longest-held piece has been out. A count alone cannot tell a
    # busy stage from a stuck one, and "stuck" is the only reason to look.
    oldest_days: int | None = None


class DashboardDay(BaseModel):
    """One day's worth of trading, for the charts."""

    day: date
    sales_value: Decimal
    sales_count: int
    # Fine grams into and out of the safe, off the metal ledger itself rather
    # than the stock table — the ledger is the only place that has already
    # converted every purity to a comparable figure.
    gold_in_g: Decimal
    gold_out_g: Decimal
    # Carried forward across days nobody set a rate on, so the line is
    # continuous. A gap in a rate chart reads as a crash, not a closed shop.
    gold_rate_per_g: Decimal | None = None


class DashboardAlert(BaseModel):
    """One thing worth doing something about."""

    key: str
    label: str
    detail: str | None = None
    count: int
    # `bad` is money or metal already at risk; `warn` is heading that way;
    # `info` is a nudge. The colour is decided here, not in the browser, so the
    # rule is the same on every screen that shows these.
    tone: str = "info"
    to: str


class DashboardReport(BaseModel):
    as_of: date
    days: int
    today: DashboardToday
    series: list[DashboardDay] = Field(default_factory=list)
    alerts: list[DashboardAlert] = Field(default_factory=list)
    floor: list[DashboardFloorRow] = Field(default_factory=list)
