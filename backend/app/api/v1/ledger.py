"""
The books: chart of accounts, the journal, and the reports read off them.

Nothing here writes a journal row directly — every posting goes through
`app.services.ledger.post_entry`, which is where the balancing invariant lives.
The routes' job is to turn a request into an `EntryDraft` and to read balances
back out in the shapes the counter and the owner actually ask for.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, desc, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.core import clock
from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.core import lock_keys
from app.models.account import Account, AccountType, SystemAccount
from app.models.bank import BankAccount
from app.models.currency import Currency
from app.models.customer import Customer
from app.models.gold_rate import GoldRate
from app.models.journal import Commodity, JournalEntry, JournalLine, PartyType
from app.models.purchase import Supplier
from app.models.vendor import Vendor
from app.schemas.ledger import (
    AccountCreate,
    AccountRead,
    AccountUpdate,
    EntryReverseRequest,
    JournalEntryRead,
    JournalLineRead,
    ManualEntryCreate,
    OpeningBalancePosted,
    OpeningBalanceResult,
    OpeningBalanceSkipped,
    PartyStatementReport,
    PartyStatementRow,
    PositionReport,
    StatementReport,
    StatementRow,
    MetalValuationRead,
    RevaluationPreview,
    RevaluationResult,
    TrialBalanceReport,
    TrialBalanceRow,
)
from app.models.metal import Metal
from app.services import ledger, revaluation
from app.services.audit import log_action
from app.services.gold_rate import rate_in_force

router = APIRouter()
read = Depends(require_perm("ledger:read"))
write = Depends(require_perm("ledger:write"))
post = Depends(require_perm("ledger:post"))
# Removing an account reshapes every historic report that grouped by it, so it
# is held apart from `ledger:write` and granted to admins only — the same line
# drawn around deleting a master.
delete = Depends(require_perm("ledger:delete"))
confirm = Depends(require_password_confirm)

_ZERO = Decimal("0")
_OPENING_SOURCE = "opening_balance"


def _account_read(a: Account) -> AccountRead:
    return AccountRead(
        id=a.id,
        created_at=a.created_at,
        updated_at=a.updated_at,
        code=a.code,
        name=a.name,
        type=a.type,
        parent_id=a.parent_id,
        is_system=a.is_system,
        is_postable=a.is_postable,
        is_active=a.is_active,
        notes=a.notes,
        parent_name=a.parent_name,
    )


def _entry_read(e: JournalEntry) -> JournalEntryRead:
    lines = [
        JournalLineRead(
            id=ln.id,
            account_id=ln.account_id,
            account_code=ln.account.code,
            account_name=ln.account.name,
            commodity=ln.commodity,
            quantity=ledger.d(ln.quantity),
            rate=ledger.d(ln.rate),
            value_pkr=ledger.d(ln.value_pkr),
            native_weight_g=ln.native_weight_g,
            native_purity=ln.native_purity,
            party_type=ln.party_type,
            party_id=ln.party_id,
            memo=ln.memo,
        )
        for ln in e.lines
    ]
    debit = sum((ln.value_pkr for ln in lines if ln.value_pkr > 0), _ZERO)
    credit = sum((-ln.value_pkr for ln in lines if ln.value_pkr < 0), _ZERO)
    return JournalEntryRead(
        id=e.id,
        entry_no=e.entry_no,
        entry_date=e.entry_date,
        memo=e.memo,
        source_type=e.source_type,
        source_id=e.source_id,
        reverses_entry_id=e.reverses_entry_id,
        posted_at=e.posted_at,
        created_by_user_id=e.created_by_user_id,
        total_debit=debit,
        total_credit=credit,
        lines=lines,
    )


async def _load_account(db: DbSession, account_id: int) -> Account:
    """`Account.parent` points at its own table, which SQLAlchemy will not eager
    load by default, so `parent_name` has to be asked for explicitly."""
    return (
        await db.execute(
            select(Account)
            .options(selectinload(Account.parent))
            .where(Account.id == account_id)
            .execution_options(populate_existing=True)
        )
    ).unique().scalar_one()


async def _load_entry(db: DbSession, entry_id: int) -> JournalEntry:
    """Re-read an entry with its lines. Lines are created by entry_id inside the
    posting service, so a freshly posted entry's collection is still empty."""
    entry = (
        await db.execute(
            select(JournalEntry)
            .where(JournalEntry.id == entry_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    return entry


# --------------------------------------------------------------------------
# Chart of accounts
# --------------------------------------------------------------------------
@router.get("/accounts", response_model=list[AccountRead], dependencies=[read])
async def list_accounts(
    db: DbSession,
    type: AccountType | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    q: str | None = Query(default=None, description="Search code or name"),
) -> list[AccountRead]:
    stmt = select(Account).options(selectinload(Account.parent)).order_by(Account.code)
    if type is not None:
        stmt = stmt.where(Account.type == type)
    if is_active is not None:
        stmt = stmt.where(Account.is_active == is_active)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Account.code.ilike(like), Account.name.ilike(like)))
    return [_account_read(a) for a in (await db.execute(stmt)).unique().scalars().all()]


@router.post(
    "/accounts",
    response_model=AccountRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[write],
)
async def create_account(payload: AccountCreate, db: DbSession) -> AccountRead:
    parent = await db.get(Account, payload.parent_id)
    if parent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Parent account not found")

    account = Account(**payload.model_dump(), is_system=False)
    db.add(account)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"An account with code '{payload.code}' already exists.",
        ) from exc
    return _account_read(await _load_account(db, account.id))


