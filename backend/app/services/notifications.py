"""
Telling customers things, and writing down that you did.

Two rules shape this module. First, a send is *logged whatever happens* —
sent, failed, or never attempted because no provider is configured. A message
that silently didn't go is worse than one that was never tried: the counter
believes the customer knows, and nobody finds out until they walk in annoyed.

Second, nothing here sends by itself. Every message is triggered by somebody at
the counter deciding to send it. A shop that auto-messages on a status change
will, sooner or later, wish a customer happy birthday on the day of a
bereavement, or tell them a piece is ready that a colleague has just found a
fault in.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.customer import Customer
from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
)
from app.services import whatsapp

# The shop trades in Pakistan and sometimes in dollars. The invoice renderer
# shipped with an Indian rupee sign, which is neither — on a bill sent to a
# customer that is not a typo, it is a wrong price, and one the customer is
# entitled to hold the shop to.
SYMBOLS = {"PKR": "₨", "USD": "$"}
BASE_CURRENCY = "PKR"


def _money(value, currency: str | None = None) -> str:
    """
    An amount with the symbol of the currency it is actually in.

    Defaults to rupees because the ledger is kept in rupees — a customer
    balance or an order estimate has no currency of its own. An invoice does,
    and passes it, so a dollar bill is never quoted in rupees.
    """
    code = getattr(currency, "value", currency) or BASE_CURRENCY
    symbol = SYMBOLS.get(code, code)
    return f"{symbol} {float(value or 0):,.2f}"


def _greeting(customer: Customer | None) -> str:
    return f"Assalam-o-Alaikum {customer.name}" if customer else "Assalam-o-Alaikum"


def render(kind: NotificationKind, *, customer: Customer | None, ctx: dict) -> str:
    """
    The message body for a kind, in the shop's own voice.

    Plain text on purpose: WhatsApp templates with placeholders need approval
    per template and per provider, and a shop that has just switched its
    provider should not lose the ability to tell someone their ring is ready.
    """
    shop = settings.app_name
    hello = _greeting(customer)

    if kind is NotificationKind.order_confirmed:
        due = ctx.get("promised_date")
        when = f" It should be ready by {due}." if due else ""
        return (
            f"{hello}, your order {ctx.get('order_no')} at {shop} is confirmed — "
            f"{ctx.get('title')}.{when} We'll message you when it's ready."
        )

    if kind is NotificationKind.order_ready:
        est = ctx.get("estimate_amount")
        amount = f" The balance due is {_money(est)}." if est and float(est) > 0 else ""
        return (
            f"{hello}, your {ctx.get('title')} ({ctx.get('order_no')}) is ready to collect "
            f"from {shop}.{amount} Please bring this message with you."
        )

    if kind is NotificationKind.order_delivered:
        return (
            f"{hello}, thank you for collecting {ctx.get('order_no')} from {shop}. "
            "We hope you're delighted with it — please do come back to us."
        )

    if kind is NotificationKind.invoice:
        return (
            f"{hello}, here is your invoice {ctx.get('invoice_no')} from {shop}. "
            f"Total {_money(ctx.get('total'), ctx.get('currency'))}. "
            "Thank you for your custom."
        )

    if kind is NotificationKind.payment_reminder:
        return (
            f"{hello}, this is a gentle reminder from {shop} — "
            f"{_money(ctx.get('balance'))} is outstanding on your account. "
            "Please get in touch if you'd like to settle it or discuss."
        )

    if kind is NotificationKind.birthday:
        return (
            f"{hello}, many happy returns of the day from all of us at {shop}. "
            "We hope your year ahead sparkles."
        )

    if kind is NotificationKind.anniversary:
        return (
            f"{hello}, happy anniversary from all of us at {shop}. "
            "Wishing you both many more happy years together."
        )

    return ctx.get("body") or ""


async def dispatch(
    db: AsyncSession,
    *,
    kind: NotificationKind,
    customer: Customer | None,
    body: str,
    related_type: str | None = None,
    related_id: int | None = None,
    user_id: int | None = None,
    to_phone: str | None = None,
) -> Notification:
    """
    Send it, and record the attempt either way.

    Never raises on a send failure. The caller is a counter hand who has just
    clicked "tell the customer"; the useful response is a row saying what
    happened, not a 502 that leaves them wondering whether it went. The refusal
    cases — no provider, no number — are recorded as `skipped`, which is the
    honest description: nothing was tried, and the customer still doesn't know.
    """
    phone = (to_phone or (customer.phone if customer else None) or "").strip()

    note = Notification(
        kind=kind,
        channel=NotificationChannel.whatsapp,
        status=NotificationStatus.skipped,
        customer_id=customer.id if customer else None,
        to_phone=phone or None,
        body=body,
        related_type=related_type,
        related_id=related_id,
        created_by_user_id=user_id,
    )

    if not phone:
        note.error = (
            f"{customer.name if customer else 'This customer'} has no phone number on file, "
            "so nothing could be sent. Add one, or ring them."
        )
    elif settings.whatsapp_provider == "none":
        note.error = (
            "No WhatsApp provider is configured, so nothing was sent. The message is saved "
            "here — set WHATSAPP_PROVIDER and the Twilio credentials to send for real."
        )
    else:
        try:
            result = await whatsapp.send_text(phone, body)
            note.status = NotificationStatus.sent
            note.provider = result.provider
            note.provider_message_id = result.message_sid
            note.sent_at = datetime.now(timezone.utc)
        except HTTPException as exc:
            note.status = NotificationStatus.failed
            note.provider = settings.whatsapp_provider
            note.error = str(exc.detail)[:1000]
        except Exception as exc:  # noqa: BLE001 — a send must never break the caller
            note.status = NotificationStatus.failed
            note.provider = settings.whatsapp_provider
            note.error = f"{type(exc).__name__}: {exc}"[:1000]

    db.add(note)
    await db.flush()
    return note


def occasion_within(day: date | None, *, today: date, window: int) -> int | None:
    """
    Days until a birthday or anniversary comes round again, ignoring the year.

    Returns None when it falls outside the window. Wrapping across the new year
    is handled by trying this year and next: a date of 2 January is one day
    away on 1 January, not three hundred and sixty-four.
    """
    if day is None:
        return None
    for year in (today.year, today.year + 1):
        try:
            occurrence = day.replace(year=year)
        except ValueError:
            # 29 February in a non-leap year. Marked on the 28th, which is what
            # a shop would do rather than skip the customer for three years.
            occurrence = day.replace(year=year, day=28)
        delta = (occurrence - today).days
        if 0 <= delta <= window:
            return delta
    return None
