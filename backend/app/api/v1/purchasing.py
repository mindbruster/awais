"""
Purchasing: bullion from a dealer, old gold over the counter, and stones from
suppliers.

Two channels the shop lives on that the system could not previously see. Both
move real material and real money, so each one writes stock *and* books in a
single transaction — the translation lives in `app.services.purchasing`, and
nothing here writes a journal row directly.

The stone-stock report at the bottom is the reason the stone side exists at
all: it is what finally answers "how much 12 PTR commercial do I have left",
which no screen in this system could answer before.
"""
from datetime import date, datetime, time, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select

from app.core import clock
from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.api.v1.masters import make_master_router
from app.models.currency import Currency
from app.models.customer import Customer
from app.models.journal import JournalEntry
from app.models.branch import Branch
from app.models.bank import BankAccount
from app.models.purchase import (
    GoldKind,
    GoldPaymentMode,
    GoldPurchase,
    GoldPurchaseItem,
    OldGoldPurchase,
    StonePurchase,
    StonePurchaseItem,
    Supplier,
)
from app.models.stock_movement import MovementType
from app.models.stone import Stone, StoneCategory
from app.schemas.purchase import (
    GoldPurchaseCreate,
    GoldPurchaseDetail,
    GoldPurchaseItemRead,
    GoldPurchaseRead,
    OldGoldCreate,
    OldGoldRead,
    StonePurchaseCreate,
    StonePurchaseDetail,
    StonePurchaseItemRead,
    StonePurchaseRead,
    StoneStockReport,
    StoneStockRow,
    SupplierCreate,
    SupplierRead,
    SupplierUpdate,
)
from app.services import branches, fx, purchasing
from app.services.audit import log_action
from app.services.gold_rate import rate_in_force
from app.services.inventory import post_movement
from app.services.ledger import d, fine_grams

router = APIRouter()
read = Depends(require_perm("inventory:read"))
write = Depends(require_perm("inventory:write"))
stock_report = Depends(require_perm("report:stock"))
confirm = Depends(require_password_confirm)

_ZERO = Decimal("0")


# --------------------------------------------------------------------------
# Suppliers
# --------------------------------------------------------------------------
# Generated from the same factory as the other masters rather than written out
# again, so a supplier gets the behaviour that is easy to get wrong per-copy:
# a duplicate name comes back 409 instead of 500, and a delete that would
# orphan stone bills is refused rather than cascading.
suppliers_router = make_master_router(
    model=Supplier,
    create_schema=SupplierCreate,
    update_schema=SupplierUpdate,
    read_schema=SupplierRead,
    label="supplier",
    search_fields=(Supplier.name, Supplier.phone),
    order_by=(Supplier.name,),
)
router.include_router(suppliers_router, prefix="/suppliers")


# --------------------------------------------------------------------------
# Old gold
# --------------------------------------------------------------------------
async def _reversals_for(db: DbSession, entry_ids: list[int]) -> dict[int, str]:
    """Which of these entries have already been reversed, and by what."""
    if not entry_ids:
        return {}
    rows = (
        await db.execute(
            select(JournalEntry.reverses_entry_id, JournalEntry.entry_no).where(
                JournalEntry.reverses_entry_id.in_(entry_ids)
            )
        )
    ).all()
    return {int(original): no for original, no in rows if original is not None}


def _old_gold_read(
    p: OldGoldPurchase,
    *,
    entry_no: str | None = None,
    reversal_no: str | None = None,
) -> OldGoldRead:
    fine = fine_grams(p.weight_g, p.purity)
    return OldGoldRead(
        id=p.id,
        created_at=p.created_at,
        updated_at=p.updated_at,
        purchase_no=p.purchase_no,
        customer_id=p.customer_id,
        customer_name=p.customer.name if p.customer else None,
        walk_in_name=p.walk_in_name,
        seller_name=(p.customer.name if p.customer else None) or p.walk_in_name or "Walk-in",
        kind=p.kind,
        weight_g=d(p.weight_g),
        purity=p.purity,
        rate_per_g=d(p.rate_per_g),
        amount=d(p.amount),
        fine_weight_g=fine,
        effective_rate_per_fine_g=(
            purchasing.effective_fine_rate(d(p.amount), fine) if fine > 0 else _ZERO
        ),
        inventory_item_id=p.inventory_item_id,
        journal_entry_id=p.journal_entry_id,
        journal_entry_no=entry_no,
        is_reversed=reversal_no is not None,
        reversal_entry_no=reversal_no,
        purchased_at=p.purchased_at,
        notes=p.notes,
    )


