from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.order import OrderKind, OrderStatus
from app.schemas.common import ORMModel, TimestampedRead


class OrderCreate(BaseModel):
    """
    Take the job in.

    `kind` drives what the rest of the form means, so it has no default — a
    repair recorded as a commission would lose the customer's own metal, and
    that is not a mistake worth allowing a default to make.
    """

    kind: OrderKind
    customer_id: int
    branch_id: int | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    promised_date: date | None = None
    estimate_amount: Decimal = Field(default=Decimal("0"), ge=0)

    # Repair intake — the customer's own piece across the counter.
    intake_weight_g: Decimal | None = Field(default=None, gt=0)
    intake_purity: int | None = Field(default=None, ge=1, le=24)
    intake_notes: str | None = None
    product_id: int | None = None

    notes: str | None = None

    @model_validator(mode="after")
    def _repair_needs_a_weight(self) -> "OrderCreate":
        # A repair leaves with the customer's metal in it. Taking one in without
        # weighing it is how a dispute becomes one person's word against
        # another's, so the weight is required rather than merely offered.
        if self.kind is OrderKind.repair and self.intake_weight_g is None:
            raise ValueError(
                "A repair arrives with the customer's own piece. Weigh it in — "
                "intake_weight_g is what settles a later dispute."
            )
        if self.kind is OrderKind.custom and self.intake_weight_g is not None:
            raise ValueError(
                "A commission is made from the shop's own metal, so there is nothing to "
                "take in. Record it as a repair if the customer supplied the piece."
            )
        return self


class OrderUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    promised_date: date | None = None
    estimate_amount: Decimal | None = Field(default=None, ge=0)
    intake_notes: str | None = None
    notes: str | None = None


class OrderTransition(BaseModel):
    to: OrderStatus
    note: str | None = None


class OrderCancel(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class OrderStartWork(BaseModel):
    """
    Put the job on the bench.

    `item_id` is what the design number is minted from — a taka becomes
    TK-00042 — so the counter has to say what kind of piece this is before the
    workshop can track it.
    """

    item_id: int
    notes: str | None = None


class OrderEventRead(TimestampedRead):
    from_status: OrderStatus | None = None
    to_status: OrderStatus | None = None
    note: str | None = None
    user_id: int | None = None


class OrderRead(TimestampedRead):
    order_no: str
    kind: OrderKind
    status: OrderStatus
    customer_id: int
    customer_name: str | None = None
    customer_phone: str | None = None
    branch_id: int
    branch_name: str | None = None
    title: str
    description: str | None = None
    promised_date: date | None = None
    # Positive when the promised date has passed and the job is not out of the
    # door. Computed server-side so every client agrees on what "late" means.
    days_overdue: int | None = None
    estimate_amount: Decimal
    intake_weight_g: Decimal | None = None
    intake_purity: int | None = None
    intake_notes: str | None = None
    image_url: str | None = None
    product_id: int | None = None
    design_id: int | None = None
    design_no: str | None = None
    invoice_id: int | None = None
    delivered_at: datetime | None = None
    cancelled_reason: str | None = None
    notes: str | None = None
    # Which buttons the counter may press, straight off the same table the API
    # enforces — so the UI cannot offer a move the server will refuse.
    allowed_transitions: list[OrderStatus] = Field(default_factory=list)


class OrderDetail(OrderRead):
    events: list[OrderEventRead] = Field(default_factory=list)


class OrderBoard(ORMModel):
    """Counts for the workbench tabs, so the shop can see its day at a glance."""

    draft: int
    confirmed: int
    in_progress: int
    ready: int
    overdue: int
