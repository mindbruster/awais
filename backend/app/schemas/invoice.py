from decimal import Decimal
from datetime import date, datetime

from pydantic import BaseModel, Field, computed_field, model_validator

from app.models.currency import Currency
from app.models.invoice import GoldCharge, InvoiceKind, InvoiceStatus, SaleType
from app.schemas.branch import Letterhead
from app.schemas.common import TimestampedRead
from app.schemas.payment import PaymentRead
from app.services.pricing import DEFAULT_RATTI_BASE, apply_ratti_discount, apply_sale_wastage


class InvoiceItemCreate(BaseModel):
    product_id: int | None = None
    description: str = Field(min_length=1, max_length=255)
    quantity: int = Field(default=1, ge=1)
    gold_weight_g: Decimal = Field(default=Decimal("0"), ge=0)
    gold_purity: int | None = Field(default=None, ge=1, le=24)
    # Assayed fineness as a percentage — 91.6, 99.5. Wins over the karat above
    # when given, because a karat integer cannot tell 91.6 from 92.0 and
    # between jewellers that difference is money.
    gold_tunch_pct: Decimal | None = Field(default=None, gt=0, le=100)
    gold_rate_per_g: Decimal = Field(default=Decimal("0"), ge=0)
    stone_weight_ct: Decimal = Field(default=Decimal("0"), ge=0)
    stone_rate_per_ct: Decimal = Field(default=Decimal("0"), ge=0)
    labor_amount: Decimal = Field(default=Decimal("0"), ge=0)
    line_discount: Decimal = Field(default=Decimal("0"), ge=0)
    # Ratti discount reduces the billable *gold weight*, not the money — a
    # separate lever from line_discount above, and it stays on the line so the
    # giveaway can be reported on its own.
    discount_ratti: Decimal = Field(default=Decimal("0"), ge=0)
    ratti_base: int = Field(default=DEFAULT_RATTI_BASE, ge=1)
    # Wastage the customer is charged: the shop bills for more gold than the
    # piece contains. The counter quotes it as a percentage or as flat grams
    # depending on what the customer is arguing in, and both can appear on one
    # line, so they are additive rather than exclusive.
    sale_wastage_pct: Decimal = Field(default=Decimal("0"), ge=0)
    sale_wastage_g: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def ratti_within_base(self) -> "InvoiceItemCreate":
        # At the full base the gold is free; beyond it the customer would be
        # credited for metal they are walking out with. Refuse rather than let
        # pricing.py's clamp silently swallow a typo'd figure.
        if self.discount_ratti > self.ratti_base:
            raise ValueError(
                f"discount_ratti ({self.discount_ratti}) cannot exceed "
                f"ratti_base ({self.ratti_base}) — the whole weight would be free."
            )
        return self


