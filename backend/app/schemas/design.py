from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.design import DesignStatus, LabourBasis, LegStatus, WastageBasis
from app.models.metal import Metal
from app.schemas.common import ORMModel, TimestampedRead
from app.services.pricing import DEFAULT_RATTI_BASE


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
    """
    What goes out to a department, and on what terms.

    The three settlement fields are `None` rather than zero when omitted so the
    router can tell "the counter didn't state it, use the department's standing
    terms" from "the counter deliberately said none". A shop issuing to setting
    twenty times a day must not have to retype 0.400g/100 and Rs 5 a stone, but
    an explicit zero has to survive as a zero.
    """

    department_id: int
    # Optional, because several stages are done in-house: cleaning, burning,
    # rhodium, finish. There is no outside karigar holding the metal and nobody
    # to owe it back, and forcing a name here would mean inventing a worker
    # record for the shop's own bench — which then appears in the wastage
    # reports as a party who is losing you metal. Leave it unset for in-house
    # work; the leg still tracks the metal, it just carries no ledger party.
    worker_id: int | None = None
    metal: Metal = Metal.gold
    # Zero is legal, and only on a leg the worker is supplying the metal for.
    # The router refuses a nothing-issued leg that is not marked that way, so
    # this stays a weight rather than becoming a second flag.
    gold_issued_g: Decimal = Field(default=Decimal("0"), ge=0)
    gold_issued_purity: int | None = Field(default=None, ge=1, le=24)
    # Fineness as the trade quotes it — 99.9, 91.6, 87.5 — and preferred over
    # the karat band above wherever both are sent. Silver is quoted this way
    # only, which is the other reason it exists.
    gold_issued_tunch_pct: Decimal | None = Field(default=None, gt=0, le=100)
    # Not required when nothing is being issued: there is no shelf to take metal
    # off. Required the moment a gram moves, and the router enforces that.
    gold_source_inventory_id: int | None = None
    stones: list[LegStoneIssue] = Field(default_factory=list)
    stone_source_inventory_id: int | None = None
    # Pieces this leg covers — stones to be set, items to be lacquered.
    piece_count: int | None = Field(default=None, ge=0)
    wastage_basis: WastageBasis | None = None
    wastage_per_100_pcs_g: Decimal | None = Field(default=None, ge=0)
    # The percentage deal, stated per job rather than read off the worker.
    # Terms are struck job by job — the same maker works one piece on wastage
    # and the next on a flat per-gram — so the counter has to be able to say so
    # here. Left unset it still falls back to the worker's standing rate, which
    # is what the shop retypes least.
    wastage_allowed_pct: Decimal | None = Field(default=None, ge=0)
    # The maker's deal: ratti of the weight he returns, against a base of 96.
    wastage_ratti: Decimal | None = Field(default=None, ge=0)
    wastage_ratti_base: int = Field(default=DEFAULT_RATTI_BASE, ge=1)
    labour_basis: LabourBasis = LabourBasis.per_gram
    labour_rate: Decimal | None = Field(default=None, ge=0)
    # The piece is being made on the worker's own gold, which the shop will owe
    # back. Separate from a zero issue weight because the shop sometimes issues
    # *part* of the metal and the worker tops the rest up from his own.
    metal_on_credit: bool = False
    metal_due_date: date | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _deal_is_stated(self) -> "LegIssue":
        """
        A ratti figure and a ratti basis have to arrive together.

        Either half alone settles silently and wrongly. A basis with no figure
        allows the maker nothing and charges him the whole difference between
        24k out and 21k back — which is most of the piece. A figure with no
        basis is read against whatever convention the department defaults to
        and is quietly ignored, so the shop believes it granted an allowance it
        did not.
        """
        if self.wastage_basis is WastageBasis.ratti_of_received and self.wastage_ratti is None:
            raise ValueError(
                "This leg settles wastage in ratti, so it needs a ratti figure. "
                "Send wastage_ratti — with none the worker is allowed nothing and "
                "charged for the whole difference between what went out and what came back."
            )
        if self.wastage_ratti is not None and self.wastage_basis not in (
            None,
            WastageBasis.ratti_of_received,
        ):
            raise ValueError(
                f"wastage_ratti was sent on a leg settling by {self.wastage_basis.value}, "
                "where it means nothing. Send wastage_basis=ratti_of_received, or drop the ratti."
            )
        if self.wastage_ratti is not None and self.wastage_ratti > self.wastage_ratti_base:
            raise ValueError(
                f"wastage_ratti ({self.wastage_ratti}) cannot exceed wastage_ratti_base "
                f"({self.wastage_ratti_base}) — the worker would be allowed to keep "
                "everything he returned."
            )
        return self