async def _load_old_gold(db: DbSession, purchase_id: int) -> OldGoldPurchase:
    purchase = (
        await db.execute(
            select(OldGoldPurchase)
            .where(OldGoldPurchase.id == purchase_id)
            .execution_options(populate_existing=True)
        )
    ).unique().scalar_one_or_none()
    if purchase is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Old gold purchase not found")
    return purchase


async def _decorate_old_gold(db: DbSession, rows: list[OldGoldPurchase]) -> list[OldGoldRead]:
    """Attach entry numbers and reversal status in two queries, not two per row."""
    entry_ids = [r.journal_entry_id for r in rows if r.journal_entry_id is not None]
    numbers: dict[int, str] = {}
    if entry_ids:
        numbers = {
            int(eid): no
            for eid, no in (
                await db.execute(
                    select(JournalEntry.id, JournalEntry.entry_no).where(
                        JournalEntry.id.in_(entry_ids)
                    )
                )
            ).all()
        }
    reversals = await _reversals_for(db, entry_ids)
    return [
        _old_gold_read(
            r,
            entry_no=numbers.get(r.journal_entry_id or -1),
            reversal_no=reversals.get(r.journal_entry_id or -1),
        )
        for r in rows
    ]


@router.post(
    "/old-gold",
    response_model=OldGoldRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[write],
)
async def buy_old_gold(
    payload: OldGoldCreate, db: DbSession, current: CurrentUser
) -> OldGoldRead:
    """
    Buy metal back over the counter.

    Stock and books move together: the metal lands in the melt pot for its
    purity as a `purchase_in`, and the same transaction debits 1130 Gold in
    Hand in fine grams and credits 1110 Cash in Hand for the rupees paid. If
    either half fails, neither happens.
    """
    customer: Customer | None = None
    if payload.customer_id is not None:
        customer = await db.get(Customer, payload.customer_id)
        if customer is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")

    # `pure` with no purity stated is bullion, which is 24k by definition. Used
    # jewellery has already been refused by the schema unless it says what it
    # assays at, because the ledger holds fine grams and guessing there would
    # overstate the shop's metal by the alloy fraction, permanently.
    purity = payload.purity or 24
    weight = d(payload.weight_g)
    rate = d(payload.rate_per_g)
    amount = purchasing.old_gold_amount(weight, rate)
    fine = fine_grams(weight, purity)
    purchased_at = payload.purchased_at or datetime.now(timezone.utc)

    # The shop buys below the day's rate; that spread is the margin. Paying at
    # or above it is a loss dressed as a purchase, so it has to be said out
    # loud. No rate on record is not an obstacle — a buy-back is priced by
    # negotiation, not by the board — so the check simply does not run.
    paid_per_fine = purchasing.effective_fine_rate(amount, fine)
    market = await rate_in_force(db, currency=Currency.PKR, purity=24, as_of=clock.shop_date(purchased_at))
    if (
        market is not None
        and d(market.rate_per_g) > 0
        and paid_per_fine >= d(market.rate_per_g)
        and not payload.allow_above_market
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"That works out to {paid_per_fine} per fine gram, at or above the day's "
            f"rate of {d(market.rate_per_g)}. The shop buys below rate — that spread is "
            "the margin. Lower the rate, or send allow_above_market to book it anyway.",
        )

    buy_branch = await branches.resolve_branch(db, requested_id=payload.branch_id, user=current)
    item = await purchasing.raw_gold_item(db, purity=purity, branch_id=buy_branch.id)
    purchase = OldGoldPurchase(
        purchase_no=await purchasing.next_old_gold_no(db),
        customer_id=payload.customer_id,
        walk_in_name=(payload.walk_in_name or "").strip() or None,
        kind=payload.kind,
        weight_g=weight,
        purity=purity,
        rate_per_g=rate,
        amount=amount,
        inventory_item_id=item.id,
        purchased_at=purchased_at,
        notes=payload.notes,
        created_by_user_id=current.id,
    )
    db.add(purchase)
    await db.flush()

    await post_movement(
        db,
        item=item,
        type=MovementType.purchase_in,
        weight_g_delta=weight,
        reference_type=purchasing.OLD_GOLD_SOURCE,
        reference_id=purchase.id,
        notes=f"{purchase.purchase_no} — {payload.kind.value} {purity}k at {rate}/g",
        user_id=current.id,
    )
    seller = (customer.name if customer else None) or purchase.walk_in_name or "walk-in"
    entry = await purchasing.post_old_gold_purchase(
        db, purchase, seller=seller, user_id=current.id
    )
    purchase.journal_entry_id = entry.id

    await log_action(
        db,
        user=current,
        action="purchasing.old_gold.buy",
        resource_type="old_gold_purchase",
        resource_id=purchase.id,
        details={
            "purchase_no": purchase.purchase_no,
            "weight_g": str(weight),
            "purity": purity,
            "rate_per_g": str(rate),
            "amount": str(amount),
            "entry_no": entry.entry_no,
        },
    )
    await db.commit()
    return (await _decorate_old_gold(db, [await _load_old_gold(db, purchase.id)]))[0]