@router.patch("/accounts/{account_id}", response_model=AccountRead, dependencies=[write])
async def update_account(account_id: int, payload: AccountUpdate, db: DbSession) -> AccountRead:
    account = await db.get(Account, account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")

    changes = payload.model_dump(exclude_unset=True)
    # The posting service resolves system heads by code, so a renamed code
    # would break automatic posting everywhere at once. The flag itself is
    # never user-settable: it is what makes that protection meaningful.
    if "is_system" in changes and changes["is_system"] != account.is_system:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "is_system is set by the ledger seed and cannot be changed.",
        )
    if account.is_system and changes.get("code", account.code) != account.code:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"'{account.name}' is a system account — its code {account.code} is what "
            "automatic posting looks up. Rename it instead.",
        )
    changes.pop("is_system", None)

    for k, v in changes.items():
        setattr(account, k, v)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account with that code already exists."
        ) from exc
    return _account_read(await _load_account(db, account.id))


@router.delete(
    "/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[delete, confirm],
)
async def delete_account(account_id: int, db: DbSession, current: CurrentUser) -> None:
    account = await db.get(Account, account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    if account.is_system:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"'{account.name}' is a system account and cannot be deleted. "
            "Deactivate it if it is unused.",
        )

    children = (
        await db.execute(
            select(func.count(Account.id)).where(Account.parent_id == account_id)
        )
    ).scalar_one()
    if children:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"'{account.name}' still has {children} child account(s). Remove or "
            "reparent them first.",
        )

    used = (
        await db.execute(
            select(func.count(JournalLine.id)).where(JournalLine.account_id == account_id)
        )
    ).scalar_one()
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"'{account.name}' carries {used} posting(s). The ledger is append-only, "
            "so deactivate it instead of deleting it.",
        )

    await log_action(
        db,
        user=current,
        action="ledger.account.delete",
        resource_type="account",
        resource_id=account_id,
        details={"code": account.code, "name": account.name},
    )
    await db.delete(account)
    await db.commit()


