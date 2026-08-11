import enum

from sqlalchemy import Boolean, Enum, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class AttributeKind(str, enum.Enum):
    cut = "cut"
    color = "color"
    clarity = "clarity"
    quality = "quality"


class AttributeOption(Base, TimestampMixin):
    """
    Governed vocabulary for stone and diamond attributes.

    These were free-text columns on `stones`, which meant VS1, vs1 and "VS 1"
    all coexisted within a month and nothing could be grouped or filtered
    reliably. Holding them as options makes the entry forms dropdowns and the
    stone stock report groupable.

    One table rather than four: the four kinds differ only in what populates
    them, and `quality` (deluxe / commercial) already proves the set isn't
    closed — the shop will invent a fifth.
    """

    __tablename__ = "attribute_options"
    __table_args__ = (
        UniqueConstraint("kind", "value", name="uq_attribute_options_kind_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[AttributeKind] = mapped_column(
        Enum(AttributeKind, name="attribute_kind"), nullable=False, index=True
    )
    value: Mapped[str] = mapped_column(String(60), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
