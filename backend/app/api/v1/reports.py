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

from app.core import clock
from app.core.config import settings
from app.api.deps import CurrentUser, DbSession, require_perm
from app.models.account import Account, SystemAccount
from app.models.currency import Currency
from app.models.customer import Customer
from app.models.department import Department
from app.models.design import Design, JobLeg, LegStatus
from app.models.metal import Metal
from app.models.profit import ProfitBasis
from app.models.inventory import InventoryItem
from app.models.invoice import Invoice, InvoiceItem, InvoiceStatus
from app.models.item import Item
from app.models.journal import Commodity, JournalLine, PartyType
from app.models.manufacturing import JobStage, ManufacturingJob
from app.models.product import Product
from app.models.purchase import OldGoldPurchase, StonePurchaseItem
from app.models.stone_draw import StoneDraw
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
    MaterialOutsideReport,
    MaterialOutsideRow,
    NetWorth,
    OverviewReport,
    PeriodSummary,
    WorthLine,
    ProfitCurrencyTotal,
    ProfitReport,
    ProfitRow,
    SalesBucket,
    SalesReport,
    MetalPosition,
    StockBucket,
    CustomerPerformanceReport,
    CustomerPerformanceRow,
    ProfitSplitLine,
    ProfitSplitReport,
    StockPositionReport,
    StockReport,
    VendorLossRow,
    WorkerDepartmentLossRow,
    WorkerPerformanceReport,
    WorkerPerformanceRow,
)
from app.api.v1.cash import cash_flow
from app.api.v1.ledger import position as position_report
from app.services import ledger, margin, purchasing
from app.services.gold_rate import fine_rate_per_g, rate_in_force
from app.services.ledger import fine_grams

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


def _fine_any_metal_sql(weight, purity, tunch):
    """
    Fine grams for either metal, preferring the assayed tunch.

    The karat-only version above cannot describe silver at all — 999 has no
    karat, and reading a blank purity as 24 would value a kilo of silver as a
    kilo of pure gold. Tunch is a percentage of pure and serves both metals, so
    it wins wherever it is present; karat is the gold fallback; and "neither
    stated" means pure, which is how bullion is entered.
    """
    return weight * func.coalesce(
        tunch / Decimal("100"),
        purity / Decimal("24"),
        Decimal("1"),
    )


def _stamp(date_from: date | None, date_to: date | None) -> str:
    return f"{date_from or 'open'}_{date_to or clock.today()}"


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
            f"stock_{clock.today()}.csv",
            ["type", "items", "total_quantity", "total_weight_g", "total_weight_ct"],
            [
                [b.type.value, b.items, b.total_quantity, b.total_weight_g, b.total_weight_ct]
                for b in buckets
            ],
        )
    return StockReport(by_type=buckets, items_count=total_count)


