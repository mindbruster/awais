"""
Schemas for stock-taking: the sheet, the scale, and the difference.

Every weight is a Decimal to four places, like every other weight in this
system. A variance rounded through a float is a variance nobody can reproduce
by hand, which defeats the point of counting.
"""
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.metal import Metal
from app.models.stock_count import StockCountStatus
from app.schemas.common import TimestampedRead


# --------------------------------------------------------------------------
# The overview — what could be reconciled, and what the books currently say
# --------------------------------------------------------------------------
class ReconcileScope(BaseModel):
    """
    One thing the shop can check its books against.

    `countable` is stated rather than implied. Stones and bank balances appear
    here with their figures and no button, because a stone variance has to be
    valued out of the FIFO parcels it was bought in and a bank balance is
    reconciled against a statement, not a scale. Showing them greyed is honest;
    hiding them would suggest the shop has nothing else worth checking, and a
    button that half-worked would be worse than either.
    """

    key: str
    label: str
    unit: str
    # What the books say right now, in `unit`.
    book_quantity: Decimal = Decimal("0")
    # Rupee value where one can be put on it, else null.
    book_value: Decimal | None = None
    countable: bool = False
    # Why not, when it is not. Shown to the user verbatim.
    note: str | None = None
    last_counted_at: datetime | None = None
    # A sheet already on the go for this scope — being counted, or counted and
    # waiting for somebody to accept it. Both are surfaced, because a submitted
    # sheet with nowhere to be seen is a queue of one that nobody works.
    open_count_id: int | None = None
    open_count_status: str | None = None


class ReconcileOverview(BaseModel):
    as_of: date
    scopes: list[ReconcileScope] = []


# --------------------------------------------------------------------------
# The sheet
# --------------------------------------------------------------------------
class StockCountOpen(BaseModel):
    metal: Metal = Metal.gold
    branch_id: int | None = None
    counted_at: datetime | None = None
    notes: str | None = None


class StockCountLineUpdate(BaseModel):
    line_id: int
    # Null clears a weighing — "I entered that by mistake, it has not been
    # weighed yet". Distinct from zero, which is a real and alarming reading.
    counted_weight_g: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class StockCountUpdate(BaseModel):
    lines: list[StockCountLineUpdate] = Field(default_factory=list)
    reason: str | None = None
    notes: str | None = None


class StockCountLineRead(TimestampedRead):
    inventory_item_id: int
    label: str
    purity: int | None = None
    tunch_pct: Decimal | None = None
    book_weight_g: Decimal
    counted_weight_g: Decimal | None = None
    # Counted less book, as weighed. Null until the pot is weighed.
    variance_g: Decimal | None = None
    # The same difference in the fine grams the ledger will actually move.
    variance_fine_g: Decimal | None = None
    notes: str | None = None


class StockCountRead(TimestampedRead):
    count_no: str
    branch_id: int
    branch_name: str | None = None
    metal: Metal
    status: StockCountStatus
    counted_at: datetime
    notes: str | None = None
    reason: str | None = None

    lines: list[StockCountLineRead] = []
    # Totals over the sheet, in both units.
    book_total_g: Decimal = Decimal("0")
    counted_total_g: Decimal = Decimal("0")
    variance_g: Decimal = Decimal("0")
    variance_fine_g: Decimal = Decimal("0")
    # What the variance is worth at the rate in force. Null when no rate is on
    # record — which is also why the sheet cannot be posted.
    variance_value: Decimal | None = None
    rate_per_fine_g: Decimal | None = None
    # Pots still to be weighed. Posting is refused while this is non-zero.
    unweighed_lines: int = 0

    journal_entry_id: int | None = None
    journal_entry_no: str | None = None
    posted_at: datetime | None = None
    posted_by_user_id: int | None = None
    submitted_at: datetime | None = None
    submitted_by_user_id: int | None = None
    created_by_user_id: int | None = None

    # Whether this shop requires a second person, and whether *this* reader is
    # allowed to be that person. Sent so the screen can disable the button with
    # a reason rather than letting somebody fill in a sheet and meet a 403.
    requires_second_person: bool = False
    can_post: bool = True
    blocked_reason: str | None = None
