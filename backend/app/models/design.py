import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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
from app.models.currency import Currency
from app.models.customer import Customer
from app.models.department import Department
from app.models.item import Item
from app.models.metal import Metal
from app.models.mixins import TimestampMixin
from app.models.stone import Stone
from app.models.vendor import Vendor


class DesignStatus(str, enum.Enum):
    in_production = "in_production"
    stocked = "stocked"
    sold = "sold"
    cancelled = "cancelled"
    # A lot whose metal has come back and been divided into pieces. The lot row
    # stays — it is the dealing with the maker and the ledger entries hang off
    # it — but it is no longer a thing on the floor, and it must never appear
    # in a worklist of pieces still to be made.
    split = "split"


class LegStatus(str, enum.Enum):
    issued = "issued"
    received = "received"
    cancelled = "cancelled"


class LabourBasis(str, enum.Enum):
    per_gram = "per_gram"
    # Charged on the number of pieces handled: stones set, or items lacquered.
    per_piece = "per_piece"
    flat = "flat"


class WastageBasis(str, enum.Enum):
    """
    How the metal a worker may keep is agreed.

    Three conventions are in use and none of them converts into another.

    A percentage of the weight *issued* is what goldsmithing works on. A weight
    per hundred pieces is what setting works on — a setter handling 350 small
    stones loses metal in proportion to how many he sets, not to how heavy the
    piece is, so a percentage would under-charge a light piece carrying many
    stones and over-charge a heavy one carrying few. Ratti of the weight
    *returned* is what the maker works on.

    The reference weight is the part that makes them irreconcilable: two of
    these are measured against what went out and one against what came back,
    and until the job is finished nobody knows the second number. So the basis
    is chosen when the deal is struck and travels on the leg.
    """

    percent_of_issued = "percent_of_issued"
    per_100_pieces = "per_100_pieces"
    # The maker's convention: ratti out of 96, applied to the weight he
    # *returns* rather than the weight he was issued, and added to what he is
    # credited with. Six ratti on 107.560 g allows 6.7225 g. Distinct from a
    # percentage because the reference weight is the other end of the job —
    # a percentage of issued and a ratti of received are not the same number
    # and cannot be converted into one another without knowing the outcome.
    ratti_of_received = "ratti_of_received"


class Design(Base, TimestampMixin):
    """
    A piece, identified from the moment work starts on it.

    This is the spine of the workshop. The old model only minted an identity
    when a job *completed*, so nothing identified a piece while it was moving
    between workers — which is precisely when the shop needs to find it. The
    design number is minted at the first department from the item's
    abbreviation (taka -> TK-00001) and everything downstream is keyed by it.

    `tag_no` is separate and optional: it is the physical label tied on at
    casting, and shops generate it on demand rather than for every piece.
    """

    __tablename__ = "designs"

    id: Mapped[int] = mapped_column(primary_key=True)
    design_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    tag_no: Mapped[str | None] = mapped_column(String(40), unique=True, index=True)

    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    item: Mapped[Item] = relationship(lazy="joined")

    # Who the piece is being made for, when it's a commission rather than stock.
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), index=True
    )
    customer: Mapped[Customer | None] = relationship(lazy="joined")

    current_department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), index=True
    )
    current_department: Mapped[Department | None] = relationship(lazy="joined")

    status: Mapped[DesignStatus] = mapped_column(
        Enum(DesignStatus, name="design_status"),
        nullable=False,
        default=DesignStatus.in_production,
        index=True,
    )

    # --- lots ---
    #
    # Metal does not always leave the safe as one piece. A hundred grams goes to
    # a maker and twelve bangles come back, and until they do there is nothing
    # to number them individually — no weights, and not even a reliable count.
    #
    # So a lot is minted at issue with its own number, `LOT-00001`, and it is
    # what the shop chases while the metal is out. When the maker hands the
    # pieces over, the lot *splits*: one design per piece, each with the weight
    # it actually came back at and its own `TK-00001` number, and each carrying
    # that number through setting, stock and sale.
    #
    # A lot is a Design rather than a table of its own because everything a lot
    # does, a design already does: it takes legs, it holds a worker, it posts to
    # the ledger, it appears on the floor. Splitting it into two models would
    # mean two of each of those, differing only in what the row is called.
    is_lot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    # How many pieces the lot is expected to yield, agreed when the metal goes
    # out. What the maker is actually paid for is the count at receive.
    expected_pieces: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_design_id: Mapped[int | None] = mapped_column(
        ForeignKey("designs.id", ondelete="RESTRICT"), index=True
    )
    # The weight this piece was allotted when its lot was divided, and at what
    # purity. A piece has no leg of its own until it is issued somewhere, so
    # without these there is nothing on the row saying how heavy it is — and
    # the setter's reckoning needs a starting weight.
    piece_weight_g: Mapped[float | None] = mapped_column(Numeric(14, 4))
    piece_purity: Mapped[int | None] = mapped_column(Integer)
    piece_tunch_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))

    image_url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)

    # Set when the piece is stocked and becomes a sellable product.
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )

    legs: Mapped[list["JobLeg"]] = relationship(
        back_populates="design",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="JobLeg.sequence",
    )


