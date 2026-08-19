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
    # Mint a lot rather than a piece.
    #
    # Metal that goes to a maker as one hundred grams and comes back as twelve
    # bangles has nothing to number individually until it comes back — no
    # weights, and often not even a firm count. A lot carries the job while the
    # metal is out and divides into pieces at receive.
    as_lot: bool = False
    # What the lot is expected to yield, agreed when the metal goes out.
    expected_pieces: int | None = Field(default=None, ge=1)
    notes: str | None = None

    @model_validator(mode="after")
    def pieces_belong_to_lots(self) -> "DesignCreate":
        if self.expected_pieces is not None and not self.as_lot:
            raise ValueError(
                "expected_pieces only means something on a lot. A design is one piece; "
                "send as_lot=true to mint a lot that will divide into several."
            )
        return self


class LotPiece(BaseModel):
    """One piece coming out of a lot, as it came off the scale."""

    weight_g: Decimal = Field(gt=0)
    # The purity the maker returned. Carried onto the piece so the next
    # department is issued a weight that knows what it is made of.
    purity: int | None = Field(default=None, ge=1, le=24)
    tunch_pct: Decimal | None = Field(default=None, gt=0, le=100)
    customer_id: int | None = None
    notes: str | None = None


class LotSplit(BaseModel):
    """
    Divide a received lot into the pieces the maker actually handed over.

    Every piece is weighed individually rather than the lot weight being spread
    evenly. An average would put the same number on twelve rows that differ by
    a gram each way, and from then on every piece's cost, price and wastage
    would be worked out from a weight it never had.
    """

    pieces: list[LotPiece] = Field(min_length=1)


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
    # Which metal goes out. Gold unless said otherwise.
    metal: Metal = Metal.gold
    # Zero is a real deal, not an empty field: a maker will make a piece on his
    # own gold and be owed the metal back on a date the two of them agree.
    # Nothing leaves the safe, nothing posts at issue, and the obligation
    # appears when he hands the piece over.
    gold_issued_g: Decimal = Field(ge=0)
    # Karat, and therefore gold only — the scale stops at 24. Silver states its
    # purity as a fineness in `gold_issued_tunch_pct`, where 925 is 92.5.
    gold_issued_purity: int | None = Field(default=None, ge=1, le=24)
    gold_issued_tunch_pct: Decimal | None = Field(default=None, gt=0, le=100)
    gold_source_inventory_id: int
    stones: list[LegStoneIssue] = Field(default_factory=list)
    stone_source_inventory_id: int | None = None
    # Pieces this leg covers — stones to be set, items to be lacquered.
    piece_count: int | None = Field(default=None, ge=0)
    wastage_basis: WastageBasis | None = None
    wastage_per_100_pcs_g: Decimal | None = Field(default=None, ge=0)
    # How many pieces that figure is quoted against. A hundred is the common
    # case and never the only one — deals are struck per 50, per 250, per 1000.
    wastage_pieces_base: int | None = Field(default=None, ge=1)
    # The maker's allowance, quoted 1 to 24 against a base of 96. Bounded at
    # the base rather than left open: a ratti figure at or above its base
    # allows the entire returned weight, which is not a generous deal but a
    # typo, and one that would forgive a kilo as readily as a gram.
    wastage_ratti: Decimal | None = Field(default=None, ge=0)
    wastage_ratti_base: int = Field(default=DEFAULT_RATTI_BASE, ge=1)
    labour_basis: LabourBasis = LabourBasis.per_gram
    labour_rate: Decimal | None = Field(default=None, ge=0)
    # When the shop owes the maker metal rather than the other way round: he
    # works on his own gold and is repaid by this date. Recorded at issue
    # because a promise nobody wrote down is one nobody chases.
    metal_due_date: date | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def ratti_within_base(self) -> "LegIssue":
        if self.wastage_ratti is not None and self.wastage_ratti >= self.wastage_ratti_base:
            raise ValueError(
                f"wastage_ratti ({self.wastage_ratti}) must be below wastage_ratti_base "
                f"({self.wastage_ratti_base}) — at or above it the whole returned weight "
                "would be allowed as wastage."
            )
        return self

    @model_validator(mode="after")
    def no_metal_issued_needs_a_ratti_and_a_date(self) -> "LegIssue":
        """
        A leg that issues nothing is the maker working on his own gold, and two
        things have to be true or the shop gets his metal for free.

        **It has to settle in ratti.** Under a percentage or a per-100 figure
        the excess floors at zero — those conventions are caps on what a worker
        can be *charged*, and there is no such thing as being charged a negative
        amount. Issue nothing under one of them and the piece he hands over is
        credited to nobody: the metal arrives, the books balance, and he is owed
        not one gram of it. Only the maker's ratti is signed, because only there
        is the allowance an entitlement rather than a cap.

        **It has to carry a due date.** This is the one case where the shop owes
        the metal rather than holding it, and a promise nobody wrote down is one
        nobody chases.
        """
        if self.gold_issued_g == 0:
            if self.wastage_basis is not WastageBasis.ratti_of_received:
                raise ValueError(
                    "A leg that issues no metal is the maker working on his own gold, so it "
                    "must settle in ratti of what he returns. Under any other convention the "
                    "shop would be credited with his metal and owe him nothing for it."
                )
            if self.metal_due_date is None:
                raise ValueError(
                    "This leg issues no metal, so the shop will owe it back. Send "
                    "metal_due_date — an obligation with no date on it is one nobody chases."
                )
        return self

    @model_validator(mode="after")
    def silver_states_its_fineness(self) -> "LegIssue":
        """
        Silver cannot be left to the karat fallback.

        Fine weight is worked out from the tunch when there is one and from
        `purity / 24` when there is not. On silver that fallback is not merely
        imprecise, it is a different scale: 999 silver left blank would be read
        as 24-karat and valued as pure, and 925 cannot be written on the karat
        scale at all. So the fineness is required rather than defaulted, and
        the karat is refused outright — there is no such thing as 21k silver.
        """
        if self.metal is Metal.silver:
            if self.gold_issued_purity is not None:
                raise ValueError(
                    "Silver is quoted as a fineness out of a thousand, not in karat. "
                    "Send gold_issued_tunch_pct (92.5 for 925, 99.9 for 999) and leave "
                    "gold_issued_purity unset."
                )
            if self.gold_issued_tunch_pct is None:
                raise ValueError(
                    "A silver leg must state its fineness. Send gold_issued_tunch_pct — "
                    "99.9 for the pure silver the shop buys, 92.5 for 925."
                )
        return self


