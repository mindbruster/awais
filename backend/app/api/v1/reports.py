"""
The reports the shop actually runs on.

Two rules hold across everything here. Balances come off the journal, never off
a stored column — a cached balance can drift and cannot explain itself. And
gold is reported in *fine* (24k-equivalent) grams wherever it touches the
ledger, because 10g of 22k and 10g of 24k are not the same asset and summing
them gives a number that is wrong in the shop's favour.

Every endpoint takes `?format=csv`. That is not a nicety: the shop reconciles
in Excel, and a report it cannot export is a report it will not use.
"""
import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import joinedload, selectinload

from app.api.deps import DbSession, require_perm
from app.models.account import SystemAccount
from app.models.currency import Currency
from app.models.department import Department
from app.models.design import Design, JobLeg, LegStatus
from app.models.inventory import InventoryItem
from app.models.invoice import Invoice, InvoiceItem, InvoiceStatus
from app.models.item import Item
from app.models.journal import Commodity, PartyType
from app.models.manufacturing import JobStage, ManufacturingJob
from app.models.product import Product
from app.models.purchase import OldGoldPurchase
from app.models.vendor import Vendor, VendorType
from app.schemas.reports import (
    CurrencyTotal,
    DepartmentThroughputReport,
    DepartmentThroughputRow,
    GoldMovementReport,
    ItemPerformanceReport,
    ItemPerformanceRow,
    LossReport,
    MarginBreakdown,
    MarginReport,
    ProfitCurrencyTotal,
    ProfitReport,
    ProfitRow,
    SalesBucket,
    SalesReport,
    StockBucket,
    StockReport,
    VendorLossRow,
    WorkerDepartmentLossRow,
    WorkerPerformanceReport,
    WorkerPerformanceRow,
)
from app.services import ledger, margin

router = APIRouter()

_ZERO = Decimal("0")
_PKR = Decimal("0.01")
_G = Decimal("0.0001")
_PCT = Decimal("0.01")

Format = Literal["json", "csv"]


def _d(v) -> Decimal:
    return Decimal(str(v if v is not None else 0))


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    if not whole:
        return _ZERO
    return (part / whole * Decimal("100")).quantize(_PCT)


def _window(date_from: date | None, date_to: date | None) -> tuple[datetime | None, datetime | None]:
    """
    Turn two dates into a half-open-feeling but inclusive instant range.

    `date_to` is taken to the last microsecond of that day so "to 31 August"
    includes the 31st — a report that silently drops the closing day of the
    month is worse than no report.
    """
    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc) if date_from else None
    end = datetime.combine(date_to, time.max, tzinfo=timezone.utc) if date_to else None
    return start, end


def _fine_sql(weight, purity):
    """Fine-gram expression: as-weighed grams scaled by purity, missing purity
    read as pure — which is how raw bullion is entered."""
    return weight * func.coalesce(purity, 24) / Decimal("24")


def _stamp(date_from: date | None, date_to: date | None) -> str:
    return f"{date_from or 'open'}_{date_to or date.today()}"


def _csv_response(
    filename: str, header: Sequence[str], rows: Iterable[Sequence[object]]
) -> StreamingResponse:
    """
    Stream rows as CSV.

    A byte-order mark leads the file because Excel on Windows otherwise reads
    UTF-8 as the local codepage and mangles every worker's name — which is the
    first thing the owner would notice and the last thing he'd report.
    """

    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        yield "﻿"
        writer.writerow(header)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        for row in rows:
            writer.writerow(["" if v is None else str(v) for v in row])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------
@router.get("/stock", response_model=StockReport, dependencies=[Depends(require_perm("report:stock"))])
async def stock_report(db: DbSession, format: Format = Query(default="json")):
    stmt = select(
        InventoryItem.type,
        func.count(InventoryItem.id),
        func.coalesce(func.sum(InventoryItem.quantity), 0),
        func.coalesce(func.sum(InventoryItem.weight_g), 0),
        func.coalesce(func.sum(InventoryItem.weight_ct), 0),
    ).group_by(InventoryItem.type)

    rows = (await db.execute(stmt)).all()
    buckets = [
        StockBucket(
            type=t,
            items=n,
            total_quantity=int(q),
            total_weight_g=Decimal(str(wg)),
            total_weight_ct=Decimal(str(wc)),
        )
        for (t, n, q, wg, wc) in rows
    ]
    total_count = (
        await db.execute(select(func.count(InventoryItem.id)))
    ).scalar_one()

    if format == "csv":
        return _csv_response(
            f"stock_{date.today()}.csv",
            ["type", "items", "total_quantity", "total_weight_g", "total_weight_ct"],
            [
                [b.type.value, b.items, b.total_quantity, b.total_weight_g, b.total_weight_ct]
                for b in buckets
            ],
        )
    return StockReport(by_type=buckets, items_count=total_count)


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------
@router.get("/sales", response_model=SalesReport, dependencies=[Depends(require_perm("report:sales"))])
async def sales_report(
    db: DbSession,
    range_from: date | None = Query(default=None),
    range_to: date | None = Query(default=None),
    format: Format = Query(default="json"),
):
    """
    Aggregate issued/paid invoices by (currency, sale_type) within an optional
    date range.

    Dates, not timestamps, and run through `_window` like every other report
    here. Taking a raw datetime meant `range_to=2026-08-31` resolved to
    midnight and silently dropped the whole of the 31st — so the same requested
    month gave a different answer depending on which report you opened.
    """
    start, end = _window(range_from, range_to)
    base = (
        select(
            Invoice.currency,
            Invoice.sale_type,
            func.count(Invoice.id),
            func.coalesce(func.sum(Invoice.subtotal), 0),
            func.coalesce(func.sum(Invoice.discount_amount), 0),
            func.coalesce(func.sum(Invoice.total), 0),
        )
        .where(Invoice.status.in_((InvoiceStatus.issued, InvoiceStatus.paid)))
    )
    if start is not None:
        base = base.where(Invoice.issued_at >= start)
    if end is not None:
        base = base.where(Invoice.issued_at <= end)
    base = base.group_by(Invoice.currency, Invoice.sale_type).order_by(
        Invoice.currency, Invoice.sale_type
    )

    rows = (await db.execute(base)).all()
    buckets = [
        SalesBucket(
            currency=cur,
            sale_type=st,
            invoice_count=n,
            subtotal=Decimal(str(s)),
            discount=Decimal(str(d)),
            total=Decimal(str(t)),
        )
        for (cur, st, n, s, d, t) in rows
    ]

    # Per-currency rollup
    by_cur: dict[str, dict] = {}
    for b in buckets:
        agg = by_cur.setdefault(b.currency.value, {"n": 0, "total": Decimal("0")})
        agg["n"] += b.invoice_count
        agg["total"] += b.total

    if format == "csv":
        return _csv_response(
            f"sales_{date.today()}.csv",
            ["currency", "sale_type", "invoices", "subtotal", "discount", "total"],
            [
                [b.currency.value, b.sale_type.value, b.invoice_count, b.subtotal, b.discount, b.total]
                for b in buckets
            ],
        )

    return SalesReport(
        range_from=range_from,
        range_to=range_to,
        by_sale_type=buckets,
        by_currency=[
            CurrencyTotal(currency=k, invoice_count=v["n"], total=v["total"])
            for k, v in sorted(by_cur.items())
        ],
        invoice_count=sum(b.invoice_count for b in buckets),
    )


