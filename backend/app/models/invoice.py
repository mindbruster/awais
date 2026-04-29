import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.currency import Currency
from app.models.customer import Customer
from app.models.mixins import TimestampMixin
from app.models.product import Product


class SaleType(str, enum.Enum):
    normal = "normal"
    on_approval = "on_approval"


class InvoiceStatus(str, enum.Enum):
    draft = "draft"
    issued = "issued"
    paid = "paid"
    returned = "returned"
    void = "void"


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    sale_type: Mapped[SaleType] = mapped_column(
        Enum(SaleType, name="sale_type"), default=SaleType.normal, nullable=False, index=True
    )
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, name="invoice_status"),
        default=InvoiceStatus.draft,
        nullable=False,
        index=True,
    )

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    customer: Mapped[Customer] = relationship(lazy="joined")

    currency: Mapped[Currency] = mapped_column(
        Enum(Currency, name="currency"),
        nullable=False,
        default=Currency.PKR,
        index=True,
    )
    gold_rate_per_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)

    subtotal: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    discount_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    discount_weight_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    tax_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    total: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    notes: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class InvoiceItem(Base, TimestampMixin):
    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice: Mapped[Invoice] = relationship(back_populates="items")

    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    product: Mapped[Product | None] = relationship(lazy="joined")

    description: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    gold_weight_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    gold_purity: Mapped[int | None] = mapped_column(Integer)
    gold_rate_per_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    gold_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    stone_weight_ct: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    stone_rate_per_ct: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    stone_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    labor_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    # Per-line discount expressed in the invoice's currency. Subtracted from
    # (gold + stone + labor) before line_total. Capped to never go negative.
    line_discount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
