"""
The routing engine: a piece, and every department it passes through.

This replaces the fixed karigar → fixer → polish job. A design is identified
the moment work starts on it and then accumulates *legs* — one per visit to one
department — so a shop running nine stages, or sending a piece back to setting
twice, is describing normal work rather than fighting the model.

Every leg moves real material and real money, so each one posts stock movements
and a balanced ledger entry. Nothing here writes journal rows directly; that is
`app.services.ledger`'s job and the balancing invariant lives there.
"""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.models.customer import Customer
from app.models.department import Department
from app.models.design import (
    Design,
    DesignStatus,
    JobLeg,
    LabourBasis,
    LegStatus,
    LegStone,
    WastageBasis,
)
from app.core.units import carats_to_grams
from app.models.inventory import InventoryItem, InventoryType
from app.models.item import Item
from app.models.metal import Metal
from app.models.stock_movement import MovementType
from app.models.stone import Stone
from app.models.stone_draw import StoneDraw
from app.models.vendor import Vendor
from app.schemas.design import (
    DesignCreate,
    DesignDetail,
    DesignRead,
    DesignTrace,
    JobLegRead,
    LegCancel,
    LegIssue,
    LegReceive,
    LegStoneRead,
    LotSplit,
    TraceHop,
    TraceStone,
    TraceTotals,
)
from app.services import fx, stone_costing
from app.services.audit import log_action
from app.services.inventory import post_movement
from app.services.ledger import d
from app.services.routing import (
    compute_labour,
    current_gold_rate,
    net_metal_g,
    next_design_no,
    next_lot_no,
    next_tag_no,
    post_leg_cancel,
    post_leg_issue,
    post_leg_receive,
    agreed_wastage_pct,
    settle_stones,
    settle_wastage,
)

router = APIRouter()
read = Depends(require_perm("design:read"))
write = Depends(require_perm("design:write"))


def _stone_read(s: LegStone) -> LegStoneRead:
    return LegStoneRead(
        id=s.id,
        created_at=s.created_at,
        updated_at=s.updated_at,
        leg_id=s.leg_id,
        stone_id=s.stone_id,
        stone_name=s.stone.name if s.stone else None,
        quantity_issued=s.quantity_issued,
        weight_issued_ct=d(s.weight_issued_ct),
        quantity_set=s.quantity_set,
        weight_set_ct=d(s.weight_set_ct),
        quantity_returned=s.quantity_returned,
        weight_returned_ct=d(s.weight_returned_ct),
        quantity_broken=s.quantity_broken,
        weight_broken_ct=d(s.weight_broken_ct),
        weight_owed_ct=d(s.weight_owed_ct),
        quantity_used=s.quantity_used,
        rate_per_ct=d(s.rate_per_ct),
        owed_rate_per_ct=d(s.owed_rate_per_ct),
        notes=s.notes,
    )


def _leg_read(leg: JobLeg) -> JobLegRead:
    return JobLegRead(
        id=leg.id,
        created_at=leg.created_at,
        updated_at=leg.updated_at,
        design_id=leg.design_id,
        sequence=leg.sequence,
        department_id=leg.department_id,
        department_name=leg.department.name if leg.department else None,
        worker_id=leg.worker_id,
        worker_name=leg.worker.name if leg.worker else None,
        status=leg.status,
        issued_at=leg.issued_at,
        metal=leg.metal or Metal.gold,
        gold_issued_g=d(leg.gold_issued_g),
        gold_issued_purity=leg.gold_issued_purity,
        gold_issued_tunch_pct=(
            d(leg.gold_issued_tunch_pct) if leg.gold_issued_tunch_pct is not None else None
        ),
        stones_issued_ct=d(leg.stones_issued_ct),
        gold_source_inventory_id=leg.gold_source_inventory_id,
        stone_source_inventory_id=leg.stone_source_inventory_id,
        received_at=leg.received_at,
        gold_received_gross_g=d(leg.gold_received_gross_g),
        gold_received_g=d(leg.gold_received_g),
        gold_received_purity=leg.gold_received_purity,
        gold_received_tunch_pct=(
            d(leg.gold_received_tunch_pct) if leg.gold_received_tunch_pct is not None else None
        ),
        stones_set_ct=d(leg.stones_set_ct),
        stones_used_ct=d(leg.stones_used_ct),
        stones_returned_ct=d(leg.stones_returned_ct),
        stones_broken_ct=d(leg.stones_broken_ct),
        stones_owed_ct=d(leg.stones_owed_ct),
        piece_count=leg.piece_count,
        wastage_basis=leg.wastage_basis,
        wastage_per_100_pcs_g=(
            d(leg.wastage_per_100_pcs_g) if leg.wastage_per_100_pcs_g is not None else None
        ),
        wastage_pieces_base=leg.wastage_pieces_base,
        wastage_allowed_pct=(
            d(leg.wastage_allowed_pct) if leg.wastage_allowed_pct is not None else None
        ),
        wastage_ratti=d(leg.wastage_ratti) if leg.wastage_ratti is not None else None,
        wastage_ratti_base=leg.wastage_ratti_base,
        wastage_allowed_g=d(leg.wastage_allowed_g),
        wastage_actual_g=d(leg.wastage_actual_g),
        wastage_excess_g=d(leg.wastage_excess_g),
        # Nullable all the way through rather than coalesced to zero: a leg
        # settled before these existed has no fine reckoning, and showing 0.0000
        # would read as "nothing was owed" on a job that may well have been
        # short. Absent has to stay absent.
        wastage_allowed_fine_g=(
            d(leg.wastage_allowed_fine_g) if leg.wastage_allowed_fine_g is not None else None
        ),
        wastage_actual_fine_g=(
            d(leg.wastage_actual_fine_g) if leg.wastage_actual_fine_g is not None else None
        ),
        wastage_excess_fine_g=(
            d(leg.wastage_excess_fine_g) if leg.wastage_excess_fine_g is not None else None
        ),
        metal_due_date=leg.metal_due_date,
        labour_basis=leg.labour_basis,
        labour_rate=d(leg.labour_rate),
        labour_amount=d(leg.labour_amount),
        notes=leg.notes,
        stones=[_stone_read(s) for s in leg.stones],
    )