class JobLeg(Base, TimestampMixin):
    """
    One visit to one department: material out, material back.

    A leg is deliberately a *pair* of half-transactions on one row rather than
    two rows, because the shop thinks of it as one dealing with one worker —
    "what did I give Zahid and what did he return". Nothing prevents a design
    from visiting the same department twice; legs are ordered by `sequence`,
    not by department.

    Wastage is the reason this table carries so many weight columns. The old
    model stored a single `loss` and conflated three different things: metal
    genuinely burned off, metal the shop has *agreed* the worker may keep, and
    metal the worker owes back. Those have opposite financial consequences, so
    they are separated here and settled explicitly at receive time.
    """

    __tablename__ = "job_legs"

    id: Mapped[int] = mapped_column(primary_key=True)
    design_id: Mapped[int] = mapped_column(
        ForeignKey("designs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    design: Mapped[Design] = relationship(back_populates="legs")

    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    department: Mapped[Department] = relationship(lazy="joined")
    worker_id: Mapped[int | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"), index=True
    )
    worker: Mapped[Vendor | None] = relationship(lazy="joined")

    status: Mapped[LegStatus] = mapped_column(
        Enum(LegStatus, name="leg_status"), nullable=False, default=LegStatus.issued, index=True
    )

    # --- issue side ---
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Which metal this leg is working. Gold unless said otherwise, so every
    # leg written before silver existed reads correctly without being touched.
    # Purity lives in the tunch/karat columns and works the same for both.
    metal: Mapped[Metal] = mapped_column(
        Enum(Metal, name="metal"), nullable=False, default=Metal.gold, index=True
    )
    gold_issued_g: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    gold_issued_purity: Mapped[int | None] = mapped_column(Integer)
    # Fineness in percent, preferred over the karat integer above. Metal goes
    # out to a karigar and comes back short by an agreed wastage; both sides of
    # that reckoning have to be in the same unit the metal was weighed in, or
    # the excess-wastage figure argues with the scale. See
    # `Product.gold_tunch_pct`.
    gold_issued_tunch_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))
    stones_issued_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    gold_source_inventory_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="SET NULL")
    )
    stone_source_inventory_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="SET NULL")
    )

    # --- receive side ---
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # What the scale actually read when the piece came back, stones and all.
    #
    # A setter returns one object. Put it on a gram scale and the number
    # includes the stones he set into it, so it is not the weight of metal and
    # cannot be compared with the metal that was issued. `gold_received_g`
    # below is that figure with the stones taken back out — the two differ by
    # a fifth of the carats set, and on a piece carrying 30ct that is six
    # grams, which is larger than any wastage allowance the shop ever agrees.
    #
    # Both are kept because they answer different questions: the gross is what
    # the counter and the setter both saw and can argue about, and the net is
    # what the reckoning runs on. Storing only the net would leave nothing on
    # the record matching the scale.
    #
    # Equal to `gold_received_g` on legs carrying no stones, which is every
    # maker and lacker leg and every leg written before this column existed.
    gold_received_gross_g: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    # The metal alone: gross less the stones set into the piece.
    gold_received_g: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    # The purity of what came *back*, which is not the purity of what went out.
    #
    # Pure 24k metal goes to the maker and 21k or 18k jewellery comes back. The
    # system used to value the returned weight at the *issued* purity, which
    # credited a 21k piece as though it were pure and overstated the maker's
    # return by about fourteen percent — the shop would believe a job had
    # settled while the metal was still short.
    #
    # Nullable, and read as "same as issued" when absent, so every leg recorded
    # before this column existed keeps computing exactly as it did.
    gold_received_purity: Mapped[int | None] = mapped_column(Integer)
    gold_received_tunch_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))
    stones_used_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    stones_returned_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)

    # Where every issued carat ended up. The four add back to what went out:
    #
    #     issued = set + returned + broken + owed
    #
    # and they are held apart because each has a different consequence. Set
    # carats are in the piece and become its cost. Returned carats are back on
    # the shelf. Broken carats are still the shop's property and still worth
    # something, so they move to their own stock rather than being written off.
    # Owed carats are the setter's debt.
    #
    # The stones inside a finished piece cannot be weighed, so `stones_set_ct`
    # is stated at receive and the rest is reckoned against it. That makes it
    # the one figure here the shop asserts rather than derives, which is why it
    # is worth naming: it is also what the gross weight is netted by.
    stones_set_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    stones_broken_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    stones_owed_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)

    # How many pieces this leg covers — stones to be set, items to be lacquered.
    # Drives both the per-piece charge and, where the department works that way,
    # the wastage allowance.
    piece_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- wastage settlement ---
    # Which convention this leg was agreed under, snapshotted alongside the
    # figures so a department switching conventions later cannot change how an
    # old leg is judged.
    wastage_basis: Mapped[WastageBasis] = mapped_column(
        Enum(WastageBasis, name="wastage_basis"),
        nullable=False,
        default=WastageBasis.percent_of_issued,
    )
    # Grams the worker may keep per hundred pieces handled. Used when
    # wastage_basis is per_100_pieces; the shop states it as e.g. 0.400g/100.
    wastage_per_100_pcs_g: Mapped[float | None] = mapped_column(Numeric(14, 4))
    # How many pieces that figure is quoted against.
    #
    # A hundred is the common case and the reason the column above is named as
    # it is, but the deal is struck in whatever number the two of them argue
    # in — per fifty, per two hundred, per thousand. Hard-coding a hundred made
    # every other quote unrecordable: a shop agreeing 0.400g per 250 had to
    # divide it down by hand and lose the figure it actually shook on.
    #
    # Travels on the leg for the same reason the ratti base does: it is a
    # convention rather than a constant, and an old leg must settle against the
    # deal that was in force when the metal left the safe.
    wastage_pieces_base: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # The allowance agreed with this worker, snapshotted when the material went
    # out. Terms get renegotiated; a leg must be judged against the deal that
    # was in force when the metal left the safe, not today's.
    wastage_allowed_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))
    wastage_allowed_g: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    # issued - received. Negative means the piece came back heavier (solder,
    # alloy, findings), which is normal and must not be treated as a shortfall.
    wastage_actual_g: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    # Only the part beyond the allowance is the worker's liability. This is
    # what gets debited to his gold account.
    wastage_excess_g: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)

    # Ratti of wastage allowed to the maker, against `wastage_ratti_base`.
    #
    # The maker's convention, and a third thing again from the two above. It is
    # worked out on the weight he *returns*, not on what he was issued: six
    # ratti on 107.560 g of finished 21k allows 107.560 / 96 * 6 = 6.7225 g,
    # which is added to what he is credited with. Quoted 1 to 24 against a base
    # of 96, and the base travels on the leg because it is a convention rather
    # than a constant.
    wastage_ratti: Mapped[float | None] = mapped_column(Numeric(6, 3))
    wastage_ratti_base: Mapped[int] = mapped_column(Integer, nullable=False, default=96)

    # The same three figures as above, in *fine* grams.
    #
    # The raw columns compare grams to grams, which only means anything while
    # what went out and what came back are the same purity. Once the maker
    # returns 21k against issued 24k they are different assets and the
    # reckoning has to happen in fine grams or it is subtracting apples from
    # oranges. These carry that reckoning; the raw columns above stay as what
    # the scale actually read.
    #
    # Nullable and never backfilled. A leg written before this existed has
    # nothing here, and the receive path falls back to converting the raw
    # columns exactly as it always did — so no settled job moves.
    wastage_allowed_fine_g: Mapped[float | None] = mapped_column(Numeric(14, 4))
    wastage_actual_fine_g: Mapped[float | None] = mapped_column(Numeric(14, 4))
    wastage_excess_fine_g: Mapped[float | None] = mapped_column(Numeric(14, 4))

    # When the shop has to hand the metal over.
    #
    # Work does not always start with metal leaving the safe: a maker will make
    # a piece on his own gold and be owed the metal back at a date the two of
    # them agree. Nothing else in the system records a promise to *deliver*
    # metal, and a promise nobody wrote down is one nobody chases.
    metal_due_date: Mapped[date | None] = mapped_column(Date, index=True)

    # --- labour ---
    labour_basis: Mapped[LabourBasis] = mapped_column(
        Enum(LabourBasis, name="labour_basis"), nullable=False, default=LabourBasis.per_gram
    )
    labour_rate: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    labour_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    notes: Mapped[str | None] = mapped_column(Text)

    stones: Mapped[list["LegStone"]] = relationship(
        back_populates="leg",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="LegStone.id",
    )


    @property
    def gold_issued_with_stones_g(self) -> Decimal:
        """
        Everything handed over, on one scale, the way the shop says it aloud.

        A setter is given metal and a parcel, and the shop reckons the job as
        one number out against one number back: 100g and 30ct is "106 grams
        given". The settlement below does the same arithmetic from the other
        end — it takes the set stones back out of the returned gross instead of
        adding the issued ones to what went out — and on a job where every
        carat comes back inside the piece the two are the same figure.

        They stop being the same the moment a carat does not come back, and
        that is the point: this is a statement of what left the safe, not an
        input to the metal reckoning. Nothing is settled off it.
        """
        stones_g = (Decimal(str(self.stones_issued_ct or 0)) / Decimal("5"))
        return (Decimal(str(self.gold_issued_g or 0)) + stones_g).quantize(
            Decimal("0.0001")
        )

