import enum
from datetime import date, datetime, timedelta

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core import clock
from app.core.database import Base
from app.models.branch import Branch
from app.models.currency import Currency
from app.models.customer import Customer
from app.models.sales import Seller
from app.models.mixins import TimestampMixin
from app.models.product import Product


class SaleType(str, enum.Enum):
    normal = "normal"
    on_approval = "on_approval"


class GoldCharge(str, enum.Enum):
    """
    Whether the gold on a bill is sold for money or handed over as metal.

    `rupees` is the counter sale: the metal is priced at the day's rate and the
    customer settles one figure.

    `grams` is the trade sale: the metal is not priced at all. The bill states
    the fine grams to hand over, and cash is owed only for stones and making.
    Between jewellers the rate is agreed on the day the metal actually moves, so
    printing one when the bill is written would quote a price nobody accepted —
    and billing the gold in rupees as well would charge for it twice.
    """

    rupees = "rupees"
    grams = "grams"


class InvoiceKind(str, enum.Enum):
    """
    Which of the shop's two bills this is.

    They are not one document with some columns blank. A finished piece is
    billed on its metal — weight, purity, wastage, and a discount argued in
    ratti against that weight — with the stones priced alongside. Loose
    material is a parcel of stones and nothing else: no gold column, no
    wastage, and the discount argues against the stone price instead.

    That the discount lands on a different thing is the reason this is a kind
    rather than a print option. A bill that shows a ratti discount on a parcel
    of diamonds is claiming a giveaway on metal that was never sold, and the
    margin report would file it under the wrong lever.
    """

    finished_product = "finished_product"
    loose_material = "loose_material"


class InvoiceStatus(str, enum.Enum):
    draft = "draft"
    issued = "issued"
    paid = "paid"
    returned = "returned"
    void = "void"


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    # Which counter took the sale. Every money report worth reading is sliced
    # by this the moment a second shop opens.
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    branch: Mapped[Branch] = relationship(lazy="joined")

    @property
    def letterhead(self) -> Branch:
        """
        The branch, read as the shop's identity on the customer's copy.

        Named for what the printed document wants rather than what the column
        is, so the read schema can pick it up without the API assembling a
        heading by hand on every path that returns an invoice.
        """
        return self.branch

    sale_type: Mapped[SaleType] = mapped_column(
        Enum(SaleType, name="sale_type"), default=SaleType.normal, nullable=False, index=True
    )
    # Who brought this sale — a salesman on the road or a broker who introduced
    # the buyer. Null on a walk-in, which is most bills. Kept on the invoice
    # rather than derived from the customer: the same customer can be brought
    # in by different people, and a target credited to the wrong one is worse
    # than no target at all.
    seller_id: Mapped[int | None] = mapped_column(
        ForeignKey("sellers.id", ondelete="SET NULL"), index=True
    )
    seller: Mapped["Seller | None"] = relationship(lazy="joined")

    @property
    def seller_name(self) -> str | None:
        """
        Who to credit, by name.

        A property rather than a column: the name lives on the seller record
        and copying it here would leave two versions of it to disagree the
        first time somebody fixes a spelling. Read straight off the joined
        relationship, so the list and the detail cannot show different things.
        """
        return self.seller.name if self.seller else None

    @property
    def customer_name(self) -> str | None:
        """The buyer, by name — the invoice list showed `#3` without this."""
        return self.customer.name if self.customer else None

    # Finished pieces or loose stones. Drives which columns the bill carries and
    # what a discount on it is a discount *on* — see `InvoiceKind`. Snapshotted
    # on the document rather than inferred from whether the lines happen to have
    # gold on them: a finished piece can legitimately be all stone and no metal,
    # and inferring would reclassify it into the wrong bill.
    kind: Mapped[InvoiceKind] = mapped_column(
        Enum(InvoiceKind, name="invoice_kind"),
        default=InvoiceKind.finished_product,
        nullable=False,
        index=True,
    )
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, name="invoice_status"),
        default=InvoiceStatus.draft,
        nullable=False,
        index=True,
    )

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    customer: Mapped[Customer] = relationship(lazy="joined")

    currency: Mapped[Currency] = mapped_column(
        Enum(Currency, name="currency"),
        nullable=False,
        default=Currency.PKR,
        index=True,
    )
    gold_rate_per_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    # Rupees per unit of `currency`, snapshotted when the invoice was issued.
    # NULL on a PKR bill, where the rate is definitionally 1. Held here rather
    # than looked up at read time so a dollar bill keeps the rate it was struck
    # at instead of being revalued every time the rupee moves.
    fx_rate_to_pkr: Mapped[float | None] = mapped_column(Numeric(18, 6))

    # Snapshotted from the customer when the bill is raised, never re-read.
    # A jeweller reclassified as a counter customer next year must not silently
    # turn last year's metal bills into rupee ones — the document has to keep
    # meaning what it meant when it was issued and posted.
    gold_charged_in: Mapped[GoldCharge] = mapped_column(
        Enum(GoldCharge, name="gold_charge"),
        default=GoldCharge.rupees,
        nullable=False,
        index=True,
    )
    # Fine (24k-equivalent) grams the buyer must hand over. Zero on a rupee
    # bill, where the metal was paid for in money instead.
    #
    # Stored rather than derived because it is an obligation the ledger posts
    # against account 1215, and a figure the customer's copy states outright.
    # Recomputing it at read time would let a later edit to a rate or a purity
    # move a debt that both sides already shook hands on.
    metal_due_fine_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)

    subtotal: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    discount_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    discount_weight_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    tax_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    total: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    # The shop's own paper bill book still runs alongside the system for a
    # while after go-live, and the two have to be reconcilable by hand.
    bill_book_no: Mapped[str | None] = mapped_column(String(50), index=True)
    # The difference knocked off to reach a round figure, stored explicitly.
    # A round-off that silently adjusts the total is an untracked discount, and
    # the margin report would never see it.
    round_off: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    # Credit terms, in days from the date of issue. Zero means due on the day —
    # which is a counter sale, and is why it is the default. Trade customers
    # take 30 or 60, and the bill has to say which, or the shop is chasing a
    # payment against a date only one side of the conversation knows.
    term_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    notes: Mapped[str | None] = mapped_column(Text)

    @property
    def due_date(self) -> date | None:
        """
        When the money is due. Derived, never stored: a stored copy would go
        stale the moment the terms or the issue date were corrected, and a bill
        that shows two different due dates is worse than one that shows none.
        """
        if self.issued_at is None:
            return None
        return clock.shop_date(self.issued_at) + timedelta(days=int(self.term_days or 0))

    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin",
        # Ordered explicitly. Without it Postgres is free to return the lines in
        # any order it likes, and it does change — so the same bill could print
        # with its lines shuffled between two viewings, and the serial number
        # down the left would number them differently each time.
        order_by="InvoiceItem.id",
    )