# ---------------------------------------------------------------------------
# Manufacturing loss
# ---------------------------------------------------------------------------
@router.get(
    "/manufacturing-loss",
    response_model=LossReport,
    dependencies=[Depends(require_perm("report:loss"))],
)
async def manufacturing_loss_report(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    format: Format = Query(default="json"),
):
    """
    Metal lost on the workshop floor, per worker and per department.

    This used to read `manufacturing_jobs`, which the routing engine replaced.
    That table stopped being written the moment work started flowing through
    designs and job legs, so the report quietly went to near-zero while the
    shop was still losing metal — the worst failure mode a report has, because
    nobody investigates a number that looks fine.

    It now reads `job_legs`, grouped by worker *and* department. The department
    grain is the point: the old model could only say "karigar" or "polish", so
    a worker who cast well and set badly showed up as one blended figure.

    The response shape is backward compatible. `overall_karigar_loss_g` and
    `overall_polish_loss_g` still exist and are still the sum of what karigars
    and polishers lost — now resolved through the worker's type rather than
    through two columns on a job — and `by_vendor` still carries one row per
    (worker, role), where `role` is the department the metal was lost in.

    Legs still open, and legs that were cancelled, are excluded: metal that has
    not come back is not a loss, it is an outstanding balance, and that is what
    the worker's gold account is for. Rows off the retired table are still
    included and tagged `source: legacy`, so a shop that ran both models does
    not lose the first half of its history.
    """
    start, end = _window(date_from, date_to)

    leg_q = (
        select(
            JobLeg.worker_id,
            Vendor.name,
            Vendor.type,
            JobLeg.department_id,
            Department.name,
            func.count(JobLeg.id),
            func.coalesce(func.sum(JobLeg.gold_issued_g), 0),
            func.coalesce(func.sum(JobLeg.gold_received_g), 0),
            func.coalesce(func.sum(JobLeg.wastage_allowed_g), 0),
            func.coalesce(func.sum(JobLeg.wastage_actual_g), 0),
            func.coalesce(func.sum(JobLeg.wastage_excess_g), 0),
        )
        .join(Department, Department.id == JobLeg.department_id)
        .join(Vendor, Vendor.id == JobLeg.worker_id, isouter=True)
        .where(JobLeg.status == LegStatus.received, JobLeg.received_at.is_not(None))
        .group_by(JobLeg.worker_id, Vendor.name, Vendor.type, JobLeg.department_id, Department.name)
    )
    if start is not None:
        leg_q = leg_q.where(JobLeg.received_at >= start)
    if end is not None:
        leg_q = leg_q.where(JobLeg.received_at <= end)

    detail: list[WorkerDepartmentLossRow] = []
    compat: list[VendorLossRow] = []
    karigar_loss = polish_loss = _ZERO
    legs = 0
    t_issued = t_received = t_allowed = t_actual = t_excess = _ZERO

    for (
        worker_id,
        worker_name,
        worker_type,
        dept_id,
        dept_name,
        n,
        issued,
        received,
        allowed,
        actual,
        excess,
    ) in (await db.execute(leg_q)).all():
        issued_d, actual_d = _d(issued), _d(actual)
        detail.append(
            WorkerDepartmentLossRow(
                worker_id=worker_id,
                worker_name=worker_name or "Unassigned",
                department_id=dept_id,
                department=dept_name,
                legs=n,
                gold_issued_g=issued_d.quantize(_G),
                gold_received_g=_d(received).quantize(_G),
                wastage_allowed_g=_d(allowed).quantize(_G),
                wastage_actual_g=actual_d.quantize(_G),
                wastage_excess_g=_d(excess).quantize(_G),
                wastage_pct_of_issued=_pct(actual_d, issued_d),
            )
        )
        compat.append(
            VendorLossRow(
                vendor_id=worker_id,
                vendor_name=worker_name,
                role=dept_name,
                jobs=n,
                total_loss_g=actual_d.quantize(_G),
                source="routing",
            )
        )
        if worker_type is VendorType.karigar:
            karigar_loss += actual_d
        elif worker_type is VendorType.polish:
            polish_loss += actual_d

        legs += n
        t_issued += issued_d
        t_received += _d(received)
        t_allowed += _d(allowed)
        t_actual += actual_d
        t_excess += _d(excess)

    # --- what the retired table still holds ---
    legacy_total = _ZERO
    for column, role in (
        (ManufacturingJob.karigar_id, VendorType.karigar),
        (ManufacturingJob.polish_vendor_id, VendorType.polish),
    ):
        loss_col = (
            ManufacturingJob.karigar_loss_g
            if role is VendorType.karigar
            else ManufacturingJob.polish_loss_g
        )
        q = (
            select(
                column,
                Vendor.name,
                func.count(ManufacturingJob.id),
                func.coalesce(func.sum(loss_col), 0),
            )
            .join(Vendor, Vendor.id == column, isouter=True)
            .where(
                column.isnot(None),
                # A cancelled job's metal was credited back to stock, and a
                # draft one never left it. Counting either as loss reports
                # metal the shop still has.
                ManufacturingJob.stage.notin_(
                    (JobStage.cancelled, JobStage.draft)
                ),
            )
            .group_by(column, Vendor.name)
        )
        # The legacy table has no per-leg timestamp to filter on, only the row's
        # own created_at. Windowing on that is approximate but it is far better
        # than the alternative: without it, every windowed request silently adds
        # the shop's entire all-time legacy loss to the period being asked
        # about, so a one-week report reads like a year.
        if start is not None:
            q = q.where(ManufacturingJob.created_at >= start)
        if end is not None:
            q = q.where(ManufacturingJob.created_at <= end)
        for vid, vname, n, loss in (await db.execute(q)).all():
            loss_d = _d(loss)
            if loss_d == 0:
                continue
            compat.append(
                VendorLossRow(
                    vendor_id=vid,
                    vendor_name=vname,
                    role=role.value,
                    jobs=n,
                    total_loss_g=loss_d.quantize(_G),
                    source="legacy",
                )
            )
            legacy_total += loss_d
            if role is VendorType.karigar:
                karigar_loss += loss_d
            else:
                polish_loss += loss_d

    detail.sort(key=lambda r: -r.wastage_excess_g)
    compat.sort(key=lambda r: -r.total_loss_g)

    notes: list[str] = []
    if legacy_total:
        notes.append(
            f"{legacy_total.quantize(_G)}g of this comes from the retired manufacturing_jobs "
            "table and is tagged source=legacy. Nothing has been written there since the "
            "routing engine took over; it is history, not current production."
        )
    if t_excess:
        notes.append(
            f"{t_excess.quantize(_G)}g ran past what the workers were allowed and has been "
            "charged back to their gold accounts."
        )

    if format == "csv":
        return _csv_response(
            f"manufacturing-loss_{_stamp(date_from, date_to)}.csv",
            [
                "worker", "department", "legs", "gold_issued_g", "gold_received_g",
                "wastage_allowed_g", "wastage_actual_g", "wastage_excess_g",
                "wastage_pct_of_issued",
            ],
            [
                [
                    r.worker_name, r.department, r.legs, r.gold_issued_g, r.gold_received_g,
                    r.wastage_allowed_g, r.wastage_actual_g, r.wastage_excess_g,
                    r.wastage_pct_of_issued,
                ]
                for r in detail
            ],
        )

    return LossReport(
        date_from=date_from,
        date_to=date_to,
        overall_karigar_loss_g=karigar_loss.quantize(_G),
        overall_polish_loss_g=polish_loss.quantize(_G),
        by_vendor=compat,
        legs=legs,
        overall_issued_g=t_issued.quantize(_G),
        overall_received_g=t_received.quantize(_G),
        overall_allowed_g=t_allowed.quantize(_G),
        overall_actual_loss_g=t_actual.quantize(_G),
        overall_excess_g=t_excess.quantize(_G),
        by_worker_department=detail,
        legacy_loss_g=legacy_total.quantize(_G),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Profit (per invoice)
# ---------------------------------------------------------------------------
@router.get(
    "/profit",
    response_model=ProfitReport,
    dependencies=[Depends(require_perm("report:profit"))],
)
async def profit_report(
    db: DbSession,
    range_from: date | None = Query(default=None),
    range_to: date | None = Query(default=None),
    format: Format = Query(default="json"),
):
    """
    Per-invoice profit = revenue − cost of goods sold, excluding draft and void
    invoices.

    COGS is the full cost of the piece: making (`product.total_cost` — karigar,
    stone fixing, polish and other) *plus* material (`product.material_cost` —
    the capitalised gold and stones), weighted by line quantity. Both are
    snapshots taken when the job completed, so this figure is stable over time.

    Inventory and stock movements track the same material in *weight* terms;
    counting it here in *value* terms is not a double count, and omitting it
    would overstate profit by the entire value of the gold.

    This is the per-document view. `/reports/margin` takes the same sales apart
    by the lever that produced the money, which is the question an owner asks
    second and cares about more.
    """
    # Cost of goods sold per invoice = labor (product.total_cost) + material
    # (product.material_cost) summed across line items, weighted by quantity.
    making_cost_subq = (
        select(
            InvoiceItem.invoice_id.label("invoice_id"),
            func.coalesce(
                func.sum(
                    case(
                        (Product.id.is_(None), Decimal("0")),
                        else_=(Product.total_cost + Product.material_cost) * InvoiceItem.quantity,
                    )
                ),
                0,
            ).label("making_cost"),
        )
        .join(Product, Product.id == InvoiceItem.product_id, isouter=True)
        .group_by(InvoiceItem.invoice_id)
        .subquery()
    )

    stmt = (
        select(
            Invoice.id,
            Invoice.invoice_no,
            Invoice.currency,
            Invoice.issued_at,
            Invoice.total,
            Invoice.tax_amount,
            func.coalesce(making_cost_subq.c.making_cost, 0),
        )
        .join(making_cost_subq, making_cost_subq.c.invoice_id == Invoice.id, isouter=True)
        .where(Invoice.status.in_((InvoiceStatus.issued, InvoiceStatus.paid)))
        .order_by(Invoice.issued_at.desc().nullslast())
    )
    if range_from is not None:
        stmt = stmt.where(Invoice.issued_at >= _window(range_from, None)[0])
    if range_to is not None:
        stmt = stmt.where(Invoice.issued_at <= _window(None, range_to)[1])

    rows: list[ProfitRow] = []
    by_cur: dict[str, dict] = {}
    for inv_id, inv_no, currency, issued_at, total, tax, mc in (await db.execute(stmt)).all():
        # Tax is collected on the state's behalf and paid straight back out. It
        # is not the shop's money and counting it inflates profit by exactly the
        # tax — which is also what made this disagree with /reports/margin.
        revenue = (Decimal(str(total)) - Decimal(str(tax or 0))).quantize(Decimal("0.01"))
        cost = Decimal(str(mc))
        profit = (revenue - cost).quantize(Decimal("0.01"))
        rows.append(
            ProfitRow(
                invoice_id=inv_id,
                invoice_no=inv_no,
                currency=currency,
                issued_at=issued_at,
                revenue=revenue,
                making_cost=cost,
                profit=profit,
            )
        )
        agg = by_cur.setdefault(
            currency.value,
            {"revenue": Decimal("0"), "cost": Decimal("0"), "profit": Decimal("0")},
        )
        agg["revenue"] += revenue
        agg["cost"] += cost
        agg["profit"] += profit

    if format == "csv":
        return _csv_response(
            f"profit_{date.today()}.csv",
            ["invoice_no", "currency", "issued_at", "revenue", "cost_of_goods", "profit"],
            [
                [
                    r.invoice_no, r.currency.value,
                    r.issued_at.isoformat() if r.issued_at else "",
                    r.revenue, r.making_cost, r.profit,
                ]
                for r in rows
            ],
        )

    return ProfitReport(
        range_from=range_from,
        range_to=range_to,
        rows=rows,
        by_currency=[
            ProfitCurrencyTotal(
                currency=k,
                revenue=v["revenue"].quantize(Decimal("0.01")),
                making_cost=v["cost"].quantize(Decimal("0.01")),
                profit=v["profit"].quantize(Decimal("0.01")),
            )
            for k, v in sorted(by_cur.items())
        ],
    )


# ---------------------------------------------------------------------------
# Margin — the headline report
# ---------------------------------------------------------------------------
def _to_schema(period: str | None, b: margin.MarginBreakdown, tax: Decimal) -> MarginBreakdown:
    return MarginBreakdown(
        period=period,
        revenue=b.revenue.quantize(_PKR),
        tax=tax.quantize(_PKR),
        cost_of_goods=b.cost_of_goods.quantize(_PKR),
        gross_profit=b.gross_profit.quantize(_PKR),
        margin_pct=_pct(b.gross_profit, b.revenue) if b.revenue else None,
        rate_spread=b.rate_spread.quantize(_PKR),
        wastage_charged=b.wastage_charged.quantize(_PKR),
        making_charges=b.making_charges.quantize(_PKR),
        stone_margin=b.stone_margin.quantize(_PKR),
        ratti_discount=b.ratti_discount.quantize(_PKR),
        cash_discount=b.cash_discount.quantize(_PKR),
        round_off=b.round_off.quantize(_PKR),
        making_cost=b.making_cost.quantize(_PKR),
        uncosted_metal=b.uncosted_metal.quantize(_PKR),
        unattributed=b.unattributed.quantize(_PKR),
        invoices=b.invoices,
        lines=b.lines,
        notes=b.notes,
    )


@router.get(
    "/margin",
    response_model=MarginReport,
    dependencies=[Depends(require_perm("report:profit"))],
)
async def margin_report(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    currency: Currency = Query(default=Currency.PKR),
    format: Format = Query(default="json"),
):
    """
    Where the money came from — profit split by the lever that produced it.

    "Revenue minus cost" is true and nearly useless to a jeweller. The shop
    pulls four levers that behave completely differently — the spread between
    the rate metal was costed at and the rate it sold at, the wastage charged
    on top of the weight delivered, the making charge, and the margin on stones
    — and against them sit the giveaways: the ratti discount, the flat
    discount, and the round-off. Two shops with identical profit can be running
    in opposite directions, and a single number cannot tell them apart.

    The decomposition itself lives in `app.services.margin`, which works one
    invoice *line* at a time. Three figures are struck at the document level and
    are invisible to it: the flat discount, the weight discount (grams the
    customer was not billed for, valued at the rate the invoice was struck on —
    money, however it was typed in), and the round-off. Those are folded in
    here, or the residual would carry them and the report would accuse itself
    of not reconciling.

    Tax is held out of revenue. It is the government's money passing through,
    and counting it as income inflates every margin on the page.

    `by_month` is the same breakdown per calendar month, because the question is
    never "what was the margin" but "which lever is moving". A shop whose profit
    is flat while its rate spread doubles and its making charges collapse is in
    trouble, and only the monthly split shows it.

    One currency at a time: adding rupees to dollars produces a number that
    means nothing. Invoices in the window struck in another currency are counted
    in `excluded_invoices` rather than silently dropped.
    """
    start, end = _window(date_from, date_to)

    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.items).joinedload(InvoiceItem.product))
        .where(Invoice.status.in_((InvoiceStatus.issued, InvoiceStatus.paid)))
        .order_by(Invoice.issued_at)
    )
    if start is not None:
        stmt = stmt.where(Invoice.issued_at >= start)
    if end is not None:
        stmt = stmt.where(Invoice.issued_at <= end)

    invoices = (await db.execute(stmt)).unique().scalars().all()

    total = margin.MarginBreakdown()
    months: dict[str, margin.MarginBreakdown] = {}
    total_tax = _ZERO
    month_tax: dict[str, Decimal] = {}
    excluded = 0

    for invoice in invoices:
        if invoice.currency is not currency:
            excluded += 1
            continue

        period = invoice.issued_at.strftime("%Y-%m") if invoice.issued_at else "unknown"
        bucket = months.setdefault(period, margin.MarginBreakdown())

        tax = _d(invoice.tax_amount)
        # `invoice.total` already has the flat discount, the weight discount and
        # the round-off taken off it, and the tax added on. Stripping the tax
        # back out leaves exactly the figure the levers below have to add up to.
        revenue = (_d(invoice.total) - tax).quantize(_PKR)
        weight_discount = (
            _d(invoice.discount_weight_g) * _d(invoice.gold_rate_per_g)
        ).quantize(_PKR)
        doc_discount = (_d(invoice.discount_amount) + weight_discount).quantize(_PKR)
        round_off = _d(invoice.round_off).quantize(_PKR)

        for target in (total, bucket):
            target.revenue += revenue
            target.cash_discount += doc_discount
            target.round_off += round_off
            target.invoices += 1

        total_tax += tax
        month_tax[period] = month_tax.get(period, _ZERO) + tax

        for item in invoice.items:
            for target in (total, bucket):
                margin.accumulate(
                    target, item=item, invoice=invoice, product=item.product
                )

    margin.finalise(total)
    for bucket in months.values():
        margin.finalise(bucket)

    by_month = [
        _to_schema(period, months[period], month_tax.get(period, _ZERO))
        for period in sorted(months)
    ]
    overall = _to_schema(None, total, total_tax)

    if excluded:
        overall.notes.append(
            f"{excluded} invoice(s) in this window were struck in another currency and are "
            f"not in these totals. Re-run with ?currency=… to see them."
        )

    if format == "csv":
        header = [
            "period", "invoices", "lines", "revenue", "tax", "cost_of_goods", "gross_profit",
            "margin_pct", "rate_spread", "wastage_charged", "making_charges", "stone_margin",
            "ratti_discount", "cash_discount", "round_off", "making_cost", "uncosted_metal",
                "unattributed",
        ]

        def as_row(b: MarginBreakdown) -> list[object]:
            return [
                b.period or "TOTAL", b.invoices, b.lines, b.revenue, b.tax, b.cost_of_goods,
                b.gross_profit, b.margin_pct, b.rate_spread, b.wastage_charged, b.making_charges,
                b.stone_margin, b.ratti_discount, b.cash_discount, b.round_off, b.making_cost,
                b.uncosted_metal,
                b.unattributed,
            ]

        return _csv_response(
            f"margin_{_stamp(date_from, date_to)}.csv",
            header,
            [as_row(m) for m in by_month] + [as_row(overall)],
        )

    return MarginReport(
        date_from=date_from,
        date_to=date_to,
        currency=currency,
        total=overall,
        by_month=by_month,
        excluded_invoices=excluded,
    )


