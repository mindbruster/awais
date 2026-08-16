"""
Buying: bullion from a dealer, metal back over the counter, stones from
suppliers.

Money and weights are `Decimal` end to end — Pydantic serialises them as
strings, so the browser never sees a float that has already lost paisas.
"""
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.currency import Currency
from app.models.purchase import GoldKind, GoldPaymentMode
from app.models.stone import StoneCategory, StoneKind
from app.schemas.common import ORMModel, TimestampedRead


# --------------------------------------------------------------------------
# Suppliers
# --------------------------------------------------------------------------
class SupplierBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = None
    # What the shop already owed this supplier at go-live. It sits here until
    # the ledger's opening-balance run moves it into the books; nothing here
    # posts it, because a master record is not a journal.
    opening_balance: Decimal = Decimal("0")
    is_active: bool = True
    notes: str | None = None


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = None
    opening_balance: Decimal | None = None
    is_active: bool | None = None
    notes: str | None = None


class SupplierRead(TimestampedRead, SupplierBase):
    pass


# --------------------------------------------------------------------------
# Old gold
# --------------------------------------------------------------------------
class OldGoldCreate(BaseModel):
    """
    A buy-back at the counter.

    `rate_per_g` has no default on purpose. The shop buys below the day's rate
    and that spread is the entire margin on the transaction, so a rate that
    quietly fell back to the market number would book the purchase at zero
    profit and nobody would ever see it happen.
    """
    # Which shop this belongs to. Optional: left unset it falls back to the
    # user's own branch, then to the default, so a single-shop business
    # never sees the field and a multi-shop one can be explicit.
    branch_id: int | None = None

    customer_id: int | None = None
    walk_in_name: str | None = Field(default=None, max_length=150)
    kind: GoldKind = GoldKind.used
    weight_g: Decimal = Field(gt=0)
    # Optional only for pure metal, which is taken as 24k. Used jewellery must
    # state what it assays at — see the validator.
    purity: int | None = Field(default=None, ge=1, le=24)
    rate_per_g: Decimal = Field(gt=0)
    purchased_at: datetime | None = None
    # Paying at or above the day's rate is a loss, not a purchase, so it is
    # refused unless the counter says it meant it.
    allow_above_market: bool = False
    notes: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "OldGoldCreate":
        if self.customer_id is None and not (self.walk_in_name or "").strip():
            raise ValueError(
                "Record who the metal came from: pick a customer or type a walk-in name."
            )
        if self.kind is GoldKind.used and self.purity is None:
            raise ValueError(
                "Used gold needs a purity — it is what the price was struck on, and the "
                "ledger holds fine grams, so booking it as pure would overstate the shop's "
                "metal by the alloy."
            )
        return self


class OldGoldRead(TimestampedRead):
    purchase_no: str
    customer_id: int | None = None
    customer_name: str | None = None
    walk_in_name: str | None = None
    seller_name: str
    kind: GoldKind
    weight_g: Decimal
    purity: int | None = None
    rate_per_g: Decimal
    amount: Decimal
    # 24k-equivalent grams, and what the shop actually paid per one of them.
    # Derived on read rather than stored: the inputs are on the row, and a
    # stored copy is one more thing that can disagree with them.
    fine_weight_g: Decimal
    effective_rate_per_fine_g: Decimal
    inventory_item_id: int | None = None
    journal_entry_id: int | None = None
    journal_entry_no: str | None = None
    # A reversal is a new entry pointing back at the original, so "was this
    # undone" is a question for the journal, never a flag on this row.
    is_reversed: bool = False
    reversal_entry_no: str | None = None
    purchased_at: datetime
    notes: str | None = None


# --------------------------------------------------------------------------
# Stone purchases
# --------------------------------------------------------------------------
class StonePurchaseItemCreate(BaseModel):
    """
    One graded lot on the bill.

    The grading fields are snapshots. Leave them out and the stone master's own
    grading is copied in at save time — never read live afterwards, because a
    shop that renames a grade next year must not rewrite what last year's bill
    says it bought.
    """

    stone_id: int
    quantity: int = Field(default=0, ge=0)
    weight_ct: Decimal = Field(gt=0)
    rate_per_ct: Decimal = Field(default=Decimal("0"), ge=0)
    quality: str | None = Field(default=None, max_length=60)
    cut: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=40)
    clarity: str | None = Field(default=None, max_length=40)
    notes: str | None = None


class StonePurchaseCreate(BaseModel):
    # Which shop this belongs to. Optional: left unset it falls back to the
    # user's own branch, then to the default, so a single-shop business
    # never sees the field and a multi-shop one can be explicit.
    branch_id: int | None = None
    supplier_id: int
    purchased_at: datetime | None = None
    reference: str | None = Field(default=None, max_length=120)
    # Freight, certification, the supplier's loading — quoted as a percentage
    # on the subtotal, which is how these bills arrive.
    extra_cost_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    items: list[StonePurchaseItemCreate] = Field(min_length=1)
    notes: str | None = None


