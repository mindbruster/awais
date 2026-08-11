from decimal import Decimal
from datetime import datetime

from pydantic import BaseModel, Field, computed_field, model_validator

from app.models.currency import Currency
from app.models.invoice import InvoiceStatus, SaleType
from app.schemas.common import TimestampedRead
from app.schemas.payment import PaymentRead
from app.services.pricing import DEFAULT_RATTI_BASE, apply_ratti_discount, apply_sale_wastage


class InvoiceItemCreate(BaseModel):
    product_id: int | None = None
    description: str = Field(min_length=1, max_length=255)
    quantity: int = Field(default=1, ge=1)
    gold_weight_g: Decimal = Field(default=Decimal("0"), ge=0)
    gold_purity: int | None = Field(default=None, ge=1, le=24)
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
    customer_id: int
    sale_type: SaleType = SaleType.normal
    currency: Currency = Currency.PKR
    gold_rate_per_g: Decimal = Field(default=Decimal("0"), ge=0)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
    discount_weight_g: Decimal = Field(default=Decimal("0"), ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)
    # The shop's paper bill book runs alongside the system after go-live and
    # the two have to be reconcilable by hand.
    bill_book_no: str | None = Field(default=None, max_length=50)
    # Knocked off to reach a round figure. Positive rounds the total down,
    # negative rounds it up — both happen at the counter. Stored as its own
    # figure rather than folded into a discount so the margin report can see it.
    round_off: Decimal = Decimal("0")
    notes: str | None = None
    items: list[InvoiceItemCreate] = Field(default_factory=list)


class InvoiceRead(TimestampedRead):
    invoice_no: str
    sale_type: SaleType
    status: InvoiceStatus
    customer_id: int
    currency: Currency
    # Rupees per unit of `currency`, snapshotted at issue. NULL on a PKR bill,
    # where the rate is definitionally 1. Exposed so a dollar invoice can show
    # what it was converted at rather than leaving the customer to guess.
    fx_rate_to_pkr: Decimal | None = None
    gold_rate_per_g: Decimal
    subtotal: Decimal
    discount_amount: Decimal
    discount_weight_g: Decimal
    tax_amount: Decimal
    round_off: Decimal
    total: Decimal
    bill_book_no: str | None = None
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
