from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.sales import SellerKind, TargetScope
from app.schemas.common import TimestampedRead


class SellerBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    # A salesman carries the shop's stock; a broker introduces a buyer and
    # holds nothing. They settle differently, so they are never blended.
    kind: SellerKind = SellerKind.salesman
    phone: str | None = Field(default=None, max_length=30)
    cnic: str | None = Field(default=None, max_length=20)
    commission_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    is_active: bool = True
    notes: str | None = None


class SellerCreate(SellerBase):
    pass


class SellerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    kind: SellerKind | None = None
    phone: str | None = Field(default=None, max_length=30)
    cnic: str | None = Field(default=None, max_length=20)
    commission_pct: Decimal | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None
    notes: str | None = None


class SellerRead(TimestampedRead, SellerBase):
    pass


class SalesTargetCreate(BaseModel):
    """
    A figure to hit over a period, for the company or one party.

    Money and weight are both optional and at least one is required — a target
    with neither is a row that cannot be missed or met.
    """

    scope: TargetScope
    customer_id: int | None = None
    seller_id: int | None = None
    period_start: date
    period_end: date
    label: str | None = Field(default=None, max_length=80)
    target_amount: Decimal | None = Field(default=None, ge=0)
    target_weight_g: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None

    @model_validator(mode="after")
    def coherent(self) -> "SalesTargetCreate":
        if self.period_end < self.period_start:
            raise ValueError(
                "The period ends before it starts, so it measures nothing — every target "
                "set that way would silently report zero."
            )
        if self.target_amount is None and self.target_weight_g is None:
            raise ValueError(
                "A target needs a figure: an amount, a weight, or both. One with neither "
                "cannot be missed or met."
            )
        # The scope decides which party the target belongs to, and naming the
        # wrong one would measure a different party's sales without saying so.
        expected = {
            TargetScope.company: (None, None),
            TargetScope.customer: (self.customer_id, None),
            TargetScope.seller: (None, self.seller_id),
        }[self.scope]
        if self.scope is TargetScope.company and (self.customer_id or self.seller_id):
            raise ValueError("A company target is for the whole shop and names no party.")
        if self.scope is TargetScope.customer and not self.customer_id:
            raise ValueError("A customer target has to say which customer.")
        if self.scope is TargetScope.seller and not self.seller_id:
            raise ValueError("A salesman or broker target has to say which one.")
        if self.scope is TargetScope.customer and self.seller_id:
            raise ValueError("A customer target cannot also name a salesman.")
        if self.scope is TargetScope.seller and self.customer_id:
            raise ValueError("A salesman target cannot also name a customer.")
        del expected
        return self


class SalesTargetRead(TimestampedRead):
    scope: TargetScope
    customer_id: int | None = None
    customer_name: str | None = None
    seller_id: int | None = None
    seller_name: str | None = None
    period_start: date
    period_end: date
    label: str | None = None
    target_amount: Decimal | None = None
    target_weight_g: Decimal | None = None
    notes: str | None = None

    # --- progress, never stored ---
    #
    # Read off the invoices in the period every time, so a target cannot drift
    # from the sales it measures. A cached figure does exactly that the first
    # time a bill is voided.
    actual_amount: Decimal = Decimal("0")
    actual_weight_g: Decimal = Decimal("0")
    invoices: int = 0
    # Null when no figure was set for that half — the shop manages in one or
    # both and a percentage against nothing is not zero, it is meaningless.
    amount_pct: Decimal | None = None
    weight_pct: Decimal | None = None
    # How much of the period has gone. Shown beside the percentages because
    # "60% of target" reads very differently on day three than on day thirty.
    period_elapsed_pct: Decimal | None = None
    last_sale_at: datetime | None = None


# --------------------------------------------------------------------------
# One seller, in full
# --------------------------------------------------------------------------
class SellerCustomerRow(BaseModel):
    """A buyer this seller brought in, and what they were worth."""

    customer_id: int
    customer_name: str
    invoices: int = 0
    revenue: Decimal = Decimal("0")
    gross_margin: Decimal = Decimal("0")
    last_sale_at: datetime | None = None


class SellerInvoiceRow(BaseModel):
    """One bill credited to this seller."""

    invoice_id: int
    invoice_no: str
    issued_at: datetime | None = None
    customer_id: int
    customer_name: str | None = None
    currency: str
    total: Decimal = Decimal("0")
    paid: Decimal = Decimal("0")
    balance_due: Decimal = Decimal("0")
    status: str
    gold_weight_g: Decimal = Decimal("0")
    stone_weight_ct: Decimal = Decimal("0")


class SellerPerformance(BaseModel):
    """
    Everything the shop knows about one salesman or broker.

    Written as one payload rather than five endpoints because the page is read
    top to bottom in one go — a seller's worth is the relationship between his
    revenue, his margin, his collections and his target, and fetching those
    separately would let the screen show four figures from four moments.

    **Revenue is net of tax.** Tax is the government's money passing through;
    counting it would inflate the margin and, worse, the commission.

    **Collections are held apart from sales.** A salesman who writes large
    bills nobody pays is not a good salesman, and a single "sales" figure is
    exactly what hides that. `outstanding` is what is still owed on his bills.
    """

    seller: SellerRead
    date_from: date | None = None
    date_to: date | None = None

    invoices: int = 0
    revenue: Decimal = Decimal("0")
    cost_of_goods: Decimal = Decimal("0")
    gross_margin: Decimal = Decimal("0")
    margin_pct: Decimal | None = None
    # Lines with no product behind them contribute revenue and no cost, so the
    # margin above is overstated by whatever they cost. Surfaced rather than
    # buried — a seller billing mostly typed-in lines has a margin nobody
    # should act on.
    uncosted_lines: int = 0

    collected: Decimal = Decimal("0")
    outstanding: Decimal = Decimal("0")

    gold_weight_g: Decimal = Decimal("0")
    stone_weight_ct: Decimal = Decimal("0")
    average_bill: Decimal = Decimal("0")
    largest_bill: Decimal = Decimal("0")
    first_sale_at: datetime | None = None
    last_sale_at: datetime | None = None

    # What the shop owes him for the period, at his agreed rate. Computed on
    # revenue rather than on collections, and stated as an estimate: nothing in
    # this system posts a commission, so a figure presented as fact would be a
    # liability nobody put in the books.
    commission_pct: Decimal = Decimal("0")
    commission_estimate: Decimal = Decimal("0")

    customers: list[SellerCustomerRow] = []
    recent_invoices: list[SellerInvoiceRow] = []
    targets: list[SalesTargetRead] = []
