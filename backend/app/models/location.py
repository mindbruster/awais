from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Country(Base, TimestampMixin):
    """Countries customers are billed from. Overseas buyers are common enough
    in this trade that country is a reporting dimension, not just an address
    line."""

    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    iso_code: Mapped[str | None] = mapped_column(String(2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


class City(Base, TimestampMixin):
    """
    Cities within a country. Names repeat across countries (Hyderabad exists in
    both Pakistan and India), so uniqueness is scoped to the country rather
    than global.
    """

    __tablename__ = "cities"
    __table_args__ = (
        UniqueConstraint("country_id", "name", name="uq_cities_country_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    country_id: Mapped[int] = mapped_column(
        ForeignKey("countries.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    country: Mapped[Country] = relationship(lazy="joined")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