@router.get(
    "/profit-split",
    response_model=ProfitSplitReport,
    dependencies=[Depends(require_perm("report:profit"))],
)
async def profit_split_report(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    currency: Currency = Query(default=Currency.PKR),
    basis: ProfitBasis | None = Query(
        default=None,
        description="cost = metal at what we paid; replacement = metal at today's rate",
    ),
    format: Format = Query(default="json"),
):
    """
    Two businesses under one roof: the metal, and the raw material.

    The shop asked for these apart, and they are apart because they behave
    differently and are managed differently. Metal is bought at a rate that
    moves daily, sold at a rate that moves daily, and its margin is largely the
    spread plus the wastage charged. Stones are bought in parcels at a
    negotiated price, sit in stock for months, and their margin is whatever was
    agreed when the parcel was bought. A single "gross margin" averages a
    business that turns over weekly with one that turns over yearly, and the
    average describes neither.

    Making is shown as a third column rather than folded into metal. It is the
    shop's own labour sold on, it moves with neither rate, and for a wholesaler
    it is most of the margin — which is exactly what a blended figure hides.

    **How cost is split.** A product carries one `material_cost` covering both
    metal and stones. The metal half is recoverable because `gold_rate_at_cost`
    was locked onto the piece when it was costed: fine grams at that rate is
    what the gold in it cost. What remains of `material_cost` is the stones. A
    piece missing that locked rate cannot be split and is counted in
    `unsplit_lines` rather than guessed at — a guess here would move margin
    from one business to the other and nothing on the report would say so.

    **The two bases.** `cost` values metal at the rate locked onto the piece
    when it was stocked — gross profit as an accountant means it, and the only
    one of the two that reconciles to the ledger unaided. `replacement` values
    it at today's rate, answering the different and equally real question of
    whether the shop can restock what it just sold.

    The gap between them is the holding gain, and it is **not** trading profit.
    It is already reported on its own by the metal revaluation, so a shop
    reading `replacement` here and adding the revaluation would count the same
    money twice. The report says so in `assumptions` rather than leaving it to
    be discovered.

    Stones stay at parcel cost under both. There is no market rate for a grade
    of diamond the way there is for metal — a price for "12 PTR commercial VS1"
    is a negotiation, not a quotation — so a replacement value for stones would
    be a number somebody invented.

    One currency at a time. Rupees and dollars do not add.
    """
    chosen = basis or ProfitBasis(settings.default_profit_basis)
    start, end = _window(date_from, date_to)

    # Today's rate, needed only for the replacement basis. Fetched once: a rate
    # looked up per line could change mid-report and value two identical pieces
    # differently.
    today_rate: Decimal | None = None
    if chosen is ProfitBasis.replacement:
        rate_row = await rate_in_force(db, metal=Metal.gold, as_of=clock.today())
        today_rate = fine_rate_per_g(rate_row) if rate_row else None

    stmt = (
        select(
            InvoiceItem.gold_amount,
            InvoiceItem.stone_amount,
            InvoiceItem.labor_amount,
            InvoiceItem.line_discount,
            InvoiceItem.quantity,
            Product.material_cost,
            Product.total_cost,
            Product.gold_weight_g,
            Product.gold_purity,
            Product.gold_tunch_pct,
            Product.gold_rate_at_cost,
            Product.id,
        )
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .join(Product, Product.id == InvoiceItem.product_id, isouter=True)
        .where(
            Invoice.status.in_((InvoiceStatus.issued, InvoiceStatus.paid)),
            Invoice.currency == currency,
        )
    )
    if start is not None:
        stmt = stmt.where(Invoice.issued_at >= start)
    if end is not None:
        stmt = stmt.where(Invoice.issued_at <= end)

    gold_rev = stone_rev = making_rev = _ZERO
    gold_cost = stone_cost = making_cost = _ZERO
    unsplit = lines = 0

    for (
        g_amt, s_amt, l_amt, disc, qty, mat_cost, tot_cost,
        p_gold_g, p_purity, p_tunch, p_rate, product_id,
    ) in (await db.execute(stmt)).all():
        lines += 1
        n = Decimal(str(qty or 1))
        gold_rev += _d(g_amt)
        stone_rev += _d(s_amt)
        making_rev += _d(l_amt)
        # A line discount is money given away against the line as a whole. It
        # is netted off the largest revenue component rather than spread,
        # because that is what the counter was arguing about when it was given.
        discount = _d(disc)
        if discount:
            biggest = max(
                (("gold", _d(g_amt)), ("stone", _d(s_amt)), ("making", _d(l_amt))),
                key=lambda kv: kv[1],
            )[0]
            if biggest == "gold":
                gold_rev -= discount
            elif biggest == "stone":
                stone_rev -= discount
            else:
                making_rev -= discount

        if product_id is None:
            # No product, no cost. Counted in `unsplit_lines` so a report built
            # mostly from typed-in lines cannot be mistaken for a costed one.
            unsplit += 1
            continue

        making_cost += _d(tot_cost) * n
        material = _d(mat_cost) * n
        if p_rate and _d(p_rate) > 0 and _d(p_gold_g) > 0:
            fine = fine_grams(p_gold_g, p_purity, p_tunch)
            # The one line the basis actually changes. Under `cost` the metal is
            # valued at the rate locked when the piece was stocked; under
            # `replacement`, at today's. Everything else on this report is
            # identical between the two, which is worth knowing when the totals
            # move: only the gold stream can have moved.
            valued_at = (
                today_rate
                if chosen is ProfitBasis.replacement and today_rate
                else _d(p_rate)
            )
            metal_part = (fine * valued_at * n).quantize(_PKR)
            if chosen is ProfitBasis.cost:
                # Never more than the material actually cost: a rate keyed after
                # the fact could otherwise make the metal alone exceed the whole,
                # handing the stone business a negative cost and a false margin.
                metal_part = min(metal_part, material)
                gold_cost += metal_part
                stone_cost += material - metal_part
            else:
                # Under replacement the metal is *expected* to exceed what the
                # piece cost — that is the whole point in a rising market — so
                # the cap would defeat it. The stones keep their own historic
                # cost, taken from the split the locked rate gives, so a higher
                # gold valuation cannot silently eat into them.
                historic_metal = min((fine * _d(p_rate) * n).quantize(_PKR), material)
                gold_cost += metal_part
                stone_cost += material - historic_metal
        else:
            # The piece has no locked rate, so its material cannot be split
            # honestly. Charged whole to metal — most pieces are mostly metal —
            # and counted, so the reader knows how much of the split is firm.
            gold_cost += material
            unsplit += 1

    def line(name, rev, cost):
        margin = (rev - cost).quantize(_PKR)
        return ProfitSplitLine(
            stream=name,
            revenue=rev.quantize(_PKR),
            cost=cost.quantize(_PKR),
            gross_margin=margin,
            margin_pct=_pct(margin, rev) if rev else None,
        )

    streams = [
        line("gold", gold_rev, gold_cost),
        line("stones", stone_rev, stone_cost),
        line("making", making_rev, making_cost),
    ]
    total_rev = sum((s.revenue for s in streams), _ZERO)
    total_cost = sum((s.cost for s in streams), _ZERO)

    if format == "csv":
        return _csv_response(
            f"profit_split_{_stamp(date_from, date_to)}.csv",
            ["stream", "revenue", "cost", "gross_margin", "margin_pct"],
            [[s.stream, s.revenue, s.cost, s.gross_margin, s.margin_pct] for s in streams],
        )
    # ---- what this report assumed, said out loud ----
    #
    # The shop never wrote its profit formulas down, so a conventional method
    # was implemented. The honest way to ship that is to state every judgement
    # on the face of the report rather than bury it in a docstring nobody
    # opens.
    assumptions: list[str] = [
        "Revenue excludes tax — that is the government's money passing through, "
        "and counting it would inflate every margin here.",
        "A line discount is taken off the largest component of that line, not "
        "spread across all three. That is what the counter was arguing about "
        "when it was given.",
        "Making is the shop's own labour sold on, costed at what the workers "
        "were actually paid for the piece.",
        "Wastage charged to the customer sits in the gold stream, because it is "
        "billed as metal.",
    ]
    if chosen is ProfitBasis.cost:
        assumptions.insert(
            0,
            "Metal is valued at the rate locked onto each piece when it was "
            "stocked — what the shop actually paid. This is gross profit as an "
            "accountant means it, and it reconciles to the ledger.",
        )
        assumptions.append(
            "What the rate has done since is NOT in these figures. It is "
            "reported separately as the metal revaluation, which is the correct "
            "place for it.",
        )
    else:
        assumptions.insert(
            0,
            "Metal is valued at today's rate, not what was paid — this answers "
            "'can we restock what we sold?' rather than 'did we trade well?'.",
        )
        assumptions.insert(
            1,
            "The gap between this and the cost basis is the holding gain, and it "
            "is NOT trading profit. The metal revaluation already reports it, so "
            "do not add the two together.",
        )
    assumptions.append(
        "Stones are at parcel cost under both methods. There is no market rate "
        "for a grade of diamond the way there is for metal, so a replacement "
        "value for them would be invented.",
    )
    if unsplit:
        assumptions.append(
            f"{unsplit} of {lines} lines could not be split between metal and "
            "stones and were charged whole to gold. The two margins are firm "
            "only to the extent that number is small.",
        )

    fallback = None
    if chosen is ProfitBasis.replacement and today_rate is None:
        fallback = (
            "No gold rate is on record for today, so the replacement basis could "
            "not be applied — these are cost-basis figures."
        )

    return ProfitSplitReport(
        date_from=date_from,
        date_to=date_to,
        currency=currency,
        streams=streams,
        revenue=total_rev,
        cost=total_cost,
        gross_margin=(total_rev - total_cost).quantize(_PKR),
        lines=lines,
        unsplit_lines=unsplit,
        basis=chosen.value,
        basis_label=(
            "At what we paid" if chosen is ProfitBasis.cost else "At today's rate"
        ),
        assumptions=assumptions,
        basis_fallback=fallback,
    )


