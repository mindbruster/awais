"""
The stock form's contract.

The preview and the commit share the weight and cost shapes on purpose: the
figures the operator approves on screen must be the same figures the product is
minted with, and two schemas would let them drift.
"""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.design import DesignStatus, LegStatus
from app.schemas.common import ORMModel


class StoneUseRead(ORMModel):
    """A stone that went into the piece and did not come back."""

    stone_id: int
    stone_name: str | None = None
    quantity_used: int
    weight_used_ct: Decimal
    rate_per_ct: Decimal
    value: Decimal


class HopRead(ORMModel):
    """One department's contribution — what it was given, what it returned."""

    leg_id: int
    sequence: int
    department: str
    worker: str | None = None
    status: LegStatus
    gold_in_g: Decimal
    gold_out_g: Decimal
    gold_purity: int | None = None
    piece_count: int
    wastage_allowed_g: Decimal
    wastage_actual_g: Decimal
    wastage_excess_g: Decimal
    labour_basis: str
    labour_rate: Decimal
    labour_amount: Decimal
    stone_value: Decimal
    stones: list[StoneUseRead] = Field(default_factory=list)


class WeightsRead(ORMModel):
    """
    The working, not just the answer: gross − stones = net metal, and
    net × purity/24 = pure. All three travel together so the form can show how
    the priced weight was arrived at.
    """

    gross_weight_g: Decimal
    stone_weight_ct: Decimal
    stone_weight_g: Decimal
    net_metal_g: Decimal
    gold_purity: int | None = None
    pure_weight_g: Decimal


class StockTotals(ORMModel):
    hops: int
    pieces: int
    gold_issued_g: Decimal
    gold_received_g: Decimal
    wastage_allowed_g: Decimal
    wastage_actual_g: Decimal
    wastage_excess_g: Decimal
    stone_weight_ct: Decimal
    stone_value: Decimal
    # Accrued on the legs as they were received; this is what becomes the
    # product's total_cost once other charges are added.
    labour_total: Decimal


class StockPreview(ORMModel):
    """
    Everything the stock form needs, computed from the legs rather than stored.

    The costs here are what the piece *would* be stocked at with the suggested
    weight; the form recomputes as the operator edits, and the commit recomputes
    again from what he actually sends.
    """

    design_id: int
    design_no: str
    tag_no: str | None = None
    item: str | None = None
    customer: str | None = None
    status: DesignStatus
    hops: list[HopRead] = Field(default_factory=list)
    stones: list[StoneUseRead] = Field(default_factory=list)
    totals: StockTotals

    # What the last department handed back — the weight to put on the form. Not
    # a sum of receipts: the same piece is issued and received at every hop.
    suggested_gold_weight_g: Decimal
    suggested_gold_purity: int | None = None
    suggested_name: str
    # PKR per fine gram, in force now. The metal is capitalised at this rate and
    # the rate is then locked on the product, so a later recompute cannot
    # re-price the piece's gold.
    gold_rate_per_g: Decimal
    weights: WeightsRead
    gold_value: Decimal
    material_cost: Decimal
    # labour + material — the number the screen exists to show.
    piece_cost: Decimal


class StockStoneLine(BaseModel):
    """
    Stones mounted on the finished piece.

    `weight_ct` is the **line total**, the way the setting leg records it — 350
    stones at 12.5ct is `quantity=350, weight_ct=12.5`, not 12.5 carats each.
    That is what the operator is reading off the job card, and asking him to
    divide it by hand is asking for a costing error.
    """

    stone_id: int
    # At least one: `product_stones` values a line as weight x rate x quantity,
    # so a zero count would capitalise the stones at nothing.
    quantity: int = Field(default=1, ge=1)
    weight_ct: Decimal = Field(default=Decimal("0"), ge=0)
    # Omitted means "the rate this design actually consumed it at", falling back
    # to the stone's default. Never zero by accident: a zero rate silently
    # capitalises the stones at nothing.
    rate_per_ct: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class StockDesign(BaseModel):
    """
    Turn the piece into a product.

    `stones` omitted (null) means "whatever the design consumed" — the setter's
    lines are already on the legs and dropping them would understate the piece's
    material cost. An explicit empty list means the operator is saying this piece
    carries no stones, which is a different statement and is honoured.
    """

    name: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=80)
    description: str | None = None
    gross_weight_g: Decimal = Field(gt=0)
    gold_weight_g: Decimal = Field(gt=0)
    gold_purity: int | None = Field(default=None, ge=1, le=24)
    other_charges: Decimal = Field(default=Decimal("0"), ge=0)
    finished_inventory_location: str | None = Field(default=None, max_length=100)
    stones: list[StockStoneLine] | None = None


class StockResult(ORMModel):
    """What the commit did, in the terms the operator asked for it."""

    design_id: int
    design_no: str
    product_id: int
    serial_no: str
    name: str
    category: str | None = None
    status: DesignStatus
    stocked_at: datetime | None = None

    weights: WeightsRead
    gold_rate_per_g: Decimal
    labour_total: Decimal
    other_charges: Decimal
    # Making charge: labour accrued on the legs plus other charges.
    total_cost: Decimal
    # Capitalised material: gold at the locked rate plus the stones.
    material_cost: Decimal
    stone_value: Decimal
    piece_cost: Decimal

    inventory_item_id: int
    inventory_location: str | None = None
    entry_id: int
    entry_no: str
