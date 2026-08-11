from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.currency import Currency
from app.schemas.common import TimestampedRead


class GoldRateBase(BaseModel):
    rate_date: date
    currency: Currency = Currency.PKR
    rate_per_g: Decimal = Field(gt=0)
    purity: int = Field(default=24, ge=1, le=24)
    notes: str | None = Field(default=None, max_length=255)


class GoldRateCreate(GoldRateBase):
    pass


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