@router.get(
    "/customers",
    response_model=CustomerPerformanceReport,
    dependencies=[Depends(require_perm("report:profit"))],
)
async def customer_performance_report(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    format: Format = Query(default="json"),
):
    """
    Who the shop's customers actually are, biggest first, and what each is worth.

    Two questions in one table because they are asked together and answered
    differently. *Spend* is what they bought — the obvious ranking, and the one
    that flatters a customer who buys heavy metal at a thin margin. *Margin* is
    what the shop kept, and it reorders the list: the second-biggest spender is
    routinely the best customer, and nothing in the system could say so.

    Cost is the same figure the profit report uses — `total_cost` plus
    `material_cost` off the product, weighted by line quantity — so the two
    reports cannot disagree about what a sale cost. Lines carrying no product
    contribute revenue and no cost, which overstates margin on those; that is
    visible as `uncosted_lines` rather than buried, because a customer bought
    entirely on typed-in lines has a margin figure nobody should trust.

    One currency at a time. Rupees and dollars do not add, and ranking a mixed
    list would sort by a number that means nothing.
    """
    start, end = _window(date_from, date_to)

    cost_subq = (
        select(
            InvoiceItem.invoice_id.label("invoice_id"),
            func.coalesce(
                func.sum(
                    case(
                        (Product.id.is_(None), Decimal("0")),
                        else_=(Product.total_cost + Product.material_cost)
                        * InvoiceItem.quantity,
                    )
                ),
                0,
            ).label("cost"),
            func.coalesce(
                func.sum(case((Product.id.is_(None), 1), else_=0)), 0
            ).label("uncosted"),
            func.coalesce(func.sum(InvoiceItem.gold_weight_g), 0).label("gold_g"),
            func.coalesce(func.sum(InvoiceItem.stone_weight_ct), 0).label("stone_ct"),
        )
        .join(Product, Product.id == InvoiceItem.product_id, isouter=True)
        .group_by(InvoiceItem.invoice_id)
        .subquery()
    )

    stmt = (
        select(
            Customer.id,
            Customer.name,
            Invoice.currency,
            func.count(Invoice.id),
            func.coalesce(func.sum(Invoice.total), 0),
            func.coalesce(func.sum(Invoice.tax_amount), 0),
            func.coalesce(func.sum(cost_subq.c.cost), 0),
            func.coalesce(func.sum(cost_subq.c.uncosted), 0),
            func.coalesce(func.sum(cost_subq.c.gold_g), 0),
            func.coalesce(func.sum(cost_subq.c.stone_ct), 0),
            func.max(Invoice.issued_at),
        )
        .join(Customer, Customer.id == Invoice.customer_id)
        .join(cost_subq, cost_subq.c.invoice_id == Invoice.id, isouter=True)
        .where(Invoice.status.in_((InvoiceStatus.issued, InvoiceStatus.paid)))
        .group_by(Customer.id, Customer.name, Invoice.currency)
    )
    if start is not None:
        stmt = stmt.where(Invoice.issued_at >= start)
    if end is not None:
        stmt = stmt.where(Invoice.issued_at <= end)

    rows: list[CustomerPerformanceRow] = []
    for (
        cust_id, name, currency, invoices, total, tax, cost, uncosted, gold_g, stone_ct, last
    ) in (await db.execute(stmt)).all():
        # Tax is the government's money passing through; counting it as revenue
        # would inflate every margin on this report by the tax rate.
        revenue = (_d(total) - _d(tax)).quantize(_PKR)
        cost_d = _d(cost).quantize(_PKR)
        margin = (revenue - cost_d).quantize(_PKR)
        rows.append(
            CustomerPerformanceRow(
                customer_id=cust_id,
                customer_name=name,
                currency=currency,
                invoices=int(invoices),
                revenue=revenue,
                cost_of_goods=cost_d,
                gross_margin=margin,
                margin_pct=_pct(margin, revenue) if revenue else None,
                gold_weight_g=_d(gold_g).quantize(_G),
                stone_weight_ct=_d(stone_ct).quantize(_G),
                uncosted_lines=int(uncosted),
                last_purchase_at=last,
            )
        )

    # Ranked by what they spent, which is the question as asked. `margin_pct`
    # is on every row so the reader can re-sort by what the shop actually kept —
    # and will often find a different customer at the top.
    rows.sort(key=lambda r: r.revenue, reverse=True)

    if format == "csv":
        return _csv_response(
            f"customers_{_stamp(date_from, date_to)}.csv",
            ["customer", "currency", "invoices", "revenue", "cost_of_goods",
             "gross_margin", "margin_pct", "gold_g", "stone_ct", "uncosted_lines"],
            [
                [r.customer_name, r.currency.value, r.invoices, r.revenue, r.cost_of_goods,
                 r.gross_margin, r.margin_pct, r.gold_weight_g, r.stone_weight_ct,
                 r.uncosted_lines]
                for r in rows
            ],
        )
    return CustomerPerformanceReport(
        date_from=date_from,
        date_to=date_to,
        rows=rows,
        customers=len({r.customer_id for r in rows}),
        revenue=sum((r.revenue for r in rows), _ZERO),
        gross_margin=sum((r.gross_margin for r in rows), _ZERO),
    )


