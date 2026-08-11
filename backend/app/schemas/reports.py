from datetime import date, datetime
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
    # Which department the metal was lost in. Before the routing engine this
    # could only ever say "karigar" or "polish"; it now carries the real stage.
    role: str
    jobs: int
    total_loss_g: Decimal
    # 'routing' for job legs, 'legacy' for rows still coming off the retired
    # manufacturing_jobs table. Kept visible so a shop mid-migration can see
    # which half of its history a figure came from.
    source: str = "routing"


class WorkerDepartmentLossRow(BaseModel):
    """One worker's metal in one department — the grain the shop argues at."""

    worker_id: int | None
    worker_name: str
    department_id: int | None
    department: str | None
    legs: int
    gold_issued_g: Decimal
    gold_received_g: Decimal
    wastage_allowed_g: Decimal
    wastage_actual_g: Decimal
    wastage_excess_g: Decimal
    wastage_pct_of_issued: Decimal


class LossReport(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    overall_karigar_loss_g: Decimal
    overall_polish_loss_g: Decimal
    by_vendor: list[VendorLossRow]

    # --- the routing-engine view, added when job_legs replaced the old model ---
    legs: int = 0
    overall_issued_g: Decimal = Decimal("0")
    overall_received_g: Decimal = Decimal("0")
    overall_allowed_g: Decimal = Decimal("0")
    overall_actual_loss_g: Decimal = Decimal("0")
    overall_excess_g: Decimal = Decimal("0")
    by_worker_department: list[WorkerDepartmentLossRow] = []
    legacy_loss_g: Decimal = Decimal("0")
    notes: list[str] = []


# ---------------------------------------------------------------------------
# Margin decomposition
# ---------------------------------------------------------------------------
class MarginBreakdown(BaseModel):
    """
    One period's profit, split by the lever that produced it.

    Mirrors `app.services.margin.MarginBreakdown` field for field, plus the
    invoice-level figures that decomposition does not see (it works a line at a
    time) and the period label.
    """

    # "2026-08" on a monthly row, null on the overall total.
    period: str | None = None

    revenue: Decimal
    # Sales tax collected. Held out of `revenue` because it is the government's
    # money passing through, and counting it as income would inflate every
    # margin on this report by the tax rate.
    tax: Decimal
    cost_of_goods: Decimal
    gross_profit: Decimal
    margin_pct: Decimal | None = None

    # --- what earned it ---
    rate_spread: Decimal
    wastage_charged: Decimal
    making_charges: Decimal
    stone_margin: Decimal

    # --- what gave it away (held positive, subtracted) ---
    ratti_discount: Decimal
    cash_discount: Decimal
    round_off: Decimal
    making_cost: Decimal

    # Metal billed with no matching recorded cost. Reads as profit only because
    # nothing was ever booked against it — bookkeeping owed, not margin earned.
    uncosted_metal: Decimal = Decimal("0")
    unattributed: Decimal
    invoices: int
    lines: int
    notes: list[str] = []


class MarginReport(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    currency: Currency
    total: MarginBreakdown
    by_month: list[MarginBreakdown]
    # Invoices in the window struck in another currency, left out rather than
    # summed into a total that would mean nothing.
    excluded_invoices: int = 0


# ---------------------------------------------------------------------------
# Worker performance
# ---------------------------------------------------------------------------
class WorkerPerformanceRow(BaseModel):
    worker_id: int | None
    worker_name: str
    department: str | None
    legs: int
    gold_issued_g: Decimal
    gold_received_g: Decimal
    wastage_allowed_g: Decimal
    wastage_actual_g: Decimal
    wastage_excess_g: Decimal
    wastage_pct_of_issued: Decimal
    labour_earned: Decimal
    # Read off the ledger as it stands today, not windowed — "what is he
    # holding right now" is a position, not a period figure.
    #
    # Named `_fine_g` deliberately. Every weight above comes off the job legs
    # as the shop weighed it; this one comes off the ledger, which holds fine
    # (24k-equivalent) grams. They are different units sitting on one row, and
    # a reader who adds them gets a number that is wrong in the shop's favour.
    gold_balance_fine_g: Decimal
    cash_payable: Decimal


class WorkerPerformanceReport(BaseModel):
    days: int
    period_from: date
    period_to: date
    rows: list[WorkerPerformanceRow]
    legs: int
    gold_issued_g: Decimal
    wastage_actual_g: Decimal
    wastage_excess_g: Decimal
    wastage_pct_of_issued: Decimal
    labour_earned: Decimal


# ---------------------------------------------------------------------------
# Item performance
# ---------------------------------------------------------------------------
class ItemPerformanceRow(BaseModel):
    item_id: int
    item_name: str
    abbreviation: str
    designs_started: int
    designs_stocked: int
    # Fine (24k-equivalent) grams embodied in the pieces stocked in the window.
    gold_consumed_g: Decimal
    pieces_sold: int
    revenue: Decimal
    cost_of_goods: Decimal
    gross_margin: Decimal
    margin_pct: Decimal | None = None


class ItemPerformanceReport(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    rows: list[ItemPerformanceRow]
    designs_started: int
    designs_stocked: int
    pieces_sold: int
    revenue: Decimal
    gross_margin: Decimal


# ---------------------------------------------------------------------------
# Department throughput
# ---------------------------------------------------------------------------
class DepartmentThroughputRow(BaseModel):
    department_id: int
    department: str
    code: str | None
    legs_completed: int
    # From the department's side of the counter: `in` is metal handed to it,
    # `out` is metal it handed back.
    gold_in_g: Decimal
    gold_out_g: Decimal
    wastage_allowed_g: Decimal
    wastage_actual_g: Decimal
    wastage_excess_g: Decimal
    wastage_pct_of_issued: Decimal
    labour_cost: Decimal
    avg_days_held: Decimal | None = None


class DepartmentThroughputReport(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    rows: list[DepartmentThroughputRow]
    legs_completed: int
    gold_in_g: Decimal
    gold_out_g: Decimal
    wastage_actual_g: Decimal
    wastage_excess_g: Decimal
    labour_cost: Decimal


# ---------------------------------------------------------------------------
# Gold movement
# ---------------------------------------------------------------------------
class GoldMovementReport(BaseModel):
    """Every figure in fine (24k-equivalent) grams — the ledger's own unit."""

    date_from: date | None = None
    date_to: date | None = None

    # --- in ---
    bought_old_gold_g: Decimal
    bought_old_gold_purchases: int
    received_from_workers_g: Decimal

    # --- out ---
    issued_to_workers_g: Decimal
    # Burnt off on the bench: issued minus returned, across legs received in
    # the window.
    wastage_g: Decimal
    excess_charged_to_workers_g: Decimal
    # Metal that stopped being loose stock and became a sellable piece.
    consumed_into_pieces_g: Decimal
    sold_g: Decimal

    # --- where it stands at date_to ---
    closing_gold_in_hand_g: Decimal
    closing_with_workers_g: Decimal
    closing_finished_goods_g: Decimal
    closing_total_g: Decimal
    notes: list[str] = []


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
