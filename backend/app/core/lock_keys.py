"""
Every Postgres advisory-lock key in one place.

Advisory locks are just integers with no namespace, so two features that happen
to pick the same number serialise against each other for no reason — minting an
invoice number would queue behind someone posting an opening balance, and
nothing in either file would explain why. Worse, the collision is invisible: it
does not error, it just makes the system mysteriously slower under load.

Scattering the constants across the services that use them makes a clash a
matter of luck. Keeping them here makes it a matter of reading one file.

Two rules:

* **Never reuse a number.** Retire one rather than repoint it.
* **Keys are per-resource, not per-caller.** Everything that mints a design
  number takes the same lock, or the lock does nothing.

The 7_4xx_xxx block is for *derived* keys — a base to which a row id is added,
so a per-item or per-purity lock does not serialise against its neighbours.
Leave a wide gap after each base.
"""

# --- documents (7_300_0xx) ---------------------------------------------------
PRODUCT_SERIAL = 7_300_001
MANUFACTURING_JOB_NO = 7_300_002
INVOICE_NO = 7_300_003

# 7_300_004 .. 7_300_006 are RESERVED. The `Dev` branch assigns them to its
# finished-goods, raw-gold and loose-material serials. Nothing here may take
# them, so that branch can merge without a silent collision — see
# docs/BRANCH_DIVERGENCE.md.
_RESERVED_DEV = (7_300_004, 7_300_005, 7_300_006)

PAYMENT_NO = 7_300_007
OLD_GOLD_PURCHASE_NO = 7_300_010
STONE_PURCHASE_NO = 7_300_011
RAW_STONE_ITEM = 7_300_012

# --- ledger and routing (7_300_02x) -----------------------------------------
JOURNAL_ENTRY_NO = 7_300_020
TAG_NO = 7_300_021
# The opening-balance run is a read-then-write over every party at once, so the
# whole endpoint is serialised rather than each party in turn.
OPENING_BALANCES = 7_300_022

# --- derived bases (7_4xx_xxx) ----------------------------------------------
# Design numbers count within an item, so the lock is per item: minting a TK
# and an RG at the same moment must not queue.
DESIGN_NO_BASE = 7_400_000
# Melt pots are per purity, so buying 22k does not serialise against 21k.
RAW_GOLD_ITEM_BASE = 7_420_000


def assert_unique() -> None:
    """
    Called by the test suite. A duplicate here is not a crash, it is a silent
    performance bug, so something has to look.
    """
    fixed = {
        "PRODUCT_SERIAL": PRODUCT_SERIAL,
        "MANUFACTURING_JOB_NO": MANUFACTURING_JOB_NO,
        "INVOICE_NO": INVOICE_NO,
        "PAYMENT_NO": PAYMENT_NO,
        "OLD_GOLD_PURCHASE_NO": OLD_GOLD_PURCHASE_NO,
        "STONE_PURCHASE_NO": STONE_PURCHASE_NO,
        "RAW_STONE_ITEM": RAW_STONE_ITEM,
        "JOURNAL_ENTRY_NO": JOURNAL_ENTRY_NO,
        "TAG_NO": TAG_NO,
        "OPENING_BALANCES": OPENING_BALANCES,
    }
    seen: dict[int, str] = {}
    for name, key in fixed.items():
        if key in seen:
            raise AssertionError(f"Advisory lock key {key} used by both {seen[key]} and {name}")
        if key in _RESERVED_DEV:
            raise AssertionError(
                f"{name} uses {key}, which is reserved for the Dev branch's serials"
            )
        seen[key] = name
