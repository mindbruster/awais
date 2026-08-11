from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.currency import Currency
from app.models.payment import PaymentDirection, PaymentMethod
from app.schemas.common import TimestampedRead


class PaymentCreate(BaseModel):
    """
    Money or metal taken at the counter.

    `amount` is the rupee value whatever the method — a balance has to be one
    number, not two. For a gold exchange it is not accepted from the caller at
    all: the server derives it from weight, purity and the agreed rate so the
    receipt and the journal line cannot disagree.
    """

    customer_id: int
    # Left out for an advance: money taken before the bill exists is normal for
    # a commissioned piece, and forcing an invoice on it would mean inventing
    # one.
    invoice_id: int | None = None
    method: PaymentMethod
    direction: PaymentDirection = PaymentDirection.received
    # What actually came across the counter. A customer can settle a dollar
    # bill in rupees or the other way round, so this is the payment's own
    # currency, not the invoice's.
    currency: Currency = Currency.PKR
    amount: Decimal = Field(default=Decimal("0"), ge=0)

    # Gold exchange only. The rate is PKR per *fine* (24k-equivalent) gram, the
    # same convention the invoice rate uses, so a 22k exchange is not paid for
    # as though it were pure.
    gold_weight_g: Decimal | None = Field(default=None, ge=0)
    gold_purity: int | None = Field(default=None, ge=1, le=24)
    gold_rate_per_g: Decimal | None = Field(default=None, ge=0)

    bank_account_id: int | None = None
    paid_at: datetime | None = None
    reference: str | None = Field(default=None, max_length=120)
    notes: str | None = None

    @model_validator(mode="after")
    def method_carries_its_own_details(self) -> "PaymentCreate":
        if self.method is PaymentMethod.gold_exchange:
            if not self.gold_weight_g or self.gold_weight_g <= 0:
                raise ValueError(
                    "A gold exchange needs the weight taken — that is what is being paid with."
                )
            if self.gold_purity is None:
                raise ValueError(
                    "A gold exchange needs the karat of the metal taken. Without it the "
                    "weight is banked as if it were pure, so 22k credits the customer "
                    "about 9% more than the gold is worth and overstates the shop's metal."
                )
            if not self.gold_rate_per_g or self.gold_rate_per_g <= 0:
                raise ValueError(
                    "A gold exchange needs the rate agreed at the counter. Valuing it later "
                    "at whatever the market has moved to would re-price a settled bill."
                )
        elif self.amount <= 0:
            raise ValueError("Enter the amount taken — a payment of nothing is not a payment.")

        if self.method is PaymentMethod.bank and self.bank_account_id is None:
            raise ValueError(
                "A bank payment has to name the account it landed in, or it cannot be reconciled."
            )
        return self


class PaymentRead(TimestampedRead):
    currency: Currency = Currency.PKR
    fx_rate_to_pkr: Decimal | None = None
    payment_no: str
    invoice_id: int | None = None
    invoice_no: str | None = None
    customer_id: int
    customer_name: str | None = None
    method: PaymentMethod
    direction: PaymentDirection
    amount: Decimal

    gold_weight_g: Decimal | None = None
    gold_purity: int | None = None
    gold_rate_per_g: Decimal | None = None
    # Fine (24k-equivalent) grams — what actually moved in the ledger. Derived
    # server-side so no client has to re-implement the purity conversion.
    gold_fine_g: Decimal | None = None

    bank_account_id: int | None = None
    bank_account_label: str | None = None

    paid_at: datetime
    reference: str | None = None
    notes: str | None = None

    journal_entry_id: int | None = None
    entry_no: str | None = None
    # A reversed payment keeps its row and stops counting. The flag is read off
    # the journal (an entry that reverses this one exists), never stored.
    is_reversed: bool = False


class PaymentReverseRequest(BaseModel):
    """Why the money went back. Recorded on the audit trail, not the row."""

    reason: str | None = None
