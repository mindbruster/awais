import enum

from sqlalchemy import Boolean, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.department import Department
from app.models.mixins import TimestampMixin


class VendorType(str, enum.Enum):
    karigar = "karigar"
    stone_fixer = "stone_fixer"
    polish = "polish"
    other = "other"


# The department a worker belongs to, said again in the old three-role
# vocabulary the loss report still groups on. Derived rather than asked for:
# the department is the routing key, and a form offering both invites a worker
# filed under Maker while typed `polish`, which the report would then believe.
#
# Unknown codes fall to `other` on purpose. Departments are editable data, so a
# shop that adds a fourth stage tomorrow gets a worker who is simply absent
# from the two legacy roll-ups — never one filed under a stage he never worked.
LEGACY_TYPE_BY_DEPARTMENT_CODE = {
    "MAKE": VendorType.karigar,
    "SET": VendorType.stone_fixer,
    # A lacker is not a polisher. `other` says so rather than guessing.
    "LAC": VendorType.other,
}


def legacy_type_for(department: "Department | None") -> VendorType:
    if department is None:
        return VendorType.other
    return LEGACY_TYPE_BY_DEPARTMENT_CODE.get(department.code, VendorType.other)


class Vendor(Base, TimestampMixin):
    """
    A worker the shop gives material to — karigar, stone fixer, polisher.

    `department_id` is the routing key: a foreign key into the editable
    department list, so the floor is configured rather than compiled in.

    `type` is the original fixed three-role enum, kept only because the loss
    report still reports two all-time totals against it. Nobody sets it by
    hand any more — see `legacy_type_for`, which derives it from the department
    so the two cannot disagree.
    """

    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    type: Mapped[VendorType] = mapped_column(
        Enum(VendorType, name="vendor_type"), nullable=False, index=True
    )
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    department: Mapped[Department | None] = relationship(lazy="joined")

    phone: Mapped[str | None] = mapped_column(String(30))
    cnic: Mapped[str | None] = mapped_column(String(20), index=True)
    address: Mapped[str | None] = mapped_column(Text)

    # Wastage this particular worker is allowed, as a percentage of the weight
    # issued to him. Overrides the department default; NULL falls back to it.
    # Terms are negotiated per worker in practice, which is why the override
    # sits here rather than only on the department.
    default_wastage_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))

    # What the worker owed, or was owed, when the shop started on this system.
    # Gold and cash are tracked separately because they settle separately — a
    # karigar can be 12g short and simultaneously owed his labour in rupees.
    # Positive gold means the worker holds shop metal.
    opening_cash_balance: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    opening_gold_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    @property
    def department_name(self) -> str | None:
        return self.department.name if self.department else None

    @property
    def effective_wastage_pct(self):
        """
        The allowance actually in force for this worker: his own agreed figure,
        falling back to his department's norm. Resolved in one place so the UI,
        the reports and (later) the routing engine can't drift on the rule.
        """
        if self.default_wastage_pct is not None:
            return self.default_wastage_pct
        return self.department.default_wastage_pct if self.department else None
