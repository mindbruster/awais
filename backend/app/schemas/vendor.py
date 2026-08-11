from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.vendor import VendorType
from app.schemas.common import TimestampedRead


class VendorBase(BaseModel):
    """
    A worker the shop issues material to.

    `type` is the original three-role enum and `department_id` is what replaces
    it. Both are accepted while the manufacturing module still routes on the
    enum; new records should set the department.
    """

    name: str = Field(min_length=1, max_length=150)
    type: VendorType
    department_id: int | None = None
    phone: str | None = Field(default=None, max_length=30)
    cnic: str | None = Field(default=None, max_length=20)
    address: str | None = None
    # Wastage allowed to this worker as a percentage of the weight issued.
    # Overrides the department default; leave unset to inherit it.
    default_wastage_pct: Decimal | None = Field(default=None, ge=0, le=100)
    # What the worker owed, or was owed, at go-live. Tracked separately because
    # metal and money settle separately — a karigar can be short on gold and
    # simultaneously owed his labour in rupees.
    opening_cash_balance: Decimal = Decimal("0")
    opening_gold_g: Decimal = Decimal("0")
    is_active: bool = True
    notes: str | None = None


class VendorCreate(VendorBase):
    pass


class VendorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    type: VendorType | None = None
    department_id: int | None = None
    phone: str | None = Field(default=None, max_length=30)
    cnic: str | None = Field(default=None, max_length=20)
    address: str | None = None
    default_wastage_pct: Decimal | None = Field(default=None, ge=0, le=100)
    opening_cash_balance: Decimal | None = None
    opening_gold_g: Decimal | None = None
    is_active: bool | None = None
    notes: str | None = None


class VendorRead(TimestampedRead, VendorBase):
    department_name: str | None = None
    # The wastage percentage actually in force: this worker's own figure, or
    # the department's if he has none. Resolved server-side so the UI and the
    # manufacturing module can't drift on the fallback rule.
    effective_wastage_pct: Decimal | None = None
