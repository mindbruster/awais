from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.currency import Currency
from app.models.invoice import SaleType
from app.models.inventory import InventoryType


class StockBucket(BaseModel):
    type: InventoryType
    items: int
    total_quantity: int
    total_weight_g: Decimal
    total_weight_ct: Decimal


class StockReport(BaseModel):
    by_type: list[StockBucket]
    items_count: int


class SalesBucket(BaseModel):
    currency: Currency
    sale_type: SaleType
    invoice_count: int
    subtotal: Decimal
    discount: Decimal
    total: Decimal


class CurrencyTotal(BaseModel):
    currency: Currency
    invoice_count: int
    total: Decimal


class SalesReport(BaseModel):
    range_from: datetime | None = None
    range_to: datetime | None = None
    by_sale_type: list[SalesBucket]
    by_currency: list[CurrencyTotal]
    invoice_count: int


class VendorLossRow(BaseModel):
    vendor_id: int | None
    vendor_name: str | None
    role: str
    jobs: int
    total_loss_g: Decimal


class LossReport(BaseModel):
    overall_karigar_loss_g: Decimal
    overall_polish_loss_g: Decimal
    by_vendor: list[VendorLossRow]


class ProfitRow(BaseModel):
    invoice_id: int
    invoice_no: str
    currency: Currency
    issued_at: datetime | None
    revenue: Decimal
    making_cost: Decimal
    profit: Decimal


class ProfitCurrencyTotal(BaseModel):
    currency: Currency
    revenue: Decimal
    making_cost: Decimal
    profit: Decimal


class ProfitReport(BaseModel):
    range_from: datetime | None = None
    range_to: datetime | None = None
    rows: list[ProfitRow]
    by_currency: list[ProfitCurrencyTotal]
