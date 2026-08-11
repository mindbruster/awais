"""
Schemas for the reference data the shop configures once: departments, items,
stone/diamond attribute options, locations and banks.

They share a shape — a Base with the writable fields, a Create, a partial
Update where every field is optional, and a Read carrying timestamps — so the
routers over them can stay thin.
"""
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.attribute_option import AttributeKind
from app.models.currency import Currency
from app.models.design import WastageBasis
from app.schemas.common import TimestampedRead


# --------------------------------------------------------------------------
# Departments
# --------------------------------------------------------------------------
class DepartmentBase(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=1, max_length=12)
    sequence: int = Field(default=0, ge=0)
    consumes_stones: bool = False
    default_wastage_pct: Decimal | None = Field(default=None, ge=0, le=100)
    # Setting agrees its allowance per hundred stones instead of as a
    # percentage of weight, so the basis has to be configurable per department
    # rather than assumed. Percentage is the default because that is what every
    # worker's own agreed rate is expressed in.
    default_wastage_basis: WastageBasis = WastageBasis.percent_of_issued
    default_wastage_per_100_pcs_g: Decimal | None = Field(default=None, ge=0)
    # Rupees per piece for stages that charge by the piece — stone setting at 5
    # or 10 a stone, lacquering at 500 or 1000 an item.
    default_rate_per_piece: Decimal | None = Field(default=None, ge=0)
    is_active: bool = True
    notes: str | None = None

    @field_validator("code")
    @classmethod
    def upper_code(cls, v: str) -> str:
        return v.strip().upper()


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    code: str | None = Field(default=None, min_length=1, max_length=12)
    sequence: int | None = Field(default=None, ge=0)
    consumes_stones: bool | None = None
    default_wastage_pct: Decimal | None = Field(default=None, ge=0, le=100)
    default_wastage_basis: WastageBasis | None = None
    default_wastage_per_100_pcs_g: Decimal | None = Field(default=None, ge=0)
    default_rate_per_piece: Decimal | None = Field(default=None, ge=0)
    is_active: bool | None = None
    notes: str | None = None

    @field_validator("code")
    @classmethod
    def upper_code(cls, v: str | None) -> str | None:
        return v.strip().upper() if v else v


class DepartmentRead(TimestampedRead, DepartmentBase):
    pass


# --------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------
class ItemBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # Design numbers are minted as <abbreviation>-<NNNNN>, so this has to stay
    # short and free of anything that would make a number ambiguous to read
    # off a job card or a tag.
    abbreviation: str = Field(min_length=1, max_length=8, pattern=r"^[A-Za-z0-9]+$")
    category: str | None = Field(default=None, max_length=80)
    is_active: bool = True
    notes: str | None = None

    @field_validator("abbreviation")
    @classmethod
    def upper_abbreviation(cls, v: str) -> str:
        return v.strip().upper()


class ItemCreate(ItemBase):
    pass


class ItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    abbreviation: str | None = Field(
        default=None, min_length=1, max_length=8, pattern=r"^[A-Za-z0-9]+$"
    )
    category: str | None = Field(default=None, max_length=80)
    is_active: bool | None = None
    notes: str | None = None

    @field_validator("abbreviation")
    @classmethod
    def upper_abbreviation(cls, v: str | None) -> str | None:
        return v.strip().upper() if v else v


class ItemRead(TimestampedRead, ItemBase):
    pass


# --------------------------------------------------------------------------
# Attribute options (cut / colour / clarity / quality)
# --------------------------------------------------------------------------
class AttributeOptionBase(BaseModel):
    kind: AttributeKind
    value: str = Field(min_length=1, max_length=60)
    sort_order: int = Field(default=0, ge=0)
    is_active: bool = True


class AttributeOptionCreate(AttributeOptionBase):
    pass


class AttributeOptionUpdate(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=60)
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class AttributeOptionRead(TimestampedRead, AttributeOptionBase):
    pass


# --------------------------------------------------------------------------
# Countries / cities
# --------------------------------------------------------------------------
class CountryBase(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    iso_code: str | None = Field(default=None, min_length=2, max_length=2)
    is_active: bool = True

    @field_validator("iso_code")
    @classmethod
    def upper_iso(cls, v: str | None) -> str | None:
        return v.strip().upper() if v else v


class CountryCreate(CountryBase):
    pass


class CountryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    iso_code: str | None = Field(default=None, min_length=2, max_length=2)
    is_active: bool | None = None

    @field_validator("iso_code")
    @classmethod
    def upper_iso(cls, v: str | None) -> str | None:
        return v.strip().upper() if v else v


class CountryRead(TimestampedRead, CountryBase):
    pass


class CityBase(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    country_id: int
    is_active: bool = True


class CityCreate(CityBase):
    pass


class CityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    country_id: int | None = None
    is_active: bool | None = None


class CityRead(TimestampedRead, CityBase):
    country_name: str | None = None


# --------------------------------------------------------------------------
# Banks / bank accounts
# --------------------------------------------------------------------------
class BankBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # Percentage the bank deducts on a transaction.
    deduction_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    is_active: bool = True
    notes: str | None = None


class BankCreate(BankBase):
    pass


class BankUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    deduction_rate: Decimal | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None
    notes: str | None = None


class BankRead(TimestampedRead, BankBase):
    pass


class BankAccountBase(BaseModel):
    bank_id: int
    account_no: str = Field(min_length=1, max_length=50)
    title: str | None = Field(default=None, max_length=150)
    currency: Currency = Currency.PKR
    # Cash already in the account at go-live. May be negative for an overdrawn
    # account, so no lower bound.
    opening_balance: Decimal = Decimal("0")
    is_active: bool = True


class BankAccountCreate(BankAccountBase):
    pass


class BankAccountUpdate(BaseModel):
    bank_id: int | None = None
    account_no: str | None = Field(default=None, min_length=1, max_length=50)
    title: str | None = Field(default=None, max_length=150)
    currency: Currency | None = None
    opening_balance: Decimal | None = None
    is_active: bool | None = None


class BankAccountRead(TimestampedRead, BankAccountBase):
    bank_name: str | None = None


__all__ = [
    "DepartmentCreate", "DepartmentUpdate", "DepartmentRead",
    "ItemCreate", "ItemUpdate", "ItemRead",
    "AttributeOptionCreate", "AttributeOptionUpdate", "AttributeOptionRead",
    "CountryCreate", "CountryUpdate", "CountryRead",
    "CityCreate", "CityUpdate", "CityRead",
    "BankCreate", "BankUpdate", "BankRead",
    "BankAccountCreate", "BankAccountUpdate", "BankAccountRead",
]
