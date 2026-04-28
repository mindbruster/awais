from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.currency import Currency
from app.models.stone import StoneKind
from app.schemas.common import TimestampedRead


class StoneBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    kind: StoneKind
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
    cut: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=40)
    clarity: str | None = Field(default=None, max_length=40)
    default_rate_per_ct: Decimal | None = Field(default=None, ge=0)
    currency: Currency | None = None
    notes: str | None = None


class StoneRead(TimestampedRead, StoneBase):
    pass