# ---------------------------------------------------------------------------
# Worker performance
# ---------------------------------------------------------------------------
@router.get(
    "/worker-performance",
    response_model=WorkerPerformanceReport,
    dependencies=[Depends(require_perm("report:profit"))],
)
async def worker_performance_report(
    db: DbSession,
    days: int = Query(default=90, ge=1, le=1095),
    format: Format = Query(default="json"),
):
    """
    Who is worth keeping.

    Two different kinds of figure sit side by side here on purpose. The
    workshop columns — legs, metal issued and returned, wastage against what he
    was allowed, labour earned — are for the window. The last two are not:
    `gold_balance_fine_g` and `cash_payable` are read off the ledger as it stands
    right now, because "how much of my metal is Zahid holding" and "what do I
    owe him" are positions, not period totals, and an owner deciding whether to
    keep a worker needs both halves on one line.

    Wastage as a percentage of issued is the column that ranks people. Raw grams
    just ranks whoever handles the most metal, which is usually the best worker
    in the shop.

    Only received legs count. An open leg's metal has not come back yet, so its
    "wastage" is not a loss — it is an outstanding balance, and the gold column
    already says so.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    q = (
        select(
            JobLeg.worker_id,
            Vendor.name,
            Department.name,
            func.count(JobLeg.id),
            func.coalesce(func.sum(JobLeg.gold_issued_g), 0),
            func.coalesce(func.sum(JobLeg.gold_received_g), 0),
            func.coalesce(func.sum(JobLeg.wastage_allowed_g), 0),
            func.coalesce(func.sum(JobLeg.wastage_actual_g), 0),
            func.coalesce(func.sum(JobLeg.wastage_excess_g), 0),
            func.coalesce(func.sum(JobLeg.labour_amount), 0),
        )
        .join(Vendor, Vendor.id == JobLeg.worker_id, isouter=True)
        .join(Department, Department.id == Vendor.department_id, isouter=True)
        .where(
            JobLeg.status == LegStatus.received,
            JobLeg.received_at.is_not(None),
            JobLeg.received_at >= start,
            JobLeg.received_at <= end,
        )
        .group_by(JobLeg.worker_id, Vendor.name, Department.name)
    )

    rows: list[WorkerPerformanceRow] = []
    t_legs = 0
    t_issued = t_actual = t_excess = t_labour = _ZERO

    for (
        worker_id,
        worker_name,
        department,
        legs,
        issued,
        received,
        allowed,
        actual,
        excess,
        labour,
    ) in (await db.execute(q)).all():
        issued_d, actual_d = _d(issued), _d(actual)
        # Unassigned legs have no ledger party, so they carry no balance —
        # there is nobody to owe it.
        gold_balance = (
            await ledger.balance(
                db,
                account_code=SystemAccount.GOLD_WITH_WORKERS.value,
                commodity=Commodity.GOLD,
                party_type=PartyType.worker,
                party_id=worker_id,
            )
            if worker_id
            else _ZERO
        )
        # 2120 is a liability, so what the shop owes sits there as a credit —
        # negative. Flipped here so the column reads as money out.
        payable = (
            -await ledger.balance(
                db,
                account_code=SystemAccount.WORKERS_PAYABLE.value,
                commodity=Commodity.PKR,
                party_type=PartyType.worker,
                party_id=worker_id,
            )
            if worker_id
            else _ZERO
        )

        rows.append(
            WorkerPerformanceRow(
                worker_id=worker_id,
                worker_name=worker_name or "Unassigned",
                department=department,
                legs=legs,
                gold_issued_g=issued_d.quantize(_G),
                gold_received_g=_d(received).quantize(_G),
                wastage_allowed_g=_d(allowed).quantize(_G),
                wastage_actual_g=actual_d.quantize(_G),
                wastage_excess_g=_d(excess).quantize(_G),
                wastage_pct_of_issued=_pct(actual_d, issued_d),
                labour_earned=_d(labour).quantize(_PKR),
                gold_balance_fine_g=gold_balance.quantize(_G),
                cash_payable=payable.quantize(_PKR),
            )
        )
        t_legs += legs
        t_issued += issued_d
        t_actual += actual_d
        t_excess += _d(excess)
        t_labour += _d(labour)

    rows.sort(key=lambda r: -r.wastage_excess_g)

    if format == "csv":
        return _csv_response(
            f"worker-performance_{days}d_{date.today()}.csv",
            [
                "worker", "department", "legs", "gold_issued_g", "gold_received_g",
                "wastage_allowed_g", "wastage_actual_g", "wastage_excess_g",
                "wastage_pct_of_issued", "labour_earned", "gold_balance_fine_g", "cash_payable",
            ],
            [
                [
                    r.worker_name, r.department, r.legs, r.gold_issued_g, r.gold_received_g,
                    r.wastage_allowed_g, r.wastage_actual_g, r.wastage_excess_g,
                    r.wastage_pct_of_issued, r.labour_earned, r.gold_balance_fine_g, r.cash_payable,
                ]
                for r in rows
            ],
        )

    return WorkerPerformanceReport(
        days=days,
        period_from=start.date(),
        period_to=end.date(),
        rows=rows,
        legs=t_legs,
        gold_issued_g=t_issued.quantize(_G),
        wastage_actual_g=t_actual.quantize(_G),
        wastage_excess_g=t_excess.quantize(_G),
        wastage_pct_of_issued=_pct(t_actual, t_issued),
        labour_earned=t_labour.quantize(_PKR),
    )


# ---------------------------------------------------------------------------
# Item performance
# ---------------------------------------------------------------------------
@router.get(
    "/item-performance",
    response_model=ItemPerformanceReport,
    dependencies=[Depends(require_perm("report:profit"))],
)
async def item_performance_report(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    format: Format = Query(default="json"),
):
    """
    Which kinds of piece are worth making.

    Rows are the `items` master — ring, bangle, taka — because that is the unit
    a shop decides production in. Every item is listed, including the ones that
    did nothing: an item with designs started and none sold is exactly what the
    owner is looking for.

    The three columns come off three different clocks and cannot be merged.
    `designs_started` counts pieces that entered the workshop in the window;
    `designs_stocked` and `gold_consumed_g` count pieces that *left* it and
    became sellable; the sales columns count what was billed. A piece begun in
    March and sold in June appears in one column in each month, which is
    correct — production and sales are different questions.

    Revenue is line totals, so a discount typed at the foot of the invoice is
    not attributed to any item. Per-item attribution of a document-level
    discount is a guess, and `/reports/margin` already reports it honestly at
    the level it was actually given.
    """
    start, end = _window(date_from, date_to)

    started_q = select(Design.item_id, func.count(Design.id)).group_by(Design.item_id)
    if start is not None:
        started_q = started_q.where(Design.created_at >= start)
    if end is not None:
        started_q = started_q.where(Design.created_at <= end)
    started = {item_id: n for item_id, n in (await db.execute(started_q)).all()}

    stocked_q = (
        select(
            Design.item_id,
            func.count(Product.id),
            func.coalesce(func.sum(_fine_sql(Product.gold_weight_g, Product.gold_purity)), 0),
        )
        .join(Design, Design.id == Product.design_id)
        .where(Product.stocked_at.is_not(None))
        .group_by(Design.item_id)
    )
    if start is not None:
        stocked_q = stocked_q.where(Product.stocked_at >= start)
    if end is not None:
        stocked_q = stocked_q.where(Product.stocked_at <= end)
    stocked = {
        item_id: (n, _d(grams)) for item_id, n, grams in (await db.execute(stocked_q)).all()
    }

    sold_q = (
        select(
            Design.item_id,
            func.coalesce(func.sum(InvoiceItem.quantity), 0),
            func.coalesce(func.sum(InvoiceItem.line_total), 0),
            func.coalesce(
                func.sum((Product.total_cost + Product.material_cost) * InvoiceItem.quantity), 0
            ),
        )
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .join(Product, Product.id == InvoiceItem.product_id)
        .join(Design, Design.id == Product.design_id)
        .where(Invoice.status.in_((InvoiceStatus.issued, InvoiceStatus.paid)))
        .group_by(Design.item_id)
    )
    if start is not None:
        sold_q = sold_q.where(Invoice.issued_at >= start)
    if end is not None:
        sold_q = sold_q.where(Invoice.issued_at <= end)
    sold = {
        item_id: (int(qty), _d(rev), _d(cost))
        for item_id, qty, rev, cost in (await db.execute(sold_q)).all()
    }

    items = (await db.execute(select(Item).order_by(Item.name))).scalars().all()

    rows: list[ItemPerformanceRow] = []
    for item in items:
        n_stocked, grams = stocked.get(item.id, (0, _ZERO))
        pieces, revenue, cost = sold.get(item.id, (0, _ZERO, _ZERO))
        gross = (revenue - cost).quantize(_PKR)
        rows.append(
            ItemPerformanceRow(
                item_id=item.id,
                item_name=item.name,
                abbreviation=item.abbreviation,
                designs_started=started.get(item.id, 0),
                designs_stocked=n_stocked,
                gold_consumed_g=grams.quantize(_G),
                pieces_sold=pieces,
                revenue=revenue.quantize(_PKR),
                cost_of_goods=cost.quantize(_PKR),
                gross_margin=gross,
                margin_pct=_pct(gross, revenue) if revenue else None,
            )
        )

    rows.sort(key=lambda r: (-r.revenue, r.item_name))

    if format == "csv":
        return _csv_response(
            f"item-performance_{_stamp(date_from, date_to)}.csv",
            [
                "item", "abbreviation", "designs_started", "designs_stocked", "gold_consumed_g",
                "pieces_sold", "revenue", "cost_of_goods", "gross_margin", "margin_pct",
            ],
            [
                [
                    r.item_name, r.abbreviation, r.designs_started, r.designs_stocked,
                    r.gold_consumed_g, r.pieces_sold, r.revenue, r.cost_of_goods,
                    r.gross_margin, r.margin_pct,
                ]
                for r in rows
            ],
        )

    return ItemPerformanceReport(
        date_from=date_from,
        date_to=date_to,
        rows=rows,
        designs_started=sum(r.designs_started for r in rows),
        designs_stocked=sum(r.designs_stocked for r in rows),
        pieces_sold=sum(r.pieces_sold for r in rows),
        revenue=sum((r.revenue for r in rows), _ZERO).quantize(_PKR),
        gross_margin=sum((r.gross_margin for r in rows), _ZERO).quantize(_PKR),
    )


# ---------------------------------------------------------------------------
# Department throughput
# ---------------------------------------------------------------------------
@router.get(
    "/department-throughput",
    response_model=DepartmentThroughputReport,
    dependencies=[Depends(require_perm("report:loss"))],
)
async def department_throughput_report(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    format: Format = Query(default="json"),
):
    """
    What each stage of the floor cost and how long it held the work.

    `avg_days_held` is the column that finds the bottleneck. Casting losing 2%
    is a costing question; setting sitting on every piece for nine days is a
    delivery-date question, and the shop only ever hears about the second one
    from the customer.

    Legs are attributed to the department they were worked in, not to the
    worker's home department — a polisher who takes a casting leg is casting
    capacity that day, and the throughput of the casting bench is what this
    report is about.
    """
    start, end = _window(date_from, date_to)

    held_days = func.avg(
        func.extract("epoch", JobLeg.received_at - JobLeg.issued_at)
    ) / Decimal("86400")

    q = (
        select(
            Department.id,
            Department.name,
            Department.code,
            func.count(JobLeg.id),
            func.coalesce(func.sum(JobLeg.gold_issued_g), 0),
            func.coalesce(func.sum(JobLeg.gold_received_g), 0),
            func.coalesce(func.sum(JobLeg.wastage_allowed_g), 0),
            func.coalesce(func.sum(JobLeg.wastage_actual_g), 0),
            func.coalesce(func.sum(JobLeg.wastage_excess_g), 0),
            func.coalesce(func.sum(JobLeg.labour_amount), 0),
            held_days,
        )
        .join(Department, Department.id == JobLeg.department_id)
        .where(JobLeg.status == LegStatus.received, JobLeg.received_at.is_not(None))
        .group_by(Department.id, Department.name, Department.code)
        .order_by(Department.sequence, Department.name)
    )
    if start is not None:
        q = q.where(JobLeg.received_at >= start)
    if end is not None:
        q = q.where(JobLeg.received_at <= end)

    rows: list[DepartmentThroughputRow] = []
    t_legs = 0
    t_in = t_out = t_actual = t_excess = t_labour = _ZERO

    for (
        dept_id,
        dept_name,
        code,
        legs,
        issued,
        received,
        allowed,
        actual,
        excess,
        labour,
        avg_days,
    ) in (await db.execute(q)).all():
        issued_d, actual_d = _d(issued), _d(actual)
        rows.append(
            DepartmentThroughputRow(
                department_id=dept_id,
                department=dept_name,
                code=code,
                legs_completed=legs,
                gold_in_g=issued_d.quantize(_G),
                gold_out_g=_d(received).quantize(_G),
                wastage_allowed_g=_d(allowed).quantize(_G),
                wastage_actual_g=actual_d.quantize(_G),
                wastage_excess_g=_d(excess).quantize(_G),
                wastage_pct_of_issued=_pct(actual_d, issued_d),
                labour_cost=_d(labour).quantize(_PKR),
                avg_days_held=_d(avg_days).quantize(_PCT) if avg_days is not None else None,
            )
        )
        t_legs += legs
        t_in += issued_d
        t_out += _d(received)
        t_actual += actual_d
        t_excess += _d(excess)
        t_labour += _d(labour)

    if format == "csv":
        return _csv_response(
            f"department-throughput_{_stamp(date_from, date_to)}.csv",
            [
                "department", "code", "legs_completed", "gold_in_g", "gold_out_g",
                "wastage_allowed_g", "wastage_actual_g", "wastage_excess_g",
                "wastage_pct_of_issued", "labour_cost", "avg_days_held",
            ],
            [
                [
                    r.department, r.code, r.legs_completed, r.gold_in_g, r.gold_out_g,
                    r.wastage_allowed_g, r.wastage_actual_g, r.wastage_excess_g,
                    r.wastage_pct_of_issued, r.labour_cost, r.avg_days_held,
                ]
                for r in rows
            ],
        )

    return DepartmentThroughputReport(
        date_from=date_from,
        date_to=date_to,
        rows=rows,
        legs_completed=t_legs,
        gold_in_g=t_in.quantize(_G),
        gold_out_g=t_out.quantize(_G),
        wastage_actual_g=t_actual.quantize(_G),
        wastage_excess_g=t_excess.quantize(_G),
        labour_cost=t_labour.quantize(_PKR),
    )


# ---------------------------------------------------------------------------
# Gold movement
# ---------------------------------------------------------------------------
@router.get(
    "/gold-movement",
    response_model=GoldMovementReport,
    dependencies=[Depends(require_perm("report:stock"))],
)
async def gold_movement_report(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    format: Format = Query(default="json"),
):
    """
    Where the metal came from and where it went, in fine grams.

    The flows are counted off the business records — old-gold purchases, job
    legs, pieces stocked, pieces sold — because only those know *why* metal
    moved; the journal knows that 1130 went down but not whether it went to a
    worker or into a finished piece.

    The closing position is the opposite: it comes off the journal, summed as
    of `date_to`, because a balance reconstructed from lines can always explain
    itself and can never drift from what was posted. Flows and position are
    therefore two different questions answered from two different places, and
    that is deliberate.

    Nothing here is a running reconciliation of the form opening + in − out =
    closing. Metal in the shop's hands moves through accounts that this report
    does not enumerate (wastage burnt off, metal charged back to a worker), and
    presenting a tidy identity that only holds sometimes would be worse than
    presenting none.
    """
    start, end = _window(date_from, date_to)

    def bounded(q, column):
        if start is not None:
            q = q.where(column >= start)
        if end is not None:
            q = q.where(column <= end)
        return q

    bought_q = bounded(
        select(
            func.count(OldGoldPurchase.id),
            func.coalesce(
                func.sum(_fine_sql(OldGoldPurchase.weight_g, OldGoldPurchase.purity)), 0
            ),
        ),
        OldGoldPurchase.purchased_at,
    )
    purchases, bought_g = (await db.execute(bought_q)).one()

    issued_q = bounded(
        select(
            func.coalesce(
                func.sum(_fine_sql(JobLeg.gold_issued_g, JobLeg.gold_issued_purity)), 0
            )
        ).where(JobLeg.status != LegStatus.cancelled, JobLeg.issued_at.is_not(None)),
        JobLeg.issued_at,
    )
    issued_g = _d((await db.execute(issued_q)).scalar_one())

    # Received, burnt and charged back all settle on the same event, so they
    # come off one pass over the legs that closed in the window.
    recv_q = bounded(
        select(
            func.coalesce(
                func.sum(_fine_sql(JobLeg.gold_received_g, JobLeg.gold_issued_purity)), 0
            ),
            func.coalesce(
                func.sum(_fine_sql(JobLeg.wastage_actual_g, JobLeg.gold_issued_purity)), 0
            ),
            func.coalesce(
                func.sum(_fine_sql(JobLeg.wastage_excess_g, JobLeg.gold_issued_purity)), 0
            ),
        ).where(JobLeg.status == LegStatus.received, JobLeg.received_at.is_not(None)),
        JobLeg.received_at,
    )
    received_g, wastage_g, excess_g = [_d(v) for v in (await db.execute(recv_q)).one()]

    consumed_q = bounded(
        select(
            func.coalesce(func.sum(_fine_sql(Product.gold_weight_g, Product.gold_purity)), 0)
        ).where(Product.stocked_at.is_not(None)),
        Product.stocked_at,
    )
    consumed_g = _d((await db.execute(consumed_q)).scalar_one())

    sold_q = bounded(
        select(
            func.coalesce(
                func.sum(
                    _fine_sql(Product.gold_weight_g, Product.gold_purity) * InvoiceItem.quantity
                ),
                0,
            ),
            func.count(case((Product.gold_rate_at_cost.is_(None), 1))),
        )
        .select_from(InvoiceItem)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .join(Product, Product.id == InvoiceItem.product_id)
        .where(Invoice.status.in_((InvoiceStatus.issued, InvoiceStatus.paid))),
        Invoice.issued_at,
    )
    sold_g, uncosted_lines = (await db.execute(sold_q)).one()
    sold_g = _d(sold_g)

    in_hand = await ledger.balance(
        db, account_code=SystemAccount.GOLD_IN_HAND.value, commodity=Commodity.GOLD, up_to=date_to
    )
    with_workers = await ledger.balance(
        db,
        account_code=SystemAccount.GOLD_WITH_WORKERS.value,
        commodity=Commodity.GOLD,
        up_to=date_to,
    )
    finished = await ledger.balance(
        db, account_code=SystemAccount.FINISHED_GOODS.value, commodity=Commodity.GOLD, up_to=date_to
    )

    # Quantized once, up front, so the CSV and the JSON can never disagree on
    # a figure the shop is about to reconcile against.
    bought_g = _d(bought_g).quantize(_G)
    received_g = received_g.quantize(_G)
    issued_g = issued_g.quantize(_G)
    wastage_g = wastage_g.quantize(_G)
    excess_g = excess_g.quantize(_G)
    consumed_g = consumed_g.quantize(_G)
    sold_g = sold_g.quantize(_G)
    in_hand = in_hand.quantize(_G)
    with_workers = with_workers.quantize(_G)
    finished = finished.quantize(_G)

    notes: list[str] = []
    if uncosted_lines:
        notes.append(
            f"{uncosted_lines} sold line(s) are against pieces that never went through the "
            "stock form, so they carry no locked cost rate and nothing was relieved from "
            "Finished Goods for them. Their metal is in `sold_g` but not in the closing "
            "position, which is why 1150 can read heavier than the shop's shelves."
        )
    if finished < 0:
        notes.append(
            f"Finished Goods is showing {finished}g — a negative balance means "
            "more metal has been sold out of it than was ever stocked into it. Pieces are "
            "being invoiced without being stocked first."
        )

    if format == "csv":
        return _csv_response(
            f"gold-movement_{_stamp(date_from, date_to)}.csv",
            ["measure", "fine_grams"],
            [
                ["bought as old gold", bought_g],
                ["received back from workers", received_g],
                ["issued to workers", issued_g],
                ["burnt off as wastage", wastage_g],
                ["charged back to workers", excess_g],
                ["consumed into pieces", consumed_g],
                ["sold", sold_g],
                ["closing: gold in hand (1130)", in_hand],
                ["closing: with workers (1160)", with_workers],
                ["closing: finished goods (1150)", finished],
                ["closing: total", in_hand + with_workers + finished],
            ],
        )

    return GoldMovementReport(
        date_from=date_from,
        date_to=date_to,
        bought_old_gold_g=bought_g,
        bought_old_gold_purchases=purchases,
        received_from_workers_g=received_g,
        issued_to_workers_g=issued_g,
        wastage_g=wastage_g,
        excess_charged_to_workers_g=excess_g,
        consumed_into_pieces_g=consumed_g,
        sold_g=sold_g,
        closing_gold_in_hand_g=in_hand,
        closing_with_workers_g=with_workers,
        closing_finished_goods_g=finished,
        closing_total_g=in_hand + with_workers + finished,
        notes=notes,
    )
