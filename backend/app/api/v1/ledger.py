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

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.core import lock_keys
from app.models.account import Account, AccountType, SystemAccount
from app.models.bank import BankAccount
from app.models.currency import Currency
from app.models.customer import Customer
from app.models.gold_rate import GoldRate
from app.models.journal import Commodity, JournalEntry, JournalLine, PartyType
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
    PositionReport,
    StatementReport,
    StatementRow,
    TrialBalanceReport,
    TrialBalanceRow,
)
from app.services import ledger
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
    receivable = await ledger.balance_pkr(db, account_code=SystemAccount.CUSTOMERS.value)
    suppliers = await ledger.balance_pkr(db, account_code=SystemAccount.SUPPLIERS.value)
    workers = await ledger.balance_pkr(db, account_code=SystemAccount.WORKERS_PAYABLE.value)

    return PositionReport(
        as_of=datetime.now(timezone.utc).date(),
        cash_in_hand=cash,
        gold_in_hand_g=gold,
        gold_with_workers_g=with_workers,
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