class LegStone(Base, TimestampMixin):
    """
    An itemised stone line on a setting leg.

    Without this, stone consumption is a single aggregate carat figure and the
    shop cannot answer "how much 12 PTR commercial is left" — which is the
    whole point of the stone stock report. Issued and returned are tracked
    separately in both weight and count because stones are counted, not just
    weighed, and a fixer returning nine of ten stones is a different event from
    returning the same carats in smaller pieces.
    """

    __tablename__ = "leg_stones"

    id: Mapped[int] = mapped_column(primary_key=True)
    leg_id: Mapped[int] = mapped_column(
        ForeignKey("job_legs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    leg: Mapped[JobLeg] = relationship(back_populates="stones")

    stone_id: Mapped[int] = mapped_column(
        ForeignKey("stones.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    stone: Mapped[Stone] = relationship(lazy="joined")

    quantity_issued: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weight_issued_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    quantity_returned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weight_returned_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    # Carats stated to be set into the piece, per material.
    #
    # Per line rather than one figure for the whole leg, because a leg can
    # carry stones from thirty different materials and the three things that
    # happen to the shortfall all need to know *which*. Broken stock has to say
    # what broke or it is a heap of anonymous carats; the setter's debt has to
    # be valued at the rate of the stone he actually lost; and the piece's cost
    # has to draw from the parcel its stones came out of.
    quantity_set: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weight_set_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    # Chipped in the setting and handed back. Still the shop's property and
    # still saleable, so it moves to broken stock at cost rather than being
    # expensed — nothing is lost until it is disposed of.
    quantity_broken: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weight_broken_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    rate_per_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    # What the shop charges the setter per carat he cannot produce, snapshotted
    # at receive. The *selling* rate, not what the parcel cost: a stone lost in
    # setting costs the shop the sale, not merely the purchase, and charging
    # cost would make losing stones free of consequence. Kept on the line
    # because the stone master's rate is editable and re-reading it later would
    # retroactively change what this charge meant.
    owed_rate_per_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    # A rate without its currency is a number, not a price. Both are snapshotted
    # here rather than read back off the stone master, which can be edited — and
    # editing it would otherwise retroactively change what this row meant.
    currency: Mapped[Currency] = mapped_column(
        Enum(Currency, name="currency"), nullable=False, default=Currency.PKR
    )
    # Rupees per unit of `currency` when this row was written. 1 for PKR.
    fx_rate_to_pkr: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=1)

    notes: Mapped[str | None] = mapped_column(Text)

    @property
    def quantity_used(self) -> int:
        """
        Stones that ended up in the piece.

        This is `quantity_set`, not "issued less returned". The two agreed
        while the only question asked at receive was how many came back — but
        once a stone can also be broken or owed, the old formula charges both
        to the piece: a diamond the setter lost would be costed into the
        article as though it were mounted on it, and the same carats would be
        billed to him at the same time.

        Legs settled before that distinction existed were restated in these
        columns by the migration, so this reads correctly for every row.
        """
        return self.quantity_set

    @property
    def weight_used_ct(self):
        """Carats that ended up in the piece — see `quantity_used`."""
        return Decimal(str(self.weight_set_ct or 0))

    @property
    def weight_owed_ct(self):
        """
        Carats the setter can neither show set nor hand back — his debt.

        Derived rather than stored so the identity cannot be broken by an entry
        form: issued is what left, and set, returned and broken are each
        asserted at receive, so what remains is owed by definition. A typed
        fourth figure could disagree with the other three and there would be no
        way to tell which was wrong.
        """
        def dec(v) -> Decimal:
            return Decimal(str(v if v is not None else 0))

        return max(
            dec(self.weight_issued_ct)
            - dec(self.weight_set_ct)
            - dec(self.weight_returned_ct)
            - dec(self.weight_broken_ct),
            Decimal("0"),
        )
