import enum
from datetime import date, datetime

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
    text,
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

    # Whose metal this leg is made of.
    #
    # Work does not always start with metal leaving the safe: a maker will make
    # a piece on his own gold and be owed it back. That is not the same event as
    # a piece coming back heavier, which is what solder and findings do and is
    # the shop's own gain — but in raw arithmetic the two look identical, both
    # being "more metal returned than issued". Told apart by this flag rather
    # than guessed from the weights, because guessing wrong either forgives a
    # debt the shop owes or books a worker's gold as free alloy.
    #
    # False on every existing leg, which is what they all were.
    metal_on_credit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # When the shop has to hand that metal over.
    #
    # A promise to *deliver* metal is recorded nowhere else in the system, and
    # one nobody wrote down is one nobody chases. Separate from the flag above
    # because the two are agreed at different moments: the gold arrives today
    # and the date it is owed back may not be settled until later.
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
    rate_per_ct: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
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
        return self.quantity_issued - self.quantity_returned
