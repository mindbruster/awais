from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.branch import TransferStatus
from app.schemas.common import ORMModel, TimestampedRead


class BranchCreate(BaseModel):
    code: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = None
    city_id: int | None = None
    is_active: bool = True
    # Promoting a branch to default demotes whichever held it. Sent explicitly
    # rather than inferred, because it changes where every unscoped row lands.
    is_default: bool = False
    # What the shop is called on paper. Blank falls back to `name`.
    letterhead_name: str | None = Field(default=None, max_length=120)
    tagline: str | None = Field(default=None, max_length=160)
    notes: str | None = None


class BranchUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=16)
    name: str | None = Field(default=None, min_length=1, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = None
    city_id: int | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    letterhead_name: str | None = Field(default=None, max_length=120)
    tagline: str | None = Field(default=None, max_length=160)
    notes: str | None = None


class BranchRead(TimestampedRead):
    code: str
    name: str
    phone: str | None = None
    address: str | None = None
    city_id: int | None = None
    city_name: str | None = None
    is_active: bool
    is_default: bool
    letterhead_name: str | None = None
    tagline: str | None = None
    logo_url: str | None = None
    # `letterhead_name or name`, resolved server-side so every document that
    # prints a heading applies the fallback the same way.
    print_name: str = ""
    notes: str | None = None


class Letterhead(ORMModel):
    """
    Who the shop is, as it appears at the top of a printed document.

    Carried on the invoice itself rather than fetched separately, so the
    printable page renders from one response. A bill that draws its heading
    from a second request can print half-formed, and the half that goes missing
    is the shop's own name.
    """

    print_name: str
    tagline: str | None = None
    logo_url: str | None = None
    phone: str | None = None
    address: str | None = None
    city_name: str | None = None


class BranchStock(ORMModel):
    """What a branch is actually holding, for the branch list."""

    branch_id: int
    products_in_stock: int
    gold_g: Decimal
    stone_ct: Decimal


class TransferLineIn(BaseModel):
    """
    One thing going on the van.

    Exactly one of `product_id` and `inventory_item_id`, matching the check
    constraint on the table — a line that names both cannot say what arrived,
    and one that names neither cannot be received at all.
    """

    product_id: int | None = None
    inventory_item_id: int | None = None
    quantity: int = Field(default=0, ge=0)
    weight_g: Decimal = Field(default=Decimal("0"), ge=0)
    weight_ct: Decimal = Field(default=Decimal("0"), ge=0)
    purity: int | None = Field(default=None, ge=1, le=24)
    notes: str | None = None

    @model_validator(mode="after")
    def _one_subject(self) -> "TransferLineIn":
        named = (self.product_id is not None) + (self.inventory_item_id is not None)
        if named != 1:
            raise ValueError(
                "A transfer line names either a finished piece or a stock item, not both and "
                "not neither."
            )
        if self.inventory_item_id is not None and (
            self.weight_g <= 0 and self.weight_ct <= 0 and self.quantity <= 0
        ):
            raise ValueError("A raw stock line has to move some weight or quantity.")
        return self


class TransferCreate(BaseModel):
    from_branch_id: int
    to_branch_id: int
    lines: list[TransferLineIn] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def _distinct_branches(self) -> "TransferCreate":
        if self.from_branch_id == self.to_branch_id:
            raise ValueError("A transfer needs two different branches.")
        return self


class TransferCancel(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class TransferLineRead(TimestampedRead):
    transfer_id: int
    product_id: int | None = None
    product_serial: str | None = None
    product_name: str | None = None
    inventory_item_id: int | None = None
    inventory_label: str | None = None
    quantity: int
    weight_g: Decimal
    weight_ct: Decimal
    purity: int | None = None
    received_inventory_item_id: int | None = None
    notes: str | None = None


class TransferRead(TimestampedRead):
    transfer_no: str
    from_branch_id: int
    from_branch_name: str | None = None
    to_branch_id: int
    to_branch_name: str | None = None
    status: TransferStatus
    sent_at: datetime | None = None
    received_at: datetime | None = None
    sent_by_id: int | None = None
    received_by_id: int | None = None
    notes: str | None = None
    lines: list[TransferLineRead] = Field(default_factory=list)
