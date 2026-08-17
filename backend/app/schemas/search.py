"""
Schemas for the one search box.

A hit is deliberately flat and display-ready — title, subtitle, badge, route —
rather than a nested record. The palette shows a line and navigates; giving it
whole entities would make it decide how to render eight different shapes, and
every new searchable type would then need frontend work to appear at all.
"""
from pydantic import BaseModel


class SearchHit(BaseModel):
    """One record the caller is allowed to open."""

    # Machine name, for grouping and icons.
    type: str
    # What to print above the group — "Invoice", "Karigar", "Broker".
    type_label: str
    id: int
    # The identifier a person would have typed: a document number, or a name.
    title: str
    subtitle: str | None = None
    # A status word, shown as a chip. Optional because most records have none
    # worth showing in a one-line result.
    badge: str | None = None
    # Where clicking it goes. Never null — a hit with no destination is a tease.
    to: str
    # Lower sorts first: 0 exact document number, 1 partial document number,
    # 2 name starts-with, 3 name contains. Sent to the client so the ordering
    # survives any regrouping it does.
    score: int = 3


class SearchResults(BaseModel):
    query: str
    hits: list[SearchHit] = []
    # How many were found before the limit was applied, so the UI can say
    # "showing 8 of 23" rather than implying it found everything.
    total: int = 0
