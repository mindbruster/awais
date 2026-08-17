"""
The cash book: money in and out that no other document explains, and the
report that reads a day's whole money movement off the ledger.

Two endpoints groups here and they answer different questions. `/cash/entries`
is where rent, wages, the courier and the owner's float get recorded — the
things that were previously invisible because no invoice or payment produced
them. `/cash/flow` is the day's money in total, and it deliberately does *not*
read those entries: it reads the journal, so a customer settling a bill, a
supplier being paid and the electricity bill all appear side by side. A cash
report that only knew about manual entries would answer a question nobody asks.
"""
import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, require_perm
from app.core import clock
from app.models.account import Account, SystemAccount
from app.models.bank import BankAccount
from app.models.branch import Branch
from app.models.cash import CashCategory, CashDirection, CashEntry, CashMethod
from app.models.journal import JournalEntry, JournalLine
from app.schemas.cash import (
    CashCategoryCreate,
    CashCategoryRead,
    CashCategoryUpdate,
    CashEntryCreate,
    CashEntryRead,
    CashFlowHead,
    CashFlowLine,
    CashFlowReport,
)
from app.services import cash as cash_service
from app.services.audit import log_action
from app.services.ledger import d

router = APIRouter()
read = Depends(require_perm("cash:read"))
write = Depends(require_perm("cash:write"))
# The whole day's money — what came in, what went out, and the closing
# position. That is owner information, so it is a permission of its own rather
# than riding on the one that lets the counter record a taxi fare.

_ZERO = d(0)


def _csv_response(
    filename: str, header: Sequence[str], rows: Iterable[Sequence[object]]
):
    """Stream rows as CSV, with the byte-order mark Excel needs on Windows."""

    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        yield "\ufeff"
        writer.writerow(header)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        for row in rows:
            writer.writerow(["" if v is None else str(v) for v in row])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

# The two heads money physically sits in. A drawer is counted and a bank
# account is agreed against a statement, so they are reported apart even though
# both are "money".
_SIDES = {
    SystemAccount.CASH_IN_HAND.value: "cash",
    SystemAccount.BANK.value: "bank",
}


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
@router.get("/categories", response_model=list[CashCategoryRead], dependencies=[read])
async def list_categories(
    db: DbSession,
    direction: CashDirection | None = Query(default=None),
    is_active: bool | None = Query(default=None),
) -> list[CashCategory]:
    stmt = select(CashCategory).order_by(CashCategory.name)
    if direction is not None:
        # A category with no direction is usable either way, so it belongs in
        # both lists rather than neither.
        stmt = stmt.where(
            (CashCategory.direction == direction) | (CashCategory.direction.is_(None))
        )
    if is_active is not None:
        stmt = stmt.where(CashCategory.is_active == is_active)
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "/categories",
    response_model=CashCategoryRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[write],
)
async def create_category(
    payload: CashCategoryCreate, db: DbSession, current: CurrentUser
) -> CashCategory:
    await _check_account_code(db, payload.account_code)
    row = CashCategory(**payload.model_dump())
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A cash category named '{payload.name}' already exists."
        ) from exc
    await db.refresh(row)
    return row


@router.patch("/categories/{category_id}", response_model=CashCategoryRead, dependencies=[write])
async def update_category(
    category_id: int, payload: CashCategoryUpdate, db: DbSession
) -> CashCategory:
    row = await db.get(CashCategory, category_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cash category not found")
    data = payload.model_dump(exclude_unset=True)
    if "account_code" in data:
        await _check_account_code(db, data["account_code"])
    for k, v in data.items():
        setattr(row, k, v)
    await db.commit()
    await db.refresh(row)
    return row


async def _check_account_code(db: DbSession, code: str | None) -> None:
    """
    Refuse a category pointing at a head that cannot be posted to.

    Caught here rather than at the first entry, because a category is set up
    once and used every day: a bad code discovered on the hundredth expense is
    ninety-nine entries filed under a fallback nobody noticed.
    """
    if not code:
        return
    account = (
        await db.execute(select(Account).where(Account.code == code))
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"No account with code '{code}' exists in the chart of accounts.",
        )
    if not account.is_postable:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{account.name}' is a heading and cannot be posted to directly.",
        )


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------
def _entry_read(row: CashEntry, *, journal_no: str | None = None) -> CashEntryRead:
    bank = row.bank_account
    return CashEntryRead(
        id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        entry_no=row.entry_no,
        direction=row.direction,
        method=row.method,
        category_id=row.category_id,
        category_name=row.category.name if row.category else None,
        occurred_on=row.occurred_on,
        amount=d(row.amount),
        currency=row.currency,
        fx_rate_to_pkr=d(row.fx_rate_to_pkr),
        amount_pkr=(d(row.amount) * d(row.fx_rate_to_pkr)).quantize(d("0.01")),
        bank_account_id=row.bank_account_id,
        bank_account_label=(
            f"{bank.bank.name} · {bank.account_no}" if bank and bank.bank else None
        ),
        counterparty=row.counterparty,
        reference=row.reference,
        branch_id=row.branch_id,
        journal_entry_id=row.journal_entry_id,
        entry_no_journal=journal_no,
        notes=row.notes,
    )


