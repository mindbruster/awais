import enum


class Metal(str, enum.Enum):
    """
    Which precious metal a weight is made of.

    The shop buys pure gold at 24k and pure silver at 999, gives either to the
    same three workers, and gets back jewellery in either. Everything between
    those two points — the wastage reckoning, the worker's running balance, the
    stock — works identically for both, but the two are not interchangeable and
    a gram of one must never settle a gram of the other.

    Purity is *not* part of this. Gold is quoted in karat and silver in
    fineness, which look like different scales but both reduce to a percentage
    of pure: 21k is 87.5, 999 silver is 99.9. `tunch_pct` carries that for both,
    so this enum only has to say which metal, never how pure.
    """

    gold = "gold"
    silver = "silver"
