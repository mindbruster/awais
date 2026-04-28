from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

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
