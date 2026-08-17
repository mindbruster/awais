"""
Who brings the business, and what they are asked to bring.

Sellers and targets sit in one module because neither is useful alone: a target
with nobody to hold it, or a salesman with no figure to hit, is half a feature.

Progress is computed on every read rather than stored. That is the whole design
decision here — a cached actual drifts from the sales it measures the first time
a bill is voided, and the shop then argues with a number the system is still
confidently printing.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from decimal import Decimal

from sqlalchemy import case, func, or_, select

from app.api.deps import CurrentUser, DbSession, require_perm
from app.core import clock
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem, InvoiceStatus
from app.models.payment import Payment
from app.models.product import Product
from app.models.sales import SalesTarget, Seller, SellerKind, TargetScope
from app.schemas.sales import (
    SalesTargetCreate,
    SalesTargetRead,
    SellerCreate,
    SellerCustomerRow,
    SellerInvoiceRow,
    SellerPerformance,
    SellerRead,
    SellerUpdate,
)
from app.services.audit import log_action
from app.services.ledger import d

router = APIRouter()
read = Depends(require_perm("seller:read"))
write = Depends(require_perm("seller:write"))
# Targets are money figures about people. Held to the same line as the sales
# report rather than to the one that lets the counter look up a salesman's
# phone number.
target_read = Depends(require_perm("report:sales"))

_ZERO = d(0)
_PKR = d("0.01")
_G = d("0.0001")
_PCT = d("0.01")


# ---------------------------------------------------------------------------
# Sellers
# ---------------------------------------------------------------------------
@router.get("/sellers", response_model=list[SellerRead], dependencies=[read])
async def list_sellers(
    db: DbSession,
    kind: SellerKind | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    q: str | None = Query(default=None),
) -> list[Seller]:
    stmt = select(Seller).order_by(Seller.name)
    if kind is not None:
        stmt = stmt.where(Seller.kind == kind)
    if is_active is not None:
        stmt = stmt.where(Seller.is_active == is_active)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Seller.name.ilike(like), Seller.phone.ilike(like)))
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "/sellers", response_model=SellerRead, status_code=status.HTTP_201_CREATED,
    dependencies=[write],
)
async def create_seller(payload: SellerCreate, db: DbSession, current: CurrentUser) -> Seller:
    row = Seller(**payload.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await log_action(
        db, user=current, action="seller.create", resource_type="seller", resource_id=row.id,
        details={"name": row.name, "kind": row.kind.value},
    )
    await db.commit()
    return row


@router.patch("/sellers/{seller_id}", response_model=SellerRead, dependencies=[write])
async def update_seller(seller_id: int, payload: SellerUpdate, db: DbSession) -> Seller:
    row = await db.get(Seller, seller_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Salesman or broker not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/sellers/{seller_id}", response_model=SellerRead, dependencies=[read])
async def get_seller(seller_id: int, db: DbSession) -> Seller:
    row = await db.get(Seller, seller_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Salesman or broker not found")
    return row


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------
async def _progress(db: DbSession, t: SalesTarget) -> tuple:
    """
    What was actually sold against this target, in both units.

    Scoped three ways and the scope decides the filter: a company target counts
    every bill, a customer's counts theirs, a salesman's counts what he brought.
    Draft and void bills are excluded — a target measured against documents that
    were never issued would be met by typing.

    Weight is summed off the line items, not the invoice, because the invoice
    has no weight of its own. It is as-weighed grams rather than fine: a gram
    target is a selling target, and the counter sells 22k by the gram on the
    scale, not by its pure content.
    """
    money_q = (
        select(
            func.count(func.distinct(Invoice.id)),
            func.coalesce(
                func.sum(Invoice.total * func.coalesce(Invoice.fx_rate_to_pkr, 1)), 0
            ),
            func.max(Invoice.issued_at),
        )
        .where(
            Invoice.status.in_((InvoiceStatus.issued, InvoiceStatus.paid)),
            func.date(Invoice.issued_at) >= t.period_start,
            func.date(Invoice.issued_at) <= t.period_end,
        )
    )
    weight_q = (
        select(func.coalesce(func.sum(InvoiceItem.gold_weight_g * InvoiceItem.quantity), 0))
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(
            Invoice.status.in_((InvoiceStatus.issued, InvoiceStatus.paid)),
            func.date(Invoice.issued_at) >= t.period_start,
            func.date(Invoice.issued_at) <= t.period_end,
        )
    )
    if t.scope is TargetScope.customer:
        money_q = money_q.where(Invoice.customer_id == t.customer_id)
        weight_q = weight_q.where(Invoice.customer_id == t.customer_id)
    elif t.scope is TargetScope.seller:
        money_q = money_q.where(Invoice.seller_id == t.seller_id)
        weight_q = weight_q.where(Invoice.seller_id == t.seller_id)

    invoices, amount, last = (await db.execute(money_q)).one()
    weight = (await db.execute(weight_q)).scalar_one()
    return int(invoices or 0), d(amount), d(weight), last


def _pct(part, whole):
    if not whole:
        return None
    return (d(part) / d(whole) * d(100)).quantize(_PCT)


async def _target_read(db: DbSession, t: SalesTarget) -> SalesTargetRead:
    invoices, amount, weight, last = await _progress(db, t)
    today = clock.today()
    # How much of the window has gone. Shown beside the percentages because
    # "60% of target" reads very differently on day three than on day thirty,
    # and a reader without it will draw the wrong conclusion from the same
    # number twice a month.
    span = (t.period_end - t.period_start).days + 1
    gone = min(max((today - t.period_start).days + 1, 0), span)
    return SalesTargetRead(
        id=t.id,
        created_at=t.created_at,
        updated_at=t.updated_at,
        scope=t.scope,
        customer_id=t.customer_id,
        customer_name=t.customer.name if t.customer else None,
        seller_id=t.seller_id,
        seller_name=t.seller.name if t.seller else None,
        period_start=t.period_start,
        period_end=t.period_end,
        label=t.label,
        target_amount=d(t.target_amount) if t.target_amount is not None else None,
        target_weight_g=d(t.target_weight_g) if t.target_weight_g is not None else None,
        notes=t.notes,
        actual_amount=amount.quantize(_PKR),
        actual_weight_g=weight.quantize(_G),
        invoices=invoices,
        amount_pct=_pct(amount, t.target_amount) if t.target_amount else None,
        weight_pct=_pct(weight, t.target_weight_g) if t.target_weight_g else None,
        period_elapsed_pct=_pct(gone, span) if span else None,
        last_sale_at=last,
    )


@router.get("/targets", response_model=list[SalesTargetRead], dependencies=[target_read])
async def list_targets(
    db: DbSession,
    scope: TargetScope | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    seller_id: int | None = Query(default=None),
    on: date | None = Query(
        default=None, description="Only targets whose period covers this date."
    ),
    limit: int = Query(default=100, le=500),
) -> list[SalesTargetRead]:
    stmt = (
        select(SalesTarget)
        .order_by(SalesTarget.period_start.desc(), SalesTarget.id.desc())
        .limit(limit)
    )
    if scope is not None:
        stmt = stmt.where(SalesTarget.scope == scope)
    if customer_id is not None:
        stmt = stmt.where(SalesTarget.customer_id == customer_id)
    if seller_id is not None:
        stmt = stmt.where(SalesTarget.seller_id == seller_id)
    if on is not None:
        stmt = stmt.where(SalesTarget.period_start <= on, SalesTarget.period_end >= on)
    rows = list((await db.execute(stmt)).scalars().all())
    return [await _target_read(db, t) for t in rows]


@router.post(
    "/targets", response_model=SalesTargetRead, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_perm("report:sales")), write],
)
async def create_target(
    payload: SalesTargetCreate, db: DbSession, current: CurrentUser
) -> SalesTargetRead:
    if payload.customer_id is not None and await db.get(Customer, payload.customer_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    if payload.seller_id is not None and await db.get(Seller, payload.seller_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Salesman or broker not found")

    row = SalesTarget(**payload.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return await _target_read(db, row)


@router.delete("/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[write])
async def delete_target(target_id: int, db: DbSession) -> None:
    """
    Remove a target.

    Safe in a way most deletes here are not: a target measures sales, it does
    not record them. The invoices it was counting are untouched, so nothing is
    lost but the aspiration.
    """
    row = await db.get(SalesTarget, target_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Target not found")
    await db.delete(row)
    await db.commit()


@router.get(
    "/sellers/{seller_id}/performance",
    response_model=SellerPerformance,
    dependencies=[Depends(require_perm("report:profit"))],
)
async def seller_performance(
    seller_id: int,
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> SellerPerformance:
    """
    One salesman or broker, in full.

    Behind the same permission as the profit reports, not the seller master:
    this is margin, collections and commission on a named colleague, which is
    an owner's information and not a counter hand's.

    Three things it is careful about, each of which would otherwise flatter the
    figures:

    * **Revenue is net of tax**, which is the government's money passing
      through. Counting it would inflate the margin and the commission with it.
    * **Collections are reported apart from sales.** A salesman writing large
      bills nobody pays is not a good salesman, and one blended "sales" number
      is precisely what hides that.
    * **Commission is an estimate and says so.** Nothing in this system posts
      one, so presenting it as fact would put a liability on screen that is in
      nobody's books.
    """
    seller = await db.get(Seller, seller_id)
    if seller is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Seller not found")

    sold = (InvoiceStatus.issued, InvoiceStatus.paid)
    window = []
    if date_from is not None:
        window.append(func.date(Invoice.issued_at) >= date_from)
    if date_to is not None:
        window.append(func.date(Invoice.issued_at) <= date_to)
    base = [Invoice.seller_id == seller_id, Invoice.status.in_(sold), *window]

    # Cost per invoice, the same expression `/reports/customers` uses, so the
    # two screens cannot disagree about what a sale cost.
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
            func.coalesce(func.sum(case((Product.id.is_(None), 1), else_=0)), 0).label(
                "uncosted"
            ),
            func.coalesce(func.sum(InvoiceItem.gold_weight_g), 0).label("gold_g"),
            func.coalesce(func.sum(InvoiceItem.stone_weight_ct), 0).label("stone_ct"),
        )
        .join(Product, Product.id == InvoiceItem.product_id, isouter=True)
        .group_by(InvoiceItem.invoice_id)
        .subquery()
    )

    totals = (
        await db.execute(
            select(
                func.count(Invoice.id),
                func.coalesce(func.sum(Invoice.total), 0),
                func.coalesce(func.sum(Invoice.tax_amount), 0),
                func.coalesce(func.sum(cost_subq.c.cost), 0),
                func.coalesce(func.sum(cost_subq.c.uncosted), 0),
                func.coalesce(func.sum(cost_subq.c.gold_g), 0),
                func.coalesce(func.sum(cost_subq.c.stone_ct), 0),
                func.coalesce(func.max(Invoice.total), 0),
                func.min(Invoice.issued_at),
                func.max(Invoice.issued_at),
            )
            .select_from(Invoice)
            .join(cost_subq, cost_subq.c.invoice_id == Invoice.id, isouter=True)
            .where(*base)
        )
    ).one()
    (count, total, tax, cost, uncosted, gold_g, stone_ct, largest, first_at, last_at) = totals

    revenue = (d(total) - d(tax)).quantize(_PKR)
    cost_d = d(cost).quantize(_PKR)
    margin = (revenue - cost_d).quantize(_PKR)

    # What has actually come in against his bills. Payments carry no seller of
    # their own — they settle an invoice — so this is read through them.
    collected = d(
        (
            await db.execute(
                select(func.coalesce(func.sum(Payment.amount), 0))
                .join(Invoice, Invoice.id == Payment.invoice_id)
                .where(*base)
            )
        ).scalar_one()
    ).quantize(_PKR)

    customers = [
        SellerCustomerRow(
            customer_id=cid,
            customer_name=cname,
            invoices=int(n or 0),
            revenue=(d(t) - d(tx)).quantize(_PKR),
            gross_margin=((d(t) - d(tx)) - d(c)).quantize(_PKR),
            last_sale_at=last,
        )
        for cid, cname, n, t, tx, c, last in (
            await db.execute(
                select(
                    Customer.id,
                    Customer.name,
                    func.count(Invoice.id),
                    func.coalesce(func.sum(Invoice.total), 0),
                    func.coalesce(func.sum(Invoice.tax_amount), 0),
                    func.coalesce(func.sum(cost_subq.c.cost), 0),
                    func.max(Invoice.issued_at),
                )
                .select_from(Invoice)
                .join(Customer, Customer.id == Invoice.customer_id)
                .join(cost_subq, cost_subq.c.invoice_id == Invoice.id, isouter=True)
                .where(*base)
                .group_by(Customer.id, Customer.name)
                .order_by(func.coalesce(func.sum(Invoice.total), 0).desc())
            )
        ).all()
    ]

    paid_subq = (
        select(
            Payment.invoice_id.label("invoice_id"),
            func.coalesce(func.sum(Payment.amount), 0).label("paid"),
        )
        .group_by(Payment.invoice_id)
        .subquery()
    )
    recent = [
        SellerInvoiceRow(
            invoice_id=inv.id,
            invoice_no=inv.invoice_no,
            issued_at=inv.issued_at,
            customer_id=inv.customer_id,
            customer_name=cname,
            currency=inv.currency.value,
            total=d(inv.total),
            paid=d(paid),
            balance_due=(d(inv.total) - d(paid)).quantize(_PKR),
            status=inv.status.value,
            gold_weight_g=d(g_).quantize(_G),
            stone_weight_ct=d(s_).quantize(_G),
        )
        for inv, cname, paid, g_, s_ in (
            await db.execute(
                select(
                    Invoice,
                    Customer.name,
                    func.coalesce(paid_subq.c.paid, 0),
                    func.coalesce(cost_subq.c.gold_g, 0),
                    func.coalesce(cost_subq.c.stone_ct, 0),
                )
                .join(Customer, Customer.id == Invoice.customer_id)
                .join(paid_subq, paid_subq.c.invoice_id == Invoice.id, isouter=True)
                .join(cost_subq, cost_subq.c.invoice_id == Invoice.id, isouter=True)
                .where(*base)
                .order_by(Invoice.issued_at.desc().nullslast(), Invoice.id.desc())
                .limit(50)
            )
        ).all()
    ]

    targets = [
        await _target_read(db, t)
        for t in (
            await db.execute(
                select(SalesTarget)
                .where(
                    SalesTarget.scope == TargetScope.seller,
                    SalesTarget.seller_id == seller_id,
                )
                .order_by(SalesTarget.period_start.desc())
            )
        )
        .scalars()
        .all()
    ]

    return SellerPerformance(
        seller=SellerRead.model_validate(seller),
        date_from=date_from,
        date_to=date_to,
        invoices=int(count or 0),
        revenue=revenue,
        cost_of_goods=cost_d,
        gross_margin=margin,
        margin_pct=_pct(margin, revenue) if revenue else None,
        uncosted_lines=int(uncosted or 0),
        collected=collected,
        outstanding=(revenue + d(tax) - collected).quantize(_PKR),
        gold_weight_g=d(gold_g).quantize(_G),
        stone_weight_ct=d(stone_ct).quantize(_G),
        average_bill=(revenue / int(count)).quantize(_PKR) if count else _ZERO,
        largest_bill=d(largest).quantize(_PKR),
        first_sale_at=first_at,
        last_sale_at=last_at,
        commission_pct=d(seller.commission_pct),
        commission_estimate=(revenue * d(seller.commission_pct) / d(100)).quantize(_PKR),
        customers=customers,
        recent_invoices=recent,
        targets=targets,
    )
