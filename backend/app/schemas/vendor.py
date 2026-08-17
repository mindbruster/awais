from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.vendor import VendorType
from app.schemas.common import TimestampedRead


class VendorBase(BaseModel):
    """
    A worker the shop issues material to.

    `department_id` is the routing key and is required on new records. A worker
    without one cannot be picked on a job leg — the worker dropdown is filtered
    by department, deliberately, so casting work cannot be sent to a polisher —
    which means creating one without a department produces a worker who is
    invisible everywhere and looks like a bug in the design screen.

    `type`, the original three-role enum, is not writable. It is derived from
    the department on save, because the two say the same thing and only one of
    them can be the truth.
    """

    name: str = Field(min_length=1, max_length=150)
    # Optional on the model (historical rows predate departments) but required
    # here, so nothing new can be created unusable.
    department_id: int = Field(description="Which department this worker belongs to.")
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
    # Reading is looser than writing on purpose: workers created before
    # departments existed have none, and they have to stay visible so somebody
    # can go and fix them. Requiring it here would make the list endpoint fail
    # on exactly the records that need attention.
    department_id: int | None = None
    department_name: str | None = None
    # Read-only: whatever the department implies. Still reported because the
    # loss report groups on it and somebody comparing the two screens should be
    # able to see the value rather than infer it.
    type: VendorType = VendorType.other
    # The wastage percentage actually in force: this worker's own figure, or
    # the department's if he has none. Resolved server-side so the UI and the
    # manufacturing module can't drift on the fallback rule.
    effective_wastage_pct: Decimal | None = None