def _design_read(design: Design) -> DesignRead:
    return DesignRead(
        id=design.id,
        created_at=design.created_at,
        updated_at=design.updated_at,
        design_no=design.design_no,
        tag_no=design.tag_no,
        item_id=design.item_id,
        item_name=design.item.name if design.item else None,
        customer_id=design.customer_id,
        customer_name=design.customer.name if design.customer else None,
        current_department_id=design.current_department_id,
        current_department_name=(
            design.current_department.name if design.current_department else None
        ),
        status=design.status,
        is_lot=design.is_lot,
        expected_pieces=design.expected_pieces,
        parent_design_id=design.parent_design_id,
        piece_weight_g=(
            d(design.piece_weight_g) if design.piece_weight_g is not None else None
        ),
        piece_purity=design.piece_purity,
        piece_tunch_pct=(
            d(design.piece_tunch_pct) if design.piece_tunch_pct is not None else None
        ),
        image_url=design.image_url,
        notes=design.notes,
        product_id=design.product_id,
    )


def _design_detail(design: Design) -> DesignDetail:
    return DesignDetail(
        **_design_read(design).model_dump(),
        legs=[_leg_read(leg) for leg in design.legs],
    )


async def _lock_row(db: DbSession, model, row_id: int) -> None:
    """
    Take a row lock held until the transaction ends.

    Selecting only the primary key is deliberate: these models eager-join their
    optional relations, and Postgres refuses `FOR UPDATE` on the nullable side
    of an outer join. Locking the bare row first and loading the object
    afterwards keeps the lock without fighting the eager loads.
    """
    await db.execute(select(model.id).where(model.id == row_id).with_for_update())


async def _get_design(db: DbSession, design_id: int, *, lock: bool = False) -> Design:
    """
    Load a design, optionally taking a row lock for the rest of the transaction.

    `lock=True` on the paths that decide whether a piece may move. The "only one
    open leg" rule is a read followed by a write, so without a lock two requests
    that arrive together both see no open leg and both issue the same metal to
    two different workers. There is no database constraint that can express
    "at most one issued leg per design", so the lock is the guard.
    """
    if lock:
        await _lock_row(db, Design, design_id)
    design = await db.get(Design, design_id)
    if design is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Design not found")
    return design


async def _get_leg(db: DbSession, leg_id: int, *, lock: bool = False) -> JobLeg:
    """`lock=True` when about to settle the leg — receiving or cancelling twice
    would post the material movements and journal entries twice over."""
    if lock:
        await _lock_row(db, JobLeg, leg_id)
    leg = await db.get(JobLeg, leg_id)
    if leg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leg not found")
    return leg


def _department_basis(department: Department) -> WastageBasis:
    """
    The convention this department settles wastage under.

    Stored as free text on the department, so an unrecognised value is read as
    the percentage basis: that is what every worker's agreed rate is already
    expressed in, and falling through to the per-100 basis instead would judge
    the leg against an allowance nobody has configured.
    """
    try:
        return WastageBasis(department.default_wastage_basis)
    except ValueError:
        return WastageBasis.percent_of_issued


async def _get_inventory(db: DbSession, item_id: int) -> InventoryItem:
    item = await db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Inventory item #{item_id} not found")
    return item


BROKEN_STONE_LABEL = "Broken / miscellaneous stones"


async def _broken_stone_item(db: DbSession, leg: JobLeg, *, user) -> InventoryItem:
    """
    The branch's broken-stone row, made on first use.

    Created rather than demanded from the caller. Stones break during setting
    whether or not anyone remembered to set up somewhere to put them, and a
    receive that fails because the row is missing pushes the counter into
    recording the breakage as something else — usually as stones returned
    whole, which puts chipped material back among the parcel it can no longer
    serve. Getting the classification right matters more than making the shop
    configure it first.

    Scoped to the branch that issued the stones, so broken material is counted
    where it physically is.
    """
    branch_id = None
    if leg.stone_source_inventory_id is not None:
        source = await db.get(InventoryItem, leg.stone_source_inventory_id)
        branch_id = source.branch_id if source is not None else None
    if branch_id is None:
        if leg.gold_source_inventory_id is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This leg records no source of material, so there is no branch to hold the "
                "broken stones in. Restore the inventory item before receiving.",
            )
        gold_source = await _get_inventory(db, leg.gold_source_inventory_id)
        branch_id = gold_source.branch_id

    existing = (
        await db.execute(
            select(InventoryItem).where(
                InventoryItem.type == InventoryType.broken_stone,
                InventoryItem.branch_id == branch_id,
                InventoryItem.label == BROKEN_STONE_LABEL,
            )
        )
    ).scalars().first()
    if existing is not None:
        return existing

    item = InventoryItem(
        type=InventoryType.broken_stone,
        label=BROKEN_STONE_LABEL,
        branch_id=branch_id,
        quantity=0,
        weight_g=Decimal("0"),
        weight_ct=Decimal("0"),
    )
    db.add(item)
    await db.flush()
    await log_action(
        db, user=user,
        action="inventory.create",
        resource_type="inventory_item", resource_id=item.id,
        details={"label": BROKEN_STONE_LABEL, "type": InventoryType.broken_stone.value,
                 "reason": "first breakage recorded at a stone setting leg"},
    )
    return item


