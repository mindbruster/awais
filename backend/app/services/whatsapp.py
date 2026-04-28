"""
Phase 9 — WhatsApp send. Pluggable provider behind a feature flag.

The Twilio backend is wired (HTTP only — no SDK dependency) so a real
account_sid + auth_token + whatsapp_from will work without code changes.
When `whatsapp_provider="none"` (the default), `send_text` raises a
HTTP 503 so callers can surface a clear error.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx
from fastapi import HTTPException, status

from app.core.config import settings


@dataclass
class SendResult:
    provider: str
    message_sid: str | None
    raw: dict


def _normalize_phone(number: str) -> str:
    """Twilio expects `whatsapp:+<E.164 number>`."""
    n = number.strip()
    if n.startswith("whatsapp:"):
        return n
    if not n.startswith("+"):
        n = "+" + n.lstrip("0")
    return f"whatsapp:{n}"


async def send_text(to_phone: str, body: str) -> SendResult:
    if settings.whatsapp_provider == "none":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "WhatsApp provider not configured. Set WHATSAPP_PROVIDER, "
                "TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_FROM."
            ),
        )

    if settings.whatsapp_provider == "twilio":
        sid = settings.twilio_account_sid
        token = settings.twilio_auth_token
        sender = settings.twilio_whatsapp_from
        if not (sid and token and sender):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Twilio credentials incomplete.",
            )
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        creds = base64.b64encode(f"{sid}:{token}".encode()).decode()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Basic {creds}"},
                data={
                    "To": _normalize_phone(to_phone),
                    "From": sender if sender.startswith("whatsapp:") else f"whatsapp:{sender}",
                    "Body": body,
                },
            )
        if resp.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Twilio rejected the send: {resp.text[:300]}",
            )
        data = resp.json()
        return SendResult(provider="twilio", message_sid=data.get("sid"), raw=data)

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unknown WHATSAPP_PROVIDER '{settings.whatsapp_provider}'",
    )


def render_invoice_message(invoice, customer) -> str:
    """Plain-text invoice summary suitable for a WhatsApp body."""
    lines = [
        f"Hi {customer.name}, here's your invoice {invoice.invoice_no} from {settings.app_name}.",
        "",
    ]
    for item in invoice.items:
        bits = [item.description, f"Qty {item.quantity}", f"₹{item.line_total}"]
        lines.append(" · ".join(bits))
    lines += [
        "",
        f"Subtotal: ₹{invoice.subtotal}",
        f"Discount: ₹{invoice.discount_amount}",
        f"Tax: ₹{invoice.tax_amount}",
        f"Total: ₹{invoice.total}",
    ]
    return "\n".join(lines)
