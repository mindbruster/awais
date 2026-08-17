"""
One piece, from raw metal to the customer's hand.

The events are flat and display-ready rather than nested, for the same reason
the search hits are: the page draws a vertical list and each row has to fit on
one line. Nesting the source documents would make the frontend understand seven
different shapes, and every new event type would then need frontend work before
it could appear at all.
"""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class TimelineEvent(BaseModel):
    """
    One thing that happened to this piece.

    `at` may be null — a job leg that has been issued and not received has no
    received date, and a piece stocked before this system tracked it has no
    stocking timestamp. Undated events are shown at the end rather than assumed
    to have happened at the epoch, which would put them before the metal was
    bought.
    """

    # Machine name: 'ordered', 'job', 'issued', 'received', 'stocked',
    # 'transfer', 'approval_out', 'approval_back', 'sold', 'movement'.
    kind: str
    # The heading on the row — "Issued to Ravi Karigar".
    title: str
    # One line under it, carrying the numbers.
    detail: str | None = None
    at: datetime | None = None
    # The document this came from, and where to open it.
    reference: str | None = None
    to: str | None = None
    # Weights, when the event moved metal or stones. Shown in the row's own
    # unit and never added across events.
    weight_g: Decimal | None = None
    stone_ct: Decimal | None = None
    amount: Decimal | None = None
    # 'good' | 'warn' | 'bad' | 'plain' — how the row reads at a glance.
    tone: str = "plain"


class ProductTimeline(BaseModel):
    """
    The piece's whole life, and the figures that survived it.

    `metal_in` and `metal_out` are not a balance and must not be read as one:
    metal issued to a maker for a lot may have become twelve pieces, and only
    this one's share is here. They are shown so a reader can see the shape of
    the job, not to reconcile it — that is the job leg's own settlement.
    """

    product_id: int
    serial_no: str
    name: str
    status: str
    image_url: str | None = None

    gold_weight_g: Decimal = Decimal("0")
    gold_purity: int | None = None
    gold_tunch_pct: Decimal | None = None
    stone_weight_ct: Decimal = Decimal("0")
    gross_weight_g: Decimal | None = None

    total_cost: Decimal = Decimal("0")
    material_cost: Decimal = Decimal("0")
    gold_rate_at_cost: Decimal | None = None
    # What it sold for, once it has. Null while it is still in stock.
    sold_for: Decimal | None = None
    # Sale less cost. Null until sold, because a margin on an unsold piece is a
    # guess dressed as a figure.
    margin: Decimal | None = None

    design_id: int | None = None
    design_no: str | None = None

    events: list[TimelineEvent] = []
