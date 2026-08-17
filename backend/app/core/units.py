"""
The two units the shop weighs in, and the one place they meet.

Gold is weighed in grams and stones in carats, and every screen, report and
stock figure keeps them that way — a carat total that has quietly become grams
is not a smaller number, it is a wrong one, and nothing on the page says so.

They have to meet in exactly one place: the reckoning with a stone setter. He
is handed a piece and a parcel of stones and hands back one object on one
scale, so what went out has to be expressed in grams to be compared with what
came back, and the stones inside the returned piece have to come back out of
that gross weight to leave the metal alone.

Defining the conversion here rather than at either call site is the point. It
is a definition, not a measurement — a carat is a fifth of a gram exactly — and
a second copy of it is a second thing to get wrong.
"""
from decimal import Decimal

# Weights are held to four decimals throughout, so conversions quantize to the
# same place rather than carrying a longer tail into a stored column.
WEIGHT_DP = Decimal("0.0001")

CARAT_G = Decimal("0.2")
CARATS_PER_G = Decimal("5")


def carats_to_grams(carats: Decimal | float | None) -> Decimal:
    """Stone weight as the gram scale would read it."""
    return (Decimal(str(carats or 0)) * CARAT_G).quantize(WEIGHT_DP)


def grams_to_carats(grams: Decimal | float | None) -> Decimal:
    """Gram weight back in the unit stones are counted and sold in."""
    return (Decimal(str(grams or 0)) * CARATS_PER_G).quantize(WEIGHT_DP)