@router.post("", response_model=DesignRead, status_code=status.HTTP_201_CREATED, dependencies=[write])
async def mint_design(payload: DesignCreate, db: DbSession, current: CurrentUser) -> DesignRead:
    """
    Give a piece its identity before any metal moves, so the shop can find it
    from the first department onward.

    With `as_lot`, the identity minted is a *lot* — one dealing with a maker
    that will divide into several pieces when the metal comes back. It takes a
    `LOT-` number from its own sequence rather than the item's, because until
    the pieces exist the item is a plan and the maker is the fact.
    """
    item = await db.get(Item, payload.item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    if payload.customer_id is not None and await db.get(Customer, payload.customer_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")

    design = Design(
        design_no=await (next_lot_no(db) if payload.as_lot else next_design_no(db, item)),
        item_id=item.id,
        customer_id=payload.customer_id,
        status=DesignStatus.in_production,
        is_lot=payload.as_lot,
        expected_pieces=payload.expected_pieces or 0,
        notes=payload.notes,
    )
    db.add(design)
    await db.commit()
    await db.refresh(design)
    return _design_read(design)


@router.get("", response_model=list[DesignRead], dependencies=[read])
async def list_designs(
    db: DbSession,
    status_: DesignStatus | None = Query(default=None, alias="status"),
    current_department_id: int | None = Query(default=None),
    item_id: int | None = Query(default=None),
    worker_id: int | None = Query(
        default=None, description="Pieces this worker has a leg on."
    ),
    held_by_worker: bool = Query(
        default=False,
        description="With worker_id, narrow to pieces still in his hands right now.",
    ),
    q: str | None = Query(default=None, description="Design or tag number"),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[DesignRead]:
    stmt = select(Design).order_by(Design.id.desc()).limit(limit).offset(offset)
    if worker_id is not None:
        # An EXISTS rather than a join: a piece that visited the same worker
        # twice would come back twice from a join, and a worklist that lists a
        # ring three times is one the shop stops trusting.
        leg_match = select(JobLeg.id).where(
            JobLeg.design_id == Design.id, JobLeg.worker_id == worker_id
        )
        if held_by_worker:
            leg_match = leg_match.where(JobLeg.status == LegStatus.issued)
        stmt = stmt.where(leg_match.exists())
    if status_:
        stmt = stmt.where(Design.status == status_)
    if current_department_id is not None:
        stmt = stmt.where(Design.current_department_id == current_department_id)
    if item_id is not None:
        stmt = stmt.where(Design.item_id == item_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Design.design_no.ilike(like), Design.tag_no.ilike(like)))
    rows = list((await db.execute(stmt)).scalars().all())
    return [_design_read(r) for r in rows]


@router.get("/{design_id}", response_model=DesignDetail, dependencies=[read])
async def get_design(design_id: int, db: DbSession) -> DesignDetail:
    return _design_detail(await _get_design(db, design_id))


@router.post("/{design_id}/tag", response_model=DesignRead, dependencies=[write])
async def generate_tag(design_id: int, db: DbSession, current: CurrentUser) -> DesignRead:
    """
    Tie a physical tag to the piece.

    Tags are printed on demand — usually at casting — rather than for every
    piece, so this is a separate action from minting the design. Re-tagging is
    refused: two labels for one piece is how a shop loses track of it.
    """
    design = await _get_design(db, design_id)
    if design.tag_no:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{design.design_no} already carries tag {design.tag_no}."
        )
    design.tag_no = await next_tag_no(db)
    await db.commit()
    await db.refresh(design)
    return _design_read(design)


@router.post(
    "/{design_id}/split",
    response_model=list[DesignRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[write],
)
async def split_lot(
    design_id: int, payload: LotSplit, db: DbSession, current: CurrentUser
) -> list[DesignRead]:
    """
    Divide a received lot into the pieces the maker handed over.

    Each piece is weighed individually and gets its own design number from the
    item, which it then carries through setting, stock and sale. An even split
    of the lot weight would be quicker and wrong: twelve bangles differ by a
    gram either way, and every piece's cost, price and wastage would afterwards
    be worked out from a weight it never had.

    The total is checked against the metal that actually came back, not against
    what went out. What went out was pure and what came back is 21k, and the
    difference between them is the maker's wastage — already settled on his
    leg. Reconciling against the issue would demand the pieces weigh what the
    bullion did and make every honest split fail.
    """
    lot = await _get_design(db, design_id, lock=True)
    if not lot.is_lot:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{lot.design_no} is a single piece, not a lot. Only a lot divides.",
        )
    if lot.status is DesignStatus.split:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{lot.design_no} has already been divided. Splitting it twice would mint a "
            "second set of numbers for metal that only came back once.",
        )
    if lot.status is DesignStatus.cancelled:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{lot.design_no} is cancelled and holds no metal."
        )

    received = [leg for leg in lot.legs if leg.status is LegStatus.received]
    if not received:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Nothing has come back on {lot.design_no} yet, so there are no pieces to divide. "
            "Receive the metal from the maker first.",
        )
    if any(leg.status is LegStatus.issued for leg in lot.legs):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{lot.design_no} is still out with a worker. Receive it before dividing, or the "
            "pieces would be numbered from metal the shop is not holding.",
        )

    # The last leg to come back is what the shop is holding. Earlier legs were
    # relieved when the piece moved on, and summing them would count the same
    # metal once per department it passed through.
    last = max(received, key=lambda leg: (leg.received_at or leg.id, leg.id))
    back = d(last.gold_received_g)
    total = sum((d(p.weight_g) for p in payload.pieces), Decimal("0")).quantize(Decimal("0.0001"))
    if total != back:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"The pieces add up to {total}g but {back}g came back on {lot.design_no}. "
            f"{'Some metal is unaccounted for' if total < back else 'The pieces weigh more than what returned'}"
            " — check the weights before dividing.",
        )

    item = await db.get(Item, lot.item_id)
    pieces: list[Design] = []
    for line in payload.pieces:
        if line.customer_id is not None and await db.get(Customer, line.customer_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
        piece = Design(
            design_no=await next_design_no(db, item),
            item_id=lot.item_id,
            # The lot's customer carries down unless the piece names its own —
            # a commission lot is twelve commissioned pieces.
            customer_id=line.customer_id if line.customer_id is not None else lot.customer_id,
            status=DesignStatus.in_production,
            parent_design_id=lot.id,
            piece_weight_g=line.weight_g,
            # Falling back to what the leg recorded rather than leaving these
            # empty: the maker stated the purity when he handed the metal over,
            # and asking the counter to retype it per piece invites twelve
            # chances to mistype what is already on the row.
            piece_purity=line.purity if line.purity is not None else last.gold_received_purity,
            piece_tunch_pct=(
                line.tunch_pct if line.tunch_pct is not None else last.gold_received_tunch_pct
            ),
            notes=line.notes,
        )
        db.add(piece)
        # Flushed per piece, not once at the end. `next_design_no` reads the
        # highest suffix out of the table, and rows sitting unflushed in the
        # session are invisible to it — so twelve pieces would all be handed
        # TK-00007 and the unique index would reject the lot on the last one.
        await db.flush()
        pieces.append(piece)

    lot.status = DesignStatus.split
    # A lot that has divided is not on the floor any more. Leaving it pointing
    # at a department would keep it in the worklist of things still out.
    lot.current_department_id = None
    await db.flush()

    await log_action(
        db, user=current,
        action="design.lot_split",
        resource_type="design", resource_id=lot.id,
        details={
            "lot_no": lot.design_no,
            "received_g": str(back),
            "pieces": [
                {"design_no": p.design_no, "weight_g": str(d(p.piece_weight_g))} for p in pieces
            ],
        },
    )
    await db.commit()
    for piece in pieces:
        await db.refresh(piece)
    return [_design_read(p) for p in pieces]


@router.post(
    "/{design_id}/legs",
    response_model=JobLegRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[write],
)
async def issue_leg(
    design_id: int, payload: LegIssue, db: DbSession, current: CurrentUser
) -> JobLegRead:
    """
    Send the piece out to a department.

    A design may only be in one pair of hands at a time, and the worker must
    belong to the department it is going to — both are refused rather than
    corrected, because either one means the counter is describing a movement
    that did not happen.
    """
    design = await _get_design(db, design_id, lock=True)
    if design.status in (DesignStatus.sold, DesignStatus.cancelled):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{design.design_no} is {design.status.value} and cannot be issued.",
        )
    open_leg = next((l for l in design.legs if l.status is LegStatus.issued), None)
    if open_leg is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{design.design_no} is still out with "
            f"{open_leg.worker.name if open_leg.worker else 'a worker'} at "
            f"{open_leg.department.name}. Receive or cancel leg #{open_leg.sequence} first.",
        )

    department = await db.get(Department, payload.department_id)
    if department is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found")
    # No worker means the shop's own bench — cleaning, burning, rhodium, finish.
    # The leg still records every gram; it just has no ledger party, because
    # there is nobody holding the metal and nobody to bill a shortfall to.
    worker = None
    if payload.worker_id is not None:
        worker = await db.get(Vendor, payload.worker_id)
        if worker is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Worker not found")
        if worker.department_id != department.id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{worker.name} works in "
                f"{worker.department_name or 'no department'}, not {department.name}.",
            )
    # Every message and movement note below names whoever holds the metal. On an
    # in-house leg that is the shop itself.
    who = worker.name if worker else "the shop's own bench"

    if payload.stones and payload.stone_source_inventory_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "stone_source_inventory_id is required when issuing stones.",
        )

    # The department's standing terms fill in whatever the counter didn't state.
    # Resolved here and frozen onto the leg below, never re-read at receive:
    # setting's rate gets renegotiated and an old leg must settle on the deal
    # that was in force when the metal left the safe.
    basis = payload.wastage_basis or _department_basis(department)
    per_100 = payload.wastage_per_100_pcs_g
    if per_100 is None and department.default_wastage_per_100_pcs_g is not None:
        per_100 = d(department.default_wastage_per_100_pcs_g)
    # The base the figure is quoted against, from the request, then the
    # department, then the customary hundred.
    pieces_base = payload.wastage_pieces_base or department.default_wastage_pieces_base or 100
    pieces = payload.piece_count if payload.piece_count is not None else 0
    labour_rate = payload.labour_rate
    if labour_rate is None:
        labour_rate = (
            d(department.default_rate_per_piece)
            if payload.labour_basis is LabourBasis.per_piece
            and department.default_rate_per_piece is not None
            else Decimal("0")
        )

    if basis is WastageBasis.per_100_pieces:
        # Both of these would settle to a zero allowance without a word, and the
        # worker would be charged for every gram he lost on work the shop had
        # already agreed loses metal. Refused rather than defaulted.
        if pieces <= 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{department.name} allows wastage per 100 pieces, so this leg needs a piece "
                f"count. Send piece_count — with none, {who} would be allowed nothing "
                "and charged for the whole loss.",
            )
        if per_100 is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{department.name} allows wastage per 100 pieces but no grams-per-100 figure "
                "is set. Send wastage_per_100_pcs_g, or configure the department's default.",
            )

    if basis is WastageBasis.ratti_of_received and payload.wastage_ratti is None:
        # The same silent-zero trap as above, and worse here: the maker's ratti
        # is added to what he is *credited* with, so a missing figure does not
        # merely allow him nothing — it charges him the entire difference
        # between pure metal issued and alloy returned, which on a 21k job is
        # about an eighth of the weight. Refused rather than defaulted.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{department.name} settles wastage in ratti of the returned weight, so this leg "
            f"needs the agreed figure. Send wastage_ratti — with none, {who} would be charged "
            "the whole difference between the pure metal issued and the jewellery returned.",
        )

    # The same silent-zero trap on the pay side: per-piece labour multiplies the
    # rate by the count, so a missing count settles the worker's earnings at
    # nothing. Guarded here rather than at receive, when the metal is already
    # out and refusing would strand the leg.
    if payload.labour_basis is LabourBasis.per_piece and pieces <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Labour on this leg is charged per piece, so it needs a piece count. "
            f"Send piece_count — with none, {who} would be paid nothing.",
        )

    rate = await current_gold_rate(db, payload.metal)
    gold_source = await _get_inventory(db, payload.gold_source_inventory_id)
    # The metal on the leg and the metal in the drawer have to be the same
    # thing. They are separate fields — one says what is being worked, the
    # other says where it came from — and nothing but this check stops a silver
    # leg from drawing 100g out of the gold vault, posting it to the silver
    # accounts, and leaving both stock figures wrong in opposite directions.
    expected_source = (
        InventoryType.raw_silver if payload.metal is Metal.silver else InventoryType.raw_gold
    )
    if gold_source.type is not expected_source:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"This is a {payload.metal.value} leg but '{gold_source.label}' holds "
            f"{gold_source.type.value.replace('_', ' ')}. Draw the metal from a "
            f"{expected_source.value.replace('_', ' ')} item.",
        )

    leg = JobLeg(
        design_id=design.id,
        sequence=max((l.sequence for l in design.legs), default=0) + 1,
        # Set as objects, not ids: the ledger memo reads the names, and a fresh
        # row would have to lazy-load them — which async SQLAlchemy refuses.
        department=department,
        worker=worker,
        status=LegStatus.issued,
        issued_at=datetime.now(timezone.utc),
        metal=payload.metal,
        gold_issued_g=payload.gold_issued_g,
        gold_issued_purity=payload.gold_issued_purity,
        gold_issued_tunch_pct=payload.gold_issued_tunch_pct,
        gold_source_inventory_id=gold_source.id,
        # The allowance in force today, frozen onto the leg. Terms get
        # renegotiated and the leg must be judged against the deal that was in
        # force when the metal left the safe.
        # Frozen now, never re-read. See settle_wastage.
        wastage_allowed_pct=agreed_wastage_pct(worker),
        piece_count=pieces,
        wastage_basis=basis,
        wastage_per_100_pcs_g=per_100,
        wastage_pieces_base=pieces_base,
        wastage_ratti=payload.wastage_ratti,
        wastage_ratti_base=payload.wastage_ratti_base,
        metal_due_date=payload.metal_due_date,
        labour_basis=payload.labour_basis,
        labour_rate=labour_rate,
        notes=payload.notes,
    )
    db.add(leg)
    await db.flush()

    stones_ct = Decimal("0")
    for line in payload.stones:
        stone = await db.get(Stone, line.stone_id)
        if stone is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Stone #{line.stone_id} not found")
        # Per line, because a leg can carry lots priced in different currencies.
        leg_currency, leg_fx = await fx.snapshot_for_stone(db, stone)
        leg_stone = LegStone(
            leg_id=leg.id,
            stone_id=stone.id,
            quantity_issued=line.quantity_issued,
            weight_issued_ct=line.weight_issued_ct,
            currency=leg_currency,
            fx_rate_to_pkr=leg_fx,
            rate_per_ct=line.rate_per_ct or d(stone.default_rate_per_ct),
        )
        db.add(leg_stone)
        await db.flush()

        # Drawn from the parcels the shop actually bought, oldest first, and
        # the line is then costed at what those parcels cost rather than at the
        # master's standing rate. A rate typed on the request still wins — the
        # counter is stating a price it has agreed, and overriding that with a
        # historic purchase would be the system arguing with the shop.
        allocations = await stone_costing.allocate(
            db, stone=stone, carats=d(line.weight_issued_ct)
        )
        for alloc in allocations:
            db.add(
                StoneDraw(
                    leg_stone_id=leg_stone.id,
                    purchase_item_id=alloc.purchase_item_id,
                    weight_ct=alloc.weight_ct,
                    rate_per_ct_pkr=alloc.rate_per_ct_pkr,
                )
            )
        await db.flush()
        if not line.rate_per_ct and allocations:
            leg_stone.rate_per_ct = stone_costing.weighted_rate(
                [
                    StoneDraw(weight_ct=a.weight_ct, rate_per_ct_pkr=a.rate_per_ct_pkr)
                    for a in allocations
                ]
            )
        stones_ct += d(line.weight_issued_ct)
    leg.stones_issued_ct = stones_ct
    if payload.stone_source_inventory_id is not None:
        leg.stone_source_inventory_id = payload.stone_source_inventory_id

    # Nothing moves and nothing posts when nothing was issued. This is the
    # maker working on his own gold: the drawer named above is where the piece
    # will *land* when he brings it, not where anything came from, and writing
    # a zero-gram movement against it would put a line in the stock ledger
    # recording an event that did not happen.
    issuing_metal = d(payload.gold_issued_g) > 0
    if issuing_metal:
        await post_movement(
            db,
            item=gold_source,
            type=MovementType.manufacturing_out,
            weight_g_delta=-d(payload.gold_issued_g),
            reference_type="job_leg",
            reference_id=leg.id,
            notes=f"{design.design_no} issued to {who} ({department.name})",
            user_id=current.id,
        )
    if stones_ct > 0:
        await post_movement(
            db,
            item=await _get_inventory(db, payload.stone_source_inventory_id),
            type=MovementType.manufacturing_out,
            weight_ct_delta=-stones_ct,
            reference_type="job_leg",
            reference_id=leg.id,
            notes=f"{design.design_no} stones to {who}",
            user_id=current.id,
        )

    if issuing_metal:
        await post_leg_issue(db, leg, design=design, worker=worker, rate=rate, user_id=current.id)

    design.current_department_id = department.id
    await log_action(
        db, user=current,
        action="design.leg_issue",
        resource_type="job_leg", resource_id=leg.id,
        details={
            "design_no": design.design_no,
            "department": department.name,
            "worker": worker.name if worker else None,
            "gold_issued_g": str(d(leg.gold_issued_g)),
            "stones_issued_ct": str(stones_ct),
            "piece_count": pieces,
            "wastage_basis": basis.value,
            "wastage_per_100_pcs_g": str(per_100) if per_100 is not None else None,
            "wastage_allowed_pct": str(d(leg.wastage_allowed_pct)),
            "labour_basis": payload.labour_basis.value,
            "labour_rate": str(d(labour_rate)),
        },
    )
    await db.commit()
    await db.refresh(leg)
    return _leg_read(leg)


