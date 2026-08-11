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


class Vendor(Base, TimestampMixin):
    """
    A worker the shop gives material to — karigar, stone fixer, polisher.

    `type` is the original fixed three-role enum and `department_id` is what
    replaces it: a foreign key into the editable department list, so a shop
    running nine stages isn't limited to three. Both are present while the
    manufacturing module still routes on the enum; the enum goes away with the
    routing engine, when this table is also renamed to `workers`.
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
