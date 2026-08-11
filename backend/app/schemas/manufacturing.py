from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.manufacturing import JobStage
from app.schemas.common import TimestampedRead


class ManufacturingJobCreate(BaseModel):
    """Open a new job. Optional initial karigar assignment."""
    karigar_id: int | None = None
    gold_assigned_g: Decimal = Field(default=Decimal("0"), ge=0)
    gold_assigned_purity: int | None = Field(default=None, ge=1, le=24)
    gold_source_inventory_id: int | None = Field(
        default=None,
        description="Inventory item to draw gold from when karigar_id + weight provided.",
    )
    notes: str | None = None


class AssignKarigar(BaseModel):
    karigar_id: int
    gold_assigned_g: Decimal = Field(gt=0)
    gold_assigned_purity: int | None = Field(default=None, ge=1, le=24)
    gold_source_inventory_id: int = Field(description="Raw-gold inventory item to debit.")
    notes: str | None = None


class ReceiveFromKarigar(BaseModel):
    # May legitimately exceed the assigned weight — karigars add solder, alloy
    # and findings during working, so the piece often comes back heavier.
    jewelry_received_g: Decimal = Field(gt=0)
    notes: str | None = None


class AssignStoneFixer(BaseModel):
    stone_fixer_id: int
    stones_assigned_ct: Decimal = Field(gt=0)
    stone_source_inventory_id: int
    notes: str | None = None


class ReceiveFromStoneFixer(BaseModel):
    stones_used_ct: Decimal = Field(ge=0)
    stones_returned_ct: Decimal = Field(ge=0)
    notes: str | None = None


class AssignPolish(BaseModel):
    polish_vendor_id: int
    weight_before_polish_g: Decimal = Field(gt=0)
    notes: str | None = None


class ReceiveFromPolish(BaseModel):
    # Polishing normally removes metal, but rhodium/plating can add a little,
    # so a gain is allowed here too and recorded as a negative loss.
    weight_after_polish_g: Decimal = Field(gt=0)
    notes: str | None = None


class CancelJob(BaseModel):
    """
    Cancel a job and settle the material that was issued against it.

    Whatever the shop physically gets back is credited to the source inventory
    rows; the remainder is written off on the job and stays outstanding against
    the worker. Both default to zero so that omitting them can never invent
    stock that isn't there.
    """

    gold_recovered_g: Decimal = Field(default=Decimal("0"), ge=0)
    stones_recovered_ct: Decimal = Field(default=Decimal("0"), ge=0)
    reason: str = Field(min_length=1, max_length=500)


class CompleteJob(BaseModel):
    """Materialise the finished piece as a Product + add to inventory."""
    product_name: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=80)
    finished_inventory_location: str | None = Field(default=None, max_length=100)


class SetJobCosts(BaseModel):
    """Set/override the labor + ancillary costs charged to a job. May be called
    at any stage before completion."""
    karigar_cost: Decimal | None = Field(default=None, ge=0)
    stone_fixing_cost: Decimal | None = Field(default=None, ge=0)
    polish_cost: Decimal | None = Field(default=None, ge=0)
    other_cost: Decimal | None = Field(default=None, ge=0)


class ManufacturingJobRead(TimestampedRead):
    job_no: str
    stage: JobStage
    karigar_id: int | None = None
    gold_assigned_g: Decimal
    gold_assigned_purity: int | None = None
    jewelry_received_g: Decimal
    karigar_loss_g: Decimal
    stone_fixer_id: int | None = None
    stones_assigned_ct: Decimal
    stones_used_ct: Decimal
    stones_returned_ct: Decimal
    polish_vendor_id: int | None = None
    weight_before_polish_g: Decimal
    weight_after_polish_g: Decimal
    polish_loss_g: Decimal
    karigar_cost: Decimal
    stone_fixing_cost: Decimal
    polish_cost: Decimal
    other_cost: Decimal
    product_id: int | None = None
    gold_source_inventory_id: int | None = None
    stone_source_inventory_id: int | None = None
    gold_written_off_g: Decimal
    stones_written_off_ct: Decimal
    cancel_reason: str | None = None
    notes: str | None = None
