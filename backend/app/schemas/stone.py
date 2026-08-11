from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.currency import Currency
from app.models.stone import StoneCategory, StoneKind
from app.schemas.common import TimestampedRead


class StoneBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    kind: StoneKind
    # Diamonds are bought, graded, priced and stocked differently from coloured
    # stones, so this drives which fields the entry forms show.
    category: StoneCategory = StoneCategory.stone
    abbreviation: str | None = Field(default=None, max_length=8)
    # Trade grade — "Deluxe" / "Commercial" for diamonds. Free text against the
    # `quality` attribute options rather than an enum; shops invent grades.
    quality: str | None = Field(default=None, max_length=60)
    cut: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=40)
    clarity: str | None = Field(default=None, max_length=40)
    default_rate_per_ct: Decimal | None = Field(default=None, ge=0)
    currency: Currency = Currency.PKR
    notes: str | None = None


class StoneCreate(StoneBase):
    pass


class StoneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    kind: StoneKind | None = None
    category: StoneCategory | None = None
    abbreviation: str | None = Field(default=None, max_length=8)
    quality: str | None = Field(default=None, max_length=60)
    cut: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=40)
    clarity: str | None = Field(default=None, max_length=40)
    default_rate_per_ct: Decimal | None = Field(default=None, ge=0)
    currency: Currency | None = None
    notes: str | None = None


class StoneRead(TimestampedRead, StoneBase):
    pass
