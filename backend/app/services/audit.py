"""
Audit service — single entrypoint for recording sensitive actions.

The stock_movements table covers stock-level audit. This service covers
everything else: invoice lifecycle, manufacturing transitions, deletes, etc.

Usage from a router:
    from app.services.audit import log_action
    await log_action(
        db, user=current,
        action="invoice.issue",
        resource_type="invoice", resource_id=inv.id,
        details={"sale_type": inv.sale_type.value, "currency": inv.currency.value, "total": str(inv.total)},
    )
    # call this BEFORE db.commit() so the audit row is part of the same tx
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.middleware import current_request_id
from app.models.audit_log import AuditLog
from app.models.user import User

# Columns nobody audits: surrogate keys and the timestamps every row carries.
# Logging that `updated_at` changed on an update is noise that makes the real
# change harder to find.
UNAUDITED = {"id", "created_at", "updated_at"}


def _plain(value: Any) -> Any:
    """
    A value JSONB can hold and a person can read.

    Decimals become strings rather than floats — this log is read to settle
    arguments about weights and money, and 2.6 arriving back as
    2.5999999999999996 would undermine the entire point of keeping it.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def snapshot(obj: Any) -> dict[str, Any]:
    """
    Every audited column of a row, as plain values.

    Taken from the mapper rather than `__dict__` so it sees columns the ORM
    knows about and nothing else — no relationships, no lazy loads, and no
    accidental database round trip while building a log line.
    """
    if obj is None:
        return {}
    mapper = inspect(type(obj))
    return {
        col.key: _plain(getattr(obj, col.key, None))
        for col in mapper.column_attrs
        if col.key not in UNAUDITED
    }


def changes(
    before: dict[str, Any], after: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    The two sides of a change, reduced to the fields that actually moved.

    Returns a pair of dicts with identical keys, so a reader can put them side
    by side without checking whether each field exists on both. An update that
    changed nothing returns two empty dicts — and the caller should not write a
    log line at all, because "Abdul edited this and altered nothing" is a row
    that only makes the real edits harder to see.
    """
    moved = [k for k in set(before) | set(after) if before.get(k) != after.get(k)]
    return (
        {k: before.get(k) for k in sorted(moved)},
        {k: after.get(k) for k in sorted(moved)},
    )


async def log_action(
    db: AsyncSession,
    *,
    user: User | None,
    action: str,
    resource_type: str,
    resource_id: int | None = None,
    details: dict[str, Any] | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditLog:
    row = AuditLog(
        actor_user_id=user.id if user else None,
        actor_email=user.email if user else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        before=before,
        after=after,
        reason=reason,
        request_id=current_request_id(),
    )
    db.add(row)
    await db.flush()
    return row