class LegStoneReturn(BaseModel):
    leg_stone_id: int
    quantity_returned: int = Field(default=0, ge=0)
    weight_returned_ct: Decimal = Field(default=Decimal("0"), ge=0)


class LegReceive(BaseModel):
    """
    What came back, and what it was.

    The purity fields are the correction this release turns on. Pure metal goes
    out to the maker and 21k jewellery comes back; left unstated, the return is
    read as the same metal that went out and is credited as though it were
    pure. Send whichever the scale and the touchstone gave you — they are read
    as a pair, and stating either one means "this is what came back".
    """

    # May exceed what was issued. Solder, alloy and findings are added while the
    # piece is being worked, so a heavier return is routine and rejecting it
    # would push the shop into falsifying the weight to get the leg closed.
    gold_received_g: Decimal = Field(ge=0)
    gold_received_purity: int | None = Field(default=None, ge=1, le=24)
    gold_received_tunch_pct: Decimal | None = Field(default=None, gt=0, le=100)
    # Where the metal lands, for the one leg that has no shelf of its own to go
    # back to: the worker supplied the gold, so nothing was ever taken out of
    # stock and there is no source to return it to. Ignored on every other leg,
    # which puts the metal back where it came from.
    gold_destination_inventory_id: int | None = None
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
    metal: Metal
    issued_at: datetime | None = None
    gold_issued_g: Decimal
    gold_issued_purity: int | None = None
    gold_issued_tunch_pct: Decimal | None = None
    stones_issued_ct: Decimal
    gold_source_inventory_id: int | None = None
    stone_source_inventory_id: int | None = None
    received_at: datetime | None = None
    gold_received_g: Decimal
    gold_received_purity: int | None = None
    gold_received_tunch_pct: Decimal | None = None
    metal_on_credit: bool = False
    metal_due_date: date | None = None
    stones_used_ct: Decimal
    stones_returned_ct: Decimal
    piece_count: int
    # Both settlement terms travel with the leg, not with the department, so a
    # client can show how the allowance below was arrived at long after the
    # department has been retuned.
    wastage_basis: WastageBasis
    wastage_per_100_pcs_g: Decimal | None = None
    wastage_allowed_pct: Decimal | None = None
    wastage_ratti: Decimal | None = None
    wastage_ratti_base: int = DEFAULT_RATTI_BASE
    wastage_allowed_g: Decimal
    wastage_actual_g: Decimal
    wastage_excess_g: Decimal
    # The same three in fine grams, which is where the liability is actually
    # settled once the two ends of the job are different purities. Null on legs
    # closed before that reckoning existed.
    wastage_allowed_fine_g: Decimal | None = None
    wastage_actual_fine_g: Decimal | None = None
    wastage_excess_fine_g: Decimal | None = None
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
    piece_count: int
    wastage_basis: WastageBasis
    wastage_per_100_pcs_g: Decimal | None = None
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
    # Stones set and items lacquered across the piece's route. Kept as a count,
    # not a weight: it is what the per-piece charges and the per-100 wastage
    # allowances were worked out from.
    pieces: int
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