@router.get(
    "/stock-position",
    response_model=StockPositionReport,
    dependencies=[Depends(require_perm("report:stock"))],
)
async def stock_position(db: DbSession) -> StockPositionReport:
    """
    Everything the shop is holding, in the unit it is held in, and what it is
    worth this morning.

    `/reports/stock` groups inventory rows by type and stops there — it can say
    there are 1,240 grams of raw gold, but not that they are 22k, not what they
    are worth, and not that the eight kilos beside them are silver. This answers
    the question the owner actually asks when he walks in.

    Three rules hold it together, and each of them is a thing that would
    otherwise go quietly wrong:

    * **Every metal is converted to fine grams before it is valued**, preferring
      the assayed tunch over the karat. Valuing as-weighed grams at the pure
      rate over-values every 22k bar by nine percent.
    * **Gold and silver are never added.** They differ a hundredfold in value
      and a combined "metal" figure is a number in no unit at all. The only
      place they meet is the rupee total, where they have both become money.
    * **A metal with no rate on record is reported unvalued rather than at
      zero.** A stock page that silently shows a kilo of silver as worthless is
      worse than one that says it does not know today's silver rate.

    Stones are held at what they cost — the parcels they were bought in, less
    what has been drawn out of them — because there is no market rate for a
    grade of diamond the way there is for metal.
    """
    metals = []
    total_value = _ZERO
    unpriced: list[str] = []

    for metal, inv_type in ((Metal.gold, "raw_gold"), (Metal.silver, "raw_silver")):
        weight, fine = (
            await db.execute(
                select(
                    func.coalesce(func.sum(InventoryItem.weight_g), 0),
                    func.coalesce(
                        func.sum(
                            _fine_any_metal_sql(
                                InventoryItem.weight_g,
                                InventoryItem.purity,
                                InventoryItem.tunch_pct,
                            )
                        ),
                        0,
                    ),
                ).where(InventoryItem.type == inv_type)
            )
        ).one()
        rate_row = await rate_in_force(db, currency=Currency.PKR, purity=24, metal=metal)
        rate = fine_rate_per_g(rate_row) if rate_row is not None else None
        fine_d = _d(fine).quantize(_G)
        value = (fine_d * rate).quantize(_PKR) if rate else None
        if value is not None:
            total_value += value
        elif fine_d:
            unpriced.append(metal.value)
        metals.append(
            MetalPosition(
                metal=metal,
                weight_g=_d(weight).quantize(_G),
                fine_weight_g=fine_d,
                rate_per_fine_g=rate,
                value=value,
            )
        )

    # Stones on the shelf, and what remains unconsumed of the parcels they were
    # bought in. The two are counted from different places on purpose: carats
    # come off the inventory rows the counter actually issues from, cost comes
    # off the purchase lines, and a shop whose opening stock predates the system
    # will legitimately hold more carats than it has bills for.
    stone_ct = _d(
        (
            await db.execute(
                select(func.coalesce(func.sum(InventoryItem.weight_ct), 0)).where(
                    InventoryItem.type == "raw_stone"
                )
            )
        ).scalar_one()
    ).quantize(_G)
    broken_ct = _d(
        (
            await db.execute(
                select(func.coalesce(func.sum(InventoryItem.weight_ct), 0)).where(
                    InventoryItem.type == "broken_stone"
                )
            )
        ).scalar_one()
    ).quantize(_G)

    drawn = (
        select(
            StoneDraw.purchase_item_id.label("item_id"),
            func.coalesce(func.sum(StoneDraw.weight_ct), 0).label("ct"),
        )
        .where(StoneDraw.purchase_item_id.is_not(None))
        .group_by(StoneDraw.purchase_item_id)
        .subquery()
    )
    stone_value = _d(
        (
            await db.execute(
                select(
                    func.coalesce(
                        func.sum(
                            (StonePurchaseItem.weight_ct - func.coalesce(drawn.c.ct, 0))
                            * StonePurchaseItem.rate_per_ct
                            * StonePurchaseItem.fx_rate_to_pkr
                        ),
                        0,
                    )
                ).select_from(StonePurchaseItem).outerjoin(
                    drawn, drawn.c.item_id == StonePurchaseItem.id
                )
            )
        ).scalar_one()
    ).quantize(_PKR)
    # Negative when more carats have been issued than the recorded purchases
    # cover, which is what opening stock looks like from the books' side. Held
    # at zero rather than subtracted from the shop's worth.
    stone_value = max(stone_value, _ZERO)
    total_value += stone_value

    pieces, finished_value = (
        await db.execute(
            select(
                func.count(InventoryItem.id),
                func.coalesce(func.sum(Product.material_cost), 0),
            )
            .select_from(InventoryItem)
            .join(Product, Product.id == InventoryItem.product_id, isouter=True)
            .where(InventoryItem.type == "finished_product")
        )
    ).one()
    finished_value_d = _d(finished_value).quantize(_PKR)
    total_value += finished_value_d

    return StockPositionReport(
        as_of=clock.today(),
        metals=metals,
        stone_weight_ct=stone_ct,
        stone_value=stone_value,
        broken_stone_weight_ct=broken_ct,
        finished_pieces=int(pieces or 0),
        finished_value=finished_value_d,
        total_value=total_value.quantize(_PKR),
        unpriced_metals=unpriced,
    )


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
            f"sales_{clock.today()}.csv",
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
    metal: Metal = Query(
        default=Metal.gold,
        description="Which metal to report. Gold and silver grams cannot be added together.",
    ),
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

    **One metal at a time.** The figures here are grams, and grams of gold and
    grams of silver are different assets at a hundredfold difference in value —
    summing them produces a number in no unit at all, and the report would say
    a shop losing a kilo of silver was losing a kilo of gold. So the metal is a
    filter rather than a grouping, defaulting to gold, which is what every leg
    written before silver existed is.
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
        .where(
            JobLeg.status == LegStatus.received,
            JobLeg.received_at.is_not(None),
            JobLeg.metal == metal,
            # Wastage is issued less received. A leg that issued nothing is the
            # maker working on his own gold, where that subtraction is not a
            # loss but the whole weight of the piece arriving — counted here it
            # reads as a large gain and hides every real loss beside it.
            JobLeg.gold_issued_g > 0,
        )
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
    t_owed_to_workers = _ZERO

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
        # Split by sign rather than netted.
        #
        # Excess is signed on a maker's ratti leg: positive is metal he owes,
        # negative is metal the shop owes *him* — he was entitled to keep an
        # allowance and did not take all of it. Adding those together produces
        # a figure that is neither, and calling it "loss" is worse than
        # useless: one generous settlement can cancel out a real shortfall
        # somewhere else and the report says the floor lost nothing.
        excess_d = _d(excess)
        if excess_d >= 0:
            t_excess += excess_d
        else:
            t_owed_to_workers += -excess_d

    # --- what the retired table still holds ---
    #
    # Gold only, and not by choice: the retired module never knew about silver,
    # so every row in it is gold. Folding those grams into a silver report would
    # invent silver losses out of gold history.
    legacy_total = _ZERO
    legacy_roles = (
        [
            (ManufacturingJob.karigar_id, VendorType.karigar),
            (ManufacturingJob.polish_vendor_id, VendorType.polish),
        ]
        if metal is Metal.gold
        else []
    )
    for column, role in legacy_roles:
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
        metal=metal,
        overall_karigar_loss_g=karigar_loss.quantize(_G),
        overall_polish_loss_g=polish_loss.quantize(_G),
        by_vendor=compat,
        legs=legs,
        overall_issued_g=t_issued.quantize(_G),
        overall_received_g=t_received.quantize(_G),
        overall_allowed_g=t_allowed.quantize(_G),
        overall_actual_loss_g=t_actual.quantize(_G),
        overall_excess_g=t_excess.quantize(_G),
        overall_owed_to_workers_g=t_owed_to_workers.quantize(_G),
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
            Invoice.metal_due_fine_g,
            Invoice.gold_rate_per_g,
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
    for inv_id, inv_no, currency, issued_at, total, tax, mc, metal_g, gold_rate in (
        await db.execute(stmt)
    ).all():
        # Tax is collected on the state's behalf and paid straight back out. It
        # is not the shop's money and counting it inflates profit by exactly the
        # tax — which is also what made this disagree with /reports/margin.
        revenue = (Decimal(str(total)) - Decimal(str(tax or 0))).quantize(Decimal("0.01"))
        # Metal sold for metal is still sold. A trade bill never prices its
        # gold, so `total` holds only the stones and the making — but the shop
        # has parted with the metal and is owed gold for it, and this is the
        # figure the ledger credits to Sales. Without it every wholesale bill
        # reports as a loss the size of its own gold.
        revenue += (
            Decimal(str(metal_g or 0)) * Decimal(str(gold_rate or 0))
        ).quantize(Decimal("0.01"))
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
            f"profit_{clock.today()}.csv",
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
        # Metal sold for metal is still sold. On a trade bill the gold is never
        # priced, so `invoice.total` carries only the stones and the making —
        # but the shop has parted with the metal and is owed gold for it, and
        # the ledger credits Sales with exactly this figure. Leaving it out
        # would report the whole metal side of the wholesale business as a
        # dead loss: the cost of the gold in `cost_of_goods` with no revenue
        # against it, and every lever below unattributed by the same amount.
        revenue += (
            _d(invoice.metal_due_fine_g) * _d(invoice.gold_rate_per_g)
        ).quantize(_PKR)
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
    metal: Metal = Query(
        default=Metal.gold,
        description="Which metal to report. Gold and silver grams cannot be added together.",
    ),
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
            JobLeg.metal == metal,
            # See the loss report: a leg that issued nothing has no wastage to
            # measure, only a whole piece arriving.
            JobLeg.gold_issued_g > 0,
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
            -await ledger.balance_pkr(
                db,
                account_code=SystemAccount.WORKERS_PAYABLE.value,
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
            f"worker-performance_{days}d_{clock.today()}.csv",
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
    metal: Metal = Query(
        default=Metal.gold,
        description="Which metal to report. Gold and silver grams cannot be added together.",
    ),
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
        .where(
            JobLeg.status == LegStatus.received,
            JobLeg.received_at.is_not(None),
            JobLeg.metal == metal,
            # Wastage is issued less received. A leg that issued nothing is the
            # maker working on his own gold, where that subtraction is not a
            # loss but the whole weight of the piece arriving — counted here it
            # reads as a large gain and hides every real loss beside it.
            JobLeg.gold_issued_g > 0,
        )
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
        # Gold only, and not merely by convention: `_fine_sql` scales by
        # `purity / 24`, which is the karat scale. A silver leg carries no karat
        # at all — its fineness lives in the tunch column — so it would be read
        # as pure and a kilo of silver would land in this report as a kilo of
        # fine gold.
        ).where(
            JobLeg.status == LegStatus.received,
            JobLeg.received_at.is_not(None),
            JobLeg.metal == Metal.gold,
        ),
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


