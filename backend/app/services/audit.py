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

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.middleware import current_request_id
from app.models.audit_log import AuditLog
from app.models.user import User


async def log_action(
    db: AsyncSession,
    *,
    user: User | None,
    action: str,
    resource_type: str,
    resource_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    row = AuditLog(
        actor_user_id=user.id if user else None,
        actor_email=user.email if user else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        request_id=current_request_id(),
    )
    db.add(row)
    await db.flush()
    return row