# --------------------------------------------------------------------------
# Journal
# --------------------------------------------------------------------------
@router.get("/entries", response_model=list[JournalEntryRead], dependencies=[read])
async def list_entries(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    source_type: str | None = Query(default=None),
    account_id: int | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[JournalEntryRead]:
    stmt = (
        select(JournalEntry)
        .order_by(desc(JournalEntry.entry_date), desc(JournalEntry.id))
        .limit(limit)
        .offset(offset)
    )
    if date_from is not None:
        stmt = stmt.where(JournalEntry.entry_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(JournalEntry.entry_date <= date_to)
    if source_type:
        stmt = stmt.where(JournalEntry.source_type == source_type)
    if account_id is not None:
        stmt = stmt.where(
            JournalEntry.id.in_(
                select(JournalLine.entry_id).where(JournalLine.account_id == account_id)
            )
        )
    return [_entry_read(e) for e in (await db.execute(stmt)).unique().scalars().all()]


@router.get("/entries/{entry_id}", response_model=JournalEntryRead, dependencies=[read])
async def get_entry(entry_id: int, db: DbSession) -> JournalEntryRead:
    return _entry_read(await _load_entry(db, entry_id))


@router.post(
    "/entries",
    response_model=JournalEntryRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[post, confirm],
)
async def create_manual_entry(
    payload: ManualEntryCreate, db: DbSession, current: CurrentUser
) -> JournalEntryRead:
    """
    A hand-written voucher.

    The postings are handed to the posting service as-is; an entry that does
    not net to zero comes back 400 from there rather than being repaired here,
    because a voucher the user believes is right but isn't is exactly the thing
    they need told about.
    """
    draft = ledger.EntryDraft(
        memo=payload.memo,
        entry_date=payload.entry_date,
        source_type="manual",
        # GOLD arrives as the counter weighed it; the ledger holds fine grams.
        # Converting here rather than trusting the caller is the only guard
        # there is — an entry posted in as-weighed grams still balances, because
        # both sides are valued off the same wrong quantity, so it would sit in
        # the books overstating the shop's metal by the alloy fraction forever.
        postings=[
            ledger.Posting(
                account_code=p.account_code,
                quantity=(
                    ledger.fine_grams(p.quantity, p.native_purity)
                    if p.commodity is Commodity.GOLD
                    else p.quantity
                ),
                commodity=p.commodity,
                rate=p.rate,
                party_type=p.party_type,
                party_id=p.party_id,
                native_weight_g=p.quantity if p.commodity is Commodity.GOLD else None,
                native_purity=p.native_purity if p.commodity is Commodity.GOLD else None,
                memo=p.memo,
            )
            for p in payload.postings
        ],
    )
    entry = await ledger.post_entry(db, draft, user_id=current.id)
    await log_action(
        db,
        user=current,
        action="ledger.entry.post",
        resource_type="journal_entry",
        resource_id=entry.id,
        details={"entry_no": entry.entry_no, "lines": len(draft.postings)},
    )
    await db.commit()
    return _entry_read(await _load_entry(db, entry.id))


@router.post(
    "/entries/{entry_id}/reverse",
    response_model=JournalEntryRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[post, confirm],
)
async def reverse_entry(
    entry_id: int,
    db: DbSession,
    current: CurrentUser,
    payload: EntryReverseRequest | None = None,
) -> JournalEntryRead:
    entry = await _load_entry(db, entry_id)
    memo = (payload.memo if payload else None) or f"Reversal of {entry.entry_no}"
    reversal = await ledger.reverse_entry(db, entry, memo=memo, user_id=current.id)
    await log_action(
        db,
        user=current,
        action="ledger.entry.reverse",
        resource_type="journal_entry",
        resource_id=entry.id,
        details={"entry_no": entry.entry_no, "reversal_no": reversal.entry_no},
    )
    await db.commit()
    return _entry_read(await _load_entry(db, reversal.id))


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
@router.get("/statement", response_model=StatementReport, dependencies=[read])
async def statement(
    db: DbSession,
    account_id: int | None = Query(default=None),
    account_code: str | None = Query(default=None),
    party_type: PartyType | None = Query(default=None),
    party_id: int | None = Query(default=None),
    commodity: Commodity = Query(default=Commodity.PKR),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=1000, le=5000),
    offset: int = Query(default=0, ge=0),
) -> StatementReport:
    """
    A running account, in one commodity, optionally narrowed to one party.

    The opening balance carries in everything strictly before `date_from`, so
    the running balance on the first row continues the account rather than
    restarting it — the difference between a statement and a filtered list.
    """
    if account_id is None and not account_code:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Pass either account_id or account_code."
        )
    stmt = select(Account)
    stmt = stmt.where(Account.id == account_id) if account_id is not None else stmt.where(
        Account.code == account_code
    )
    account = (await db.execute(stmt)).unique().scalar_one_or_none()
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")

    def _scoped(q):
        q = q.where(JournalLine.account_id == account.id, JournalLine.commodity == commodity)
        if party_type is not None:
            q = q.where(JournalLine.party_type == party_type)
        if party_id is not None:
            q = q.where(JournalLine.party_id == party_id)
        return q

    opening = _ZERO
    if date_from is not None:
        opening = ledger.d(
            (
                await db.execute(
                    _scoped(
                        select(func.coalesce(func.sum(JournalLine.quantity), 0)).join(
                            JournalEntry, JournalEntry.id == JournalLine.entry_id
                        )
                    ).where(JournalEntry.entry_date < date_from)
                )
            ).scalar_one()
        )

    def _in_period(q):
        q = _scoped(q)
        if date_from is not None:
            q = q.where(JournalEntry.entry_date >= date_from)
        if date_to is not None:
            q = q.where(JournalEntry.entry_date <= date_to)
        return q

    # Period totals come from an aggregate over the whole period, never from the
    # page of rows below. A control account like Customers or Gold with Workers
    # carries every party's movements, so a normal month runs past any page size
    # — and totals derived from a truncated page are silently wrong rather than
    # visibly incomplete, which is the worst way for a statement to fail.
    totals_q = _in_period(
        select(
            func.coalesce(func.sum(case((JournalLine.quantity > 0, JournalLine.quantity), else_=0)), 0),
            func.coalesce(func.sum(case((JournalLine.quantity < 0, -JournalLine.quantity), else_=0)), 0),
            func.count(JournalLine.id),
        ).join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
    )
    period_debit_total, period_credit_total, total_rows = (await db.execute(totals_q)).one()
    period_debit_total = ledger.d(period_debit_total)
    period_credit_total = ledger.d(period_credit_total)

    line_q = (
        _in_period(
            select(JournalLine, JournalEntry).join(
                JournalEntry, JournalEntry.id == JournalLine.entry_id
            )
        )
        .order_by(JournalEntry.entry_date, JournalEntry.id, JournalLine.id)
        .limit(limit)
        .offset(offset)
    )
    hits = (await db.execute(line_q)).unique().all()

    # The account's balance entering the period, kept aside before the page
    # adjustment below so the closing figure stays a property of the period
    # rather than of whichever page was asked for.
    opening_for_period = opening

    # With an offset, the first row on the page continues from everything before
    # it, not from the opening balance.
    if offset:
        skipped_q = (
            _in_period(
                select(JournalLine.quantity)
                .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            )
            .order_by(JournalEntry.entry_date, JournalEntry.id, JournalLine.id)
            .limit(offset)
        ).subquery()
        opening += ledger.d(
            (await db.execute(select(func.coalesce(func.sum(skipped_q.c.quantity), 0)))).scalar_one()
        )

    # The other side of each entry, fetched in one go — a statement is unusable
    # without "against what", and a query per row is not.
    counter: dict[int, list[str]] = {}
    entry_ids = [e.id for _, e in hits]
    if entry_ids:
        others = (
            await db.execute(
                select(JournalLine.entry_id, Account.name)
                .join(Account, Account.id == JournalLine.account_id)
                .where(
                    JournalLine.entry_id.in_(entry_ids),
                    JournalLine.account_id != account.id,
                )
                .order_by(JournalLine.id)
            )
        ).all()
        for entry_id, name in others:
            names = counter.setdefault(entry_id, [])
            if name not in names:
                names.append(name)

    rows: list[StatementRow] = []
    running = opening
    period_debit = _ZERO
    period_credit = _ZERO
    for line, entry in hits:
        qty = ledger.d(line.quantity)
        debit = qty if qty > 0 else _ZERO
        credit = -qty if qty < 0 else _ZERO
        period_debit += debit
        period_credit += credit
        running += qty
        rows.append(
            StatementRow(
                line_id=line.id,
                entry_id=entry.id,
                entry_no=entry.entry_no,
                entry_date=entry.entry_date,
                memo=line.memo or entry.memo,
                counter_accounts=counter.get(entry.id, []),
                debit=debit,
                credit=credit,
                running_balance=running,
                native_weight_g=line.native_weight_g,
                native_purity=line.native_purity,
            )
        )

    return StatementReport(
        account_id=account.id,
        account_code=account.code,
        account_name=account.name,
        commodity=commodity,
        party_type=party_type,
        party_id=party_id,
        date_from=date_from,
        date_to=date_to,
        opening_balance=opening,
        rows=rows,
        # The account's real period figures, independent of the page above.
        period_debit=period_debit_total,
        period_credit=period_credit_total,
        closing_balance=opening_for_period + period_debit_total - period_credit_total,
        total_rows=total_rows,
        truncated=offset + len(rows) < total_rows,
    )