@router.get(
    "/material-outside",
    response_model=MaterialOutsideReport,
    dependencies=[Depends(require_perm("report:stock"))],
)
async def material_outside(db: DbSession) -> MaterialOutsideReport:
    """
    Who is holding the shop's material right now, and for how long.

    Every other view of this answers a different question. The position report
    gives one total — "412 grams are with workers" — which is true and useless
    when you need to know whose. A party statement gives one party in full,
    which is what you read *after* you already know which party to worry about.
    Nothing said which parties, in one list, ranked by exposure.

    Three units side by side and never added, for the reason they are never
    added anywhere else in this system: a gram of gold and a gram of silver
    differ a hundredfold, and a carat is not a gram at all. A single "material
    out" column would be a number in no unit.

    Age is carried beside the weight because it is what turns an ordinary
    balance into a problem. Three hundred grams issued yesterday is a workshop
    running normally; the same three hundred grams issued in March is a
    conversation somebody has been avoiding. `overdue_legs` counts the legs
    whose agreed metal-return date has passed — the shop's own deadline, not an
    arbitrary ageing bucket.

    Read from the ledger rather than from open job legs. The legs say what was
    *issued*; the ledger says what is still out after everything that has come
    back, which is the question. A worker with ten closed legs and one gram
    unaccounted for appears here with one gram, and the legs alone would have
    shown him as clear.
    """
    accounts = {
        SystemAccount.GOLD_WITH_WORKERS.value: (Commodity.GOLD, "gold_g"),
        SystemAccount.SILVER_WITH_WORKERS.value: (Commodity.SILVER, "silver_g"),
        SystemAccount.STONES_WITH_WORKERS.value: (Commodity.STONE, "stone_ct"),
    }

    rows: dict[tuple[str, int], dict] = {}

    for code, (commodity, field) in accounts.items():
        # Account *and* commodity together, the same pairing the position
        # report uses: a line posted to the silver account carrying the gold
        # commodity — the one mistake a metal-aware path can make — falls out
        # of both readings rather than quietly inflating one.
        stmt = (
            select(
                JournalLine.party_type,
                JournalLine.party_id,
                func.coalesce(func.sum(JournalLine.quantity), 0),
            )
            .join(Account, Account.id == JournalLine.account_id)
            .where(
                Account.code == code,
                JournalLine.commodity == commodity,
                JournalLine.party_id.is_not(None),
            )
            .group_by(JournalLine.party_type, JournalLine.party_id)
        )
        for party_type, party_id, qty in (await db.execute(stmt)).all():
            if _d(qty) == _ZERO:
                continue
            key = (party_type.value, party_id)
            rows.setdefault(
                key, {"party_type": party_type, "party_id": party_id}
            )[field] = _d(qty)

    # The money half. Fetched for parties already on the list rather than for
    # everyone: this report is about material, and a worker owed labour who
    # holds nothing does not belong on a page titled "material outside".
    if rows:
        cash_stmt = (
            select(
                JournalLine.party_type,
                JournalLine.party_id,
                func.coalesce(func.sum(JournalLine.value_pkr), 0),
            )
            .join(Account, Account.id == JournalLine.account_id)
            .where(
                Account.code == SystemAccount.WORKERS_PAYABLE.value,
                JournalLine.party_id.is_not(None),
            )
            .group_by(JournalLine.party_type, JournalLine.party_id)
        )
        for party_type, party_id, amount in (await db.execute(cash_stmt)).all():
            row = rows.get((party_type.value, party_id))
            if row is not None:
                # Negated so positive reads "the shop owes them", which is how
                # a payable is spoken about; the ledger carries it as a credit.
                row["cash_balance"] = -_d(amount)

    # Names, trades, and how long the oldest open leg has been out.
    worker_ids = [pid for (ptype, pid) in rows if ptype == PartyType.worker.value]
    vendors: dict[int, Vendor] = {}
    if worker_ids:
        vendors = {
            v.id: v
            for v in (
                (
                    await db.execute(
                        select(Vendor).where(Vendor.id.in_(worker_ids))
                    )
                )
                .unique()
                .scalars()
                .all()
            )
        }

    ages: dict[int, tuple[int, date | None, int]] = {}
    if worker_ids:
        age_stmt = (
            select(
                JobLeg.worker_id,
                func.count(JobLeg.id),
                func.min(JobLeg.issued_at),
                func.count(JobLeg.id).filter(
                    JobLeg.metal_due_date.is_not(None),
                    JobLeg.metal_due_date < clock.today(),
                ),
            )
            .where(
                JobLeg.worker_id.in_(worker_ids),
                JobLeg.status == LegStatus.issued,
            )
            .group_by(JobLeg.worker_id)
        )
        for wid, open_legs, oldest, overdue in (await db.execute(age_stmt)).all():
            ages[wid] = (int(open_legs), oldest.date() if oldest else None, int(overdue or 0))

    today = clock.today()
    out: list[MaterialOutsideRow] = []
    for (ptype, pid), data in rows.items():
        vendor = vendors.get(pid) if ptype == PartyType.worker.value else None
        open_legs, oldest, overdue = ages.get(pid, (0, None, 0))
        out.append(
            MaterialOutsideRow(
                party_type=data["party_type"],
                party_id=pid,
                party_name=vendor.name if vendor else None,
                department=(
                    vendor.department.name if vendor and vendor.department else None
                ),
                gold_g=data.get("gold_g", _ZERO),
                silver_g=data.get("silver_g", _ZERO),
                stone_ct=data.get("stone_ct", _ZERO),
                cash_balance=data.get("cash_balance", _ZERO),
                open_legs=open_legs,
                oldest_issue_date=oldest,
                days_out=(today - oldest).days if oldest else None,
                overdue_legs=overdue,
            )
        )

    # Ranked by gold, which is what a jeweller means by exposure. Silver and
    # stones break the tie rather than being added to it.
    out.sort(key=lambda r: (r.gold_g, r.silver_g, r.stone_ct), reverse=True)

    return MaterialOutsideReport(
        as_of=today,
        rows=out,
        total_gold_g=sum((r.gold_g for r in out), _ZERO),
        total_silver_g=sum((r.silver_g for r in out), _ZERO),
        total_stone_ct=sum((r.stone_ct for r in out), _ZERO),
        parties=len(out),
    )