class InvoiceItem(Base, TimestampMixin):
    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice: Mapped[Invoice] = relationship(back_populates="items")

    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    product: Mapped[Product | None] = relationship(lazy="joined")

    description: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    gold_weight_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    gold_purity: Mapped[int | None] = mapped_column(Integer)
    # Fineness in percent — 91.6, 99.5. Preferred over the karat integer above
    # wherever it is set; see `Product.gold_tunch_pct` for why both exist.
    gold_tunch_pct: Mapped[float | None] = mapped_column(Numeric(6, 3))
    gold_rate_per_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    gold_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    stone_weight_ct: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    stone_rate_per_ct: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    stone_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    labor_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    # Per-line discount expressed in the invoice's currency. Subtracted from
    # (gold + stone + labor) before line_total. Capped to never go negative.
    line_discount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    # Discount quoted the way the counter negotiates it — in ratti, against a
    # base of 96. Six ratti bills 90/96 of the gold weight. It reduces billable
    # metal rather than the money, which is a different lever from
    # `line_discount` and has to be visible as its own giveaway in reporting.
    discount_ratti: Mapped[float] = mapped_column(Numeric(8, 3), default=0, nullable=False)
    ratti_base: Mapped[int] = mapped_column(Integer, default=96, nullable=False)

    # Wastage charged to the customer: the shop bills for more gold than the
    # piece contains. This is revenue and one of the three margin levers in the
    # trade, alongside the rate spread and making charges — so it is stored as
    # its own figure rather than folded into the weight, or the profit report
    # cannot show where the money actually came from. Quoted either way round;
    # the counter picks whichever the customer is arguing in.
    sale_wastage_pct: Mapped[float] = mapped_column(Numeric(6, 3), default=0, nullable=False)
    sale_wastage_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    # Read through to the piece, so a bill can say which one it is rather than
    # only what it cost. Read live rather than snapshotted on purpose: a
    # photograph and a serial identify a physical object that still exists, and
    # if the shop replaces a bad photo the old bill should show the good one.
    # The money columns above are the opposite — those are snapshots and must
    # never move. `product` is eager-joined, so none of these cost a query.
    @property
    def product_name(self) -> str | None:
        return self.product.name if self.product else None

    @property
    def product_serial_no(self) -> str | None:
        return self.product.serial_no if self.product else None

    @property
    def product_image_url(self) -> str | None:
        return self.product.image_url if self.product else None
