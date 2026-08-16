from datetime import date
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import TimestampedRead


class CustomerBase(BaseModel):
    """
    Only `name` is required. Customers at the counter routinely decline to give
    a CNIC or a second number, and a form that insists on them gets filled with
    junk — so everything else is captured when it's offered.
    """

    name: str = Field(min_length=1, max_length=150)
    # Another jeweller rather than a walk-in buyer. Decides the shape of every
    # bill they are given: a trade buyer settles the metal in fine grams and
    # pays cash only for stones and making, a counter customer pays rupees for
    # the lot. Defaults to the counter, so an unspecified customer is never
    # silently handed a trade bill.
    is_trade: bool = False
    # The shop's own ledger number for this account. Printed on their bills.
    account_no: str | None = Field(default=None, max_length=30)
    phone: str | None = Field(default=None, max_length=30)
    phone2: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    cnic: str | None = Field(default=None, max_length=20)
    address: str | None = None
    reference: str | None = Field(default=None, max_length=150)
    date_of_birth: date | None = None
    anniversary: date | None = None
    city_id: int | None = None
    country_id: int | None = None
    # Carried in from whatever the shop used before. Positive means the
    # customer owes the shop; negative means the shop holds their credit.
    opening_balance: Decimal = Decimal("0")
    notes: str | None = None


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    is_trade: bool | None = None
    account_no: str | None = Field(default=None, max_length=30)
    phone: str | None = Field(default=None, max_length=30)
    phone2: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    cnic: str | None = Field(default=None, max_length=20)
    address: str | None = None
    reference: str | None = Field(default=None, max_length=150)
    date_of_birth: date | None = None
    anniversary: date | None = None
    city_id: int | None = None
    country_id: int | None = None
    opening_balance: Decimal | None = None
    notes: str | None = None


class CustomerRead(TimestampedRead, CustomerBase):
    # Flattened so customer lists don't need a second lookup per row.
    city_name: str | None = None
    country_name: str | None = None