@router.get("/old-gold", response_model=list[OldGoldRead], dependencies=[read])
async def list_old_gold(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    customer_id: int | None = Query(default=None),
    kind: GoldKind | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[OldGoldRead]:
    stmt = (
        select(OldGoldPurchase)
        .order_by(desc(OldGoldPurchase.purchased_at), desc(OldGoldPurchase.id))
        .limit(limit)
        .offset(offset)
    )
    if date_from is not None:
        stmt = stmt.where(OldGoldPurchase.purchased_at >= datetime.combine(
            date_from, datetime.min.time(), tzinfo=timezone.utc
        ))
    if date_to is not None:
        # Inclusive of the whole day, which is what a counter means by "to".
        stmt = stmt.where(OldGoldPurchase.purchased_at < datetime.combine(
            date_to, datetime.max.time(), tzinfo=timezone.utc
        ))
    if customer_id is not None:
        stmt = stmt.where(OldGoldPurchase.customer_id == customer_id)
    if kind is not None:
        stmt = stmt.where(OldGoldPurchase.kind == kind)
    rows = list((await db.execute(stmt)).unique().scalars().all())
    return await _decorate_old_gold(db, rows)


@router.get("/old-gold/{purchase_id}", response_model=OldGoldRead, dependencies=[read])
async def get_old_gold(purchase_id: int, db: DbSession) -> OldGoldRead:
    return (await _decorate_old_gold(db, [await _load_old_gold(db, purchase_id)]))[0]


@router.post(
    "/old-gold/{purchase_id}/reverse",
    response_model=OldGoldRead,
    dependencies=[write, confirm],
)
async def reverse_old_gold(
    purchase_id: int, db: DbSession, current: CurrentUser
) -> OldGoldRead:
    """
    Undo a buy-back: metal back out of stock, cash back into the till.

    The row is not edited or deleted. The ledger is append-only, so the
    correction is a reversing entry pointing at the original, and "was this
    undone" stays a question the journal answers rather than a flag that can
    drift out of step with it. A second attempt comes back 409.
    """
    purchase = await _load_old_gold(db, purchase_id)
    reversal = await purchasing.reverse_old_gold_purchase(db, purchase, user_id=current.id)
    await log_action(
        db,
        user=current,
        action="purchasing.old_gold.reverse",
        resource_type="old_gold_purchase",
        resource_id=purchase.id,
        details={"purchase_no": purchase.purchase_no, "reversal_no": reversal.entry_no},
    )
    await db.commit()
    return (await _decorate_old_gold(db, [await _load_old_gold(db, purchase_id)]))[0]


# --------------------------------------------------------------------------
# Stone purchases
# --------------------------------------------------------------------------
def _item_read(i: StonePurchaseItem) -> StonePurchaseItemRead:
    return StonePurchaseItemRead(
        id=i.id,
        created_at=i.created_at,
        updated_at=i.updated_at,
        purchase_id=i.purchase_id,
        stone_id=i.stone_id,
        stone_name=i.stone.name if i.stone else None,
        quantity=i.quantity,
        weight_ct=d(i.weight_ct),
        rate_per_ct=d(i.rate_per_ct),
        amount=d(i.amount),
        quality=i.quality,
        cut=i.cut,
        color=i.color,
        clarity=i.clarity,
        inventory_item_id=i.inventory_item_id,
        notes=i.notes,
    )


def _purchase_read(p: StonePurchase, *, entry_no: str | None = None) -> StonePurchaseRead:
    return StonePurchaseRead(
        id=p.id,
        created_at=p.created_at,
        updated_at=p.updated_at,
        purchase_no=p.purchase_no,
        supplier_id=p.supplier_id,
        supplier_name=p.supplier.name if p.supplier else None,
        purchased_at=p.purchased_at,
        reference=p.reference,
        subtotal=d(p.subtotal),
        extra_cost_pct=d(p.extra_cost_pct),
        extra_cost_amount=(d(p.total) - d(p.subtotal)).quantize(Decimal("0.01")),
        total=d(p.total),
        item_count=len(p.items),
        total_weight_ct=sum((d(i.weight_ct) for i in p.items), _ZERO),
        journal_entry_id=p.journal_entry_id,
        journal_entry_no=entry_no,
        notes=p.notes,
    )


def _purchase_detail(p: StonePurchase, *, entry_no: str | None = None) -> StonePurchaseDetail:
    base = _purchase_read(p, entry_no=entry_no)
    return StonePurchaseDetail(**base.model_dump(), items=[_item_read(i) for i in p.items])


async def _load_stone_purchase(db: DbSession, purchase_id: int) -> StonePurchase:
    purchase = (
        await db.execute(
            select(StonePurchase)
            .where(StonePurchase.id == purchase_id)
            .execution_options(populate_existing=True)
        )
    ).unique().scalar_one_or_none()
    if purchase is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stone purchase not found")
    return purchase


async def _entry_no(db: DbSession, entry_id: int | None) -> str | None:
    if entry_id is None:
        return None
    return (
        await db.execute(select(JournalEntry.entry_no).where(JournalEntry.id == entry_id))
    ).scalar_one_or_none()


@router.post(
    "/stone-purchases",
    response_model=StonePurchaseDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[write],
)
async def create_stone_purchase(
    payload: StonePurchaseCreate, db: DbSession, current: CurrentUser
) -> StonePurchaseDetail:
    """
    Record a supplier's bill and put the stones on the shelf.

    Each line goes into the packet for its stone *and grade* as a `purchase_in`,
    and the bill total posts once: debit 1140 Stone Inventory, credit 2110
    Suppliers against this supplier. Grading is snapshotted onto the line — the
    bill has to keep saying what was bought even after the shop renames a grade.
    """
    supplier = await db.get(Supplier, payload.supplier_id)
    if supplier is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier not found")

    # Stones land in the packet at the branch that bought them, so that a bill
    # taken at one shop cannot silently top up another shop's shelf.
    buy_branch = await branches.resolve_branch(db, requested_id=payload.branch_id, user=current)

    stone_ids = {i.stone_id for i in payload.items}
    stones = {
        s.id: s
        for s in (await db.execute(select(Stone).where(Stone.id.in_(stone_ids))))
        .unique()
        .scalars()
        .all()
    }
    missing = sorted(stone_ids - stones.keys())
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Stone(s) not found: {', '.join(map(str, missing))}"
        )

    purchased_at = payload.purchased_at or datetime.now(timezone.utc)
    purchase = StonePurchase(
        purchase_no=await purchasing.next_stone_purchase_no(db),
        supplier_id=supplier.id,
        purchased_at=purchased_at,
        reference=payload.reference,
        subtotal=_ZERO,
        extra_cost_pct=d(payload.extra_cost_pct),
        total=_ZERO,
        notes=payload.notes,
        created_by_user_id=current.id,
    )
    db.add(purchase)
    await db.flush()

    subtotal = _ZERO
    rows: list[StonePurchaseItem] = []
    for line in payload.items:
        stone = stones[line.stone_id]
        # Blank grading is filled from the master *now* and then frozen. Reading
        # it live later would let a rename rewrite history.
        quality = line.quality or stone.quality
        cut = line.cut or stone.cut
        color = line.color or stone.color
        clarity = line.clarity or stone.clarity
        # Converted before anything accumulates it. The supplier quotes in their
        # own currency and the books are kept in rupees, so the line value, the
        # bill subtotal, the stock value and the journal entry all have to be
        # the same number — not three that happen to look similar.
        line_currency, line_fx = await fx.snapshot_for_stone(db, stone)
        amount = (
            purchasing.stone_line_amount(line.weight_ct, line.rate_per_ct) * line_fx
        ).quantize(Decimal("0.01"))
        subtotal += amount

        item = await purchasing.raw_stone_item(
            db, stone=stone, quality=quality, cut=cut, color=color, clarity=clarity,
            branch_id=buy_branch.id,
        )
        row = StonePurchaseItem(
            purchase_id=purchase.id,
            stone_id=stone.id,
            quantity=line.quantity,
            weight_ct=d(line.weight_ct),
            rate_per_ct=d(line.rate_per_ct),
            currency=line_currency,
            fx_rate_to_pkr=line_fx,
            # Held in rupees, like every other money column in the system. The
            # supplier quoted in their own currency; converting here means the
            # bill total, the stock value and the ledger entry are the same
            # number rather than three that happen to look similar.
            amount=amount,
            quality=quality,
            cut=cut,
            color=color,
            clarity=clarity,
            inventory_item_id=item.id,
            notes=line.notes,
        )
        db.add(row)
        await db.flush()
        rows.append(row)

        await post_movement(
            db,
            item=item,
            type=MovementType.purchase_in,
            quantity_delta=line.quantity,
            weight_ct_delta=d(line.weight_ct),
            reference_type=purchasing.STONE_PURCHASE_SOURCE,
            reference_id=purchase.id,
            notes=f"{purchase.purchase_no} — {stone.name}",
            user_id=current.id,
        )

    purchase.subtotal = subtotal.quantize(Decimal("0.01"))
    purchase.total = purchasing.apply_extra_cost(purchase.subtotal, purchase.extra_cost_pct)
    await db.flush()

    entry = await purchasing.post_stone_purchase(
        db,
        purchase,
        supplier_name=supplier.name,
        line_count=len(rows),
        user_id=current.id,
    )
    purchase.journal_entry_id = entry.id

    await log_action(
        db,
        user=current,
        action="purchasing.stone_purchase.create",
        resource_type="stone_purchase",
        resource_id=purchase.id,
        details={
            "purchase_no": purchase.purchase_no,
            "supplier": supplier.name,
            "lines": len(rows),
            "subtotal": str(purchase.subtotal),
            "total": str(purchase.total),
            "entry_no": entry.entry_no,
        },
    )
    await db.commit()
    fresh = await _load_stone_purchase(db, purchase.id)
    return _purchase_detail(fresh, entry_no=await _entry_no(db, fresh.journal_entry_id))