class StonePurchaseItemRead(TimestampedRead):
    purchase_id: int
    stone_id: int
    stone_name: str | None = None
    quantity: int
    weight_ct: Decimal
    rate_per_ct: Decimal
    amount: Decimal
    quality: str | None = None
    cut: str | None = None
    color: str | None = None
    clarity: str | None = None
    inventory_item_id: int | None = None
    notes: str | None = None


class StonePurchaseRead(TimestampedRead):
    purchase_no: str
    supplier_id: int
    supplier_name: str | None = None
    purchased_at: datetime
    reference: str | None = None
    subtotal: Decimal
    extra_cost_pct: Decimal
    extra_cost_amount: Decimal
    total: Decimal
    item_count: int
    total_weight_ct: Decimal
    journal_entry_id: int | None = None
    journal_entry_no: str | None = None
    notes: str | None = None


class StonePurchaseDetail(StonePurchaseRead):
    items: list[StonePurchaseItemRead] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Stone stock
# --------------------------------------------------------------------------
class StoneStockRow(ORMModel):
    stone_id: int
    stone_name: str
    stone_kind: StoneKind
    category: StoneCategory
    abbreviation: str | None = None
    quality: str | None = None
    cut: str | None = None
    color: str | None = None
    clarity: str | None = None

    purchased_quantity: int
    purchased_weight_ct: Decimal
    purchased_value: Decimal
    avg_rate_per_ct: Decimal

    used_quantity: int
    used_weight_ct: Decimal

    available_quantity: int
    available_weight_ct: Decimal


class StoneStockReport(ORMModel):
    date_from: date | None = None
    date_to: date | None = None
    category: StoneCategory | None = None
    quality: str | None = None
    cut: str | None = None
    clarity: str | None = None
    rows: list[StoneStockRow] = Field(default_factory=list)
    total_purchased_weight_ct: Decimal
    total_used_weight_ct: Decimal
    total_available_weight_ct: Decimal


# --------------------------------------------------------------------------
# Gold purchases (from a dealer)
# --------------------------------------------------------------------------
class GoldPurchaseItemCreate(BaseModel):
    """
    One lot on the dealer's bill: a bar, or a parcel of one purity.

    `rate_per_g` is quoted against the actual weight, the way the trade quotes
    it. The fine-gram conversion happens once, server-side, from `purity` — so
    nothing on the counter has to do karat arithmetic to fill this in.
    """

    description: str | None = Field(default=None, max_length=150)
    purity: int = Field(ge=1, le=24)
    weight_g: Decimal = Field(gt=0)
    rate_per_g: Decimal = Field(ge=0)
    notes: str | None = None


class GoldPurchaseCreate(BaseModel):
    # Which shop this belongs to. Optional: left unset it falls back to the
    # user's own branch, then to the default, so a single-shop business never
    # sees the field and a multi-shop one can be explicit.
    branch_id: int | None = None
    supplier_id: int
    purchased_at: datetime | None = None
    reference: str | None = Field(default=None, max_length=120)
    # What the dealer quoted in. Anything but rupees needs an exchange rate on
    # record for the day, or the bill is refused rather than booked at 1.
    currency: Currency = Currency.PKR
    # How it was paid. `cash` is the default because it is the common case at a
    # small shop; `credit` is what puts the bill on the supplier's account.
    payment_mode: GoldPaymentMode = GoldPaymentMode.cash
    bank_account_id: int | None = None
    # Carriage, assay, the dealer's loading — quoted as a percentage on the
    # subtotal, which is how these bills arrive.
    extra_cost_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    items: list[GoldPurchaseItemCreate] = Field(min_length=1)
    notes: str | None = None


class GoldPurchaseItemRead(TimestampedRead):
    purchase_id: int
    description: str | None = None
    purity: int
    weight_g: Decimal
    rate_per_g: Decimal
    currency: Currency
    fx_rate_to_pkr: Decimal
    amount: Decimal
    # 24k-equivalent grams. Derived on read rather than stored: the inputs are
    # on the row, and a stored copy is one more thing that can disagree.
    fine_weight_g: Decimal
    inventory_item_id: int | None = None
    notes: str | None = None


class GoldPurchaseRead(TimestampedRead):
    purchase_no: str
    supplier_id: int
    supplier_name: str | None = None
    branch_id: int
    branch_name: str | None = None
    purchased_at: datetime
    reference: str | None = None
    payment_mode: GoldPaymentMode
    bank_account_id: int | None = None
    subtotal: Decimal
    extra_cost_pct: Decimal
    extra_cost_amount: Decimal
    total: Decimal
    item_count: int
    total_weight_g: Decimal
    total_fine_g: Decimal
    # What the metal actually cost per fine gram once loading is in. This is
    # the number to compare against the day's rate — the quoted rate per gram
    # is not, because it is against gross weight and excludes carriage.
    effective_rate_per_fine_g: Decimal
    journal_entry_id: int | None = None
    journal_entry_no: str | None = None
    # A reversal is a new entry pointing back at the original, so "was this
    # undone" is a question for the journal, never a flag on this row.
    is_reversed: bool = False
    reversal_entry_no: str | None = None
    notes: str | None = None


class GoldPurchaseDetail(GoldPurchaseRead):
    items: list[GoldPurchaseItemRead] = Field(default_factory=list)
