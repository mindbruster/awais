"""
The opening screen.

Three questions, in the order a jeweller actually asks them:

  1. What is true right now — the rate, the cash, the metal, what sold today.
  2. What is the shape of the last few weeks.
  3. What needs doing about it.

The third is the one that earns the screen. A shop does not open the software
to admire a trend line; it opens it to find out which memo is overdue and who
is still holding metal. So the alerts are computed from the same rules the
detail screens use, and each one carries the link to where it gets fixed.

Everything comes back in one response. A dashboard assembled from six requests
renders in six stages, and a half-drawn screen is one somebody acts on before
the number they need has arrived.
"""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, cast, func, select

from app.core import clock
from app.core.config import settings
from app.api.deps import DbSession, require_perm
from app.models.account import SystemAccount
from app.models.approval import Approval, ApprovalItem, ApprovalLineStatus, ApprovalStatus
from app.models.currency import Currency
from app.models.design import JobLeg, LegStatus
from app.models.gold_rate import GoldRate
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import Commodity, JournalEntry, JournalLine
from app.models.order import CustomerOrder, OrderStatus
from app.models.account import Account
from app.schemas.dashboard import (
    DashboardAlert,
    DashboardDay,
    DashboardReport,
    DashboardToday,
)
from app.services import ledger

router = APIRouter()
# Deliberately the sales-report permission, not a new one. This screen shows
# money: what is in the till, what is owed, what sold. A user who may not read
# the sales report may not read it on a dashboard either.
read = Depends(require_perm("report:sales"))

_ZERO = Decimal("0")
# Long enough to see a month's rhythm, short enough that a shop with a year of
# history is not handed 365 bars three pixels wide.
DEFAULT_DAYS = 30
OPEN_MEMOS = (ApprovalStatus.out, ApprovalStatus.partly_returned)
OPEN_ORDERS = (
    OrderStatus.draft,
    OrderStatus.confirmed,
    OrderStatus.in_progress,
    OrderStatus.ready,
)


def _shop_day(column):
    """
    Which shop day a stored UTC timestamp falls on.

    Grouping on the raw UTC date puts everything rung up before 05:00 local on
    the previous day, so the first hours of trading land on yesterday's bar.
    """
    return cast(func.timezone(settings.shop_timezone, column), Date)


def _d(v) -> Decimal:
    return Decimal(str(v)) if v is not None else _ZERO


async def _count(db: DbSession, model, *where) -> int:
    return int((await db.execute(select(func.count(model.id)).where(*where))).scalar_one())