@router.post("/legs/{leg_id}/receive", response_model=JobLegRead, dependencies=[write])
async def receive_leg(
    leg_id: int, payload: LegReceive, db: DbSession, current: CurrentUser
) -> JobLegRead:
    """
    Take the piece back and settle the leg.

    `gold_received_g` on the payload is what the scale reads: the whole object,
    stones and all. The metal alone is worked out here by taking the set stones
    back out, and it is that figure the wastage runs on — see `net_metal_g`.

    A heavier return is legal and is recorded as negative wastage — see
    `settle_wastage`. What the worker is charged for is only the metal missing
    beyond his agreed allowance.
    """
    leg = await _get_leg(db, leg_id, lock=True)
    if leg.status is not LegStatus.issued:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Leg #{leg.id} is already {leg.status.value}."
        )
    # A ratti leg has to say what came back.
    #
    # The maker's convention exists *because* the purity changes: pure metal
    # goes out and 21k jewellery returns. Leave it blank and the fallback reads
    # it as "same as issued", so 107.560g of 21k is credited as 107.560g of
    # pure — the shop ends up owing him about a seventh of the job on work he
    # is actually short on, and every figure downstream agrees with itself.
    #
    # Silence must not be able to produce that, so it is refused rather than
    # defaulted. The other conventions are unaffected: a setting or lacker leg
    # hands the piece over and back at one purity, and blank there is true.
    if leg.wastage_basis is WastageBasis.ratti_of_received and (
        payload.gold_received_purity is None and payload.gold_received_tunch_pct is None
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This leg settles in ratti of the returned weight, so it has to say what purity "
            "came back. Send gold_received_purity (21 for 21k) or gold_received_tunch_pct — "
            "without one the metal is credited as though it came back pure.",
        )
    design = await _get_design(db, leg.design_id)
    # Valued in the metal the leg is actually working, not always gold.
    rate = await current_gold_rate(db, leg.metal or Metal.gold)

    by_id = {s.id: s for s in leg.stones}
    # One return per line. Repeating a line would overwrite the row but
    # *accumulate* into the running total, so the same carats would be credited
    # back to stock twice — stones the shop never got back, conjured out of a
    # duplicated payload entry.
    seen: set[int] = set()
    returned_ct = Decimal("0")
    broken_ct = Decimal("0")
    for ret in payload.stones:
        if ret.leg_stone_id in seen:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Stone line #{ret.leg_stone_id} appears more than once. "
                "Send one return per line, with the full returned amount.",
            )
        seen.add(ret.leg_stone_id)
        line = by_id.get(ret.leg_stone_id)
        if line is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"Stone line #{ret.leg_stone_id} is not on leg #{leg.id}.",
            )
        name = line.stone.name if line.stone else "stone"
        # Checked against the total, not each part separately. Set, returned
        # and broken are three ways the same carat can be spoken for, and
        # allowing each to reach the issued figure on its own would let a line
        # account for three times what left the safe — with the leftover
        # arriving as a *negative* debt, which reads as the shop owing the
        # setter stones it never gave him.
        accounted = (
            d(ret.weight_set_ct) + d(ret.weight_returned_ct) + d(ret.weight_broken_ct)
        )
        if accounted > d(line.weight_issued_ct):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{name}: {accounted}ct accounted for (set {d(ret.weight_set_ct)}, "
                f"returned {d(ret.weight_returned_ct)}, broken {d(ret.weight_broken_ct)}) "
                f"but only {d(line.weight_issued_ct)}ct was issued.",
            )
        counted = ret.quantity_set + ret.quantity_returned + ret.quantity_broken
        if counted > line.quantity_issued:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{name}: {counted} stones accounted for but only "
                f"{line.quantity_issued} were issued on that line.",
            )
        line.quantity_set = ret.quantity_set
        line.weight_set_ct = ret.weight_set_ct
        line.quantity_returned = ret.quantity_returned
        line.weight_returned_ct = ret.weight_returned_ct
        line.quantity_broken = ret.quantity_broken
        line.weight_broken_ct = ret.weight_broken_ct
        # Snapshotted now, while the charge is being raised. The stone master's
        # rates are editable, and re-reading one later would silently restate
        # what a setter was billed months ago.
        if line.stone is not None:
            line.owed_rate_per_ct = d(
                line.stone.selling_rate_per_ct
                if line.stone.selling_rate_per_ct is not None
                else line.stone.default_rate_per_ct
            )
        # Stones handed back unset go home to the parcel they came out of.
        # Only the returned ones: broken and owed carats are gone from stock
        # whoever ends up paying for them, and restoring those would leave the
        # shop believing it holds stones that are in a bin or with a setter.
        if d(ret.weight_returned_ct) > 0:
            await stone_costing.release(
                db, leg_stone_id=line.id, carats=d(ret.weight_returned_ct)
            )
        returned_ct += d(ret.weight_returned_ct)
        broken_ct += d(ret.weight_broken_ct)

    # The count of stones set, which drives both the per-100 allowance and the
    # per-piece charge. Prefilled from the deal at issue and corrected here,
    # because what pays the setter is what he actually set.
    if payload.piece_count is not None:
        leg.piece_count = payload.piece_count

    settle_stones(leg)
    # What the scale read, kept as the scale read it, and the metal alone.
    leg.gold_received_gross_g = payload.gold_received_g
    leg.gold_received_g = net_metal_g(payload.gold_received_g, leg.stones_set_ct)
    if d(leg.gold_received_g) < 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"The stones stated as set weigh {carats_to_grams(leg.stones_set_ct)}g, which is "
            f"more than the {d(payload.gold_received_g)}g the piece weighs. Check the gross "
            "weight and the carats set — one of them is wrong.",
        )
    # Written before `settle_wastage` runs, because the whole settlement is
    # computed against it: the allowance on a maker's leg is denominated in the
    # karat he returned, and the shortfall is only meaningful once both ends are
    # in fine grams. Setting it afterwards would settle the leg at the issued
    # purity and then quietly disagree with the row it saved.
    leg.gold_received_purity = payload.gold_received_purity
    leg.gold_received_tunch_pct = payload.gold_received_tunch_pct
    settle_wastage(leg)
    leg.labour_amount = compute_labour(leg)
    leg.received_at = datetime.now(timezone.utc)
    if payload.notes:
        leg.notes = (leg.notes + "\n" if leg.notes else "") + payload.notes

    # The ledger credits Gold in Hand unconditionally below, so stock has to
    # move too or the two go out of step. Cancel refuses in this situation for
    # the same reason; silently skipping here would leave the books saying the
    # metal is back while the shelf says it never returned.
    # The metal alone, never the gross. The gross carries the stones set into
    # the piece, and crediting that to gold stock would grow the safe by a
    # fifth of every carat set — on a piece carrying 30ct, six grams of gold
    # the shop does not have.
    net_g = d(leg.gold_received_g)
    if net_g > 0 and leg.gold_source_inventory_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This leg has no recorded gold source, so the returned metal cannot be "
            "put back into stock. Restore the inventory item before receiving.",
        )
    if returned_ct > 0 and leg.stone_source_inventory_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This leg has no recorded stone source, so returned stones cannot be "
            "put back into stock. Restore the inventory item before receiving.",
        )

    if net_g > 0 and leg.gold_source_inventory_id is not None:
        await post_movement(
            db,
            item=await _get_inventory(db, leg.gold_source_inventory_id),
            type=MovementType.manufacturing_in,
            weight_g_delta=net_g,
            reference_type="job_leg",
            reference_id=leg.id,
            notes=f"{design.design_no} received from {leg.worker.name if leg.worker else 'worker'}",
            user_id=current.id,
        )
    # Stones handed back unused belong on the shelf again. Leaving them off
    # walks stone inventory down by the unused carats on every single leg.
    if returned_ct > 0 and leg.stone_source_inventory_id is not None:
        await post_movement(
            db,
            item=await _get_inventory(db, leg.stone_source_inventory_id),
            type=MovementType.manufacturing_in,
            weight_ct_delta=returned_ct,
            reference_type="job_leg",
            reference_id=leg.id,
            notes=f"{design.design_no} stones returned unused",
            user_id=current.id,
        )
    # Chipped stones are stock, not a loss — still the shop's and still worth
    # something. They go to their own row rather than back among the whole
    # stones, which cannot be issued for the piece they were bought for.
    if broken_ct > 0:
        await post_movement(
            db,
            item=await _broken_stone_item(db, leg, user=current),
            type=MovementType.manufacturing_in,
            weight_ct_delta=broken_ct,
            reference_type="job_leg",
            reference_id=leg.id,
            notes=(
                f"{design.design_no} stones broken in setting by "
                f"{leg.worker.name if leg.worker else 'the shop'}"
            ),
            user_id=current.id,
        )

    await post_leg_receive(db, leg, design=design, worker=leg.worker, rate=rate, user_id=current.id)

    leg.status = LegStatus.received
    # The piece is back in the shop's hands. "Currently at department X" means
    # out with X, so it is cleared until the next leg is issued.
    design.current_department_id = None

    await log_action(
        db, user=current,
        action="design.leg_receive",
        resource_type="job_leg", resource_id=leg.id,
        details={
            "design_no": design.design_no,
            "gold_issued_g": str(d(leg.gold_issued_g)),
            "gold_received_g": str(d(leg.gold_received_g)),
            "wastage_actual_g": str(d(leg.wastage_actual_g)),
            "wastage_allowed_g": str(d(leg.wastage_allowed_g)),
            "wastage_excess_g": str(d(leg.wastage_excess_g)),
            "labour_amount": str(d(leg.labour_amount)),
        },
    )
    await db.commit()
    await db.refresh(leg)
    return _leg_read(leg)


