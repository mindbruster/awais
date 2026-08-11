from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Item(Base, TimestampMixin):
    """
    A kind of piece the shop makes — ring, bangle, taka, earring.

    The abbreviation is the load-bearing field: design numbers are minted as
    `<abbreviation>-<NNNNN>` (taka -> TK-00001), so it is the prefix every
    piece is tracked by from the first department through to sale. Changing an
    abbreviation does not rewrite design numbers already issued, which is why
    it is validated tightly on the way in.
    """

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    abbreviation: Mapped[str] = mapped_column(String(8), unique=True, nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(80), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
