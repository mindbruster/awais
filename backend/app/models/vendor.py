import enum

from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class VendorType(str, enum.Enum):
    karigar = "karigar"
    stone_fixer = "stone_fixer"
    polish = "polish"
    other = "other"


class Vendor(Base, TimestampMixin):
    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    type: Mapped[VendorType] = mapped_column(
        Enum(VendorType, name="vendor_type"), nullable=False, index=True
    )
    phone: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
