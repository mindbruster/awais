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

    # The shop's own paper bill book still runs alongside the system for a
    # while after go-live, and the two have to be reconcilable by hand.
    bill_book_no: Mapped[str | None] = mapped_column(String(50), index=True)
    # The difference knocked off to reach a round figure, stored explicitly.
    # A round-off that silently adjusts the total is an untracked discount, and
    # the margin report would never see it.
    round_off: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

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

    # Discount quoted the way the counter negotiates it — in ratti, against a
    # base of 96. Six ratti bills 90/96 of the gold weight. It reduces billable
    # metal rather than the money, which is a different lever from
    # `line_discount` and has to be visible as its own giveaway in reporting.
    discount_ratti: Mapped[float] = mapped_column(Numeric(8, 3), default=0, nullable=False)
    ratti_base: Mapped[int] = mapped_column(Integer, default=96, nullable=False)

    # Wastage charged to the customer: the shop bills for more gold than the
    # piece contains. This is revenue and one of the three margin levers in the
    # trade, alongside the rate spread and making charges — so it is stored as
    # its own figure rather than folded into the weight, or the profit report
    # cannot show where the money actually came from. Quoted either way round;
    # the counter picks whichever the customer is arguing in.
    sale_wastage_pct: Mapped[float] = mapped_column(Numeric(6, 3), default=0, nullable=False)
    sale_wastage_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
