from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.design import DesignStatus, LabourBasis, LegStatus
from app.schemas.common import ORMModel, TimestampedRead


class DesignCreate(BaseModel):
    """
    Mint a piece.

    The design number is generated from the item's abbreviation and is never
    supplied by the caller — it is the identity everything downstream keys on,
    so it may not be chosen by whoever happens to be at the counter.
    """

    item_id: int
    customer_id: int | None = None
    notes: str | None = None


class LegStoneIssue(BaseModel):
    stone_id: int
    quantity_issued: int = Field(default=0, ge=0)
    weight_issued_ct: Decimal = Field(gt=0)
    rate_per_ct: Decimal = Field(default=Decimal("0"), ge=0)


class LegIssue(BaseModel):
    department_id: int
    worker_id: int
    gold_issued_g: Decimal = Field(gt=0)
    gold_issued_purity: int | None = Field(default=None, ge=1, le=24)
    gold_source_inventory_id: int
    stones: list[LegStoneIssue] = Field(default_factory=list)
    stone_source_inventory_id: int | None = None
    labour_basis: LabourBasis = LabourBasis.per_gram
    labour_rate: Decimal = Field(default=Decimal("0"), ge=0)
    notes: str | None = None


class LegStoneReturn(BaseModel):
    leg_stone_id: int
    quantity_returned: int = Field(default=0, ge=0)
    weight_returned_ct: Decimal = Field(default=Decimal("0"), ge=0)


class LegReceive(BaseModel):
    # May exceed what was issued. Solder, alloy and findings are added while the
    # piece is being worked, so a heavier return is routine and rejecting it
    # would push the shop into falsifying the weight to get the leg closed.
    gold_received_g: Decimal = Field(ge=0)
    stones: list[LegStoneReturn] = Field(default_factory=list)
    notes: str | None = None


class LegCancel(BaseModel):
    """
    Abandon a leg and say what came back.

    Both recovery figures default to zero so that omitting them can never
    invent stock that isn't on the shelf; whatever is not declared stays
    outstanding against the worker.
    """

    gold_recovered_g: Decimal = Field(default=Decimal("0"), ge=0)
    stones_recovered_ct: Decimal = Field(default=Decimal("0"), ge=0)
    reason: str = Field(min_length=1, max_length=500)


class LegStoneRead(TimestampedRead):
    leg_id: int
    stone_id: int
    stone_name: str | None = None
    quantity_issued: int
    weight_issued_ct: Decimal
    quantity_returned: int
    weight_returned_ct: Decimal
    quantity_used: int
    rate_per_ct: Decimal
    notes: str | None = None


class JobLegRead(TimestampedRead):
    design_id: int
    sequence: int
    department_id: int
    department_name: str | None = None
    worker_id: int | None = None
    worker_name: str | None = None
    status: LegStatus
    issued_at: datetime | None = None
    gold_issued_g: Decimal
    gold_issued_purity: int | None = None
    stones_issued_ct: Decimal
    gold_source_inventory_id: int | None = None
    stone_source_inventory_id: int | None = None
    received_at: datetime | None = None
    gold_received_g: Decimal
    stones_used_ct: Decimal
    stones_returned_ct: Decimal
    wastage_allowed_pct: Decimal | None = None
    wastage_allowed_g: Decimal
    wastage_actual_g: Decimal
    wastage_excess_g: Decimal
    labour_basis: LabourBasis
    labour_rate: Decimal
    labour_amount: Decimal
    notes: str | None = None
    stones: list[LegStoneRead] = Field(default_factory=list)


class DesignRead(TimestampedRead):
    design_no: str
    tag_no: str | None = None
    item_id: int
    item_name: str | None = None
    customer_id: int | None = None
    customer_name: str | None = None
    current_department_id: int | None = None
    current_department_name: str | None = None
    status: DesignStatus
    image_url: str | None = None
    notes: str | None = None
    product_id: int | None = None


class DesignDetail(DesignRead):
    legs: list[JobLegRead] = Field(default_factory=list)


class TraceStone(ORMModel):
    stone_name: str | None = None
    quantity_issued: int
    weight_issued_ct: Decimal
    quantity_returned: int
    weight_returned_ct: Decimal
    weight_used_ct: Decimal


class TraceHop(ORMModel):
    """One department the piece has been through, as the shop reads it."""

    leg_id: int
    sequence: int
    department: str
    worker: str | None = None
    status: LegStatus
    issued_at: datetime | None = None
    received_at: datetime | None = None
    days_held: int | None = None
    gold_in_g: Decimal
    gold_purity: int | None = None
    gold_out_g: Decimal
    wastage_allowed_pct: Decimal | None = None
    wastage_allowed_g: Decimal
    wastage_actual_g: Decimal
    wastage_excess_g: Decimal
    stones_issued_ct: Decimal
    stones_used_ct: Decimal
    stones_returned_ct: Decimal
    labour_basis: LabourBasis
    labour_rate: Decimal
    labour_amount: Decimal
    notes: str | None = None
    stones: list[TraceStone] = Field(default_factory=list)


class TraceTotals(ORMModel):
    hops: int
    open_hops: int
    gold_issued_g: Decimal
    gold_received_g: Decimal
    wastage_allowed_g: Decimal
    wastage_actual_g: Decimal
    # What the workers on this piece still owe in metal. The number the shop
    # chases, which is why it is a total and not something the reader has to
    # add up from the hops.
    wastage_excess_g: Decimal
    stones_issued_ct: Decimal
    stones_used_ct: Decimal
    stones_returned_ct: Decimal
    labour_amount: Decimal


class DesignTrace(ORMModel):
    design_id: int
    design_no: str
    tag_no: str | None = None
    item: str | None = None
    customer: str | None = None
    status: DesignStatus
    current_department: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    days_in_production: int | None = None
    hops: list[TraceHop] = Field(default_factory=list)
    totals: TraceTotals
