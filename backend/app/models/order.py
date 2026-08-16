import enum
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.branch import Branch
from app.models.customer import Customer
from app.models.mixins import TimestampMixin


class OrderKind(str, enum.Enum):
    """
    Why the piece is on the bench.

    A commission and a repair run through the same departments and are tracked
    the same way, but they differ in one respect that matters commercially: a
    repair arrives with the customer's own metal already in it, and that metal
    is not the shop's to sell. Keeping them apart lets the intake weight mean
    something on one and stay empty on the other.
    """

    custom = "custom"
    repair = "repair"


class OrderStatus(str, enum.Enum):
    """
    Where the job is, in the words the counter uses when the customer rings.

    `ready` is separate from `delivered` on purpose — the gap between the two
    is exactly the list a shop needs to work through every morning, and
    collapsing them would lose the one question a customer actually asks.
    """

    draft = "draft"
    confirmed = "confirmed"
    in_progress = "in_progress"
    ready = "ready"
    delivered = "delivered"
    cancelled = "cancelled"


# Which statuses may follow which. Held as data rather than as branching inside
# the router so that the rule reads in one place and the UI can be driven from
# the same table instead of restating it.
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.draft: {OrderStatus.confirmed, OrderStatus.cancelled},
    OrderStatus.confirmed: {OrderStatus.in_progress, OrderStatus.ready, OrderStatus.cancelled},
    OrderStatus.in_progress: {OrderStatus.ready, OrderStatus.cancelled},
    # A piece can go back to the bench: the customer sees it and wants the
    # shank thinner. Refusing that would push the counter into opening a second
    # order for one job.
    OrderStatus.ready: {OrderStatus.delivered, OrderStatus.in_progress, OrderStatus.cancelled},
    OrderStatus.delivered: set(),
    OrderStatus.cancelled: set(),
}


class CustomerOrder(Base, TimestampMixin):
    """
    Work promised to a named customer.

    Deliberately not a ledger document. An order is a promise, and a promise
    moves no metal and earns no money — the advance is an ordinary payment
    against the customer, and the delivery is an ordinary invoice. Both are
    linked from here rather than reimplemented, so there is exactly one code
    path that can touch the books.

    The bridge to the workshop is `design_id`. When work actually starts, the
    order mints a design and everything the routing engine already does —
    legs, wastage, labour, per-department costing — applies unchanged. That is
    the whole reason this module is small: it is a front door onto machinery
    that already exists.
    """

    __tablename__ = "customer_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)

    kind: Mapped[OrderKind] = mapped_column(
        Enum(OrderKind, name="order_kind"), nullable=False, index=True
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status"),
        nullable=False,
        default=OrderStatus.draft,
        index=True,
    )

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    customer: Mapped[Customer] = relationship(lazy="joined")

    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    branch: Mapped[Branch] = relationship(lazy="joined")

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # What the counter promised. The single most-asked question about an order,
    # so it is a column rather than something buried in the notes.
    promised_date: Mapped[date | None] = mapped_column(Date, index=True)

    # What the job was quoted at. Not a price the books know about — the
    # invoice at delivery is the priced document — but the number the customer
    # was told, which is worth keeping so the two can be compared.
    estimate_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    # --- repair intake ---
    # The customer's own piece, weighed across the counter as it is taken in.
    # This metal is not the shop's: it is returned in the finished job, and
    # recording it is what lets a dispute be settled by the book rather than by
    # memory.
    intake_weight_g: Mapped[float | None] = mapped_column(Numeric(14, 4))
    intake_purity: Mapped[int | None] = mapped_column(Integer)
    # Fineness in percent, preferred over the karat integer above. This is the
    # customer's own metal, weighed across the counter — the row most likely to
    # be produced in a dispute, so it records what the scale said rather than
    # the nearest karat band. See `Product.gold_tunch_pct`.
    intake_tunch_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))
    intake_notes: Mapped[str | None] = mapped_column(Text)
    # A photograph at intake, for the same reason.
    image_url: Mapped[str | None] = mapped_column(String(500))

    # An existing piece the shop sold, when the repair is on one of its own.
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )

    # --- links out ---
    # The workshop job, minted when work starts. Everything about cost, wastage
    # and which karigar held it lives on the design, not here.
    design_id: Mapped[int | None] = mapped_column(
        ForeignKey("designs.id", ondelete="SET NULL"), index=True
    )
    # The bill raised on delivery.
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL"), index=True
    )

    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_reason: Mapped[str | None] = mapped_column(Text)

    notes: Mapped[str | None] = mapped_column(Text)

    events: Mapped[list["OrderEvent"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="OrderEvent.id",
    )


class OrderEvent(Base, TimestampMixin):
    """
    What happened to the order, in order.

    The audit log already records who changed what, but it is an admin tool
    keyed by resource id. This is the customer-facing history — the thing a
    counter hand reads out over the phone — so it carries the shop's own
    wording and, where a message was sent, proof that it was.
    """

    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("customer_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order: Mapped[CustomerOrder] = relationship(back_populates="events")

    # Null on an event that is not a status change — a note, or a message sent.
    from_status: Mapped[OrderStatus | None] = mapped_column(
        Enum(OrderStatus, name="order_status")
    )
    to_status: Mapped[OrderStatus | None] = mapped_column(Enum(OrderStatus, name="order_status"))

    note: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