class InvoiceItemRead(TimestampedRead, InvoiceItemCreate):
    invoice_id: int
    gold_amount: Decimal
    stone_amount: Decimal
    line_total: Decimal

    # Who the piece is, not just what it cost. `description` is free text typed
    # at the counter and is often just "ring" — it cannot identify anything.
    # These come off the product already eager-joined on the row, so they cost
    # no extra query. Without them a bill cannot be checked against the piece in
    # the box, and a returned item cannot be traced to what it was made from.
    product_name: str | None = None
    product_serial_no: str | None = None
    product_image_url: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def charged_gold_weight_g(self) -> Decimal:
        """The net weight plus the wastage the customer is being billed for."""
        return apply_sale_wastage(
            self.gold_weight_g, self.sale_wastage_pct, self.sale_wastage_g
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def billable_gold_weight_g(self) -> Decimal:
        """
        The weight the money is actually calculated on: marked up by wastage,
        then reduced by the ratti discount — the same order `price_line` uses,
        because applying the percentage to an already-discounted weight would
        quietly shrink the discount the customer was promised.

        Derived here from the one implementation in pricing.py so no client has
        to re-derive the formula (and drift from it).
        """
        return apply_ratti_discount(
            self.charged_gold_weight_g, self.discount_ratti, self.ratti_base
        )


class InvoiceCreate(BaseModel):
    # Which shop this belongs to. Optional: left unset it falls back to the
    # user's own branch, then to the default, so a single-shop business
    # never sees the field and a multi-shop one can be explicit.
    branch_id: int | None = None
    customer_id: int
    sale_type: SaleType = SaleType.normal
    # Who brought the sale — a salesman on the road, or a broker who introduced
    # the buyer. Null on a walk-in, which is most bills.
    seller_id: int | None = None
    # Which of the shop's two bills this is: a finished piece, or a parcel of
    # loose stones. Defaults to the counter's usual so nothing existing changes.
    kind: InvoiceKind = InvoiceKind.finished_product
    currency: Currency = Currency.PKR
    gold_rate_per_g: Decimal = Field(default=Decimal("0"), ge=0)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
    discount_weight_g: Decimal = Field(default=Decimal("0"), ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)
    # The shop's paper bill book runs alongside the system after go-live and
    # the two have to be reconcilable by hand.
    bill_book_no: str | None = Field(default=None, max_length=50)
    # Days of credit. 0 — due on issue — is a counter sale and the common case.
    term_days: int = Field(default=0, ge=0, le=365)
    # Knocked off to reach a round figure. Positive rounds the total down,
    # negative rounds it up — both happen at the counter. Stored as its own
    # figure rather than folded into a discount so the margin report can see it.
    round_off: Decimal = Decimal("0")
    notes: str | None = None
    items: list[InvoiceItemCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def loose_material_sells_no_metal(self) -> "InvoiceCreate":
        """
        A loose-material bill has no gold on it, in any of the three ways gold
        appears.

        Not tidiness. Each of these would put a figure on the wrong bill and
        report it under the wrong lever: a weight makes a parcel of stones look
        like a piece, wastage bills the customer for metal that was never sold,
        and a ratti discount claims a giveaway against gold that is not there —
        the margin report would then show the shop discounting metal on a sale
        that contained none.

        The discount a loose bill argues in is `line_discount`, against the
        stone price, which is exactly what the shop asked for.
        """
        if self.kind is not InvoiceKind.loose_material:
            return self
        for n, item in enumerate(self.items, start=1):
            if item.gold_weight_g:
                raise ValueError(
                    f"Line {n} carries {item.gold_weight_g}g of gold on a loose-material "
                    "bill. Raise a finished-product invoice, or move the metal off the line."
                )
            if item.sale_wastage_pct or item.sale_wastage_g:
                raise ValueError(
                    f"Line {n} charges wastage on a loose-material bill. Wastage is metal "
                    "billed above what a piece contains, and there is no piece here."
                )
            if item.discount_ratti:
                raise ValueError(
                    f"Line {n} discounts in ratti on a loose-material bill. Ratti reduces "
                    "billable gold weight; discount the stone price with line_discount "
                    "instead."
                )
        return self


class InvoiceRead(TimestampedRead):
    invoice_no: str
    sale_type: SaleType
    seller_id: int | None = None
    # Names, so a list does not have to say "#3". Read off the joined records
    # rather than stored, so they cannot fall out of step with the masters.
    seller_name: str | None = None
    kind: InvoiceKind = InvoiceKind.finished_product
    status: InvoiceStatus
    branch_id: int | None = None
    # The heading of the customer's copy: which shop raised this, under the
    # name that shop trades as.
    letterhead: Letterhead | None = None
    customer_id: int
    customer_name: str | None = None
    currency: Currency
    # Rupees per unit of `currency`, snapshotted at issue. NULL on a PKR bill,
    # where the rate is definitionally 1. Exposed so a dollar invoice can show
    # what it was converted at rather than leaving the customer to guess.
    fx_rate_to_pkr: Decimal | None = None
    gold_rate_per_g: Decimal
    # Whether the gold on this bill was sold for money or handed over as metal,
    # snapshotted from the customer when it was raised. `metal_due_fine_g` is
    # what the buyer must hand over, and is zero on a rupee bill where the
    # metal was paid for in money instead.
    gold_charged_in: GoldCharge = GoldCharge.rupees
    metal_due_fine_g: Decimal = Decimal("0")
    subtotal: Decimal
    discount_amount: Decimal
    discount_weight_g: Decimal
    tax_amount: Decimal
    round_off: Decimal
    total: Decimal
    bill_book_no: str | None = None
    # Credit terms in days, and the date they land on. `due_date` is derived
    # from `issued_at + term_days` on the model, so it cannot disagree with
    # them — and it is null until the bill is issued, because a draft has no
    # date to count from.
    term_days: int = 0
    due_date: date | None = None
    issued_at: datetime | None = None
    paid_at: datetime | None = None
    notes: str | None = None
    items: list[InvoiceItemRead] = Field(default_factory=list)


class InvoiceDetail(InvoiceRead):
    """
    One invoice with its settlement worked out.

    `amount_paid` and `balance_due` are summed from the payment rows on every
    read, never stored: a cached figure would have to be maintained by every
    path that takes, reverses or voids money, and the first one that forgets
    leaves a balance nobody can reconcile.
    """

    amount_paid: Decimal
    balance_due: Decimal
    # Rupees this customer owes across everything, from the ledger. Negative
    # means they are in credit — an advance sitting against their account that
    # this bill has not been settled with yet.
    customer_balance: Decimal
    payments: list[PaymentRead] = Field(default_factory=list)
