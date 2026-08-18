"""
Which parts of the system this shop uses.

One row per sidebar section, because a switch should match a heading somebody
already sees. A shop that does no manufacturing turns Manufacturing off and
stops being asked about karigars it does not employ.

`key` and `label` are fixed after seeding and only `enabled` moves. A module
whose key could be edited is a permission check that can be renamed out of
existence — every guard in the API looks the module up by that key.

Two modules cannot be switched off at all. A shop that turned off **Settings**
could never turn anything back on, and one without a **Dashboard** loses the
alerts that would tell it what is wrong.
"""
from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Module(Base, TimestampMixin):
    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_disable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