@router.post(
    "/legs/{leg_id}/cancel",
    response_model=JobLegRead,
    # Cancelling reverses posted entries and moves material back — irreversible
    # from the UI, so the caller re-authenticates.
    dependencies=[write, Depends(require_password_confirm)],
)
async def cancel_leg(
    leg_id: int, payload: LegCancel, db: DbSession, current: CurrentUser
) -> JobLegRead:
    """
    Abandon a leg and settle what is physically left.

    The caller declares what came back; that returns to stock. Everything else
    stays outstanding against the worker in the ledger rather than being
    forgiven, which is the same rule the manufacturing cancel follows.
    """
    leg = await _get_leg(db, leg_id, lock=True)
    if leg.status is not LegStatus.issued:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Leg #{leg.id} is already {leg.status.value}."
        )
    design = await _get_design(db, leg.design_id)
    # Valued in the metal the leg is actually working, not always gold.
    rate = await current_gold_rate(db, leg.metal or Metal.gold)

    gold_outstanding = d(leg.gold_issued_g)
    stones_outstanding = d(leg.stones_issued_ct)
    gold_recovered = d(payload.gold_recovered_g)
    stones_recovered = d(payload.stones_recovered_ct)

    if gold_recovered > gold_outstanding:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Cannot recover {gold_recovered}g — only {gold_outstanding}g is out on this leg.",
        )
    if stones_recovered > stones_outstanding:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Cannot recover {stones_recovered}ct — only {stones_outstanding}ct is out on this leg.",
        )

    if gold_recovered > 0:
        if leg.gold_source_inventory_id is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This leg has no recorded gold source, so recovered gold cannot be returned.",
            )
        await post_movement(
            db,
            item=await _get_inventory(db, leg.gold_source_inventory_id),
            type=MovementType.manufacturing_in,
            weight_g_delta=gold_recovered,
            reference_type="job_leg",
            reference_id=leg.id,
            notes=f"{design.design_no} gold recovered on cancellation",
            user_id=current.id,
        )
    if stones_recovered > 0:
        if leg.stone_source_inventory_id is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This leg has no recorded stone source, so recovered stones cannot be returned.",
            )
        await post_movement(
            db,
            item=await _get_inventory(db, leg.stone_source_inventory_id),
            type=MovementType.manufacturing_in,
            weight_ct_delta=stones_recovered,
            reference_type="job_leg",
            reference_id=leg.id,
            notes=f"{design.design_no} stones recovered on cancellation",
            user_id=current.id,
        )

    await post_leg_cancel(
        db,
        leg,
        design=design,
        worker=leg.worker,
        gold_recovered_g=gold_recovered,
        rate=rate,
        user_id=current.id,
    )

    leg.status = LegStatus.cancelled
    # Record what actually came back, so the carats still with the worker are
    # derivable as issued - returned. Leaving these at zero would make a
    # cancelled leg look like the stones were never issued, which is the same
    # quiet forgiveness the gold claim exists to prevent.
    #
    # Nothing was set: the piece was abandoned, so no stone reached it. The
    # remainder is outstanding against the worker and is recorded on the row
    # rather than posted. A cancelled leg's stones do not reach 1170 the way a
    # received leg's shortfall does — the receive path knows the carats are
    # *gone*, while a cancellation only knows they have not come back yet, and
    # billing a worker for stones still sitting on his bench is a different
    # decision from billing him for stones he lost.
    leg.stones_returned_ct = stones_recovered
    leg.stones_set_ct = Decimal("0")
    leg.stones_broken_ct = Decimal("0")
    leg.stones_owed_ct = Decimal("0")
    leg.stones_used_ct = Decimal("0")
    leg.notes = (leg.notes + "\n" if leg.notes else "") + f"Cancelled: {payload.reason}"
    design.current_department_id = None

    stones_outstanding_after = stones_outstanding - stones_recovered
    await log_action(
        db, user=current,
        action="design.leg_cancel",
        resource_type="job_leg", resource_id=leg.id,
        details={
            "design_no": design.design_no,
            "reason": payload.reason,
            "gold_recovered_g": str(gold_recovered),
            "gold_outstanding_g": str(gold_outstanding - gold_recovered),
            "stones_recovered_ct": str(stones_recovered),
            # Not written back to stock and not in the piece: still with the worker.
            "stones_outstanding_ct": str(stones_outstanding_after),
        },
    )
    await db.commit()
    await db.refresh(leg)
    return _leg_read(leg)


