from decimal import Decimal
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.currency import Currency
from app.models.invoice import InvoiceStatus, SaleType
from app.schemas.common import TimestampedRead


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


class InvoiceItemRead(TimestampedRead, InvoiceItemCreate):
    invoice_id: int
    gold_amount: Decimal
    stone_amount: Decimal
    line_total: Decimal


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
