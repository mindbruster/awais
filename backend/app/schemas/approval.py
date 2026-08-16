from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.approval import ApprovalLineStatus, ApprovalStatus
from app.schemas.common import ORMModel, TimestampedRead


class ApprovalCreate(BaseModel):
    customer_id: int
    branch_id: int | None = None
    product_ids: list[int] = Field(min_length=1)
    # The single most useful field on a memo. Without a date nobody chases it,
    # and a piece nobody chases is a piece the shop finds missing at stock-take.
    due_date: date | None = None
    notes: str | None = None


class ApprovalLines(BaseModel):
    line_ids: list[int] = Field(min_length=1)


class ApprovalSold(ApprovalLines):
    invoice_id: int | None = None


class ApprovalCancel(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ApprovalItemRead(TimestampedRead):
    approval_id: int
    product_id: int
    product_serial: str | None = None
    product_name: str | None = None
    gold_weight_g: Decimal | None = None
    status: ApprovalLineStatus
    returned_at: datetime | None = None
    invoice_id: int | None = None
    notes: str | None = None


class ApprovalRead(TimestampedRead):
    approval_no: str
    customer_id: int
    customer_name: str | None = None
    customer_phone: str | None = None
    branch_id: int
    branch_name: str | None = None
    status: ApprovalStatus
    issued_at: datetime | None = None
    due_date: date | None = None
    closed_at: datetime | None = None
    # Positive once the return date has passed with pieces still out. Computed
    # server-side so every client agrees what overdue means.
    days_overdue: int | None = None
    out_count: int
    total_count: int
    notes: str | None = None
    cancelled_reason: str | None = None
    items: list[ApprovalItemRead] = Field(default_factory=list)


class ApprovalBoard(ORMModel):
    out: int
    partly_returned: int
    overdue: int
    pieces_out: int