@router.get("/{design_id}/trace", response_model=DesignTrace, dependencies=[read])
async def trace_design(design_id: int, db: DbSession) -> DesignTrace:
    """
    Where the piece has been, in order, with what went out and what came back.

    This is the view the shop floor lives in — "where is TK-00007 and who has
    my gold" — so it is assembled here rather than left to the client to stitch
    together from legs and stone lines.

    Cancelled legs appear as hops because they are part of the piece's history,
    but they are left out of the totals: their material was reversed and
    counting it would overstate what the piece has consumed.
    """
    design = await _get_design(db, design_id)

    hops: list[TraceHop] = []
    totals = {
        "gold_issued_g": Decimal("0"),
        "gold_received_g": Decimal("0"),
        "wastage_allowed_g": Decimal("0"),
        "wastage_actual_g": Decimal("0"),
        "wastage_excess_g": Decimal("0"),
        "wastage_allowed_fine_g": Decimal("0"),
        "wastage_actual_fine_g": Decimal("0"),
        "wastage_excess_fine_g": Decimal("0"),
        "stones_broken_ct": Decimal("0"),
        "stones_owed_ct": Decimal("0"),
        "stones_issued_ct": Decimal("0"),
        "stones_used_ct": Decimal("0"),
        "stones_returned_ct": Decimal("0"),
        "labour_amount": Decimal("0"),
    }
    open_hops = 0
    # Counted, not summed with the weights: pieces are what the per-piece
    # charges and the per-100 allowances above were derived from.
    pieces = 0

    for leg in design.legs:
        end = leg.received_at or datetime.now(timezone.utc)
        hops.append(
            TraceHop(
                leg_id=leg.id,
                sequence=leg.sequence,
                department=leg.department.name if leg.department else "—",
                worker=leg.worker.name if leg.worker else None,
                status=leg.status,
                issued_at=leg.issued_at,
                received_at=leg.received_at,
                days_held=(end - leg.issued_at).days if leg.issued_at else None,
                gold_in_g=d(leg.gold_issued_g),
                gold_purity=leg.gold_issued_purity,
                gold_out_g=d(leg.gold_received_g),
                piece_count=leg.piece_count,
                wastage_basis=leg.wastage_basis,
                wastage_per_100_pcs_g=(
                    d(leg.wastage_per_100_pcs_g)
                    if leg.wastage_per_100_pcs_g is not None
                    else None
                ),
                wastage_allowed_pct=(
                    d(leg.wastage_allowed_pct) if leg.wastage_allowed_pct is not None else None
                ),
                wastage_allowed_g=d(leg.wastage_allowed_g),
                wastage_actual_g=d(leg.wastage_actual_g),
                wastage_excess_g=d(leg.wastage_excess_g),
                stones_issued_ct=d(leg.stones_issued_ct),
                stones_used_ct=d(leg.stones_used_ct),
                stones_returned_ct=d(leg.stones_returned_ct),
                labour_basis=leg.labour_basis,
                labour_rate=d(leg.labour_rate),
                labour_amount=d(leg.labour_amount),
                notes=leg.notes,
                stones=[
                    TraceStone(
                        stone_name=s.stone.name if s.stone else None,
                        quantity_issued=s.quantity_issued,
                        weight_issued_ct=d(s.weight_issued_ct),
                        quantity_returned=s.quantity_returned,
                        weight_returned_ct=d(s.weight_returned_ct),
                        weight_broken_ct=d(s.weight_broken_ct),
                        weight_owed_ct=d(s.weight_owed_ct),
                        weight_used_ct=d(s.weight_used_ct),
                    )
                    for s in leg.stones
                ],
            )
        )
        if leg.status is LegStatus.cancelled:
            continue
        if leg.status is LegStatus.issued:
            open_hops += 1
        pieces += leg.piece_count
        totals["gold_issued_g"] += d(leg.gold_issued_g)
        totals["gold_received_g"] += d(leg.gold_received_g)
        totals["wastage_allowed_g"] += d(leg.wastage_allowed_g)
        totals["wastage_actual_g"] += d(leg.wastage_actual_g)
        totals["wastage_excess_g"] += d(leg.wastage_excess_g)
        # And the same three in fine grams, which is the only one of the two
        # that can honestly be added up. A piece goes to a maker at 24k and to
        # a setter at 21k, so the raw column sums grams of two different assets
        # — and "what do the workers on this piece still owe me" is exactly the
        # question a total is asked to answer. Legs settled before the fine
        # columns existed contribute nothing rather than a wrong number.
        totals["wastage_allowed_fine_g"] += d(leg.wastage_allowed_fine_g)
        totals["wastage_actual_fine_g"] += d(leg.wastage_actual_fine_g)
        totals["wastage_excess_fine_g"] += d(leg.wastage_excess_fine_g)
        totals["stones_broken_ct"] += d(leg.stones_broken_ct)
        totals["stones_owed_ct"] += d(leg.stones_owed_ct)
        totals["stones_issued_ct"] += d(leg.stones_issued_ct)
        totals["stones_used_ct"] += d(leg.stones_used_ct)
        totals["stones_returned_ct"] += d(leg.stones_returned_ct)
        totals["labour_amount"] += d(leg.labour_amount)

    started = next((l.issued_at for l in design.legs if l.issued_at), None)
    completed = (
        design.legs[-1].received_at
        if design.legs and open_hops == 0 and design.legs[-1].received_at
        else None
    )
    return DesignTrace(
        design_id=design.id,
        design_no=design.design_no,
        tag_no=design.tag_no,
        item=design.item.name if design.item else None,
        customer=design.customer.name if design.customer else None,
        status=design.status,
        current_department=(
            design.current_department.name if design.current_department else None
        ),
        started_at=started,
        completed_at=completed,
        days_in_production=(
            ((completed or datetime.now(timezone.utc)) - started).days if started else None
        ),
        hops=hops,
        totals=TraceTotals(hops=len(hops), open_hops=open_hops, pieces=pieces, **totals),
    )