def _window_before(start: date, end: date) -> tuple[date, date]:
    """
    The equal stretch immediately before this one.

    Equal in *days*, not in calendar months. Comparing a 31-day August against
    a 28-day February would make February look like a collapse, and the shop
    would go looking for a problem that was a calendar.
    """
    span = (end - start).days
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=span), prev_end


async def _trading(
    db: DbSession, *, label: str, start: date, end: date, basis: ProfitBasis
) -> tuple[PeriodSummary, list[str]]:
    """One period's trading, from the same report the Profit screen reads."""
    split = await profit_split_report(
        db, date_from=start, date_to=end, currency=Currency.PKR, basis=basis, format="json"
    )
    flow = await cash_flow(db, date_from=start, date_to=end, format="json")

    # Money out of the drawer and the bank together. Not the same as "expenses"
    # in the accounting sense — it includes suppliers paid and wages, which are
    # cash leaving whether or not they are a cost of this period — and the page
    # says so rather than labelling it profit.
    expenses = _d(flow.money_out)
    margin = _d(split.gross_margin)
    return (
        PeriodSummary(
            label=label,
            date_from=start,
            date_to=end,
            invoices=split.lines,
            sales=_d(split.revenue),
            cost_of_goods=_d(split.cost),
            gross_margin=margin,
            margin_pct=_pct(margin, _d(split.revenue)) if _d(split.revenue) else None,
            expenses=expenses,
            net=(margin - expenses).quantize(_PKR),
            cash_opened=(_d(flow.opening_cash) + _d(flow.opening_bank)).quantize(_PKR),
            cash_closed=(_d(flow.closing_cash) + _d(flow.closing_bank)).quantize(_PKR),
        ),
        list(split.assumptions),
    )


