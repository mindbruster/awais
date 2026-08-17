"""
Shapes for the analysis endpoints.

Every response carries `ai_enabled` and every narrative field is optional. That
is the contract the frontend is built against: figures always, prose sometimes.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Wastage anomalies
# --------------------------------------------------------------------------
class WastageHalf(BaseModel):
    """One half of the window, for a single worker."""

    legs: int
    issued_g: Decimal
    actual_g: Decimal
    rate_pct: Decimal


class WastageJobRef(BaseModel):
    """A leg the owner can go and look at."""

    leg_id: int
    design_no: str
    department: str
    received_at: datetime | None
    issued_g: Decimal
    received_g: Decimal
    excess_g: Decimal


class WastageWorkerRow(BaseModel):
    worker_id: int | None
    worker_name: str
    legs: int
    issued_g: Decimal
    actual_wastage_g: Decimal
    allowed_g: Decimal
    excess_g: Decimal
    # Actual wastage as a percentage of what was issued. Signed: negative means
    # the pieces came back heavier overall, which solder and findings do.
    wastage_rate_pct: Decimal
    # Excess against allowance. 2.0 means twice what was agreed was lost.
    excess_to_allowance: Decimal | None
    earlier: WastageHalf
    recent: WastageHalf
    flags: list[str] = Field(default_factory=list)
    worst_legs: list[WastageJobRef] = Field(default_factory=list)
    narrative: str | None = None


class WastageAnomalyReport(BaseModel):
    days: int
    period_from: date
    period_to: date
    midpoint: date
    min_legs_per_half: int
    deterioration_ratio: Decimal
    shop_issued_g: Decimal
    shop_actual_wastage_g: Decimal
    shop_excess_g: Decimal
    shop_wastage_rate_pct: Decimal
    rows: list[WastageWorkerRow]
    flagged_count: int
    ai_enabled: bool
    ai_note: str | None = None


# --------------------------------------------------------------------------
# Margin watch
# --------------------------------------------------------------------------
class MarginRow(BaseModel):
    invoice_id: int
    invoice_no: str
    customer_id: int
    customer_name: str
    currency: str
    issued_at: datetime | None
    revenue: Decimal
    cogs: Decimal
    profit: Decimal
    margin_pct: Decimal | None
    # True when at least one line has no product behind it, so the COGS figure
    # is a floor rather than the whole cost.
    cogs_incomplete: bool
    flags: list[str] = Field(default_factory=list)
    narrative: str | None = None


class CustomerDiscountRow(BaseModel):
    customer_id: int
    customer_name: str
    invoices: int
    gross: Decimal
    discount: Decimal
    discount_pct: Decimal
    # Percentage points above the shop average.
    above_shop_avg_pp: Decimal
    flags: list[str] = Field(default_factory=list)
    narrative: str | None = None


class MarginWatchReport(BaseModel):
    days: int
    period_from: date
    period_to: date
    floor_margin_pct: Decimal
    revenue: Decimal
    cogs: Decimal
    profit: Decimal
    margin_pct: Decimal | None
    shop_discount_pct: Decimal
    rows: list[MarginRow]
    customers: list[CustomerDiscountRow]
    flagged_count: int
    ai_enabled: bool
    ai_note: str | None = None


# --------------------------------------------------------------------------
# Ask
# --------------------------------------------------------------------------
class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class AskResponse(BaseModel):
    question: str
    sql: str
    model: str
    notes: str | None
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    answer: str | None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    """
    The whole conversation, sent each turn.

    Stateless on purpose: nothing about a chat belongs in the shop's database,
    and holding threads server-side would mean deciding when they expire and
    who else may read them. The client owns the transcript; the server owns the
    read-only guarantee.
    """

    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


class ChatResponse(BaseModel):
    reply: str
    # Which path answered: "data" went to the books, "howto" to the workflow
    # guide, "chat" to neither. Surfaced so the UI can show the query behind a
    # figure and say nothing at all when there wasn't one.
    kind: str
    sql: str | None = None
    columns: list[str] | None = None
    rows: list[dict[str, Any]] | None = None
    notes: str | None = None
    model: str | None = None


# --------------------------------------------------------------------------
# Karigar risk
# --------------------------------------------------------------------------
class RiskReason(BaseModel):
    """
    One component of a worker's score, with the figure behind it.

    Scores that cannot be taken apart do not get acted on — an owner is being
    asked to have a difficult conversation with a man he has worked with for
    years, and "the computer says 68" is not something he can put to him. Every
    component states what was measured, what it was measured against, and how
    many points it contributed.
    """

    code: str
    label: str
    detail: str
    points: int


class KarigarRiskRow(BaseModel):
    worker_id: int
    worker_name: str
    department: str | None = None

    legs: int
    gold_issued_g: Decimal
    excess_g: Decimal
    excess_rate_pct: Decimal
    avg_days_held: Decimal | None = None

    earlier_rate_pct: Decimal | None = None
    recent_rate_pct: Decimal | None = None

    # Metal the worker is holding right now, and the oldest leg it sits on.
    open_legs: int
    open_gold_g: Decimal
    oldest_open_days: int | None = None

    score: int
    band: str
    reasons: list[RiskReason] = Field(default_factory=list)
    narrative: str | None = None


class KarigarRiskReport(BaseModel):
    days: int
    period_from: date
    period_to: date
    # A worker below this many finished legs is reported but not scored: a
    # score built on two jobs says more about the sample than the man.
    min_legs: int
    shop_excess_rate_pct: Decimal
    shop_avg_days_held: Decimal | None = None
    rows: list[KarigarRiskRow] = Field(default_factory=list)
    scored_count: int
    high_count: int
    ai_enabled: bool
    ai_note: str | None = None
