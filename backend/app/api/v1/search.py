"""
One box that finds anything the user is allowed to open.

The command palette could already find *screens*. It could not find `INV-26-00025`,
or "Sarafa", or the piece with serial `PRD-00081` — which is what somebody at the
counter is actually holding when they reach for a search box. A shop this size
has thousands of documents and a dozen list screens with their own filters;
making a person remember which list a number lives in is making them learn the
schema.

Three rules:

**Nothing is returned that the caller could not open.** Each entity is gated on
the same permission its own endpoint uses, and types the role cannot read are
skipped rather than filtered afterwards — so a staff account searching a
customer's name gets the customer, not a redacted row proving one exists.

**Document numbers rank above names.** Typing `INV-26-00025` means one thing;
typing "ring" means many. An exact hit on an identifier is always first, then
prefix matches, then anything containing the text.

**Every result knows where it goes.** A hit with no destination is a tease, so
each row carries the route the UI should navigate to. Types whose detail screen
does not exist yet are simply not searched.
"""
from decimal import Decimal

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DbSession
from app.core.permissions import role_has
from app.models.customer import Customer
from app.models.design import Design
from app.models.invoice import Invoice
from app.models.order import CustomerOrder
from app.models.product import Product
from app.models.purchase import Supplier
from app.models.sales import Seller
from app.models.vendor import Vendor
from app.schemas.search import SearchHit, SearchResults

router = APIRouter()

# How many of each kind to return. Deliberately small: the box is for finding
# one thing, and a hundred customers named Ali is a list screen's job.
PER_TYPE = 6