@router.get(
    "/overview",
    response_model=OverviewReport,
    dependencies=[Depends(require_perm("report:profit"))],
)
async def business_overview(
    db: DbSession,
    current: CurrentUser,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    basis: ProfitBasis | None = Query(default=None),
):
    """
    The whole business on one page: what it is worth, and how it is trading.

    **Every figure is fetched from the screen that owns it** — stock values from
    the stock position, trading from the profit split, cash from the cash flow —
    rather than re-derived here. A second definition of net worth is a second
    thing to disagree with the first, and this page exists to be the one a
    partner is shown.

    It is also only honest because the shelves and the books now agree. Until
    the four write paths that moved stock without the ledger were closed, the
    metal line alone could have been out by a hundred and twenty million rupees
    depending on which table it read.

    **Worth and trading are never added together.** A shop can trade flat and be
    materially richer because the rate moved, or trade well and be poorer.
    Adding them produces a number that answers neither question.
    """
    chosen = basis or ProfitBasis(settings.default_profit_basis)
    today = clock.today()
    end = date_to or today
    start = date_from or end.replace(day=1)

    stock = await stock_position(db)
    pos = await position_report(db)

    owned: list[WorthLine] = [
        WorthLine(key="cash", label="Cash in hand", amount=_d(pos.cash_in_hand), to="/cash"),
        WorthLine(
            key="bank",
            label="Bank",
            amount=await ledger.balance_pkr(db, account_code=SystemAccount.BANK.value),
            to="/cash",
        ),
    ]
    for m in stock.metals:
        owned.append(
            WorthLine(
                key=m.metal.value,
                label=f"{m.metal.value.title()} in hand",
                amount=_d(m.value) if m.value is not None else _ZERO,
                detail=f"{m.fine_weight_g} fine g"
                + ("" if m.value is not None else " — no rate on record"),
                to="/stock",
            )
        )
    owned.append(
        WorthLine(
            key="stones",
            label="Stones at cost",
            amount=_d(stock.stone_value),
            detail=f"{stock.stone_weight_ct} ct",
            to="/purchasing/stone-stock",
        )
    )
    owned.append(
        WorthLine(
            key="finished",
            label="Finished pieces at cost",
            amount=_d(stock.finished_value),
            detail=f"{stock.finished_pieces} piece(s)",
            to="/products",
        )
    )
    owned.append(
        WorthLine(
            key="receivable",
            label="Owed to us by customers",
            amount=_d(pos.customer_receivable),
            to="/customers",
        )
    )

    # Payables are held as positive numbers on the position report — the shop
    # reads them as "what we owe" — so they are negated here to sit in a column
    # that sums.
    owed: list[WorthLine] = [
        WorthLine(
            key="suppliers",
            label="Owed to dealers",
            amount=-_d(pos.supplier_payable),
            to="/purchasing/bills",
        ),
        WorthLine(
            key="workers",
            label="Owed to workers",
            amount=-_d(pos.worker_payable),
            to="/material-outside",
        ),
    ]

    total_owned = sum((l.amount for l in owned), _ZERO).quantize(_PKR)
    total_owed = sum((l.amount for l in owed), _ZERO).quantize(_PKR)

    period, assumptions = await _trading(
        db, label="This period", start=start, end=end, basis=chosen
    )
    p_start, p_end = _window_before(start, end)
    previous, _ = await _trading(
        db, label="Previous", start=p_start, end=p_end, basis=chosen
    )

    bills = await purchasing.supplier_bills(db)
    overdue = [b for b in bills if b.status is purchasing.BillStatus.overdue]

    return OverviewReport(
        as_of=today,
        worth=NetWorth(
            as_of=today,
            owned=owned,
            owed=owed,
            total_owned=total_owned,
            total_owed=total_owed,
            net_worth=(total_owned + total_owed).quantize(_PKR),
            unpriced=list(stock.unpriced_metals),
        ),
        period=period,
        previous=previous,
        metal_outside_g=_d(pos.gold_with_workers_g),
        overdue_bills=len(overdue),
        overdue_bill_amount=sum((b.outstanding for b in overdue), _ZERO).quantize(_PKR),
        basis=chosen.value,
        assumptions=assumptions,
    )
