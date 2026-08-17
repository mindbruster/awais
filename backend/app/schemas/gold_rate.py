from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.currency import Currency
from app.models.metal import Metal
from app.schemas.common import TimestampedRead


class GoldRateBase(BaseModel):
    rate_date: date
    currency: Currency = Currency.PKR
    # Which metal this prices. Gold unless said otherwise.
    metal: Metal = Metal.gold
    rate_per_g: Decimal = Field(gt=0)
    # Karat, gold only.
    purity: int = Field(default=24, ge=1, le=24)
    # The purity the rate is quoted at, for metals karat cannot express.
    # 99.9 for the 999 silver the shop buys.
    fineness_pct: Decimal | None = Field(default=None, gt=0, le=100)
    notes: str | None = Field(default=None, max_length=255)


class GoldRateCreate(GoldRateBase):
    @model_validator(mode="after")
    def silver_states_its_fineness(self) -> "GoldRateCreate":
        """
        A silver rate has to say what purity it is quoted at.

        The ledger values metal per gram of *pure*, and the shop quotes per
        gram of 999. Without the fineness there is nothing to divide by, and
        the rate would be taken as the pure rate — every silver movement
        valued a tenth of a percent light, forever, in the same direction.

        Gold does not need it: the karat column already says it, and 24k is
        pure by definition.
        """
        if self.metal is Metal.silver and self.fineness_pct is None:
            raise ValueError(
                "A silver rate must say what fineness it is quoted at. Send fineness_pct "
                "— 99.9 for 999 silver."
            )
        return self


class GoldRateRead(TimestampedRead, GoldRateBase):
    pass


# --------------------------------------------------------------------------
# Exchange rates
# --------------------------------------------------------------------------
class ExchangeRateCreate(BaseModel):
    """
    A day's rate for one foreign currency.

    PKR is refused outright rather than defaulted: it is the book currency and
    converts to itself at exactly 1. Letting a row exist saying otherwise would
    let someone revalue the entire book by typing in a box.
    """

    currency: Currency
    rate_date: date
    pkr_per_unit: Decimal = Field(gt=0)
    notes: str | None = Field(default=None, max_length=255)

    @field_validator("currency")
    @classmethod
    def not_the_base(cls, v: Currency) -> Currency:
        if v is Currency.PKR:
            raise ValueError(
                "PKR is the book currency and converts to itself at 1. Set a rate for a "
                "foreign currency instead."
            )
        return v


class ExchangeRateRead(TimestampedRead):
    currency: Currency
    rate_date: date
    pkr_per_unit: Decimal
    notes: str | None = None


# ---------------------------------------------------------------------------
# Live market rates — display only
# ---------------------------------------------------------------------------
class LiveMetalRates(BaseModel):
    """
    What the market is doing, for looking at.

    Deliberately not the rate anything is priced at. Invoices, product costing
    and every journal entry that values metal read the rate the shop *sets*; a
    feed wired into pricing would reprice the counter mid-sale from a number
    nobody in the shop agreed to.

    It is also international spot converted into the currency asked for, which
    is not the same thing as the local market rate — that is set in the bazaar
    and differs by the import premium and the day's dollar. `caveat` carries
    that in words so it travels with the figures wherever they are shown.
    """

    currency: Currency
    # Per gram of *pure* metal, matching how 24k gold and 999 silver are quoted.
    # Null when the feed had no price for that metal.
    gold_per_gram: Decimal | None = None
    silver_per_gram: Decimal | None = None
    fetched_at: datetime
    # Set when the feed is unconfigured or unreachable. The screen shows this in
    # place of a number rather than a stale one — a rate presented as live when
    # it is not is worse than an honest gap.
    unavailable: str | None = None
    caveat: str
    source: str
