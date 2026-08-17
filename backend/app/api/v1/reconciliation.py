"""
Reconciliation: what the books say against what is actually there.

The whole module exists to serve one screen and one rule. The screen shows what
could be checked and what the books currently claim; the rule is that accepting
a difference **posts a document**, never edits a balance. There is deliberately
no endpoint here that sets a stock figure.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.core import clock
from app.core.config import settings
from app.models.account import SystemAccount
from app.models.inventory import InventoryItem, InventoryType
from app.models.journal import Commodity, JournalEntry
from app.models.metal import Metal
from app.models.stock_count import StockCount, StockCountLine, StockCountStatus
from app.schemas.reconciliation import (
    ReconcileOverview,
    ReconcileScope,
    StockCountLineRead,
    StockCountOpen,
    StockCountRead,
    StockCountUpdate,
)
from app.services import branches, ledger, reconciliation
from app.services.audit import log_action
from app.services.gold_rate import fine_rate_per_g, rate_in_force
from app.services.ledger import d

router = APIRouter()
read = Depends(require_perm("report:stock"))
# Counting is a stock job. *Accepting* the loss is not — see the post endpoint.
write = Depends(require_perm("inventory:write"))
approve = Depends(require_perm("report:profit"))
confirm = Depends(require_password_confirm)

_G = Decimal("0.0001")
_ZERO = Decimal("0")


# --------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------
@router.get("", response_model=ReconcileOverview, dependencies=[read])
async def overview(db: DbSession, current: CurrentUser) -> ReconcileOverview:
    """
    Everything the shop can check its books against, with what they claim now.

    Scopes that cannot yet be counted are listed anyway, with their figures and
    a plain sentence saying why. Hiding them would suggest there is nothing else
    worth checking; a half-working button would be worse than either.
    """
    branch = await branches.resolve_branch(db, requested_id=None, user=current)
    scopes: list[ReconcileScope] = []

    for metal in (Metal.gold, Metal.silver):
        _, commodity, account = reconciliation._METAL[metal]
        book = await ledger.balance(
            db, account_code=account.value, commodity=commodity
        )
        rate_row = await rate_in_force(db, metal=metal, as_of=clock.today())
        rate = fine_rate_per_g(rate_row) if rate_row else None

        last = (
            await db.execute(
                select(func.max(StockCount.posted_at)).where(
                    StockCount.metal == metal,
                    StockCount.status == StockCountStatus.posted,
                )
            )
        ).scalar_one_or_none()
        open_row = (
            await db.execute(
                select(StockCount.id, StockCount.status)
                .where(
                    StockCount.metal == metal,
                    StockCount.branch_id == branch.id,
                    StockCount.status.in_(
                        (StockCountStatus.draft, StockCountStatus.submitted)
                    ),
                )
                .order_by(StockCount.id.desc())
                .limit(1)
            )
        ).first()

        scopes.append(
            ReconcileScope(
                key=metal.value,
                label=f"{metal.value.title()} in hand",
                unit="fine g",
                book_quantity=book,
                book_value=(book * rate).quantize(Decimal("0.01")) if rate else None,
                countable=True,
                note=(
                    None
                    if rate
                    else f"No {metal.value} rate on record — set one before posting a count."
                ),
                last_counted_at=last,
                open_count_id=open_row[0] if open_row else None,
                open_count_status=open_row[1].value if open_row else None,
            )
        )

    stone_ct = d(
        (
            await db.execute(
                select(func.coalesce(func.sum(InventoryItem.weight_ct), 0)).where(
                    InventoryItem.type == InventoryType.raw_stone
                )
            )
        ).scalar_one()
    )
    scopes.append(
        ReconcileScope(
            key="stones",
            label="Stones in hand",
            unit="ct",
            book_quantity=stone_ct.quantize(_G),
            countable=False,
            note=(
                "Not yet countable here. A carat variance has to be valued out of the "
                "FIFO parcels the stones were bought in, not at a single rate — until "
                "that is built, a count would produce a figure that looks authoritative "
                "and is not. Use Stone parcels to see what is on the books."
            ),
        )
    )

    for key, label, account in (
        ("cash", "Cash in hand", SystemAccount.CASH_IN_HAND),
        ("bank", "Bank", SystemAccount.BANK),
    ):
        scopes.append(
            ReconcileScope(
                key=key,
                label=label,
                unit="PKR",
                book_quantity=await ledger.balance_pkr(db, account_code=account.value),
                countable=False,
                note=(
                    "Counted against the drawer at close of day rather than here — see "
                    "the Cash book."
                    if key == "cash"
                    else "Reconciled against a bank statement, which this system does not "
                    "yet import."
                ),
            )
        )

    for metal, account, unit in (
        (Metal.gold, SystemAccount.GOLD_WITH_WORKERS, "fine g"),
        (Metal.silver, SystemAccount.SILVER_WITH_WORKERS, "fine g"),
    ):
        commodity = Commodity.GOLD if metal is Metal.gold else Commodity.SILVER
        held = await ledger.balance(db, account_code=account.value, commodity=commodity)
        if held == 0 and metal is Metal.silver:
            continue
        scopes.append(
            ReconcileScope(
                key=f"{metal.value}_with_workers",
                label=f"{metal.value.title()} with workers",
                unit=unit,
                book_quantity=held,
                countable=False,
                note=(
                    "Settled with each worker on his own account rather than counted — "
                    "the metal is not in the building. See Material with others."
                ),
            )
        )

    return ReconcileOverview(as_of=clock.today(), scopes=scopes)


# --------------------------------------------------------------------------
# The sheet
# --------------------------------------------------------------------------
async def _load(db: DbSession, count_id: int) -> StockCount:
    count = (
        await db.execute(
            select(StockCount)
            .where(StockCount.id == count_id)
            .execution_options(populate_existing=True)
        )
    ).unique().scalar_one_or_none()
    if count is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stock count not found")
    return count


def _post_gate(count: StockCount, viewer_id: int | None) -> tuple[bool, str | None]:
    """
    Can *this* reader post *this* sheet, and if not, why.

    Computed on read so the screen can grey the button with a sentence rather
    than letting somebody finish a count and meet a 403 at the last click. The
    server still enforces it — this is the explanation, not the control.
    """
    if not settings.require_two_person_approval:
        return True, None
    if count.status is StockCountStatus.draft:
        return False, "Submit it for approval first — this shop requires a second person."
    if count.status is not StockCountStatus.submitted:
        return False, None
    asserted_by = count.submitted_by_user_id or count.created_by_user_id
    if asserted_by is not None and asserted_by == viewer_id:
        return False, (
            "You counted this metal, so you cannot also accept the loss. "
            "Ask a colleague to post it."
        )
    return True, None


async def _read(
    db: DbSession, count: StockCount, viewer_id: int | None = None
) -> StockCountRead:
    rate_row = await rate_in_force(db, metal=count.metal, as_of=clock.today())
    rate = fine_rate_per_g(rate_row) if rate_row else None

    lines: list[StockCountLineRead] = []
    book_total = counted_total = var_total = fine_total = _ZERO
    unweighed = 0
    for line in count.lines:
        delta = reconciliation.line_variance(line)
        fine = (
            reconciliation.item_fine(line.item, delta).quantize(_G) if delta is not None else None
        )
        book_total += d(line.book_weight_g)
        if delta is None:
            unweighed += 1
        else:
            counted_total += d(line.counted_weight_g)
            var_total += delta
            fine_total += fine or _ZERO
        lines.append(
            StockCountLineRead(
                id=line.id,
                created_at=line.created_at,
                updated_at=line.updated_at,
                inventory_item_id=line.inventory_item_id,
                label=line.item.label,
                purity=line.item.purity,
                tunch_pct=d(line.item.tunch_pct) if line.item.tunch_pct is not None else None,
                book_weight_g=d(line.book_weight_g),
                counted_weight_g=(
                    d(line.counted_weight_g) if line.counted_weight_g is not None else None
                ),
                variance_g=delta,
                variance_fine_g=fine,
                notes=line.notes,
            )
        )

    can_post, blocked = _post_gate(count, viewer_id)

    entry_no = None
    if count.journal_entry_id:
        entry_no = (
            await db.execute(
                select(JournalEntry.entry_no).where(JournalEntry.id == count.journal_entry_id)
            )
        ).scalar_one_or_none()

    return StockCountRead(
        id=count.id,
        created_at=count.created_at,
        updated_at=count.updated_at,
        count_no=count.count_no,
        branch_id=count.branch_id,
        branch_name=count.branch.name if count.branch else None,
        metal=count.metal,
        status=count.status,
        counted_at=count.counted_at,
        notes=count.notes,
        reason=count.reason,
        lines=lines,
        book_total_g=book_total.quantize(_G),
        counted_total_g=counted_total.quantize(_G),
        variance_g=var_total.quantize(_G),
        variance_fine_g=fine_total.quantize(_G),
        variance_value=(fine_total * rate).quantize(Decimal("0.01")) if rate else None,
        rate_per_fine_g=rate,
        unweighed_lines=unweighed,
        journal_entry_id=count.journal_entry_id,
        journal_entry_no=entry_no,
        posted_at=count.posted_at,
        posted_by_user_id=count.posted_by_user_id,
        submitted_at=count.submitted_at,
        submitted_by_user_id=count.submitted_by_user_id,
        created_by_user_id=count.created_by_user_id,
        requires_second_person=settings.require_two_person_approval,
        can_post=can_post,
        blocked_reason=blocked,
    )


@router.get("/counts", response_model=list[StockCountRead], dependencies=[read])
async def list_counts(
    db: DbSession,
    current: CurrentUser,
    metal: Metal | None = Query(default=None),
    status_eq: StockCountStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, le=200),
) -> list[StockCountRead]:
    stmt = select(StockCount).order_by(StockCount.id.desc()).limit(limit)
    if metal is not None:
        stmt = stmt.where(StockCount.metal == metal)
    if status_eq is not None:
        stmt = stmt.where(StockCount.status == status_eq)
    rows = list((await db.execute(stmt)).unique().scalars().all())
    return [await _read(db, r, current.id) for r in rows]


@router.get("/counts/{count_id}", response_model=StockCountRead, dependencies=[read])
async def get_count(count_id: int, db: DbSession, current: CurrentUser) -> StockCountRead:
    return await _read(db, await _load(db, count_id), current.id)


@router.post(
    "/counts",
    response_model=StockCountRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[write],
)
async def open_count(
    payload: StockCountOpen, db: DbSession, current: CurrentUser
) -> StockCountRead:
    """
    Open a sheet: every melt pot of this metal, with what the books say now.

    The book figures are **snapshotted here** and never read again. A count that
    takes an hour while the counter is still selling would otherwise show a
    variance made partly of real sales, and the shop would go looking for metal
    that legitimately left through the front door.

    One open sheet per metal per branch. Two counters filling in two sheets
    against the same pots would each post a variance measured from the same
    starting figure, and the second would write the first one off twice.
    """
    branch = await branches.resolve_branch(db, requested_id=payload.branch_id, user=current)

    existing = (
        await db.execute(
            select(StockCount.count_no).where(
                StockCount.metal == payload.metal,
                StockCount.branch_id == branch.id,
                StockCount.status == StockCountStatus.draft,
            )
        )
    ).scalars().first()
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{existing} is already open for {payload.metal.value} at {branch.name}. "
            "Finish or cancel it before starting another.",
        )

    pots = await reconciliation.pots_for(db, metal=payload.metal, branch_id=branch.id)
    if not pots:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"There are no {payload.metal.value} pots at {branch.name} to count.",
        )

    count = StockCount(
        count_no=await reconciliation.next_count_no(db),
        branch_id=branch.id,
        metal=payload.metal,
        status=StockCountStatus.draft,
        counted_at=payload.counted_at or datetime.now(timezone.utc),
        notes=payload.notes,
        created_by_user_id=current.id,
    )
    db.add(count)
    await db.flush()
    for pot in pots:
        db.add(
            StockCountLine(
                count_id=count.id,
                inventory_item_id=pot.id,
                book_weight_g=d(pot.weight_g),
            )
        )
    await db.flush()

    await log_action(
        db,
        user=current,
        action="reconciliation.count.open",
        resource_type="stock_count",
        resource_id=count.id,
        details={
            "count_no": count.count_no,
            "metal": count.metal.value,
            "branch": branch.name,
            "pots": len(pots),
            "book_total_g": str(sum((d(p.weight_g) for p in pots), _ZERO)),
        },
    )
    await db.commit()
    return await _read(db, await _load(db, count.id), current.id)


@router.patch("/counts/{count_id}", response_model=StockCountRead, dependencies=[write])
async def update_count(
    count_id: int, payload: StockCountUpdate, db: DbSession, current: CurrentUser
) -> StockCountRead:
    """Record what the scale said. Only ever on a draft."""
    count = await _load(db, count_id)
    if count.status is not StockCountStatus.draft:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{count.count_no} is {count.status.value} and cannot be edited. A submitted "
            "sheet is what the approver is being asked to sign, and a posted one is a "
            "record of what was found.",
        )
    by_id = {line.id: line for line in count.lines}
    for upd in payload.lines:
        line = by_id.get(upd.line_id)
        if line is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Line {upd.line_id} is not on this sheet."
            )
        line.counted_weight_g = upd.counted_weight_g
        if upd.notes is not None:
            line.notes = upd.notes
    if payload.reason is not None:
        count.reason = payload.reason
    if payload.notes is not None:
        count.notes = payload.notes
    await db.commit()
    return await _read(db, await _load(db, count_id), current.id)


@router.post("/counts/{count_id}/submit", response_model=StockCountRead, dependencies=[write])
async def submit_count(count_id: int, db: DbSession, current: CurrentUser) -> StockCountRead:
    """
    Say the counting is finished and hand the sheet on.

    Its own step so whoever approves has a queue to work from. Under
    `REQUIRE_TWO_PERSON_APPROVAL` this is also the moment that fixes *whose*
    figures they are — the poster is checked against the submitter, not against
    whoever happened to open the sheet.
    """
    count = await _load(db, count_id)
    reconciliation.submit_count(count, user_id=current.id)
    await log_action(
        db,
        user=current,
        action="reconciliation.count.submit",
        resource_type="stock_count",
        resource_id=count.id,
        details={"count_no": count.count_no, "metal": count.metal.value},
        reason=count.reason,
    )
    await db.commit()
    return await _read(db, await _load(db, count_id), current.id)


@router.post(
    "/counts/{count_id}/post",
    response_model=StockCountRead,
    dependencies=[approve, confirm],
)
async def post_count(count_id: int, db: DbSession, current: CurrentUser) -> StockCountRead:
    """
    Accept the count: move the stock and book the difference.

    Behind `report:profit` and a password rather than the stock permission that
    opened the sheet. Counting metal is a stock job; **writing a loss into the
    books is not**.

    Where the shop has set `REQUIRE_TWO_PERSON_APPROVAL`, seeing that two people
    were involved is not enough — the sheet must have been submitted, and the
    person posting it must not be the one who submitted it. A 403 says so in
    those words rather than failing vaguely.
    """
    count = await _load(db, count_id)
    entry = await reconciliation.post_count(db, count, user_id=current.id)
    await log_action(
        db,
        user=current,
        action="reconciliation.count.post",
        resource_type="stock_count",
        resource_id=count.id,
        details={
            "count_no": count.count_no,
            "metal": count.metal.value,
            "reason": count.reason,
            "variance_fine_g": str(
                sum((v.fine_g for v in reconciliation.variances(count)), _ZERO)
            ),
            "entry_no": entry.entry_no if entry else None,
        },
    )
    await db.commit()
    return await _read(db, await _load(db, count_id), current.id)


@router.post("/counts/{count_id}/cancel", response_model=StockCountRead, dependencies=[write])
async def cancel_count(count_id: int, db: DbSession, current: CurrentUser) -> StockCountRead:
    """
    Abandon a sheet without posting it.

    The row stays. "We counted and threw the sheet away" is itself something an
    auditor wants to be able to see.
    """
    count = await _load(db, count_id)
    if count.status is not StockCountStatus.draft:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{count.count_no} is already {count.status.value}."
        )
    count.status = StockCountStatus.cancelled
    await log_action(
        db,
        user=current,
        action="reconciliation.count.cancel",
        resource_type="stock_count",
        resource_id=count.id,
        details={"count_no": count.count_no},
    )
    await db.commit()
    return await _read(db, await _load(db, count_id), current.id)
