"""
The stock form: a finished design becomes a sellable product.

This is where the workshop hands over to the shop. Until it runs, a design is a
pile of legs — real cost, real metal, no serial number and nothing a customer
can buy. Stocking mints the product, puts the piece on the shelf and moves its
metal out of work-in-progress in the books, in one transaction, because a piece
that exists in stock but not in the ledger (or the reverse) is exactly the
disagreement this system is built to prevent.

The arithmetic lives in `app.services.stocking`; the posting lives in
`app.services.ledger`. What is here is the sequencing and the refusals.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.models.design import Design, DesignStatus
from app.models.inventory import InventoryItem, InventoryType
from app.models.product import Product, ProductStatus
from app.models.product_stone import ProductStone
from app.models.stock_movement import MovementType
from app.models.stone import Stone
from app.schemas.stocking import (
    HopRead,
    StockDesign,
    StockPreview,
    StockResult,
    StockStoneLine,
    StockTotals,
    StoneUseRead,
    WeightsRead,
)
from app.services import branches, fx, stocking
from app.services.audit import log_action
from app.services.inventory import post_movement
from app.services.ledger import d
from app.services.product_cost import recompute_material_cost
from app.services.routing import current_gold_rate
from app.services.serial import next_product_serial
from app.services.stocking import Rollup, StoneUse, Weights

async def _get_inventory(db: DbSession, item_id: int) -> InventoryItem:
    item = await db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Inventory item #{item_id} not found")
    return item


router = APIRouter()
read = Depends(require_perm("design:read"))
write = Depends(require_perm("design:write"))

_PKR = Decimal("0.01")
_CT = Decimal("0.0001")


@dataclass
class _StoneRow:
    """
    One stone line, translated into what `product_stones` stores.

    The form talks in line totals — "350 stones, 12.5ct" — because that is what
    the setting leg recorded. `product_cost.recompute_material_cost` values a
    row as weight x rate x quantity, so `weight_ct` on the row has to be the
    weight of *one* stone or the line is costed 350 times over. The division
    happens once, here, and `total_ct` is recomputed from the stored figure
    rather than kept from the payload: the product's carat weight must equal
    what its own stone rows add up to, down to the last thousandth.
    """

    stone_id: int
    quantity: int
    each_ct: Decimal
    total_ct: Decimal
    rate_per_ct: Decimal
    notes: str | None


def _stone_row(line: StockStoneLine, rate_per_ct: Decimal) -> _StoneRow:
    qty = max(line.quantity, 1)
    each = (d(line.weight_ct) / Decimal(qty)).quantize(_CT)
    return _StoneRow(
        stone_id=line.stone_id,
        quantity=qty,
        each_ct=each,
        total_ct=(each * Decimal(qty)).quantize(_CT),
        rate_per_ct=rate_per_ct,
        notes=line.notes,
    )


def _stone_read(s: StoneUse) -> StoneUseRead:
    return StoneUseRead(
        stone_id=s.stone_id,
        stone_name=s.stone_name,
        quantity_used=s.quantity_used,
        weight_used_ct=s.weight_used_ct,
        rate_per_ct=s.rate_per_ct,
        value=s.value,
    )


def _hop_read(h: stocking.Hop) -> HopRead:
    return HopRead(
        leg_id=h.leg_id,
        sequence=h.sequence,
        department=h.department,
        worker=h.worker,
        status=h.status,
        gold_in_g=h.gold_in_g,
        gold_out_g=h.gold_out_g,
        gold_purity=h.gold_purity,
        piece_count=h.piece_count,
        wastage_allowed_g=h.wastage_allowed_g,
        wastage_actual_g=h.wastage_actual_g,
        wastage_excess_g=h.wastage_excess_g,
        labour_basis=h.labour_basis,
        labour_rate=h.labour_rate,
        labour_amount=h.labour_amount,
        stone_value=h.stone_value,
        stones=[_stone_read(s) for s in h.stones],
    )


def _weights_read(w: Weights) -> WeightsRead:
    return WeightsRead(
        gross_weight_g=w.gross_weight_g,
        stone_weight_ct=w.stone_weight_ct,
        stone_weight_g=w.stone_weight_g,
        net_metal_g=w.net_metal_g,
        gold_purity=w.gold_purity,
        pure_weight_g=w.pure_weight_g,
    )


def _totals(roll: Rollup) -> StockTotals:
    return StockTotals(
        hops=len(roll.hops),
        pieces=roll.pieces,
        gold_issued_g=roll.gold_issued_g,
        gold_received_g=roll.gold_received_g,
        wastage_allowed_g=roll.wastage_allowed_g,
        wastage_actual_g=roll.wastage_actual_g,
        wastage_excess_g=roll.wastage_excess_g,
        stone_weight_ct=roll.stone_weight_ct,
        stone_value=roll.stone_value,
        labour_total=roll.labour_total,
    )


async def _get_design(db: DbSession, design_id: int, *, lock: bool = False) -> Design:
    """
    Load the design, optionally holding a row lock for the rest of the
    transaction.

    `lock=True` on the commit path. "Not already stocked" is a read followed by
    a write, and no constraint can express it — two clicks landing together
    would both see an unstocked design, mint two products for one piece and
    post its metal into Finished Goods twice. Locking the bare id first is the
    same dance `designs.py` does: the model eager-joins nullable relations and
    Postgres refuses FOR UPDATE across an outer join.
    """
    if lock:
        await db.execute(select(Design.id).where(Design.id == design_id).with_for_update())
    design = await db.get(Design, design_id)
    if design is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Design not found")
    return design


@router.get("/designs/{design_id}/preview", response_model=StockPreview, dependencies=[read])
async def preview(design_id: int, db: DbSession) -> StockPreview:
    """
    Everything the stock form needs, before anything is committed.

    Every figure is derived from the legs on the way past — there is no stored
    roll-up to go stale. The refusals are the same ones the commit applies, so
    a piece that cannot be stocked says why here rather than after the operator
    has filled the form in.
    """
    design = await _get_design(db, design_id)
    stocking.ensure_stockable(design)

    roll = stocking.roll_up(design)
    rate = await current_gold_rate(db)
    weights = stocking.derive_weights(
        gross_weight_g=roll.last_received_g,
        stone_weight_ct=roll.stone_weight_ct,
        gold_purity=roll.last_purity,
        # The piece came off the scale with its stones already in it, so the
        # suggested gross is what the last department returned and the metal is
        # what is left after the stones come off.
        net_metal_g=None,
    )
    gold_value = stocking.capitalised_gold_value(
        weights.net_metal_g, weights.gold_purity, rate
    )
    material = (gold_value + roll.stone_value).quantize(_PKR)

    return StockPreview(
        design_id=design.id,
        design_no=design.design_no,
        tag_no=design.tag_no,
        item=design.item.name if design.item else None,
        customer=design.customer.name if design.customer else None,
        status=design.status,
        hops=[_hop_read(h) for h in roll.hops],
        stones=[_stone_read(s) for s in roll.stones],
        totals=_totals(roll),
        suggested_gold_weight_g=roll.last_received_g,
        suggested_gold_purity=roll.last_purity,
        suggested_name=f"{design.item.name} {design.design_no}"
        if design.item
        else design.design_no,
        gold_rate_per_g=rate,
        weights=_weights_read(weights),
        gold_value=gold_value,
        material_cost=material,
        piece_cost=(roll.labour_total + material).quantize(_PKR),
    )


@router.post(
    "/designs/{design_id}/stock",
    response_model=StockResult,
    status_code=status.HTTP_201_CREATED,
    # This mints stock and posts to the books — undoing it needs a hand-written
    # reversal — so the operator re-authenticates.
    dependencies=[write, Depends(require_password_confirm)],
)
async def stock_design(
    design_id: int, payload: StockDesign, db: DbSession, current: CurrentUser
) -> StockResult:
    """
    Mint the product, shelve the piece, and post its metal into Finished Goods.

    Order matters. The product exists first because the inventory row and the
    journal entry both point at it; the stones are attached before the material
    cost is computed, because that is what values them; and the ledger entry is
    posted at the same rate the product's cost is locked to, so one rate governs
    both and neither can be re-priced against the other afterwards.
    """
    design = await _get_design(db, design_id, lock=True)
    stocking.ensure_stockable(design)

    roll = stocking.roll_up(design)
    rate = await current_gold_rate(db)

    # Omitted stone lines mean "whatever the design consumed". The setter's
    # lines are already on the legs, and silently dropping them would stock a
    # stone-set piece as if it were plain metal — understating both its weight
    # and its cost. An explicit empty list is a different statement and stands.
    lines: list[StockStoneLine] = (
        payload.stones
        if payload.stones is not None
        else [
            StockStoneLine(
                stone_id=s.stone_id,
                # A leg that recorded carats but never counted the stones would
                # otherwise arrive as a zero-count line, and a zero count values
                # the stones at nothing.
                quantity=max(s.quantity_used, 1),
                weight_ct=s.weight_used_ct,
                rate_per_ct=s.rate_per_ct,
            )
            for s in roll.stones
        ]
    )

    # What this design actually paid for each stone, to fall back on when the
    # form sends a line without a rate. The stone master's default is the last
    # resort: it moves, and a piece must be costed at what it consumed.
    consumed_rate = {s.stone_id: s.rate_per_ct for s in roll.stones}

    resolved: list[_StoneRow] = []
    stone_ct = Decimal("0")
    for line in lines:
        stone = await db.get(Stone, line.stone_id)
        if stone is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Stone #{line.stone_id} not found"
            )
        rate_per_ct = line.rate_per_ct
        if rate_per_ct is None:
            rate_per_ct = consumed_rate.get(line.stone_id, d(stone.default_rate_per_ct))
        row = _stone_row(line, d(rate_per_ct))
        resolved.append(row)
        stone_ct += row.total_ct

    weights = stocking.derive_weights(
        gross_weight_g=payload.gross_weight_g,
        stone_weight_ct=stone_ct,
        gold_purity=payload.gold_purity,
        net_metal_g=payload.gold_weight_g,
    )
    making = stocking.total_cost(roll.labour_total, payload.other_charges)
    stone_value = sum(
        ((r.total_ct * r.rate_per_ct) for r in resolved), Decimal("0")
    ).quantize(_PKR)

    # The showroom the finished piece goes into. The workshop may be central,
    # but the piece has to land somewhere sellable.
    shelf = await branches.resolve_branch(db, requested_id=payload.branch_id, user=current)

    product = Product(
        serial_no=await next_product_serial(db),
        branch_id=shelf.id,
        name=payload.name,
        category=payload.category,
        description=payload.description,
        gold_weight_g=weights.net_metal_g,
        gold_purity=weights.gold_purity,
        stone_weight_ct=weights.stone_weight_ct,
        gross_weight_g=weights.gross_weight_g,
        other_charges=payload.other_charges,
        stocked_at=datetime.now(timezone.utc),
        design_id=design.id,
        total_cost=making,
        status=ProductStatus.in_stock,
    )
    db.add(product)
    await db.flush()

    for row in resolved:
        # Snapshotted per row: the stone master says what currency its rate is
        # quoted in, and the conversion is locked now so the piece's cost stays
        # what it was when it was stocked.
        stone_row = await db.get(Stone, row.stone_id)
        currency, fx_rate = await fx.snapshot_for_stone(db, stone_row)
        db.add(
            ProductStone(
                product_id=product.id,
                stone_id=row.stone_id,
                quantity=row.quantity,
                weight_ct=row.each_ct,
                rate_per_ct=row.rate_per_ct,
                currency=currency,
                fx_rate_to_pkr=fx_rate,
                notes=row.notes,
            )
        )
    await db.flush()

    # Locks today's rate onto the product on this first pass. Attaching a stone
    # later recomputes the stone side only, so the piece's gold is never
    # re-priced at a rate it was not made at.
    material = await recompute_material_cost(db, product, gold_rate_pkr=rate)

    inventory = InventoryItem(
        type=InventoryType.finished_product,
        label=f"{product.name} ({design.design_no})",
        location=payload.finished_inventory_location,
        quantity=0,
        weight_g=Decimal("0"),
        weight_ct=Decimal("0"),
        purity=weights.gold_purity,
        product_id=product.id,
        branch_id=shelf.id,
    )
    db.add(inventory)
    await db.flush()
    # The snapshot is moved rather than set, so the piece arrives on the shelf
    # as a stock movement someone can point at — the same discipline every
    # other weight in this system follows. Metal and stones are booked
    # separately because that is how the sale takes them out again.
    await post_movement(
        db,
        item=inventory,
        type=MovementType.manufacturing_in,
        quantity_delta=1,
        weight_g_delta=weights.net_metal_g,
        weight_ct_delta=weights.stone_weight_ct,
        reference_type=stocking.SOURCE_TYPE,
        reference_id=product.id,
        notes=f"{design.design_no} stocked as {product.serial_no}",
        user_id=current.id,
    )

    # The metal is now on the shelf as a finished piece, so it has to leave the
    # pot it came back into. Every leg receive credited the raw-gold source, so
    # without this the same grams sit in raw_gold *and* in finished_product and
    # the stock report counts the shop's gold twice. The ledger already makes
    # this move (1130 -> 1150); this is its counterpart in the stock ledger.
    source_leg = next(
        (leg for leg in reversed(design.legs) if leg.gold_source_inventory_id is not None),
        None,
    )
    if source_leg is not None and weights.net_metal_g > 0:
        await post_movement(
            db,
            item=await _get_inventory(db, source_leg.gold_source_inventory_id),
            type=MovementType.manufacturing_out,
            weight_g_delta=-weights.net_metal_g,
            reference_type=stocking.SOURCE_TYPE,
            reference_id=product.id,
            notes=f"{design.design_no} metal moved into finished goods as {product.serial_no}",
            user_id=current.id,
        )

    entry = await stocking.post_stocking(
        db,
        design=design,
        product=product,
        weights=weights,
        rate=rate,
        user_id=current.id,
    )

    design.status = DesignStatus.stocked
    design.product_id = product.id
    # The piece is on the shelf, not out with anyone.
    design.current_department_id = None

    await log_action(
        db,
        user=current,
        action="design.stock",
        resource_type="product",
        resource_id=product.id,
        details={
            "design_no": design.design_no,
            "serial_no": product.serial_no,
            "gross_weight_g": str(weights.gross_weight_g),
            "gold_weight_g": str(weights.net_metal_g),
            "pure_weight_g": str(weights.pure_weight_g),
            "gold_purity": weights.gold_purity,
            "stone_weight_ct": str(weights.stone_weight_ct),
            "labour_total": str(roll.labour_total),
            "other_charges": str(d(payload.other_charges)),
            "total_cost": str(making),
            "material_cost": str(material),
            "gold_rate_per_g": str(rate),
            "entry_no": entry.entry_no,
        },
    )
    await db.commit()

    return StockResult(
        design_id=design.id,
        design_no=design.design_no,
        product_id=product.id,
        serial_no=product.serial_no,
        name=product.name,
        category=product.category,
        status=design.status,
        stocked_at=product.stocked_at,
        weights=_weights_read(weights),
        gold_rate_per_g=rate,
        labour_total=roll.labour_total,
        other_charges=d(payload.other_charges).quantize(_PKR),
        total_cost=making,
        material_cost=material,
        stone_value=stone_value,
        piece_cost=(making + material).quantize(_PKR),
        inventory_item_id=inventory.id,
        inventory_location=inventory.location,
        entry_id=entry.id,
        entry_no=entry.entry_no,
    )
