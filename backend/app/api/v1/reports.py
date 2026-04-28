from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select

from app.api.deps import DbSession, require_perm
from app.models.inventory import InventoryItem, InventoryType
from app.models.invoice import Invoice, InvoiceItem, InvoiceStatus, SaleType
from app.models.manufacturing import ManufacturingJob
from app.models.product import Product
from app.models.vendor import Vendor, VendorType
from app.schemas.reports import (
    LossReport,
    ProfitReport,
    ProfitRow,
    SalesBucket,
    SalesReport,
    StockBucket,
    StockReport,
    VendorLossRow,
)

router = APIRouter()


@router.get("/stock", response_model=StockReport, dependencies=[Depends(require_perm("report:stock"))])
async def stock_report(db: DbSession) -> StockReport:
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
    return StockReport(by_type=buckets, items_count=total_count)


@router.get("/sales", response_model=SalesReport, dependencies=[Depends(require_perm("report:sales"))])
async def sales_report(
    db: DbSession,
    range_from: datetime | None = Query(default=None),
    range_to: datetime | None = Query(default=None),
) -> SalesReport:
    """Aggregate issued (and paid) invoices by sale_type within an optional date range."""
    base = select(
        Invoice.sale_type,
        func.count(Invoice.id),
        func.coalesce(func.sum(Invoice.subtotal), 0),
        func.coalesce(func.sum(Invoice.discount_amount), 0),
        func.coalesce(func.sum(Invoice.total), 0),
    ).where(Invoice.status.in_((InvoiceStatus.issued, InvoiceStatus.paid)))
    if range_from is not None:
        base = base.where(Invoice.issued_at >= range_from)
    if range_to is not None:
        base = base.where(Invoice.issued_at <= range_to)
    base = base.group_by(Invoice.sale_type)

    rows = (await db.execute(base)).all()
    buckets = [
        SalesBucket(
            sale_type=st,
            invoice_count=n,
            subtotal=Decimal(str(s)),
            discount=Decimal(str(d)),
            total=Decimal(str(t)),
        )
        for (st, n, s, d, t) in rows
    ]
    invoice_count = sum(b.invoice_count for b in buckets)
    grand_total = sum((b.total for b in buckets), Decimal("0"))
    return SalesReport(
        range_from=range_from,
        range_to=range_to,
        by_sale_type=buckets,
        invoice_count=invoice_count,
        grand_total=grand_total,
    )


@router.get(
    "/manufacturing-loss",
    response_model=LossReport,
    dependencies=[Depends(require_perm("report:loss"))],
)
async def manufacturing_loss_report(db: DbSession) -> LossReport:
    """Material losses grouped by vendor (karigar + polish vendor)."""
    overall = (
        await db.execute(
            select(
                func.coalesce(func.sum(ManufacturingJob.karigar_loss_g), 0),
                func.coalesce(func.sum(ManufacturingJob.polish_loss_g), 0),
            )
        )
    ).one()

    karigar_q = (
        select(
            ManufacturingJob.karigar_id.label("vid"),
            Vendor.name.label("vname"),
            func.count(ManufacturingJob.id).label("jobs"),
            func.coalesce(func.sum(ManufacturingJob.karigar_loss_g), 0).label("loss"),
        )
        .join(Vendor, Vendor.id == ManufacturingJob.karigar_id, isouter=True)
        .where(ManufacturingJob.karigar_id.isnot(None))
        .group_by(ManufacturingJob.karigar_id, Vendor.name)
    )
    polish_q = (
        select(
            ManufacturingJob.polish_vendor_id.label("vid"),
            Vendor.name.label("vname"),
            func.count(ManufacturingJob.id).label("jobs"),
            func.coalesce(func.sum(ManufacturingJob.polish_loss_g), 0).label("loss"),
        )
        .join(Vendor, Vendor.id == ManufacturingJob.polish_vendor_id, isouter=True)
        .where(ManufacturingJob.polish_vendor_id.isnot(None))
        .group_by(ManufacturingJob.polish_vendor_id, Vendor.name)
    )
    karigar_rows = [
        VendorLossRow(
            vendor_id=vid, vendor_name=vname, role=VendorType.karigar.value,
            jobs=n, total_loss_g=Decimal(str(loss)),
        )
        for (vid, vname, n, loss) in (await db.execute(karigar_q)).all()
    ]
    polish_rows = [
        VendorLossRow(
            vendor_id=vid, vendor_name=vname, role=VendorType.polish.value,
            jobs=n, total_loss_g=Decimal(str(loss)),
        )
        for (vid, vname, n, loss) in (await db.execute(polish_q)).all()
    ]
    return LossReport(
        overall_karigar_loss_g=Decimal(str(overall[0])),
        overall_polish_loss_g=Decimal(str(overall[1])),
        by_vendor=karigar_rows + polish_rows,
    )


@router.get(
    "/profit",
    response_model=ProfitReport,
    dependencies=[Depends(require_perm("report:profit"))],
)
async def profit_report(
    db: DbSession,
    range_from: datetime | None = Query(default=None),
    range_to: datetime | None = Query(default=None),
) -> ProfitReport:
    """
    Per-invoice profit = invoice.total - SUM(product.total_cost × line.quantity).
    Excludes draft and void invoices. Material value is *not* counted as cost
    (it's tracked via inventory and stock movements).
    """
    making_cost_subq = (
        select(
            InvoiceItem.invoice_id.label("invoice_id"),
            func.coalesce(
                func.sum(
                    case(
                        (Product.id.is_(None), Decimal("0")),
                        else_=Product.total_cost * InvoiceItem.quantity,
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
            Invoice.issued_at,
            Invoice.total,
            func.coalesce(making_cost_subq.c.making_cost, 0),
        )
        .join(making_cost_subq, making_cost_subq.c.invoice_id == Invoice.id, isouter=True)
        .where(Invoice.status.in_((InvoiceStatus.issued, InvoiceStatus.paid)))
        .order_by(Invoice.issued_at.desc().nullslast())
    )
    if range_from is not None:
        stmt = stmt.where(Invoice.issued_at >= range_from)
    if range_to is not None:
        stmt = stmt.where(Invoice.issued_at <= range_to)

    rows: list[ProfitRow] = []
    total_rev = Decimal("0")
    total_cost = Decimal("0")
    for inv_id, inv_no, issued_at, total, mc in (await db.execute(stmt)).all():
        revenue = Decimal(str(total))
        cost = Decimal(str(mc))
        rows.append(
            ProfitRow(
                invoice_id=inv_id,
                invoice_no=inv_no,
                issued_at=issued_at,
                revenue=revenue,
                making_cost=cost,
                profit=(revenue - cost).quantize(Decimal("0.01")),
            )
        )
        total_rev += revenue
        total_cost += cost

    return ProfitReport(
        range_from=range_from,
        range_to=range_to,
        rows=rows,
        total_revenue=total_rev.quantize(Decimal("0.01")),
        total_making_cost=total_cost.quantize(Decimal("0.01")),
        total_profit=(total_rev - total_cost).quantize(Decimal("0.01")),
    )
