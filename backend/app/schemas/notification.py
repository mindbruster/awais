from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.notification import (
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
)
from app.schemas.common import ORMModel, TimestampedRead


class NotificationSend(BaseModel):
    """
    Ask for a message to go out.

    `body` overrides the template. Offered because no template survives contact
    with a real customer — sometimes the counter needs to say something the
    shop never anticipated — but left empty on the normal path so the wording
    stays consistent.
    """

    kind: NotificationKind
    customer_id: int | None = None
    related_id: int | None = None
    to_phone: str | None = Field(default=None, max_length=40)
    body: str | None = Field(default=None, max_length=1500)


class NotificationPreview(ORMModel):
    body: str
    customer_id: int | None = None
    customer_name: str | None = None
    to_phone: str | None = None
    related_type: str | None = None
    related_id: int | None = None
    # False when there is no number to send to. The UI disables the send button
    # rather than letting the counter click it and get a `skipped` row back.
    sendable: bool
    note: str | None = None


class NotificationRead(TimestampedRead):
    kind: NotificationKind
    channel: NotificationChannel
    status: NotificationStatus
    customer_id: int | None = None
    customer_name: str | None = None
    to_phone: str | None = None
    body: str
    related_type: str | None = None
    related_id: int | None = None
    provider: str | None = None
    provider_message_id: str | None = None
    error: str | None = None
    sent_at: datetime | None = None


class OccasionRow(ORMModel):
    customer_id: int
    customer_name: str
    phone: str | None = None
    kind: NotificationKind
    date: date
    days_away: int
    has_phone: bool


class OccasionsReport(ORMModel):
    days: int
    today: date
    rows: list[OccasionRow] = Field(default_factory=list)
