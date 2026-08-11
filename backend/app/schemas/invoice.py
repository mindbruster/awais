from decimal import Decimal
from datetime import datetime

from pydantic import BaseModel, Field, computed_field, model_validator

from app.models.currency import Currency
from app.models.invoice import InvoiceStatus, SaleType
from app.schemas.common import TimestampedRead
from app.services.pricing import DEFAULT_RATTI_BASE, apply_ratti_discount


class InvoiceItemCreate(BaseModel):
    product_id: int | None = None
    description: str = Field(min_length=1, max_length=255)
    quantity: int = Field(default=1, ge=1)
    gold_weight_g: Decimal = Field(default=Decimal("0"), ge=0)
    gold_purity: int | None = Field(default=None, ge=1, le=24)
    gold_rate_per_g: Decimal = Field(default=Decimal("0"), ge=0)
    stone_weight_ct: Decimal = Field(default=Decimal("0"), ge=0)
    stone_rate_per_ct: Decimal = Field(default=Decimal("0"), ge=0)
    labor_amount: Decimal = Field(default=Decimal("0"), ge=0)
    line_discount: Decimal = Field(default=Decimal("0"), ge=0)
    # Ratti discount reduces the billable *gold weight*, not the money — a
    # separate lever from line_discount above, and it stays on the line so the
    # giveaway can be reported on its own.
    discount_ratti: Decimal = Field(default=Decimal("0"), ge=0)
    ratti_base: int = Field(default=DEFAULT_RATTI_BASE, ge=1)

    @model_validator(mode="after")
    def ratti_within_base(self) -> "InvoiceItemCreate":
        # At the full base the gold is free; beyond it the customer would be
        # credited for metal they are walking out with. Refuse rather than let
        # pricing.py's clamp silently swallow a typo'd figure.
        if self.discount_ratti > self.ratti_base:
            raise ValueError(
                f"discount_ratti ({self.discount_ratti}) cannot exceed "
                f"ratti_base ({self.ratti_base}) — the whole weight would be free."
            )
        return self


class InvoiceItemRead(TimestampedRead, InvoiceItemCreate):
    invoice_id: int
    gold_amount: Decimal
    stone_amount: Decimal
    line_total: Decimal

    @computed_field  # type: ignore[prop-decorator]
    @property
    def billable_gold_weight_g(self) -> Decimal:
        """
        The weight the customer is actually charged for after the ratti
        discount. Derived here from the one implementation in pricing.py so no
        client has to re-derive the formula (and drift from it).
        """
        return apply_ratti_discount(
            self.gold_weight_g, self.discount_ratti, self.ratti_base
        )


class InvoiceCreate(BaseModel):
    customer_id: int
    sale_type: SaleType = SaleType.normal
    currency: Currency = Currency.PKR
    gold_rate_per_g: Decimal = Field(default=Decimal("0"), ge=0)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
    discount_weight_g: Decimal = Field(default=Decimal("0"), ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str | None = None
    items: list[InvoiceItemCreate] = Field(default_factory=list)


class InvoiceRead(TimestampedRead):
    invoice_no: str
    sale_type: SaleType
    status: InvoiceStatus
    customer_id: int
    currency: Currency
    gold_rate_per_g: Decimal
    subtotal: Decimal
    discount_amount: Decimal
    discount_weight_g: Decimal
    tax_amount: Decimal
    total: Decimal
    issued_at: datetime | None = None
    paid_at: datetime | None = None
    notes: str | None = None
    items: list[InvoiceItemRead] = Field(default_factory=list)