@router.get("/stone-purchases", response_model=list[StonePurchaseRead], dependencies=[read])
async def list_stone_purchases(
    db: DbSession,
    supplier_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[StonePurchaseRead]:
    stmt = (
        select(StonePurchase)
        .order_by(desc(StonePurchase.purchased_at), desc(StonePurchase.id))
        .limit(limit)
        .offset(offset)
    )
    if supplier_id is not None:
        stmt = stmt.where(StonePurchase.supplier_id == supplier_id)
    if date_from is not None:
        stmt = stmt.where(StonePurchase.purchased_at >= datetime.combine(
            date_from, datetime.min.time(), tzinfo=timezone.utc
        ))
    if date_to is not None:
        stmt = stmt.where(StonePurchase.purchased_at < datetime.combine(
            date_to, datetime.max.time(), tzinfo=timezone.utc
        ))
    rows = list((await db.execute(stmt)).unique().scalars().all())
    numbers = {
        int(eid): no
        for eid, no in (
            await db.execute(
                select(JournalEntry.id, JournalEntry.entry_no).where(
                    JournalEntry.id.in_([r.journal_entry_id for r in rows if r.journal_entry_id])
                )
            )
        ).all()
    }
    return [_purchase_read(r, entry_no=numbers.get(r.journal_entry_id or -1)) for r in rows]


@router.get(
    "/stone-purchases/{purchase_id}", response_model=StonePurchaseDetail, dependencies=[read]
)
async def get_stone_purchase(purchase_id: int, db: DbSession) -> StonePurchaseDetail:
    purchase = await _load_stone_purchase(db, purchase_id)
    return _purchase_detail(purchase, entry_no=await _entry_no(db, purchase.journal_entry_id))


# --------------------------------------------------------------------------
# Stone stock
# --------------------------------------------------------------------------
@router.get("/stone-stock", response_model=StoneStockReport, dependencies=[stock_report])
async def stone_stock(
    db: DbSession,
    category: StoneCategory | None = Query(default=None),
    stone_id: int | None = Query(default=None),
    quality: str | None = Query(default=None),
    cut: str | None = Query(default=None),
    clarity: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> StoneStockReport:
    """
    What was bought, what went into pieces, and what is left — per grade.

    Read off the purchase lines and the setting legs rather than off the
    inventory snapshot, because the snapshot is one number per packet and
    cannot say where the carats went. Available may be negative where stones
    were consumed that this system never saw arrive.
    """
    lines = await purchasing.stone_stock(
        db,
        category=category,
        stone_id=stone_id,
        quality=quality,
        cut=cut,
        clarity=clarity,
        date_from=date_from,
        date_to=date_to,
    )
    rows = [
        StoneStockRow(
            stone_id=ln.stone_id,
            stone_name=ln.stone_name,
            stone_kind=ln.stone_kind,
            category=ln.category,
            abbreviation=ln.abbreviation,
            quality=ln.quality,
            cut=ln.cut,
            color=ln.color,
            clarity=ln.clarity,
            purchased_quantity=ln.purchased_quantity,
            purchased_weight_ct=ln.purchased_weight_ct,
            purchased_value=ln.purchased_value,
            avg_rate_per_ct=ln.avg_rate_per_ct,
            used_quantity=ln.used_quantity,
            used_weight_ct=ln.used_weight_ct,
            available_quantity=ln.available_quantity,
            available_weight_ct=ln.available_weight_ct,
        )
        for ln in lines
    ]
    return StoneStockReport(
        date_from=date_from,
        date_to=date_to,
        category=category,
        quality=quality,
        cut=cut,
        clarity=clarity,
        rows=rows,
        total_purchased_weight_ct=sum((r.purchased_weight_ct for r in rows), _ZERO),
        total_used_weight_ct=sum((r.used_weight_ct for r in rows), _ZERO),
        total_available_weight_ct=sum((r.available_weight_ct for r in rows), _ZERO),
    )


# --------------------------------------------------------------------------
# Gold purchases (from a dealer)
# --------------------------------------------------------------------------
def _gold_item_read(i: GoldPurchaseItem) -> GoldPurchaseItemRead:
    return GoldPurchaseItemRead(
        id=i.id,
        created_at=i.created_at,
        updated_at=i.updated_at,
        purchase_id=i.purchase_id,
        description=i.description,
        purity=i.purity,
        weight_g=d(i.weight_g),
        rate_per_g=d(i.rate_per_g),
        currency=i.currency,
        fx_rate_to_pkr=d(i.fx_rate_to_pkr),
        amount=d(i.amount),
        fine_weight_g=fine_grams(i.weight_g, i.purity),
        inventory_item_id=i.inventory_item_id,
        notes=i.notes,
    )


def _gold_purchase_read(
    p: GoldPurchase, *, entry_no: str | None = None, reversal_no: str | None = None
) -> GoldPurchaseRead:
    total = d(p.total)
    fine = sum((fine_grams(i.weight_g, i.purity) for i in p.items), _ZERO)
    return GoldPurchaseRead(
        id=p.id,
        created_at=p.created_at,
        updated_at=p.updated_at,
        purchase_no=p.purchase_no,
        supplier_id=p.supplier_id,
        supplier_name=p.supplier.name if p.supplier else None,
        branch_id=p.branch_id,
        branch_name=None,
        purchased_at=p.purchased_at,
        reference=p.reference,
        payment_mode=p.payment_mode,
        bank_account_id=p.bank_account_id,
        subtotal=d(p.subtotal),
        extra_cost_pct=d(p.extra_cost_pct),
        extra_cost_amount=(total - d(p.subtotal)).quantize(Decimal("0.01")),
        total=total,
        item_count=len(p.items),
        total_weight_g=sum((d(i.weight_g) for i in p.items), _ZERO),
        total_fine_g=fine,
        # Loading included, against fine grams — the only figure that can
        # honestly be held up against the day's rate.
        effective_rate_per_fine_g=(
            purchasing.effective_fine_rate(total, fine) if fine > 0 else _ZERO
        ),
        journal_entry_id=p.journal_entry_id,
        journal_entry_no=entry_no,
        is_reversed=reversal_no is not None,
        reversal_entry_no=reversal_no,
        notes=p.notes,
    )


async def _load_gold_purchase(db: DbSession, purchase_id: int) -> GoldPurchase:
    purchase = (
        await db.execute(
            select(GoldPurchase)
            .where(GoldPurchase.id == purchase_id)
            .execution_options(populate_existing=True)
        )
    ).unique().scalar_one_or_none()
    if purchase is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gold purchase not found")
    return purchase


async def _decorate_gold(db: DbSession, rows: list[GoldPurchase]) -> list[GoldPurchaseRead]:
    """Entry numbers, reversal status and branch names in three queries, not three per row."""
    entry_ids = [r.journal_entry_id for r in rows if r.journal_entry_id is not None]
    numbers: dict[int, str] = {}
    if entry_ids:
        numbers = {
            int(eid): no
            for eid, no in (
                await db.execute(
                    select(JournalEntry.id, JournalEntry.entry_no).where(
                        JournalEntry.id.in_(entry_ids)
                    )
                )
            ).all()
        }
    reversals = await _reversals_for(db, entry_ids)
    branch_ids = {r.branch_id for r in rows}
    branch_names = (
        {
            int(bid): name
            for bid, name in (
                await db.execute(select(Branch.id, Branch.name).where(Branch.id.in_(branch_ids)))
            ).all()
        }
        if branch_ids
        else {}
    )
    out = []
    for r in rows:
        read = _gold_purchase_read(
            r,
            entry_no=numbers.get(r.journal_entry_id or -1),
            reversal_no=reversals.get(r.journal_entry_id or -1),
        )
        read.branch_name = branch_names.get(r.branch_id)
        out.append(read)
    return out


@router.post(
    "/gold-purchases",
    response_model=GoldPurchaseDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[write],
)
async def create_gold_purchase(
    payload: GoldPurchaseCreate, db: DbSession, current: CurrentUser
) -> GoldPurchaseDetail:
    """
    Record a dealer's bill and put the metal in the safe.

    Each lot goes into the melt pot for its purity as a `purchase_in`, and the
    bill posts once: debit 1130 Gold in Hand a line per lot in fine grams,
    credit cash, bank or the supplier's account depending on how it was paid.

    Deliberately *not* checked against the day's rate. That check exists on a
    buy-back because the shop buys a customer's jewellery below rate and the
    spread is the margin; a dealer sells bullion at or fractionally above the
    board, and refusing that would block the ordinary way a workshop stocks up.
    """
    supplier = await db.get(Supplier, payload.supplier_id)
    if supplier is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier not found")

    if payload.payment_mode is GoldPaymentMode.bank and payload.bank_account_id is not None:
        if await db.get(BankAccount, payload.bank_account_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bank account not found")

    # The metal lands in the safe at the shop that bought it, so a bill taken at
    # one counter cannot silently top up another shop's melt pot.
    buy_branch = await branches.resolve_branch(db, requested_id=payload.branch_id, user=current)

    purchased_at = payload.purchased_at or datetime.now(timezone.utc)
    purchase = GoldPurchase(
        purchase_no=await purchasing.next_gold_purchase_no(db),
        supplier_id=supplier.id,
        branch_id=buy_branch.id,
        purchased_at=purchased_at,
        reference=payload.reference,
        payment_mode=payload.payment_mode,
        bank_account_id=(
            payload.bank_account_id
            if payload.payment_mode is GoldPaymentMode.bank
            else None
        ),
        subtotal=_ZERO,
        extra_cost_pct=d(payload.extra_cost_pct),
        total=_ZERO,
        notes=payload.notes,
        created_by_user_id=current.id,
    )
    db.add(purchase)
    await db.flush()

    # Resolved once for the whole bill, not per lot: every lot on one dealer's
    # invoice was quoted on the same day in the same currency, and looking the
    # rate up per line would let two lots of the same bill convert differently
    # if the rate changed mid-request.
    line_currency = payload.currency
    line_fx = (
        Decimal("1")
        if line_currency is Currency.PKR
        else await fx.require_rate(db, line_currency, as_of=clock.shop_date(purchased_at))
    )

    subtotal = _ZERO
    rows: list[GoldPurchaseItem] = []
    for line in payload.items:
        # The dealer quotes in their own currency and the books are kept in
        # rupees, so the line value, the stock value and the journal entry are
        # the same number rather than three that happen to look similar.
        amount = (
            purchasing.gold_line_amount(line.weight_g, line.rate_per_g) * line_fx
        ).quantize(Decimal("0.01"))
        subtotal += amount

        pot = await purchasing.raw_gold_item(
            db, purity=line.purity, branch_id=buy_branch.id
        )
        row = GoldPurchaseItem(
            purchase_id=purchase.id,
            description=(line.description or "").strip() or None,
            purity=line.purity,
            weight_g=d(line.weight_g),
            rate_per_g=d(line.rate_per_g),
            currency=line_currency,
            fx_rate_to_pkr=line_fx,
            amount=amount,
            inventory_item_id=pot.id,
            notes=line.notes,
        )
        db.add(row)
        await db.flush()
        rows.append(row)

        await post_movement(
            db,
            item=pot,
            type=MovementType.purchase_in,
            weight_g_delta=d(line.weight_g),
            reference_type=purchasing.GOLD_PURCHASE_SOURCE,
            reference_id=purchase.id,
            notes=(
                f"{purchase.purchase_no} — {line.purity}k at {d(line.rate_per_g)}/g"
                f" from {supplier.name}"
            ),
            user_id=current.id,
        )

    purchase.subtotal = subtotal.quantize(Decimal("0.01"))
    purchase.total = purchasing.apply_extra_cost(purchase.subtotal, purchase.extra_cost_pct)
    await db.flush()

    entry = await purchasing.post_gold_purchase(
        db, purchase, rows, supplier_name=supplier.name, user_id=current.id
    )
    purchase.journal_entry_id = entry.id

    await log_action(
        db,
        user=current,
        action="purchasing.gold_purchase.create",
        resource_type="gold_purchase",
        resource_id=purchase.id,
        details={
            "purchase_no": purchase.purchase_no,
            "supplier": supplier.name,
            "lots": len(rows),
            "weight_g": str(sum((d(r.weight_g) for r in rows), _ZERO)),
            "total": str(purchase.total),
            "paid_by": purchase.payment_mode.value,
            "entry_no": entry.entry_no,
        },
    )
    await db.commit()
    fresh = await _load_gold_purchase(db, purchase.id)
    read = (await _decorate_gold(db, [fresh]))[0]
    return GoldPurchaseDetail(
        **read.model_dump(), items=[_gold_item_read(i) for i in fresh.items]
    )


@router.get("/gold-purchases", response_model=list[GoldPurchaseRead], dependencies=[read])
async def list_gold_purchases(
    db: DbSession,
    supplier_id: int | None = Query(default=None),
    branch_id: int | None = Query(default=None),
    payment_mode: GoldPaymentMode | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[GoldPurchaseRead]:
    stmt = select(GoldPurchase).order_by(GoldPurchase.id.desc()).limit(limit).offset(offset)
    if supplier_id is not None:
        stmt = stmt.where(GoldPurchase.supplier_id == supplier_id)
    if branch_id is not None:
        stmt = stmt.where(GoldPurchase.branch_id == branch_id)
    if payment_mode is not None:
        stmt = stmt.where(GoldPurchase.payment_mode == payment_mode)
    if date_from is not None:
        stmt = stmt.where(GoldPurchase.purchased_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        stmt = stmt.where(GoldPurchase.purchased_at <= datetime.combine(date_to, time.max))
    rows = list((await db.execute(stmt)).unique().scalars().all())
    return await _decorate_gold(db, rows)


@router.get(
    "/gold-purchases/{purchase_id}", response_model=GoldPurchaseDetail, dependencies=[read]
)
async def get_gold_purchase(purchase_id: int, db: DbSession) -> GoldPurchaseDetail:
    purchase = await _load_gold_purchase(db, purchase_id)
    read = (await _decorate_gold(db, [purchase]))[0]
    return GoldPurchaseDetail(
        **read.model_dump(), items=[_gold_item_read(i) for i in purchase.items]
    )


@router.post(
    "/gold-purchases/{purchase_id}/reverse",
    response_model=GoldPurchaseDetail,
    dependencies=[write, confirm],
)
async def reverse_gold_purchase(
    purchase_id: int, db: DbSession, current: CurrentUser
) -> GoldPurchaseDetail:
    """
    Undo a bill: metal back out of the safe, the money back where it came from.

    The row is not edited or deleted. The ledger is append-only, so the
    correction is a reversing entry pointing at the original, and "was this
    undone" stays a question the journal answers rather than a flag that can
    drift out of step with it. A second attempt comes back 409, and so does a
    bill whose metal has already gone to a worker.
    """
    purchase = await _load_gold_purchase(db, purchase_id)
    reversal = await purchasing.reverse_gold_purchase(db, purchase, user_id=current.id)
    await log_action(
        db,
        user=current,
        action="purchasing.gold_purchase.reverse",
        resource_type="gold_purchase",
        resource_id=purchase.id,
        details={"purchase_no": purchase.purchase_no, "reversal_no": reversal.entry_no},
    )
    await db.commit()
    fresh = await _load_gold_purchase(db, purchase_id)
    read = (await _decorate_gold(db, [fresh]))[0]
    return GoldPurchaseDetail(
        **read.model_dump(), items=[_gold_item_read(i) for i in fresh.items]
    )