@router.get("", response_model=DashboardReport, dependencies=[read])
async def dashboard(
    db: DbSession,
    days: int = Query(default=DEFAULT_DAYS, ge=7, le=180),
) -> DashboardReport:
    today = clock.today()
    start = today - timedelta(days=days - 1)

    # ---------------------------------------------------------------- today
    # The rate in force, and whether it is actually today's. A stale rate is
    # worse than none: metal gets issued and valued at last week's price, and
    # nothing on the screen says so.
    rate_row = (
        await db.execute(
            select(GoldRate)
            .where(
                GoldRate.currency == Currency.PKR,
                GoldRate.purity == 24,
                GoldRate.rate_date <= today,
            )
            .order_by(GoldRate.rate_date.desc())
            .limit(1)
        )
    ).scalars().first()

    sold_today = (
        await db.execute(
            select(
                func.count(Invoice.id),
                # Dollar bills converted at the rate snapshotted on them, so a
                # day's takings is one number rather than two that cannot be
                # added together.
                func.coalesce(
                    func.sum(Invoice.total * func.coalesce(Invoice.fx_rate_to_pkr, 1)), 0
                ),
            ).where(
                Invoice.status.in_((InvoiceStatus.issued, InvoiceStatus.paid)),
                Invoice.issued_at >= clock.day_start_utc(today),
            )
        )
    ).one()

    now = DashboardToday(
        gold_rate_per_g=_d(rate_row.rate_per_g) if rate_row else None,
        gold_rate_date=rate_row.rate_date if rate_row else None,
        gold_rate_is_stale=bool(rate_row and rate_row.rate_date < today),
        cash_in_hand=await ledger.balance_pkr(
            db, account_code=SystemAccount.CASH_IN_HAND.value
        ),
        gold_in_hand_g=await ledger.balance(
            db, account_code=SystemAccount.GOLD_IN_HAND.value, commodity=Commodity.GOLD
        ),
        gold_with_workers_g=await ledger.balance(
            db, account_code=SystemAccount.GOLD_WITH_WORKERS.value, commodity=Commodity.GOLD
        ),
        customer_receivable=await ledger.balance_pkr(
            db, account_code=SystemAccount.CUSTOMERS.value
        ),
        supplier_payable=-(
            await ledger.balance_pkr(db, account_code=SystemAccount.SUPPLIERS.value)
        ),
        sold_today_count=int(sold_today[0]),
        sold_today_value=_d(sold_today[1]),
    )

    # --------------------------------------------------------------- series
    # Built once and reused in both the SELECT and the GROUP BY. Calling the
    # helper twice emits two separate bind parameters for the timezone name,
    # and Postgres then refuses to match the grouped expression to the selected
    # one — the same expression written twice is not the same expression to it.
    invoice_day = _shop_day(Invoice.issued_at)
    sales_by_day = {
        row[0]: (int(row[1]), _d(row[2]))
        for row in (
            await db.execute(
                select(
                    invoice_day,
                    func.count(Invoice.id),
                    func.coalesce(
                        func.sum(Invoice.total * func.coalesce(Invoice.fx_rate_to_pkr, 1)), 0
                    ),
                )
                .where(
                    Invoice.status.in_((InvoiceStatus.issued, InvoiceStatus.paid)),
                    Invoice.issued_at >= clock.day_start_utc(start),
                )
                .group_by(invoice_day)
            )
        ).all()
    }

    # Metal in and out of the safe, read off account 1130 rather than the stock
    # table: the ledger has already converted every purity to fine grams, so a
    # 22k bar and a 24k one are comparable without doing the arithmetic twice.
    metal_rows = (
        await db.execute(
            select(
                JournalEntry.entry_date,
                func.sum(func.greatest(JournalLine.quantity, 0)),
                func.sum(func.least(JournalLine.quantity, 0)),
            )
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .join(Account, Account.id == JournalLine.account_id)
            .where(
                Account.code == SystemAccount.GOLD_IN_HAND.value,
                JournalLine.commodity == Commodity.GOLD,
                JournalEntry.entry_date >= start,
            )
            .group_by(JournalEntry.entry_date)
        )
    ).all()
    metal_by_day = {row[0]: (_d(row[1]), -_d(row[2])) for row in metal_rows}

    rate_rows = (
        await db.execute(
            select(GoldRate.rate_date, GoldRate.rate_per_g)
            .where(
                GoldRate.currency == Currency.PKR,
                GoldRate.purity == 24,
                GoldRate.rate_date <= today,
            )
            .order_by(GoldRate.rate_date)
        )
    ).all()
    rate_by_day = {row[0]: _d(row[1]) for row in rate_rows}
    # The rate in force on the first day of the window, so the line starts
    # somewhere instead of at nothing.
    carried = next(
        (r for d_, r in reversed(rate_rows) if d_ < start),
        None,
    )

    series: list[DashboardDay] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        count, value = sales_by_day.get(day, (0, _ZERO))
        gold_in, gold_out = metal_by_day.get(day, (_ZERO, _ZERO))
        # Carried forward. A gap in a rate chart reads as a crash, not as a day
        # nobody happened to write the rate down.
        if day in rate_by_day:
            carried = rate_by_day[day]
        series.append(
            DashboardDay(
                day=day,
                sales_count=count,
                sales_value=value,
                gold_in_g=gold_in,
                gold_out_g=gold_out,
                gold_rate_per_g=carried,
            )
        )

    # --------------------------------------------------------------- alerts
    alerts: list[DashboardAlert] = []

    if rate_row is None or rate_row.rate_date < today:
        alerts.append(
            DashboardAlert(
                key="gold_rate",
                label="Today's gold rate is not set",
                detail=(
                    f"The last rate on record is from {rate_row.rate_date}."
                    if rate_row
                    else "No rate has ever been set."
                )
                + " Metal cannot be issued to a worker until there is one.",
                count=1,
                tone="bad",
                to="/gold-rates",
            )
        )

    overdue_memos = await _count(
        db,
        Approval,
        Approval.status.in_(OPEN_MEMOS),
        Approval.due_date.is_not(None),
        Approval.due_date < today,
    )
    if overdue_memos:
        pieces = await _count(
            db,
            ApprovalItem,
            ApprovalItem.status == ApprovalLineStatus.out,
        )
        alerts.append(
            DashboardAlert(
                key="memos_overdue",
                label=f"{overdue_memos} memo(s) past their return date",
                detail=f"{pieces} piece(s) are out on approval altogether.",
                count=overdue_memos,
                tone="bad",
                to="/approvals",
            )
        )

    late_orders = await _count(
        db,
        CustomerOrder,
        CustomerOrder.status.in_(OPEN_ORDERS),
        CustomerOrder.promised_date.is_not(None),
        CustomerOrder.promised_date < today,
    )
    if late_orders:
        alerts.append(
            DashboardAlert(
                key="orders_late",
                label=f"{late_orders} order(s) past the date you promised",
                detail="The customer was given a date and it has gone by.",
                count=late_orders,
                tone="bad",
                to="/orders",
            )
        )

    unpaid = (
        await db.execute(
            select(func.count(Invoice.id)).where(Invoice.status == InvoiceStatus.issued)
        )
    ).scalar_one()
    if unpaid:
        alerts.append(
            DashboardAlert(
                key="invoices_unpaid",
                label=f"{unpaid} bill(s) issued and not settled",
                detail=f"{now.customer_receivable} owed across all customers.",
                count=int(unpaid),
                tone="warn",
                to="/invoices",
            )
        )

    # Legs still open are metal in somebody else's hands. Counted from the same
    # rule the design screen uses, so the two can never disagree.
    open_legs = await _count(db, JobLeg, JobLeg.status == LegStatus.issued)
    if open_legs:
        alerts.append(
            DashboardAlert(
                key="legs_open",
                label=f"{open_legs} job(s) still out with a worker",
                detail=f"{now.gold_with_workers_g} g of the shop's metal is with them.",
                count=open_legs,
                tone="warn" if now.gold_with_workers_g > 0 else "info",
                to="/designs",
            )
        )

    return DashboardReport(
        as_of=today,
        days=days,
        today=now,
        series=series,
        alerts=alerts,
    )
