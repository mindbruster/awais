"""
Non-destructive smoke test for customer notifications.

Nothing is sent: the provider is `none` in development, which is exactly the
path this checks — an attempt made with no provider must be recorded as
`skipped` with a readable reason, not vanish and not raise. Everything runs
inside a transaction that is rolled back.
"""
import asyncio
import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

logging.disable(logging.INFO)

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.customer import Customer  # noqa: E402
from app.models.notification import NotificationKind, NotificationStatus  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import notifications as svc  # noqa: E402

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"[PASS] {label}")
    else:
        fail += 1
        print(f"[FAIL] {label} {detail}")


async def main():
    print(f"       whatsapp_provider = {settings.whatsapp_provider!r}")
    async with SessionLocal() as db:
        admin = (await db.execute(select(User).limit(1))).scalars().first()

        with_phone = Customer(name="ZZ Smoke Phoned", phone="+923001234567")
        without = Customer(name="ZZ Smoke No Phone")
        db.add_all([with_phone, without])
        await db.flush()

        # --- templates ----------------------------------------------------------
        ready = svc.render(
            NotificationKind.order_ready,
            customer=with_phone,
            ctx={"order_no": "ORD-26-00007", "title": "resize ring",
                 "estimate_amount": Decimal("2500")},
        )
        check("ready message names the order", "ORD-26-00007" in ready)
        check("ready message names the piece", "resize ring" in ready)
        check("ready message quotes rupees, not Indian rupees",
              "₨" in ready and "₹" not in ready, f"got {ready!r}")

        reminder = svc.render(
            NotificationKind.payment_reminder,
            customer=with_phone,
            ctx={"balance": Decimal("12500.5")},
        )
        check("reminder formats the balance", "12,500.50" in reminder, f"got {reminder!r}")

        usd_bill = svc.render(
            NotificationKind.invoice,
            customer=with_phone,
            ctx={"invoice_no": "INV-9", "total": Decimal("1200"), "currency": "USD"},
        )
        check("a dollar invoice is quoted in dollars",
              "$ 1,200.00" in usd_bill and "₨" not in usd_bill, f"got {usd_bill!r}")

        pkr_bill = svc.render(
            NotificationKind.invoice,
            customer=with_phone,
            ctx={"invoice_no": "INV-8", "total": Decimal("1200"), "currency": "PKR"},
        )
        check("a rupee invoice is quoted in rupees",
              "₨ 1,200.00" in pkr_bill, f"got {pkr_bill!r}")

        birthday = svc.render(NotificationKind.birthday, customer=with_phone, ctx={})
        check("birthday greets by name", "ZZ Smoke Phoned" in birthday)

        # --- dispatch with no provider ------------------------------------------
        note = await svc.dispatch(
            db, kind=NotificationKind.order_ready, customer=with_phone,
            body=ready, related_type="customer_order", related_id=1,
            user_id=admin.id if admin else None,
        )
        check("an unconfigured send is skipped, not failed",
              note.status is NotificationStatus.skipped, f"got {note.status}")
        check("the reason says why nothing went", bool(note.error) and "provider" in note.error.lower())
        check("the body is stored as it would have gone", note.body == ready)
        check("the number is snapshotted", note.to_phone == "+923001234567")
        check("nothing claims to have been sent", note.sent_at is None)

        # --- dispatch to a customer with no number -------------------------------
        note2 = await svc.dispatch(
            db, kind=NotificationKind.birthday, customer=without,
            body=birthday, user_id=admin.id if admin else None,
        )
        check("no phone number is also skipped", note2.status is NotificationStatus.skipped)
        check("the reason names the missing number",
              bool(note2.error) and "phone" in note2.error.lower(), f"got {note2.error!r}")

        # --- occasions ----------------------------------------------------------
        today = date.today()
        soon = today + timedelta(days=3)
        check("an occasion three days out is inside a week",
              svc.occasion_within(soon.replace(year=1990), today=today, window=7) == 3)
        check("an occasion today is zero days away",
              svc.occasion_within(today.replace(year=1985), today=today, window=7) == 0)
        check("an occasion outside the window is ignored",
              svc.occasion_within((today + timedelta(days=40)).replace(year=1985),
                                  today=today, window=7) is None)
        check("no date means no occasion",
              svc.occasion_within(None, today=today, window=7) is None)
        # New-year wrap: from 30 December, 2 January is three days away.
        check("the year boundary does not add 362 days",
              svc.occasion_within(date(1990, 1, 2), today=date(2026, 12, 30), window=7) == 3,
              f"got {svc.occasion_within(date(1990, 1, 2), today=date(2026, 12, 30), window=7)}")
        # 29 February in a non-leap year falls back to the 28th.
        check("a leap-day birthday still lands in a non-leap year",
              svc.occasion_within(date(1988, 2, 29), today=date(2026, 2, 25), window=7) == 3,
              f"got {svc.occasion_within(date(1988, 2, 29), today=date(2026, 2, 25), window=7)}")

        await db.rollback()
        print("\n       rolled back — no changes committed, no messages sent")

    print(f"\n{ok} passed, {fail} failed")
    raise SystemExit(1 if fail else 0)


asyncio.run(main())
