from typing import Any

from app.schemas.common import TimestampedRead


class AuditLogRead(TimestampedRead):
    actor_user_id: int | None = None
    actor_email: str | None = None
    action: str
    resource_type: str
    resource_id: int | None = None
    details: dict[str, Any] | None = None
    request_id: str | None = None
