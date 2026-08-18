from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.inventory import InventoryType
from app.schemas.common import TimestampedRead


class InventoryItemBase(BaseModel):
    type: InventoryType
    label: str = Field(min_length=1, max_length=150)
    location: str | None = Field(default=None, max_length=100)
    # Present on the *read* shape because a caller needs to see what a pot
    # holds. Absent from create and update — see `InventoryItemCreate`.
    quantity: int = Field(default=0, ge=0)
    weight_g: Decimal = Field(default=Decimal("0"), ge=0)
    weight_ct: Decimal = Field(default=Decimal("0"), ge=0)
    # Karat, and therefore gold only — the scale stops at 24.
    purity: int | None = Field(default=None, ge=1, le=24)
    # Fineness as a percentage of pure, which is the only scale that describes
    # both metals: 999 silver is 99.9 and cannot be written as a karat at all.
    # Without it a silver row carries no purity, and every report that values
    # stock reads the blank as pure — a kilo of silver priced as a kilo of
    # fine gold.
    tunch_pct: Decimal | None = Field(default=None, gt=0, le=100)
    product_id: int | None = None


class InventoryItemCreate(BaseModel):
    """
    Open a container — a melt pot, a stone packet — and nothing more.

    **A quantity cannot be set here, and that is the whole point.** This
    endpoint used to accept `weight_g`, write it straight onto the row, and post
    neither a stock movement nor a journal entry. Metal could be typed into
    existence and the books never heard about it: on the development database
    that left 1,195 fine grams of gold in the pots that 1130 Gold in Hand had
    never seen, and a "what is the business worth" figure that differed by a
    hundred and twenty million rupees depending on which table it read.

    It is also the one rule the rest of this system is built on, and the guide
    states it outright: 100 g does not simply become 95 g without a recorded
    reason. Every other balance here — cash, metal, a worker's account — moves
    only because a document moved it.

    So a pot starts empty and fills through documents: a purchase, a job leg
    coming back, a branch transfer, a stock count. Go-live stock that predates
    the system has its own path, `POST /inventory/{id}/opening`, which posts
    both halves.
    """

    type: InventoryType
    label: str = Field(min_length=1, max_length=150)
    location: str | None = Field(default=None, max_length=100)
    purity: int | None = Field(default=None, ge=1, le=24)
    tunch_pct: Decimal | None = Field(default=None, gt=0, le=100)
    product_id: int | None = None
    # Which shop this belongs to. Optional: left unset it falls back to the
    # user's own branch, then to the default, so a single-shop business
    # never sees the field and a multi-shop one can be explicit.
    branch_id: int | None = None


class InventoryItemUpdate(BaseModel):
    """
    Rename a pot, move it, restate its purity. Never change what is in it.

    `weight_g`, `weight_ct` and `quantity` are deliberately absent. They were
    settable, wrote straight to the row, and posted nothing — which is how a
    balance changes with nobody's name on it and no entry behind it. To correct
    what a pot holds, count it: `/reconciliation` posts a movement and a journal
    entry with a reason attached, which is the same correction made honestly.
    """

    type: InventoryType | None = None
    label: str | None = Field(default=None, min_length=1, max_length=150)
    location: str | None = Field(default=None, max_length=100)
    purity: int | None = Field(default=None, ge=1, le=24)
    tunch_pct: Decimal | None = Field(default=None, gt=0, le=100)
    product_id: int | None = None


class InventoryItemRead(TimestampedRead, InventoryItemBase):
    # Which shop holds this. Always set on a stored row, so the client can
    # show and filter by it without a second lookup.
    branch_id: int | None = None


class OpeningStockCreate(BaseModel):
    """
    Stock the shop already had when it started using this system.

    The one legitimate way to put a quantity into a pot without a purchase
    behind it, and it is still a document: it posts the metal into 1130 and the
    matching value into 3200 Opening Balance Equity, so the books and the shelf
    start life agreeing. Recorded once per pot — a second one is a correction,
    and corrections are counts.
    """

    weight_g: Decimal = Field(default=Decimal("0"), ge=0)
    weight_ct: Decimal = Field(default=Decimal("0"), ge=0)
    quantity: int = Field(default=0, ge=0)
    # What it was worth on the day the shop opened its books. Required for
    # metal: an opening balance valued at nothing would put free gold on the
    # balance sheet and understate capital by exactly its worth.
    rate_per_g: Decimal | None = Field(default=None, ge=0)
    value: Decimal | None = Field(default=None, ge=0)
    as_of: date | None = None
    notes: str | None = None
