from typing import Any

from app.schemas.common import TimestampedRead


class AuditLogRead(TimestampedRead):
    actor_user_id: int | None = None
    actor_email: str | None = None
    action: str
    resource_type: str
    resource_id: int | None = None
    details: dict[str, Any] | None = None
    # Only the fields that changed, with identical keys on both sides so a
    # reader can put them next to each other without checking each one exists.
    # NULL — not `{}` — when an action was never recorded this way.
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason: str | None = None
    request_id: str | None = None
