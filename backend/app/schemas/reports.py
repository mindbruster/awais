from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.currency import Currency
from app.models.invoice import SaleType
from app.models.inventory import InventoryType
from app.models.journal import PartyType
from app.models.metal import Metal


class StockBucket(BaseModel):
    type: InventoryType
    items: int
    total_quantity: int
    total_weight_g: Decimal
    total_weight_ct: Decimal


class MetalPosition(BaseModel):
    """One metal on hand, as weighed and as pure, with what it is worth."""

    metal: Metal
    weight_g: Decimal
    # What the metal is worth is a function of its pure content, not its scale
    # reading: valuing 1,240g of 22k at the 24k rate over-states it by nine
    # percent, which on a shop's whole holding is real money.
    fine_weight_g: Decimal
    # Null when no rate is on record for this metal today. The value is then
    # null too rather than zero — a stock page that shows a kilo of silver as
    # worthless is worse than one that says it does not know the rate.
    rate_per_fine_g: Decimal | None = None
    value: Decimal | None = None


class StockPositionReport(BaseModel):
    """
    Everything the shop holds, in the unit it is held in.

    Gold and silver are listed apart and never summed as "metal": they differ a
    hundredfold in value, and the only place they legitimately meet is
    `total_value`, where both have become money.
    """

    as_of: date
    metals: list[MetalPosition]
    stone_weight_ct: Decimal
    # Held at cost — the parcels the stones were bought in, less what has been
    # drawn out of them. There is no market rate for a grade of diamond the way
    # there is for metal.
    stone_value: Decimal
    broken_stone_weight_ct: Decimal
    finished_pieces: int
    finished_value: Decimal
    total_value: Decimal
    # Metals the shop is holding but could not value today. Named so the total
    # can be read as "everything except these".
    unpriced_metals: list[str] = []


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
    # Which metal every gram below is. Gold and silver cannot share a total, so
    # a figure that does not say which it is cannot be read at all.
    metal: Metal = Metal.gold
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
    # The other side of the same coin: metal the shop owes its workers, which
    # arises when a maker on ratti did not take the whole allowance he was
    # entitled to. Reported apart from `overall_excess_g` because netting a
    # debt against a credit gives a number that is neither, and one generous
    # settlement would otherwise cancel a real shortfall somewhere else.
    overall_owed_to_workers_g: Decimal = Decimal("0")
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


# ---------------------------------------------------------------------------
# Customer performance
# ---------------------------------------------------------------------------
class CustomerPerformanceRow(BaseModel):
    """One customer's trading, in one currency."""

    customer_id: int
    customer_name: str
    currency: Currency
    invoices: int
    # Net of tax. Sales tax is the government's money passing through, and
    # counting it as revenue would inflate every margin here by the tax rate.
    revenue: Decimal
    cost_of_goods: Decimal
    gross_margin: Decimal
    margin_pct: Decimal | None = None
    # What they actually took away, in the units the shop thinks in.
    gold_weight_g: Decimal
    stone_weight_ct: Decimal
    # Lines billed with no product behind them contribute revenue and no cost,
    # which overstates the margin. Surfaced rather than buried: a customer
    # bought entirely on typed-in lines has a margin figure nobody should trust.
    uncosted_lines: int = 0
    last_purchase_at: datetime | None = None


class CustomerPerformanceReport(BaseModel):
    """
    Customers ranked by what they spent, carrying what the shop kept.

    Both figures are on every row on purpose. Spend is the obvious ranking and
    it flatters the customer who buys heavy metal at a thin margin; margin is
    what the shop lives on. They routinely disagree about who the best customer
    is, and until now nothing in the system could say so.
    """

    date_from: date | None = None
    date_to: date | None = None
    rows: list[CustomerPerformanceRow] = []
    customers: int = 0
    revenue: Decimal = Decimal("0")
    gross_margin: Decimal = Decimal("0")


# ---------------------------------------------------------------------------
# Profit split — the metal business and the stone business
# ---------------------------------------------------------------------------
class ProfitSplitLine(BaseModel):
    """One of the shop's revenue streams, with what it cost to earn."""

    # 'gold' | 'stones' | 'making'
    stream: str
    revenue: Decimal
    cost: Decimal
    gross_margin: Decimal
    margin_pct: Decimal | None = None


class ProfitSplitReport(BaseModel):
    """
    Two businesses under one roof, reported apart.

    Metal is bought and sold at a rate that moves daily and turns over weekly;
    stones are bought in parcels at a negotiated price and sit for months. A
    single gross margin averages the two and describes neither. Making is a
    third column rather than folded into metal: it moves with neither rate, and
    for a wholesaler it is most of the margin.
    """

    date_from: date | None = None
    date_to: date | None = None
    currency: Currency
    streams: list[ProfitSplitLine] = []
    revenue: Decimal = Decimal("0")
    cost: Decimal = Decimal("0")
    gross_margin: Decimal = Decimal("0")
    lines: int = 0
    # Lines whose cost could not be split between metal and stones — no product
    # behind them, or a piece with no locked gold rate. Surfaced rather than
    # buried: a split built mostly from these is not a split.
    unsplit_lines: int = 0


# --------------------------------------------------------------------------
# Material outside the company
# --------------------------------------------------------------------------
class MaterialOutsideRow(BaseModel):
    """
    One party, and everything of the shop's they are holding.

    Three units side by side and never added. A karigar holding 400 fine grams
    of gold, four kilos of silver and 2 carats owes three different things,
    settled three different ways, and a single "material" figure covering them
    would be a number in no unit at all.

    Positive means the party holds it. The accounts these come from are assets
    of the shop sitting in someone else's hands, so a negative would mean the
    shop is holding *their* metal — real during a settlement, and shown rather
    than clamped.
    """

    party_type: PartyType
    party_id: int
    party_name: str | None = None
    # What kind of work they do — 'Maker', 'Setter', 'Polish'. Read from the
    # worker's department so the list can be scanned by trade.
    department: str | None = None

    gold_g: Decimal = Decimal("0")
    silver_g: Decimal = Decimal("0")
    stone_ct: Decimal = Decimal("0")

    # Money owed to them for labour, alongside the material. A worker's account
    # has both halves and reading one without the other has led to a settlement
    # that paid cash while forgetting 400 grams.
    cash_balance: Decimal = Decimal("0")

    # Open legs, and the oldest one still out. Age is the thing that turns a
    # normal balance into a problem: 300g issued yesterday is business as usual
    # and the same 300g issued in March is a conversation.
    open_legs: int = 0
    oldest_issue_date: date | None = None
    days_out: int | None = None
    # An agreed return date that has passed, on any leg.
    overdue_legs: int = 0


class MaterialOutsideReport(BaseModel):
    as_of: date
    rows: list[MaterialOutsideRow] = []
    total_gold_g: Decimal = Decimal("0")
    total_silver_g: Decimal = Decimal("0")
    total_stone_ct: Decimal = Decimal("0")
    parties: int = 0
