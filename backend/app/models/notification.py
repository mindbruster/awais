import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.customer import Customer
from app.models.mixins import TimestampMixin


class NotificationChannel(str, enum.Enum):
    whatsapp = "whatsapp"


class NotificationKind(str, enum.Enum):
    """
    What the message is about.

    Kept as an enum rather than free text because the template, the audience
    and the question "have we already told them this?" all key off it. A shop
    that rings a customer twice about the same ready piece looks careless; one
    that never rings at all loses the sale.
    """

    order_confirmed = "order_confirmed"
    order_ready = "order_ready"
    order_delivered = "order_delivered"
    invoice = "invoice"
    payment_reminder = "payment_reminder"
    birthday = "birthday"
    anniversary = "anniversary"
    custom = "custom"


class NotificationStatus(str, enum.Enum):
    """
    What became of it.

    `skipped` is not a failure. It is the honest record of an attempt made
    while no provider was configured, or to a customer with no number on file —
    both of which the shop needs to see, because the customer was not told and
    somebody is going to have to pick up the phone.
    """

    sent = "sent"
    failed = "failed"
    skipped = "skipped"


class Notification(Base, TimestampMixin):
    """
    Every message the shop sent a customer, and every one it meant to.

    Logged whatever the outcome. A send that failed silently is worse than one
    that never happened: the counter believes the customer knows their piece is
    ready, and nobody finds out otherwise until the customer walks in annoyed.
    The body is stored as it went out, not re-rendered on read — templates get
    edited, and what was actually said is the thing worth keeping.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)

    kind: Mapped[NotificationKind] = mapped_column(
        Enum(NotificationKind, name="notification_kind"), nullable=False, index=True
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel"),
        nullable=False,
        default=NotificationChannel.whatsapp,
    )
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status"), nullable=False, index=True
    )

    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), index=True
    )
    customer: Mapped[Customer | None] = relationship(lazy="joined")

    # Snapshotted, not read off the customer at display time. People change
    # numbers, and "which number did we actually message" is the question asked
    # when a customer says they never heard from you.
    to_phone: Mapped[str | None] = mapped_column(String(40))
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # What it was about — an order, an invoice — so the thread can be shown on
    # that record without a second table per relationship.
    related_type: Mapped[str | None] = mapped_column(String(40), index=True)
    related_id: Mapped[int | None] = mapped_column(Integer, index=True)

    provider: Mapped[str | None] = mapped_column(String(30))
    provider_message_id: Mapped[str | None] = mapped_column(String(80))
    error: Mapped[str | None] = mapped_column(Text)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