class LegStoneReturn(BaseModel):
    """
    What became of one material's stones, stated at receive.

    Three of the four outcomes are declared and the fourth — what the setter
    owes — is what is left over. Asking for all four would let the line
    disagree with itself.
    """

    leg_stone_id: int
    # Set into the piece. Stated rather than weighed, because stones inside a
    # finished article cannot be put on a scale, and the gross weight alone
    # leaves two unknowns in one equation.
    quantity_set: int = Field(default=0, ge=0)
    weight_set_ct: Decimal = Field(default=Decimal("0"), ge=0)
    # Handed back whole, and going back on the shelf.
    quantity_returned: int = Field(default=0, ge=0)
    weight_returned_ct: Decimal = Field(default=Decimal("0"), ge=0)
    # Chipped in the setting and handed back. Goes to broken stock at cost.
    quantity_broken: int = Field(default=0, ge=0)
    weight_broken_ct: Decimal = Field(default=Decimal("0"), ge=0)


class LegReceive(BaseModel):
    """
    Take the piece back.

    `gold_received_g` is what the scale reads — the whole object, stones and
    all. The metal alone is worked out from it by taking the set stones back
    out at five carats to the gram, and both figures are kept: the gross is
    what the counter and the worker both saw, the net is what the reckoning
    runs on. On a leg carrying no stones they are the same number.
    """

    # May exceed what was issued. Solder, alloy and findings are added while the
    # piece is being worked, so a heavier return is routine and rejecting it
    # would push the shop into falsifying the weight to get the leg closed.
    gold_received_g: Decimal = Field(ge=0)
    # How many stones were set. Drives the wastage allowance on a per-100 leg
    # and the per-piece charge, so it is stated at receive alongside the rest.
    # Omitted leaves the count agreed at issue in place.
    piece_count: int | None = Field(default=None, ge=0)
    # The purity of what came *back*, which is the whole point of the maker
    # stage: pure metal goes out and 21k jewellery returns. Omitted means "the
    # same as went out", which is right for setting and lacker legs where the
    # piece is handed over and handed back unchanged in karat.
    gold_received_purity: int | None = Field(default=None, ge=1, le=24)
    # The assayed fineness, when the piece was tested rather than taken at its
    # nominal karat. Wins over the karat above wherever it is present — 21k
    # that assays at 86.5 is not 87.5, and on a kilo that is ten fine grams.
    gold_received_tunch_pct: Decimal | None = Field(default=None, gt=0, le=100)
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
    quantity_set: int
    weight_set_ct: Decimal
    quantity_returned: int
    weight_returned_ct: Decimal
    quantity_broken: int
    weight_broken_ct: Decimal
    # Derived: issued less set, returned and broken. The setter's debt.
    weight_owed_ct: Decimal
    quantity_used: int
    rate_per_ct: Decimal
    owed_rate_per_ct: Decimal
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
    metal: Metal = Metal.gold
    gold_issued_g: Decimal
    gold_issued_purity: int | None = None
    gold_issued_tunch_pct: Decimal | None = None
    stones_issued_ct: Decimal
    # Metal and stones on one scale — what the shop says it handed over. A
    # statement, not an input: the settlement never reads it.
    gold_issued_with_stones_g: Decimal
    gold_source_inventory_id: int | None = None
    stone_source_inventory_id: int | None = None
    received_at: datetime | None = None
    # What the scale read, stones and all, and the metal left once the set
    # stones are taken back out. Equal on a leg carrying no stones.
    gold_received_gross_g: Decimal
    gold_received_g: Decimal
    gold_received_purity: int | None = None
    gold_received_tunch_pct: Decimal | None = None
    # Where every issued carat went: set + returned + broken + owed = issued.
    stones_set_ct: Decimal
    stones_used_ct: Decimal
    stones_returned_ct: Decimal
    stones_broken_ct: Decimal
    stones_owed_ct: Decimal
    piece_count: int
    # Every settlement term travels with the leg, not with the department, so a
    # client can show how the allowance below was arrived at long after the
    # department has been retuned.
    wastage_basis: WastageBasis
    wastage_per_100_pcs_g: Decimal | None = None
    wastage_pieces_base: int = 100
    wastage_allowed_pct: Decimal | None = None
    wastage_ratti: Decimal | None = None
    wastage_ratti_base: int = DEFAULT_RATTI_BASE
    wastage_allowed_g: Decimal
    wastage_actual_g: Decimal
    wastage_excess_g: Decimal
    # The same three in fine grams, which is the reckoning that actually
    # settled. The raw trio above is what the scale read; once a maker returns
    # 21k against issued 24k the two are different assets and only these can be
    # subtracted from one another. A negative excess means the shop owes him.
    wastage_allowed_fine_g: Decimal | None = None
    wastage_actual_fine_g: Decimal | None = None
    wastage_excess_fine_g: Decimal | None = None
    metal_due_date: date | None = None
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
    is_lot: bool = False
    expected_pieces: int = 0
    parent_design_id: int | None = None
    parent_design_no: str | None = None
    piece_weight_g: Decimal | None = None
    piece_purity: int | None = None
    piece_tunch_pct: Decimal | None = None
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
    weight_broken_ct: Decimal = Decimal("0")
    weight_owed_ct: Decimal = Decimal("0")
    # What went into the piece. Not "issued less returned" — a stone broken or
    # owed left stock too, but it is not on the article.
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
    # The same three in fine grams, and the only version of them that can
    # honestly be summed. A piece goes to a maker at 24k and to a setter at
    # 21k; adding those raw adds grams of two different assets.
    wastage_allowed_fine_g: Decimal = Decimal("0")
    wastage_actual_fine_g: Decimal = Decimal("0")
    wastage_excess_fine_g: Decimal = Decimal("0")
    stones_issued_ct: Decimal
    stones_used_ct: Decimal
    stones_returned_ct: Decimal
    stones_broken_ct: Decimal = Decimal("0")
    stones_owed_ct: Decimal = Decimal("0")
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