async def _party_name(db: DbSession, party_type: PartyType, party_id: int) -> str | None:
    """
    Whose account this is. None rather than an error if the row has gone —
    a statement for a deleted party is still a truthful record of what moved.
    """
    model = {
        PartyType.customer: Customer,
        PartyType.supplier: Supplier,
        PartyType.worker: Vendor,
        # Salesmen are held as vendor rows until the route work gives them
        # somewhere better to live.
        PartyType.salesman: Vendor,
    }[party_type]
    row = await db.get(model, party_id)
    return getattr(row, "name", None) if row else None


@router.get("/party-statement", response_model=PartyStatementReport, dependencies=[read])
async def party_statement(
    db: DbSession,
    party_type: PartyType = Query(...),
    party_id: int = Query(...),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=500, le=5000),
    offset: int = Query(default=0, ge=0),
) -> PartyStatementReport:
    """
    A trade party's account in both units at once — fine grams and rupees.

    This is the document a wholesale jeweller actually keeps. His counterparty
    owes him metal *and* money, the two settle on different days by different
    means, and neither figure can be derived from the other: the metal side is
    unpriced on purpose, because the rate is agreed on the day the gold moves
    and not on the day the bill was written.

    Deliberately not scoped to one account. The metal side is every GOLD line
    carrying this party and the cash side is every non-GOLD line carrying it,
    wherever they sit in the chart. That makes the statement agnostic to which
    control account a document chose — and it means a jeweller who both buys
    and sells nets correctly across Customers and Suppliers, which is how the
    bazaar reads the relationship and how it will be argued at settlement.

    The cash side sums `value_pkr`, not `quantity`, so a dollar bill and a
    rupee bill land on the same column instead of being added as though the two
    units were interchangeable. The metal side sums `quantity`, which is always
    fine grams.
    """
    party_where = [
        JournalLine.party_type == party_type,
        JournalLine.party_id == party_id,
    ]
    # Four buckets, because the party can owe four different things and none of
    # them settles the others.
    #
    # This used to be two — gold and "everything else, in rupees" — which was
    # right while gold was the only commodity. Once silver and stones became
    # commodities of their own it stopped being right and started being
    # actively wrong: a worker holding a kilo of silver had its *rupee value*
    # added to his cash balance, so a statement said he owed money when he was
    # holding metal, and a setter's carat debt appeared as rupees. Both read as
    # a debt he could settle by paying, which he cannot.
    #
    # The cash bucket is now everything that is actually money — rupees and
    # foreign currency, summed on `value_pkr` so a dollar bill and a rupee
    # receipt land on one line.
    is_gold = JournalLine.commodity == Commodity.GOLD
    is_silver = JournalLine.commodity == Commodity.SILVER
    is_stone = JournalLine.commodity == Commodity.STONE
    is_money = JournalLine.commodity.notin_(
        (Commodity.GOLD, Commodity.SILVER, Commodity.STONE)
    )

    metal_q = func.coalesce(
        func.sum(case((is_gold, JournalLine.quantity), else_=0)), 0
    )
    silver_q = func.coalesce(
        func.sum(case((is_silver, JournalLine.quantity), else_=0)), 0
    )
    stone_q = func.coalesce(
        func.sum(case((is_stone, JournalLine.quantity), else_=0)), 0
    )
    cash_q = func.coalesce(
        func.sum(case((is_money, JournalLine.value_pkr), else_=0)), 0
    )

    # Opening carries in everything strictly before the window, so the first
    # row continues the account rather than restarting it.
    opening_metal = _ZERO
    opening_cash = _ZERO
    opening_silver = _ZERO
    opening_stone = _ZERO
    if date_from is not None:
        opening_metal, opening_cash, opening_silver, opening_stone = (
            await db.execute(
                select(metal_q, cash_q, silver_q, stone_q)
                .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                .where(*party_where, JournalEntry.entry_date < date_from)
            )
        ).one()
        opening_metal, opening_cash = ledger.d(opening_metal), ledger.d(opening_cash)
        opening_silver, opening_stone = ledger.d(opening_silver), ledger.d(opening_stone)

    def _in_period(q):
        q = q.join(JournalEntry, JournalEntry.id == JournalLine.entry_id).where(*party_where)
        if date_from is not None:
            q = q.where(JournalEntry.entry_date >= date_from)
        if date_to is not None:
            q = q.where(JournalEntry.entry_date <= date_to)
        return q

    # One row per document, not per posting. A single invoice can put several
    # lines against the same party, and a statement that showed each of them
    # would be a journal rather than an account.
    grouped = (
        _in_period(
            select(
                JournalEntry.id,
                JournalEntry.entry_no,
                JournalEntry.entry_date,
                JournalEntry.memo,
                JournalEntry.source_type,
                JournalEntry.source_id,
                metal_q,
                cash_q,
                func.coalesce(
                    func.sum(case((is_gold, JournalLine.native_weight_g), else_=0)), 0
                ),
                # Only reported when the document spoke with one voice. A bill
                # covering three lots at three tunches has no single purity, and
                # printing one of them would misdescribe the other two.
                case(
                    (
                        func.count(func.distinct(JournalLine.native_purity)) == 1,
                        func.max(JournalLine.native_purity),
                    ),
                    else_=None,
                ),
                case(
                    (
                        func.count(func.distinct(JournalLine.native_tunch_pct)) == 1,
                        func.max(JournalLine.native_tunch_pct),
                    ),
                    else_=None,
                ),
                # Appended after the existing columns on purpose: the row
                # tuple is read positionally below, and inserting these in the
                # middle would silently reassign every field after them.
                silver_q,
                stone_q,
            )
        )
        .group_by(
            JournalEntry.id,
            JournalEntry.entry_no,
            JournalEntry.entry_date,
            JournalEntry.memo,
            JournalEntry.source_type,
            JournalEntry.source_id,
        )
        .order_by(JournalEntry.entry_date, JournalEntry.id)
    )

    all_rows = (await db.execute(grouped)).all()
    total_rows = len(all_rows)

    # Period totals span the whole window even when the page does not, so a
    # truncated statement still foots. Computed from the same grouped rows
    # rather than a second query, which keeps the two definitions identical.
    metal_in_total = sum((ledger.d(r[6]) for r in all_rows if r[6] and r[6] > 0), _ZERO)
    metal_out_total = -sum((ledger.d(r[6]) for r in all_rows if r[6] and r[6] < 0), _ZERO)
    cash_debit_total = sum((ledger.d(r[7]) for r in all_rows if r[7] and r[7] > 0), _ZERO)
    cash_credit_total = -sum((ledger.d(r[7]) for r in all_rows if r[7] and r[7] < 0), _ZERO)

    # The running balance has to be carried from the start of the period even
    # when the page begins in the middle of it, or row 501 would open at
    # nothing and every balance below it would be wrong.
    metal_running = opening_metal
    cash_running = opening_cash
    silver_running = opening_silver
    stone_running = opening_stone
    rows: list[PartyStatementRow] = []
    for index, r in enumerate(all_rows):
        metal_delta = ledger.d(r[6])
        cash_delta = ledger.d(r[7])
        silver_delta = ledger.d(r[11])
        stone_delta = ledger.d(r[12])
        metal_running += metal_delta
        cash_running += cash_delta
        silver_running += silver_delta
        stone_running += stone_delta
        if index < offset or len(rows) >= limit:
            continue
        rows.append(
            PartyStatementRow(
                entry_id=r[0],
                entry_no=r[1],
                entry_date=r[2],
                memo=r[3],
                source_type=r[4],
                source_id=r[5],
                metal_in_g=metal_delta if metal_delta > 0 else _ZERO,
                metal_out_g=-metal_delta if metal_delta < 0 else _ZERO,
                metal_balance_g=metal_running,
                native_weight_g=ledger.d(r[8]) or None,
                native_purity=r[9],
                native_tunch_pct=r[10],
                cash_debit=cash_delta if cash_delta > 0 else _ZERO,
                cash_credit=-cash_delta if cash_delta < 0 else _ZERO,
                cash_balance=cash_running,
                silver_delta_g=silver_delta,
                silver_balance_g=silver_running,
                stone_delta_ct=stone_delta,
                stone_balance_ct=stone_running,
            )
        )

    return PartyStatementReport(
        party_type=party_type,
        party_id=party_id,
        party_name=await _party_name(db, party_type, party_id),
        date_from=date_from,
        date_to=date_to,
        opening_metal_g=opening_metal,
        opening_cash=opening_cash,
        opening_silver_g=opening_silver,
        opening_stone_ct=opening_stone,
        rows=rows,
        metal_in_total_g=metal_in_total,
        metal_out_total_g=metal_out_total,
        cash_debit_total=cash_debit_total,
        cash_credit_total=cash_credit_total,
        closing_metal_g=metal_running,
        closing_cash=cash_running,
        closing_silver_g=silver_running,
        closing_stone_ct=stone_running,
        total_rows=total_rows,
        truncated=offset + len(rows) < total_rows,
    )


