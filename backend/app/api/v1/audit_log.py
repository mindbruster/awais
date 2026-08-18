from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select

from app.api.deps import DbSession, require_perm
from app.core.permissions import AUDIT_READ
from app.models.audit_log import AuditLog
from app.schemas.audit_log import AuditLogRead

router = APIRouter()
# Audit log is admin-only — accountant/staff should not see who did what.
admin_only = Depends(require_perm(AUDIT_READ))


@router.get("", response_model=list[AuditLogRead], dependencies=[admin_only])
async def list_audit_log(
    db: DbSession,
    actor_user_id: int | None = Query(default=None),
    action: str | None = Query(default=None, description="Exact match, e.g. 'invoice.issue'"),
    resource_type: str | None = Query(default=None),
    resource_id: int | None = Query(default=None),
    limit: int = Query(default=200, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(desc(AuditLog.id)).limit(limit).offset(offset)
    if actor_user_id is not None:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if resource_id is not None:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    return list((await db.execute(stmt)).scalars().all())
