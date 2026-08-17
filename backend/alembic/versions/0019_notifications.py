"""Keep a record of what the shop told its customers.

WhatsApp sending existed as a single fire-and-forget endpoint on an invoice:
it either reached Twilio or raised, and either way nothing was written down.
So there was no answer to "did we tell them the piece was ready", "which number
did we message", or "why did that one not go".

Every attempt is now logged, including the ones that never left the building —
a send made while no provider is configured, or to a customer with no number on
file, records as `skipped` rather than vanishing. That distinction matters at
the counter: in both cases the customer was not told, and somebody has to pick
up the phone.

The body is stored as sent rather than re-rendered on read. Templates get
edited; what was actually said is the thing worth keeping.

Revision ID: 0019_notifications
Revises: 0018_customer_orders
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_notifications"
down_revision: Union[str, None] = "0018_customer_orders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KINDS = (
    "order_confirmed",
    "order_ready",
    "order_delivered",
    "invoice",
    "payment_reminder",
    "birthday",
    "anniversary",
    "custom",
)
_STATUSES = ("sent", "failed", "skipped")


def upgrade() -> None:
    sa.Enum(*_KINDS, name="notification_kind").create(op.get_bind(), checkfirst=True)
    sa.Enum("whatsapp", name="notification_channel").create(op.get_bind(), checkfirst=True)
    sa.Enum(*_STATUSES, name="notification_status").create(op.get_bind(), checkfirst=True)

    kind = postgresql.ENUM(*_KINDS, name="notification_kind", create_type=False)
    channel = postgresql.ENUM("whatsapp", name="notification_channel", create_type=False)
    st = postgresql.ENUM(*_STATUSES, name="notification_status", create_type=False)

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", kind, nullable=False),
        sa.Column("channel", channel, nullable=False, server_default="whatsapp"),
        sa.Column("status", st, nullable=False),
        sa.Column(
            "customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="SET NULL")
        ),
        sa.Column("to_phone", sa.String(40)),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("related_type", sa.String(40)),
        sa.Column("related_id", sa.Integer()),
        sa.Column("provider", sa.String(30)),
        sa.Column("provider_message_id", sa.String(80)),
        sa.Column("error", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for col in ("kind", "status", "customer_id", "related_type", "related_id",
                "created_by_user_id"):
        op.create_index(f"ix_notifications_{col}", "notifications", [col])
    # The common read is "what have we sent about this order", so the pair is
    # indexed together rather than relying on two single-column scans.
    op.create_index(
        "ix_notifications_related", "notifications", ["related_type", "related_id"]
    )


def downgrade() -> None:
    op.drop_table("notifications")
    sa.Enum(name="notification_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="notification_channel").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="notification_kind").drop(op.get_bind(), checkfirst=True)