@router.get("/trial-balance", response_model=TrialBalanceReport, dependencies=[read])
async def trial_balance(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> TrialBalanceReport:
    """
    Debits and credits per account, split by commodity.

    Gold and rupees are listed on separate rows because they don't add up:
    grams only balance against rupees once valued, which is what `value_pkr`
    already carries. `balanced` is the check that matters — the PKR valuation
    of every line in the system must net to nothing.
    """
    debit_q = case((JournalLine.quantity > 0, JournalLine.quantity), else_=0)
    credit_q = case((JournalLine.quantity < 0, -JournalLine.quantity), else_=0)

    stmt = (
        select(
            Account.id,
            Account.code,
            Account.name,
            Account.type,
            JournalLine.commodity,
            func.coalesce(func.sum(debit_q), 0),
            func.coalesce(func.sum(credit_q), 0),
        )
        .join(Account, Account.id == JournalLine.account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .group_by(Account.id, Account.code, Account.name, Account.type, JournalLine.commodity)
        .order_by(Account.code, JournalLine.commodity)
    )
    totals_stmt = select(
        func.coalesce(func.sum(case((JournalLine.value_pkr > 0, JournalLine.value_pkr), else_=0)), 0),
        func.coalesce(
            func.sum(case((JournalLine.value_pkr < 0, -JournalLine.value_pkr), else_=0)), 0
        ),
    ).join(JournalEntry, JournalEntry.id == JournalLine.entry_id)

    if date_from is not None:
        stmt = stmt.where(JournalEntry.entry_date >= date_from)
        totals_stmt = totals_stmt.where(JournalEntry.entry_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(JournalEntry.entry_date <= date_to)
        totals_stmt = totals_stmt.where(JournalEntry.entry_date <= date_to)

    rows = [
        TrialBalanceRow(
            account_id=aid,
            account_code=code,
            account_name=name,
            account_type=atype,
            commodity=comm,
            debit=ledger.d(dr),
            credit=ledger.d(cr),
            balance=ledger.d(dr) - ledger.d(cr),
        )
        for (aid, code, name, atype, comm, dr, cr) in (await db.execute(stmt)).all()
    ]
    total_debit, total_credit = (await db.execute(totals_stmt)).one()
    total_debit, total_credit = ledger.d(total_debit), ledger.d(total_credit)

    return TrialBalanceReport(
        date_from=date_from,
        date_to=date_to,
        rows=rows,
        total_debit_pkr=total_debit,
        total_credit_pkr=total_credit,
        balanced=abs(total_debit - total_credit) <= Decimal("0.01"),
    )


@router.get("/position", response_model=PositionReport, dependencies=[read])
async def position(db: DbSession) -> PositionReport:
    """
    What the shop is worth this morning: cash, metal, and who owes whom.

    The metal figures are grams and the money figures are rupees, so they are
    asked for differently: `balance` for a single commodity's own unit,
    `balance_pkr` for the value of an account whose lines may be in more than
    one currency. Reading the money heads per-commodity would drop the invoice
    side of any bill raised in dollars and settled in rupees.
    """
    cash = await ledger.balance_pkr(db, account_code=SystemAccount.CASH_IN_HAND.value)
    gold = await ledger.balance(
        db, account_code=SystemAccount.GOLD_IN_HAND.value, commodity=Commodity.GOLD
    )
    with_workers = await ledger.balance(
        db, account_code=SystemAccount.GOLD_WITH_WORKERS.value, commodity=Commodity.GOLD
    )
    # Each metal read against its own account *and* its own commodity. Either
    # alone would be enough today, but both together is what makes the figure
    # unable to drift: a line posted to the silver account in the gold
    # commodity — the one mistake a metal-aware posting path can make — falls
    # out of both readings instead of inflating one of them.
    silver = await ledger.balance(
        db, account_code=SystemAccount.SILVER_IN_HAND.value, commodity=Commodity.SILVER
    )
    silver_with_workers = await ledger.balance(
        db, account_code=SystemAccount.SILVER_WITH_WORKERS.value, commodity=Commodity.SILVER
    )
    stones_with_workers = await ledger.balance(
        db, account_code=SystemAccount.STONES_WITH_WORKERS.value, commodity=Commodity.STONE
    )
    receivable = await ledger.balance_pkr(db, account_code=SystemAccount.CUSTOMERS.value)
    suppliers = await ledger.balance_pkr(db, account_code=SystemAccount.SUPPLIERS.value)
    workers = await ledger.balance_pkr(db, account_code=SystemAccount.WORKERS_PAYABLE.value)

    return PositionReport(
        as_of=clock.today(),
        cash_in_hand=cash,
        gold_in_hand_g=gold,
        gold_with_workers_g=with_workers,
        silver_in_hand_g=silver,
        silver_with_workers_g=silver_with_workers,
        stones_with_workers_ct=stones_with_workers,
        customer_receivable=receivable,
        supplier_payable=-suppliers,
        worker_payable=-workers,
    )


# --------------------------------------------------------------------------
# Opening balances
# --------------------------------------------------------------------------
@router.post(
    "/opening-balances",
    response_model=OpeningBalanceResult,
    dependencies=[post, confirm],
)
async def post_opening_balances(db: DbSession, current: CurrentUser) -> OpeningBalanceResult:
    """
    Move the balances declared at go-live into the ledger.

    Until this runs, `customers.opening_balance` and friends are just numbers on
    a master record that no statement can see. Each party gets one entry against
    Opening Balance Equity, so a worker who is both owed cash and holding metal
    reads as a single event rather than two unrelated ones.

    Safe to re-run: a party that already has an opening entry is skipped, which
    matters because the alternative is silently doubling everyone's balance.
    That skip is a read followed by a write, so the whole endpoint is serialised
    on an advisory lock — two clicks landing together would otherwise both find
    nothing posted and both post, which is the exact failure the skip exists to
    prevent, and it would need hand-written reversals to undo.
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=lock_keys.OPENING_BALANCES))
    rate_row = await rate_in_force(db, currency=Currency.PKR, purity=24)
    if rate_row is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No PKR 24k gold rate on record. Set today's gold rate before posting "
            "opening balances — worker metal has to be valued to balance the entry.",
        )
    gold_rate = ledger.d(rate_row.rate_per_g)

    existing = (
        (
            await db.execute(
                select(JournalEntry).where(JournalEntry.source_type == _OPENING_SOURCE)
            )
        )
        .unique()
        .scalars()
        .all()
    )
    # Customer #1 and worker #1 share a source_id, so identity comes off the
    # lines: parties by (party_type, party_id), bank accounts by the source_id
    # of the entry that touched the Bank control account.
    done_parties = {
        (ln.party_type, ln.party_id)
        for e in existing
        for ln in e.lines
        if ln.party_type is not None
    }
    done_banks = {
        e.source_id
        for e in existing
        if any(ln.account.code == SystemAccount.BANK.value for ln in e.lines)
    }

    posted: list[OpeningBalancePosted] = []
    skipped: list[OpeningBalanceSkipped] = []

    async def _post(
        *, party_type: str, party_id: int, party_name: str, memo: str, postings: list
    ) -> None:
        contra = -sum((p.value_pkr() for p in postings), _ZERO)
        draft = ledger.EntryDraft(
            memo=memo,
            source_type=_OPENING_SOURCE,
            source_id=party_id,
            postings=[
                *postings,
                ledger.Posting(
                    account_code=SystemAccount.OPENING_BALANCE_EQUITY.value,
                    quantity=contra,
                    memo=memo,
                ),
            ],
        )
        entry = await ledger.post_entry(db, draft, user_id=current.id)
        posted.append(
            OpeningBalancePosted(
                party_type=party_type,
                party_id=party_id,
                party_name=party_name,
                entry_id=entry.id,
                entry_no=entry.entry_no,
            )
        )

    customers = (
        (await db.execute(select(Customer).order_by(Customer.id))).unique().scalars().all()
    )
    for c in customers:
        amount = ledger.d(c.opening_balance)
        if amount == 0:
            continue
        if (PartyType.customer, c.id) in done_parties:
            skipped.append(
                OpeningBalanceSkipped(
                    party_type="customer",
                    party_id=c.id,
                    party_name=c.name,
                    reason="Opening balance already posted.",
                )
            )
            continue
        await _post(
            party_type="customer",
            party_id=c.id,
            party_name=c.name,
            memo=f"Opening balance — {c.name}",
            postings=[
                ledger.Posting(
                    account_code=SystemAccount.CUSTOMERS.value,
                    quantity=amount,
                    party_type=PartyType.customer,
                    party_id=c.id,
                )
            ],
        )

    vendors = (await db.execute(select(Vendor).order_by(Vendor.id))).unique().scalars().all()
    for v in vendors:
        cash = ledger.d(v.opening_cash_balance)
        raw_gold = ledger.d(v.opening_gold_g)
        if cash == 0 and raw_gold == 0:
            continue
        if (PartyType.worker, v.id) in done_parties:
            skipped.append(
                OpeningBalanceSkipped(
                    party_type="worker",
                    party_id=v.id,
                    party_name=v.name,
                    reason="Opening balance already posted.",
                )
            )
            continue

        postings = []
        if raw_gold != 0:
            postings.append(
                ledger.Posting(
                    account_code=SystemAccount.GOLD_WITH_WORKERS.value,
                    quantity=ledger.fine_grams(raw_gold, 24),
                    commodity=Commodity.GOLD,
                    rate=gold_rate,
                    party_type=PartyType.worker,
                    party_id=v.id,
                    native_weight_g=raw_gold,
                    native_purity=24,
                )
            )
        if cash != 0:
            # Positive means the shop owes him — a credit on Workers Payable.
            postings.append(
                ledger.Posting(
                    account_code=SystemAccount.WORKERS_PAYABLE.value,
                    quantity=-cash,
                    party_type=PartyType.worker,
                    party_id=v.id,
                )
            )
        await _post(
            party_type="worker",
            party_id=v.id,
            party_name=v.name,
            memo=f"Opening balance — {v.name}",
            postings=postings,
        )

    accounts = (
        (await db.execute(select(BankAccount).order_by(BankAccount.id))).unique().scalars().all()
    )
    for ba in accounts:
        amount = ledger.d(ba.opening_balance)
        if amount == 0:
            continue
        label = f"{ba.bank.name} {ba.account_no}" if ba.bank else ba.account_no
        if ba.id in done_banks:
            skipped.append(
                OpeningBalanceSkipped(
                    party_type="bank_account",
                    party_id=ba.id,
                    party_name=label,
                    reason="Opening balance already posted.",
                )
            )
            continue
        if ba.currency is not Currency.PKR:
            # A foreign account needs an FX rate to value, and the shop has no
            # place to declare one yet.
            skipped.append(
                OpeningBalanceSkipped(
                    party_type="bank_account",
                    party_id=ba.id,
                    party_name=label,
                    reason=f"{ba.currency.value} account — post it manually at an agreed rate.",
                )
            )
            continue
        await _post(
            party_type="bank_account",
            party_id=ba.id,
            party_name=label,
            memo=f"Opening balance — {label}",
            postings=[
                ledger.Posting(account_code=SystemAccount.BANK.value, quantity=amount)
            ],
        )

    if posted:
        await log_action(
            db,
            user=current,
            action="ledger.opening_balances.post",
            resource_type="journal_entry",
            details={"entries": len(posted), "gold_rate_per_g": str(gold_rate)},
        )
    await db.commit()
    return OpeningBalanceResult(gold_rate_per_g=gold_rate, posted=posted, skipped=skipped)


# --------------------------------------------------------------------------
# Metal revaluation
# --------------------------------------------------------------------------
@router.get("/revaluation", response_model=RevaluationPreview, dependencies=[read])
async def revaluation_preview(db: DbSession) -> RevaluationPreview:
    """
    What the metal on the books is worth today, and what posting would change.

    Read-only and safe to open as often as you like. The posting is a separate,
    deliberate act — moving a balance sheet to market is a decision somebody
    makes, not something that happens while a page loads.
    """
    rows = await revaluation.value(db)
    return RevaluationPreview(
        as_of=clock.today(),
        metals=[
            MetalValuationRead(
                metal=v.metal,
                fine_grams=v.fine_grams,
                rate_per_fine_g=v.rate_per_fine_g,
                book_value=v.book_value,
                market_value=v.market_value,
                difference=v.difference,
                unpriced=v.unpriced,
            )
            for v in rows
        ],
        total_difference=sum(
            (v.difference for v in rows if v.difference is not None), _ZERO
        ),
    )


@router.post(
    "/revaluation",
    response_model=RevaluationResult,
    # It moves the balance sheet and books profit, and undoing it means a
    # hand-written reversal. The operator re-authenticates.
    dependencies=[post, confirm],
)
async def revaluation_post(db: DbSession, current: CurrentUser) -> RevaluationResult:
    """
    Bring the metal accounts to market and book the difference.

    Only money moves. The gram balances are untouched, because no metal moved —
    altering them would break the one figure that can be checked against the
    safe. What changes is the rupee value sitting beside those grams, which is
    exactly the split `balance` and `balance_pkr` already make.

    Nothing to do is a real answer on a quiet day, and comes back as a success
    with no entry rather than an error.
    """
    entry, rows = await revaluation.post(db, user_id=current.id)
    await log_action(
        db, user=current,
        action="ledger.revalue_metal",
        resource_type="journal_entry",
        resource_id=entry.id if entry else None,
        details={
            v.metal.value: {
                "fine_g": str(v.fine_grams),
                "book": str(v.book_value),
                "market": str(v.market_value) if v.market_value is not None else None,
                "difference": str(v.difference) if v.difference is not None else None,
            }
            for v in rows
        },
    )
    await db.commit()
    return RevaluationResult(
        as_of=clock.today(),
        entry_id=entry.id if entry else None,
        entry_no=entry.entry_no if entry else None,
        total_difference=sum(
            (v.difference for v in rows if v.difference is not None), _ZERO
        ),
        metals=[
            MetalValuationRead(
                metal=v.metal,
                fine_grams=v.fine_grams,
                rate_per_fine_g=v.rate_per_fine_g,
                book_value=v.book_value,
                market_value=v.market_value,
                difference=v.difference,
                unpriced=v.unpriced,
            )
            for v in rows
        ],
    )
