"""
Analysis over the books — "what am I losing and to whom", and "why is this sale
thin". Plus a natural-language question box over the same data.

The arithmetic here is ordinary SQL and Decimal. A model, when one is
configured, is handed the figures that were already computed and asked only to
write the sentence that explains them. Every endpoint below returns its full
result with `narrative` left null when no provider is set; only `/ask` — whose
entire job is to have a model write a query — refuses to work without one.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select

from app.api.deps import DbSession, require_perm
from app.models.customer import Customer
from app.models.department import Department
from app.models.design import Design, JobLeg, LegStatus
from app.models.invoice import Invoice, InvoiceItem, InvoiceStatus
from app.models.product import Product
from app.models.vendor import Vendor
from app.schemas.insights import (
    AskRequest,
    AskResponse,
    ChatRequest,
    ChatResponse,
    CustomerDiscountRow,
    MarginRow,
    MarginWatchReport,
    WastageAnomalyReport,
    WastageHalf,
    WastageJobRef,
    WastageWorkerRow,
)
from app.services import ai

router = APIRouter()
# Staff hold `report:loss` so they can see shop-wide wastage on the reports
# screen, but this analysis names individual workers and the metal each still
# owes. That is owner information — the same line drawn around the ledger — so
# every endpoint here is gated on the money permission instead.
loss = Depends(require_perm("report:profit"))
profit = Depends(require_perm("report:profit"))

_ZERO = Decimal("0")
_G = Decimal("0.0001")
_PKR = Decimal("0.01")
_PCT = Decimal("0.01")

# A worker needs this many finished legs on *each* side of the window before a
# change in his rate is treated as a trend. Two bad legs in a fortnight is a
# bad fortnight; that is not what this report is for.
MIN_LEGS_PER_HALF = 3
# Below this, a wastage difference is not worth a shop owner's attention: it is
# inside the noise of a bench scale and of how carefully each piece was weighed.
# Expressed in grams because that is what the owner would have to go and argue
# about with the worker.
MIN_MATERIAL_GRAMS = Decimal("0.5")
# "Up by more than half again" — the rate has to move by 50% to count, so
# ordinary drift between one month and the next stays quiet.
DETERIORATION_RATIO = Decimal("1.5")


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    if whole == 0:
        return _ZERO
    return (part / whole * Decimal("100")).quantize(_PCT)


def _window(days: int) -> tuple[datetime, datetime, datetime]:
    now = datetime.now(timezone.utc)
    return now - timedelta(days=days), now - timedelta(days=days / 2), now


# --------------------------------------------------------------------------
# 1. Wastage anomalies
# --------------------------------------------------------------------------
@router.get("/wastage-anomalies", response_model=WastageAnomalyReport, dependencies=[loss])
async def wastage_anomalies(
    db: DbSession,
    days: int = Query(default=90, ge=14, le=730),
) -> WastageAnomalyReport:
    """
    Where the metal is going, per worker, and whose figures have moved.

    Two different questions, because they catch different people. The *level*
    question — whose losses run furthest past what he was allowed — finds the
    worker who has always been expensive. The *trend* question compares each
    worker's recent half of the window against his own earlier half, which
    finds the one who was fine until something changed. A shop watching only
    the first never notices the second until the year-end count.

    Comparing a worker against himself rather than against the shop is
    deliberate: casting and setting lose metal at completely different rates,
    so a shop-wide league table just ranks departments.
    """
    start, midpoint, end = _window(days)

    rows = (
        await db.execute(
            select(
                JobLeg.id,
                JobLeg.worker_id,
                Vendor.name,
                Design.design_no,
                Department.name,
                JobLeg.received_at,
                JobLeg.gold_issued_g,
                JobLeg.gold_received_g,
                JobLeg.wastage_actual_g,
                JobLeg.wastage_allowed_g,
                JobLeg.wastage_excess_g,
            )
            .join(Design, Design.id == JobLeg.design_id)
            .join(Department, Department.id == JobLeg.department_id)
            .join(Vendor, Vendor.id == JobLeg.worker_id, isouter=True)
            .where(
                JobLeg.status == LegStatus.received,
                JobLeg.received_at.is_not(None),
                JobLeg.received_at >= start,
                JobLeg.received_at <= end,
            )
            .order_by(JobLeg.received_at)
        )
    ).all()

    # Aggregated in Python rather than in three grouped queries: the halves,
    # the legs to cite and the totals all come off the same pass, and a shop's
    # quarter of finished legs is a small list.
    workers: dict[int | None, dict] = {}
    for (
        leg_id,
        worker_id,
        worker_name,
        design_no,
        department,
        received_at,
        issued,
        received,
        actual,
        allowed,
        excess,
    ) in rows:
        agg = workers.setdefault(
            worker_id,
            {
                "name": worker_name or "Unassigned",
                "legs": 0,
                "issued": _ZERO,
                "actual": _ZERO,
                "allowed": _ZERO,
                "excess": _ZERO,
                "halves": {
                    "earlier": {"legs": 0, "issued": _ZERO, "actual": _ZERO},
                    "recent": {"legs": 0, "issued": _ZERO, "actual": _ZERO},
                },
                "cited": [],
            },
        )
        issued_d, actual_d, excess_d = _d(issued), _d(actual), _d(excess)
        agg["legs"] += 1
        agg["issued"] += issued_d
        agg["actual"] += actual_d
        agg["allowed"] += _d(allowed)
        agg["excess"] += excess_d

        half = agg["halves"]["recent" if received_at >= midpoint else "earlier"]
        half["legs"] += 1
        half["issued"] += issued_d
        half["actual"] += actual_d

        agg["cited"].append(
            WastageJobRef(
                leg_id=leg_id,
                design_no=design_no,
                department=department,
                received_at=received_at,
                issued_g=issued_d.quantize(_G),
                received_g=_d(received).quantize(_G),
                excess_g=excess_d.quantize(_G),
            )
        )

    shop_issued = sum((a["issued"] for a in workers.values()), _ZERO)
    shop_actual = sum((a["actual"] for a in workers.values()), _ZERO)
    shop_excess = sum((a["excess"] for a in workers.values()), _ZERO)

    # The worst excess-to-allowance ratio in the shop. Ratio rather than raw
    # grams so a worker who handles a lot of metal isn't automatically the
    # answer — this is "who overran his own terms by the most".
    # Floored on both sides. Without a floor on the allowance, a worker allowed
    # 0.01g who overran by 0.02g outranks one who lost half a kilo; without a
    # floor on the excess, someone is flagged as "worst" whenever any excess
    # exists anywhere, even when the whole shop is doing fine.
    ratios = {
        wid: (a["excess"] / a["allowed"]).quantize(_PCT)
        for wid, a in workers.items()
        if a["allowed"] >= MIN_MATERIAL_GRAMS and a["excess"] >= MIN_MATERIAL_GRAMS
    }
    worst_id = max(ratios, key=lambda k: ratios[k]) if ratios else None

    out: list[WastageWorkerRow] = []
    for wid, a in workers.items():
        earlier = a["halves"]["earlier"]
        recent = a["halves"]["recent"]
        earlier_rate = _pct(earlier["actual"], earlier["issued"])
        recent_rate = _pct(recent["actual"], recent["issued"])

        flags: list[str] = []
        # Both halves need enough legs, and the earlier rate has to be a real
        # positive baseline — a worker whose earlier half netted zero or came
        # back heavier has no rate to have got worse than.
        # A ratio alone flags noise. A worker whose wastage went from 0.02g to
        # 0.04g across six small legs trips the same threshold as one losing
        # hundreds of grams, and a report that cries wolf gets ignored — which
        # costs more than not having it. The extra grams have to be worth
        # chasing in their own right as well as proportionally.
        extra_g = (recent["actual"] - recent["issued"] * earlier_rate / Decimal("100")).quantize(_G)
        if (
            earlier["legs"] >= MIN_LEGS_PER_HALF
            and recent["legs"] >= MIN_LEGS_PER_HALF
            and earlier_rate > 0
            and recent_rate > earlier_rate * DETERIORATION_RATIO
            and extra_g >= MIN_MATERIAL_GRAMS
        ):
            flags.append("deteriorating")
        if wid is not None and wid == worst_id:
            flags.append("worst_excess_ratio")

        out.append(
            WastageWorkerRow(
                worker_id=wid,
                worker_name=a["name"],
                legs=a["legs"],
                issued_g=a["issued"].quantize(_G),
                actual_wastage_g=a["actual"].quantize(_G),
                allowed_g=a["allowed"].quantize(_G),
                excess_g=a["excess"].quantize(_G),
                wastage_rate_pct=_pct(a["actual"], a["issued"]),
                excess_to_allowance=ratios.get(wid),
                earlier=WastageHalf(
                    legs=earlier["legs"],
                    issued_g=earlier["issued"].quantize(_G),
                    actual_g=earlier["actual"].quantize(_G),
                    rate_pct=earlier_rate,
                ),
                recent=WastageHalf(
                    legs=recent["legs"],
                    issued_g=recent["issued"].quantize(_G),
                    actual_g=recent["actual"].quantize(_G),
                    rate_pct=recent_rate,
                ),
                flags=flags,
                # The legs behind the number, so the flag is checkable against
                # the job card rather than being taken on trust.
                worst_legs=sorted(a["cited"], key=lambda c: c.excess_g, reverse=True)[:3],
            )
        )

    out.sort(key=lambda r: (not r.flags, -r.excess_g, -r.actual_wastage_g))

    flagged = [r for r in out if r.flags]
    narratives = await ai.narrate_map(
        task=(
            "Each key is a worker flagged by a wastage report at a gold "
            "jewellery workshop. Explain in one sentence what his figures show "
            "— the change between the earlier and recent half of the window, or "
            "how far his losses ran past what he was allowed — and name one or "
            "two of the cited design numbers."
        ),
        payload={
            "window_days": days,
            "shop_wastage_rate_pct": str(_pct(shop_actual, shop_issued)),
            "workers": {
                str(r.worker_id): r.model_dump(mode="json", exclude={"narrative"})
                for r in flagged
            },
        },
        keys=[str(r.worker_id) for r in flagged],
    )
    for r in flagged:
        r.narrative = narratives.get(str(r.worker_id))

    return WastageAnomalyReport(
        days=days,
        period_from=start.date(),
        period_to=end.date(),
        midpoint=midpoint.date(),
        min_legs_per_half=MIN_LEGS_PER_HALF,
        deterioration_ratio=DETERIORATION_RATIO,
        shop_issued_g=shop_issued.quantize(_G),
        shop_actual_wastage_g=shop_actual.quantize(_G),
        shop_excess_g=shop_excess.quantize(_G),
        shop_wastage_rate_pct=_pct(shop_actual, shop_issued),
        rows=out,
        flagged_count=len(flagged),
        ai_enabled=ai.ai_available(),
        ai_note=ai.ai_settings().unconfigured_reason,
    )


# --------------------------------------------------------------------------
# 2. Margin watch
# --------------------------------------------------------------------------
@router.get("/margin-watch", response_model=MarginWatchReport, dependencies=[profit])
async def margin_watch(
    db: DbSession,
    days: int = Query(default=90, ge=7, le=730),
    floor_margin_pct: Decimal = Query(default=Decimal("5"), ge=-100, le=100),
) -> MarginWatchReport:
    """
    Which sales came in thin, and which customers are being given the most away.

    COGS is the same figure `/reports/profit` uses — `product.total_cost` (the
    making cost) plus `product.material_cost` (the capitalised gold and stones)
    — because a margin that ignores the metal is not a margin. A line with no
    product behind it contributes nothing to COGS, so those invoices are marked
    `cogs_incomplete` rather than being shown as unusually profitable.

    Discount is measured against gross rather than against the invoice total,
    so a line discount and an invoice-level one count the same way: the shop
    gave money away, and it doesn't matter which box it was typed into.
    """
    start, _, end = _window(days)

    per_invoice = (
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
            ).label("cogs"),
            func.coalesce(func.sum(InvoiceItem.line_discount), 0).label("line_discount"),
            func.count(case((Product.id.is_(None), 1))).label("unpriced_lines"),
        )
        .join(Product, Product.id == InvoiceItem.product_id, isouter=True)
        .group_by(InvoiceItem.invoice_id)
        .subquery()
    )

    hits = (
        await db.execute(
            select(
                Invoice.id,
                Invoice.invoice_no,
                Invoice.customer_id,
                Customer.name,
                Invoice.currency,
                Invoice.issued_at,
                Invoice.subtotal,
                Invoice.discount_amount,
                Invoice.discount_weight_g,
                Invoice.gold_rate_per_g,
                Invoice.tax_amount,
                Invoice.total,
                func.coalesce(per_invoice.c.cogs, 0),
                func.coalesce(per_invoice.c.line_discount, 0),
                func.coalesce(per_invoice.c.unpriced_lines, 0),
            )
            .join(Customer, Customer.id == Invoice.customer_id)
            .join(per_invoice, per_invoice.c.invoice_id == Invoice.id, isouter=True)
            .where(
                Invoice.status.in_((InvoiceStatus.issued, InvoiceStatus.paid)),
                Invoice.issued_at.is_not(None),
                Invoice.issued_at >= start,
                Invoice.issued_at <= end,
            )
            .order_by(Invoice.issued_at.desc())
        )
    ).all()

    rows: list[MarginRow] = []
    customers: dict[int, dict] = {}
    total_revenue = total_cogs = total_gross = total_discount = _ZERO

    for (
        inv_id,
        inv_no,
        cust_id,
        cust_name,
        currency,
        issued_at,
        subtotal,
        discount_amount,
        discount_weight_g,
        gold_rate,
        tax_amount,
        total,
        cogs,
        line_discount,
        unpriced,
    ) in hits:
        revenue = _d(total)
        cost = _d(cogs).quantize(_PKR)
        profit_amt = (revenue - cost).quantize(_PKR)
        # A weight discount is money too — it is grams the customer was not
        # billed for, valued at the rate the invoice was struck on.
        weight_discount = (_d(discount_weight_g) * _d(gold_rate)).quantize(_PKR)
        discount = (_d(line_discount) + _d(discount_amount) + weight_discount).quantize(_PKR)
        gross = (_d(subtotal) + _d(line_discount)).quantize(_PKR)

        margin = _pct(profit_amt, revenue) if revenue > 0 else None
        flags: list[str] = []
        if margin is not None and margin < floor_margin_pct:
            flags.append("below_floor_margin")

        rows.append(
            MarginRow(
                invoice_id=inv_id,
                invoice_no=inv_no,
                customer_id=cust_id,
                customer_name=cust_name,
                currency=currency.value,
                issued_at=issued_at,
                revenue=revenue.quantize(_PKR),
                cogs=cost,
                profit=profit_amt,
                margin_pct=margin,
                cogs_incomplete=bool(unpriced),
                flags=flags,
            )
        )

        total_revenue += revenue
        total_cogs += cost
        total_gross += gross
        total_discount += discount
        agg = customers.setdefault(
            cust_id,
            {"name": cust_name, "invoices": 0, "gross": _ZERO, "discount": _ZERO},
        )
        agg["invoices"] += 1
        agg["gross"] += gross
        agg["discount"] += discount

    shop_discount_pct = _pct(total_discount, total_gross)

    customer_rows: list[CustomerDiscountRow] = []
    for cid, a in customers.items():
        pct = _pct(a["discount"], a["gross"])
        above = (pct - shop_discount_pct).quantize(_PCT)
        flags = []
        # Both tests have to pass. The ratio alone flags everyone when the shop
        # barely discounts at all (0.2% against 0.1% is "double"), and the
        # points gap alone flags nobody in a shop that discounts heavily. One
        # invoice is a negotiation, not a pattern.
        if (
            a["invoices"] >= 2
            and pct > shop_discount_pct * Decimal("1.5")
            and above >= Decimal("1")
        ):
            flags.append("high_discount")
        customer_rows.append(
            CustomerDiscountRow(
                customer_id=cid,
                customer_name=a["name"],
                invoices=a["invoices"],
                gross=a["gross"].quantize(_PKR),
                discount=a["discount"].quantize(_PKR),
                discount_pct=pct,
                above_shop_avg_pp=above,
                flags=flags,
            )
        )

    rows.sort(key=lambda r: (not r.flags, r.margin_pct if r.margin_pct is not None else _ZERO))
    customer_rows.sort(key=lambda c: (not c.flags, -c.discount_pct))

    flagged_rows = [r for r in rows if r.flags]
    flagged_customers = [c for c in customer_rows if c.flags]

    narratives = await ai.narrate_map(
        task=(
            "Each key names either a thin invoice (invoice:<id>) or a customer "
            "receiving above-average discount (customer:<id>) at a gold "
            "jewellery shop. Explain in one sentence why that row was flagged, "
            "quoting the invoice number or customer name and the figures given. "
            "Note when cogs_incomplete is true that the cost is only partial."
        ),
        payload={
            "window_days": days,
            "floor_margin_pct": str(floor_margin_pct),
            "shop_margin_pct": str(_pct(total_revenue - total_cogs, total_revenue)),
            "shop_discount_pct": str(shop_discount_pct),
            "invoices": {
                f"invoice:{r.invoice_id}": r.model_dump(mode="json", exclude={"narrative"})
                for r in flagged_rows[:20]
            },
            "customers": {
                f"customer:{c.customer_id}": c.model_dump(mode="json", exclude={"narrative"})
                for c in flagged_customers[:20]
            },
        },
        keys=[f"invoice:{r.invoice_id}" for r in flagged_rows[:20]]
        + [f"customer:{c.customer_id}" for c in flagged_customers[:20]],
    )
    for r in flagged_rows:
        r.narrative = narratives.get(f"invoice:{r.invoice_id}")
    for c in flagged_customers:
        c.narrative = narratives.get(f"customer:{c.customer_id}")

    return MarginWatchReport(
        days=days,
        period_from=start.date(),
        period_to=end.date(),
        floor_margin_pct=Decimal(str(floor_margin_pct)),
        revenue=total_revenue.quantize(_PKR),
        cogs=total_cogs.quantize(_PKR),
        profit=(total_revenue - total_cogs).quantize(_PKR),
        margin_pct=_pct(total_revenue - total_cogs, total_revenue) if total_revenue > 0 else None,
        shop_discount_pct=shop_discount_pct,
        rows=rows,
        customers=customer_rows,
        flagged_count=len(flagged_rows) + len(flagged_customers),
        ai_enabled=ai.ai_available(),
        ai_note=ai.ai_settings().unconfigured_reason,
    )


# --------------------------------------------------------------------------
# 3. Ask
# --------------------------------------------------------------------------
@router.post("/ask", response_model=AskResponse, dependencies=[profit])
async def ask(payload: AskRequest, db: DbSession) -> AskResponse:
    """
    A question in English, Urdu or Roman-Urdu, answered off the books.

    Owner-level (`report:profit`) because a generated query can read anything
    in the curated schema — customer balances and margins included — so this
    endpoint is exactly as sensitive as the most sensitive table it can reach.

    The generated SQL comes back with the rows. That is not a debugging
    convenience: it is the only way the owner can tell an answer that is right
    from one that is confidently wrong, and it is why the model is never asked
    to state a figure that isn't in a returned row.
    """
    generated = await ai.generate_sql(payload.question.strip())
    columns, rows = await ai.run_select(db, generated.sql)
    answer = await ai.answer_from_rows(
        question=payload.question.strip(),
        sql=generated.sql,
        columns=columns,
        rows=rows,
    )
    return AskResponse(
        question=payload.question.strip(),
        sql=generated.sql,
        model=generated.model,
        notes=generated.notes,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=len(rows) >= ai.MAX_ROWS,
        answer=answer,
    )


@router.post("/chat", response_model=ChatResponse, dependencies=[profit])
async def chat(payload: ChatRequest, db: DbSession) -> ChatResponse:
    """
    A conversation with the shop's own records, and with its manual.

    Owner-level for the same reason `/ask` is: a data question here takes
    exactly that path — generated SELECT, validated, planner-checked against the
    table allowlist, executed read-only — so this endpoint is as sensitive as
    the most sensitive table that path can reach. It can read anything in the
    curated schema and it can write nothing.

    The transcript arrives with each request rather than being held here. A chat
    is not a business record, and storing threads would mean answering who else
    may read them — a question the shop has not asked and should not have
    imposed on it.
    """
    turn = await ai.chat(db, [m.model_dump() for m in payload.messages])
    return ChatResponse(
        reply=turn.reply,
        kind=turn.kind,
        sql=turn.sql,
        columns=turn.columns,
        rows=turn.rows,
        notes=turn.notes,
        model=turn.model,
    )