@router.get("", response_model=SearchResults)
async def search(
    db: DbSession,
    current: CurrentUser,
    q: str = Query(min_length=1, max_length=80),
    limit: int = Query(default=8, le=20),
) -> SearchResults:
    """
    Find a record by number, name, phone or serial.

    Case-insensitive and matched on `contains`, because people search by the
    tail of a number as often as the head — "00025" should find
    `INV-26-00025`. Ranked so the exact and the prefix hits come first anyway.
    """
    term = q.strip()
    if not term:
        return SearchResults(query=q, hits=[])
    like = f"%{term.lower()}%"
    role = current.role.name if current.role else ""
    hits: list[SearchHit] = []

    def allowed(perm: str) -> bool:
        return role_has(role, perm)

    # --- documents first: a number typed in full means exactly one thing -----
    if allowed("invoice:read"):
        rows = (
            await db.execute(
                select(Invoice, Customer.name)
                .join(Customer, Customer.id == Invoice.customer_id, isouter=True)
                .where(func.lower(Invoice.invoice_no).like(like))
                .order_by(func.length(Invoice.invoice_no), Invoice.id.desc())
                .limit(PER_TYPE)
            )
        ).all()
        for inv, cname in rows:
            hits.append(
                SearchHit(
                    type="invoice",
                    type_label="Invoice",
                    id=inv.id,
                    title=inv.invoice_no,
                    subtitle=" · ".join(
                        x for x in [cname, f"{inv.currency.value} {Decimal(str(inv.total))}"] if x
                    ),
                    badge=inv.status.value,
                    to=f"/invoices/{inv.id}",
                    score=0 if inv.invoice_no.lower() == term.lower() else 1,
                )
            )

    if allowed("product:read"):
        rows = (
            await db.execute(
                select(Product)
                .where(
                    or_(
                        func.lower(Product.serial_no).like(like),
                        func.lower(Product.name).like(like),
                    )
                )
                .order_by(Product.id.desc())
                .limit(PER_TYPE)
            )
        ).unique().scalars().all()
        for p in rows:
            hits.append(
                SearchHit(
                    type="product",
                    type_label="Product",
                    id=p.id,
                    title=p.serial_no,
                    subtitle=p.name,
                    badge=p.status.value if p.status else None,
                    to=f"/products/{p.id}",
                    score=0 if p.serial_no.lower() == term.lower() else 1,
                )
            )

    if allowed("design:read"):
        rows = (
            await db.execute(
                select(Design)
                .where(
                    or_(
                        func.lower(Design.design_no).like(like),
                        func.lower(func.coalesce(Design.tag_no, "")).like(like),
                    )
                )
                .order_by(Design.id.desc())
                .limit(PER_TYPE)
            )
        ).unique().scalars().all()
        for dsn in rows:
            hits.append(
                SearchHit(
                    type="design",
                    type_label="Job",
                    id=dsn.id,
                    title=dsn.design_no,
                    subtitle=f"tag {dsn.tag_no}" if dsn.tag_no else None,
                    badge=dsn.status.value,
                    to=f"/designs/{dsn.id}",
                    score=0 if dsn.design_no.lower() == term.lower() else 1,
                )
            )

    if allowed("order:read"):
        rows = (
            await db.execute(
                select(CustomerOrder)
                .where(func.lower(CustomerOrder.order_no).like(like))
                .order_by(CustomerOrder.id.desc())
                .limit(PER_TYPE)
            )
        ).unique().scalars().all()
        for o in rows:
            hits.append(
                SearchHit(
                    type="order",
                    type_label="Order",
                    id=o.id,
                    title=o.order_no,
                    subtitle=None,
                    badge=o.status.value,
                    to=f"/orders/{o.id}",
                    score=0 if o.order_no.lower() == term.lower() else 1,
                )
            )

    # --- then people -------------------------------------------------------
    if allowed("customer:read"):
        rows = (
            await db.execute(
                select(Customer)
                .where(
                    or_(
                        func.lower(Customer.name).like(like),
                        func.lower(func.coalesce(Customer.phone, "")).like(like),
                        func.lower(func.coalesce(Customer.account_no, "")).like(like),
                        func.lower(func.coalesce(Customer.cnic, "")).like(like),
                    )
                )
                .order_by(Customer.name)
                .limit(PER_TYPE)
            )
        ).unique().scalars().all()
        for c in rows:
            hits.append(
                SearchHit(
                    type="customer",
                    type_label="Customer",
                    id=c.id,
                    title=c.name,
                    subtitle=c.phone or c.account_no,
                    to=f"/customers/{c.id}",
                    score=2 if c.name.lower().startswith(term.lower()) else 3,
                )
            )

    if allowed("vendor:read"):
        rows = (
            await db.execute(
                select(Vendor)
                .where(
                    or_(
                        func.lower(Vendor.name).like(like),
                        func.lower(func.coalesce(Vendor.phone, "")).like(like),
                    )
                )
                .order_by(Vendor.name)
                .limit(PER_TYPE)
            )
        ).unique().scalars().all()
        for v in rows:
            hits.append(
                SearchHit(
                    type="worker",
                    type_label="Karigar",
                    id=v.id,
                    title=v.name,
                    subtitle=v.department.name if v.department else v.phone,
                    to=f"/vendors/{v.id}",
                    score=2 if v.name.lower().startswith(term.lower()) else 3,
                )
            )

    if allowed("inventory:read"):
        rows = (
            await db.execute(
                select(Supplier)
                .where(
                    or_(
                        func.lower(Supplier.name).like(like),
                        func.lower(func.coalesce(Supplier.phone, "")).like(like),
                    )
                )
                .order_by(Supplier.name)
                .limit(PER_TYPE)
            )
        ).unique().scalars().all()
        for sup in rows:
            hits.append(
                SearchHit(
                    type="supplier",
                    type_label="Supplier",
                    id=sup.id,
                    title=sup.name,
                    subtitle=sup.phone,
                    to=f"/purchasing/suppliers/{sup.id}",
                    score=2 if sup.name.lower().startswith(term.lower()) else 3,
                )
            )

    if allowed("seller:read"):
        rows = (
            await db.execute(
                select(Seller)
                .where(
                    or_(
                        func.lower(Seller.name).like(like),
                        func.lower(func.coalesce(Seller.phone, "")).like(like),
                        func.lower(func.coalesce(Seller.cnic, "")).like(like),
                    )
                )
                .order_by(Seller.name)
                .limit(PER_TYPE)
            )
        ).unique().scalars().all()
        for sel in rows:
            hits.append(
                SearchHit(
                    type="seller",
                    type_label=sel.kind.value.title(),
                    id=sel.id,
                    title=sel.name,
                    subtitle=sel.phone,
                    to=f"/sales/{sel.id}",
                    score=2 if sel.name.lower().startswith(term.lower()) else 3,
                )
            )

    hits.sort(key=lambda h: (h.score, h.type_label, h.title))
    return SearchResults(query=q, hits=hits[:limit], total=len(hits))
