from sqlalchemy import Boolean, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Department(Base, TimestampMixin):
    """
    A stage a piece passes through on the workshop floor — RP, casting,
    cleaning, setting, polish, rhodium and so on.

    Departments are data, not code. Every workshop runs a different set and
    reorders them freely, so the routing engine reads this table rather than
    branching on a fixed enum. `sequence` is the default order work flows in;
    it is a hint for the UI, not a constraint — pieces legitimately revisit a
    department or skip one entirely.
    """

    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    # Short label used in reports and on job cards where the full name won't fit.
    code: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)

    # Setting is the stage that consumes stones; the others move only metal.
    # Drives which fields the issue/receive forms show.
    consumes_stones: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Wastage the shop allows workers in this department, as a percentage of
    # the weight issued. A worker-level override beats this. NULL means the
    # shop hasn't agreed a departmental norm and the per-worker figure governs.
    default_wastage_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