@router.get("/entries", response_model=list[CashEntryRead], dependencies=[read])
async def list_entries(
    db: DbSession,
    direction: CashDirection | None = Query(default=None),
    method: CashMethod | None = Query(default=None),
    category_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[CashEntryRead]:
    stmt = (
        select(CashEntry)
        .order_by(CashEntry.occurred_on.desc(), CashEntry.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if direction is not None:
        stmt = stmt.where(CashEntry.direction == direction)
    if method is not None:
        stmt = stmt.where(CashEntry.method == method)
    if category_id is not None:
        stmt = stmt.where(CashEntry.category_id == category_id)
    if date_from is not None:
        stmt = stmt.where(CashEntry.occurred_on >= date_from)
    if date_to is not None:
        stmt = stmt.where(CashEntry.occurred_on <= date_to)
    rows = list((await db.execute(stmt)).scalars().all())
    return [_entry_read(r) for r in rows]


@router.post(
    "/entries",
    response_model=CashEntryRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[write],
)
async def create_entry(
    payload: CashEntryCreate, db: DbSession, current: CurrentUser
) -> CashEntryRead:
    """
    Record money in or out, and post it.

    The entry and its journal lines are written in one transaction: an expense
    on the books with no posting behind it would make the cash balance
    disagree with the cash book, and there would be no way to tell which was
    right.
    """
    cash_service.validate_method(payload.method, payload.bank_account_id)
    cash_service.validate_currency(payload.currency, payload.fx_rate_to_pkr)

    category = None
    if payload.category_id is not None:
        category = await db.get(CashCategory, payload.category_id)
        if category is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Cash category not found")
        if category.direction is not None and category.direction is not payload.direction:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"'{category.name}' is a {category.direction.value} heading, so it cannot be "
                f"used on money {payload.direction.value}.",
            )
    bank_account = None
    if payload.bank_account_id is not None:
        bank_account = await db.get(BankAccount, payload.bank_account_id)
        if bank_account is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Bank account not found")
    if payload.branch_id is not None and await db.get(Branch, payload.branch_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")

    entry = CashEntry(
        entry_no=await cash_service.next_entry_no(db),
        direction=payload.direction,
        method=payload.method,
        category=category,
        # Defaulted here rather than in the schema so the day is the shop's
        # today, not the server's interpretation of a missing field.
        occurred_on=payload.occurred_on or clock.today(),
        amount=payload.amount,
        currency=payload.currency,
        fx_rate_to_pkr=payload.fx_rate_to_pkr,
        bank_account=bank_account,
        counterparty=payload.counterparty,
        reference=payload.reference,
        branch_id=payload.branch_id,
        notes=payload.notes,
        created_by_user_id=current.id,
    )
    db.add(entry)
    await db.flush()

    journal = await cash_service.post_cash_entry(db, entry, user_id=current.id)
    entry.journal_entry_id = journal.id

    await log_action(
        db, user=current,
        action="cash.entry",
        resource_type="cash_entry", resource_id=entry.id,
        details={
            "entry_no": entry.entry_no,
            "direction": entry.direction.value,
            "method": entry.method.value,
            "amount": str(d(entry.amount)),
            "currency": entry.currency.value,
            "category": category.name if category else None,
            "counterparty": entry.counterparty,
        },
    )
    await db.commit()
    await db.refresh(entry)
    return _entry_read(entry, journal_no=journal.entry_no)


# ---------------------------------------------------------------------------
# Cash flow
# ---------------------------------------------------------------------------
@router.get(
    "/flow", response_model=CashFlowReport, dependencies=[Depends(require_perm("cash:flow"))]
)
async def cash_flow(
    db: DbSession,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    # Every other report here exports. The shop reconciles the cash book
    # against a drawer count and a bank statement in Excel, and a cash report
    # it cannot export is a cash report it will not use.
    format: Literal["json", "csv"] = Query(default="json"),
):
    """
    Every rupee that moved through the drawer and the bank, and what moved it.

    Read off the journal, not off the cash entries. A day's money is bills
    settled, suppliers paid, wages, rent and the till float all at once, and
    each of those is produced by a different document — so the only place they
    all meet is the ledger. Reading the cash-entry table instead would show the
    rent and miss every customer who paid.

    Defaults to today, because "what happened today" is the question this is
    opened for.

    Opening and closing balances are the running position of 1110 and 1120 up
    to the day before and the last day of the window. They come from the same
    lines as everything else, so the report closes on itself: opening plus the
    net of the period is the closing figure, and if it ever is not, the ledger
    is telling you something the summary cannot hide.
    """
    today = clock.today()
    start = date_from or today
    end = date_to or max(start, today if date_from is None else start)
    if end < start:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The end of the range falls before its start."
        )

    async def balance_at(code: str, upto: date):
        stmt = (
            select(func.coalesce(func.sum(JournalLine.value_pkr), 0))
            .join(Account, Account.id == JournalLine.account_id)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(Account.code == code, JournalEntry.entry_date <= upto)
        )
        return d((await db.execute(stmt)).scalar_one())

    day_before = date.fromordinal(start.toordinal() - 1)
    opening_cash = await balance_at(SystemAccount.CASH_IN_HAND.value, day_before)
    opening_bank = await balance_at(SystemAccount.BANK.value, day_before)
    closing_cash = await balance_at(SystemAccount.CASH_IN_HAND.value, end)
    closing_bank = await balance_at(SystemAccount.BANK.value, end)

    # Every entry that touched cash or bank in the window, then every *other*
    # line on those entries — which is what says where the money went. A line
    # against 1110 alone says a thousand rupees left the drawer; the line
    # beside it says it was rent.
    touched = (
        select(JournalLine.entry_id)
        .join(Account, Account.id == JournalLine.account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            Account.code.in_(list(_SIDES)),
            JournalEntry.entry_date >= start,
            JournalEntry.entry_date <= end,
        )
    ).subquery()

    rows = (
        await db.execute(
            select(
                JournalEntry.entry_date,
                JournalEntry.entry_no,
                JournalEntry.memo,
                JournalEntry.source_type,
                JournalEntry.source_id,
                Account.code,
                Account.name,
                JournalLine.value_pkr,
                JournalLine.memo,
            )
            .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
            .join(Account, Account.id == JournalLine.account_id)
            .where(JournalEntry.id.in_(select(touched.c.entry_id)))
            .order_by(JournalEntry.entry_date, JournalEntry.id, JournalLine.id)
        )
    ).all()

    lines: list[CashFlowLine] = []
    heads: dict[str, CashFlowHead] = {}
    money_in = money_out = _ZERO

    for (
        entry_date,
        entry_no,
        entry_memo,
        source_type,
        source_id,
        code,
        name,
        value,
        line_memo,
    ) in rows:
        amount = d(value)
        if code in _SIDES:
            # The cash side is the movement itself, and its sign is the
            # direction: a debit to cash is money arriving.
            if amount > 0:
                money_in += amount
            else:
                money_out += -amount
            lines.append(
                CashFlowLine(
                    entry_date=entry_date,
                    entry_no=entry_no,
                    account_code=code,
                    account_name=name,
                    side=_SIDES[code],
                    memo=line_memo or entry_memo,
                    amount=amount,
                    source_type=source_type,
                    source_id=source_id,
                )
            )
            continue
        # The other side: what the money was for. Grouped so a day reads as
        # "rent 40,000, wages 25,000, sales 310,000" rather than as a list.
        head = heads.get(code)
        if head is None:
            head = heads[code] = CashFlowHead(
                account_code=code, account_name=name, money_in=_ZERO, money_out=_ZERO, net=_ZERO
            )
        # Signs are mirrored from the cash side's point of view: a credit to
        # Sales is money coming in, so it reads as `money_in` here.
        if amount < 0:
            head.money_in += -amount
        else:
            head.money_out += amount
        head.net = head.money_in - head.money_out

    if format == "csv":
        # The movements, not the summary. A spreadsheet is opened to tie each
        # line back to a drawer count or a statement row, and a file of totals
        # cannot be reconciled against anything.
        return _csv_response(
            f"cash_flow_{start}_{end}.csv",
            ["date", "entry", "side", "account", "memo", "amount", "source"],
            [
                [
                    ln.entry_date,
                    ln.entry_no,
                    ln.side,
                    f"{ln.account_code} {ln.account_name}",
                    ln.memo,
                    ln.amount,
                    ln.source_type,
                ]
                for ln in lines
            ],
        )

    return CashFlowReport(
        date_from=start,
        date_to=end,
        opening_cash=opening_cash,
        opening_bank=opening_bank,
        closing_cash=closing_cash,
        closing_bank=closing_bank,
        money_in=money_in,
        money_out=money_out,
        net=money_in - money_out,
        # Heads that moved nothing are dropped. They arise when an entry that
        # touched cash also carried offsetting lines on another account — a
        # customer billed and settled the same day nets to zero on 1210 — and a
        # row of zeroes reads as "nothing happened here" when in fact two
        # things did and cancelled out. The lines below still carry both.
        by_head=sorted(
            (h for h in heads.values() if h.money_in or h.money_out),
            key=lambda h: h.account_code,
        ),
        lines=lines,
    )
