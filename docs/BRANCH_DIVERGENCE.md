# The `Dev` branch, and what was done about it

`origin/Dev` carries one commit that never reached `main`:

> `2abb32e feat(erp): inventory categories, purchases tab, invoice redesign`
> 3,464 insertions across 37 files.

The phase branches (`phase-1-correctness-fixes` → `phase-3-4-ledger-routing`)
were cut from `main`, so none of that work is in them, and the two lines
touch many of the same files. This is a genuine fork, not a fast-forward, and
merging it blind would silently drop one of two real implementations.

This document records what was taken, what was not, and why — so the decision
can be revisited by someone who has context this analysis did not.

## Taken

| From `Dev` | Why |
|---|---|
| `frontend/src/components/Modal.tsx` | A real bug fix, not a preference. The dialog had no max height, so a form taller than the viewport could not be scrolled and its submit button was unreachable. The issue-to-department and journal-entry forms added since are exactly that tall. |
| `fmtWeight` / `to2` in `frontend/src/lib/money.ts` | Purely additive helpers. Weights are stored to 4dp and read better at 2, and `to2` is safe to bind into a numeric input where `fmtWeight`'s thousands separators would not be. |

## Not taken

### `inventory_subcategories`

`Dev` adds a table of finished-goods subcategories — ring, pendant,
locked_set, tops_pair, locket — as a free-form dictionary.

The phase branches already carry `items`, which holds exactly these
(ring, bangle, taka…) **and** the abbreviation that every design number is
minted from (`TK-00001`). It is load-bearing: the routing engine, the trace
view and the stock form all key off it.

Taking both would leave the shop with two competing lists of "kind of piece",
maintained separately, drifting apart within a month. If the subcategory list
is wanted as a *second* axis beneath item — "ring → engagement / cocktail" —
that is a `parent_id` on `items`, not a parallel table.

### The generic `purchases` table and `PurchasesPage.tsx`

`Dev` models a purchase as one row keyed by inventory type, with a JSONB
`custom_fields` bag. It is flexible and it moves stock.

The phase branches model buying as `suppliers` + `old_gold_purchases` +
`stone_purchases`/`stone_purchase_items`, and every one of them **posts a
balanced journal entry** alongside the stock movement. That is the difference
that mattered: old gold bought below the day's rate has to book its spread,
and stones bought on credit have to land on the supplier's account. A purchase
that moves stock without touching the books leaves inventory and the ledger
disagreeing, which is the class of bug this rewrite exists to close.

If the JSONB escape hatch turns out to be needed for shop-specific attributes,
it can be added to the existing tables without giving up the postings.

### The invoice redesign

Superseded rather than rejected. The invoice screens have since gained sale
wastage, ratti discounts, bill-book numbers, round-off, a payments panel and a
derived balance due, all covered by the e2e suite. Re-applying `Dev`'s version
of the same screens would undo that.

Worth reviewing `Dev`'s layout for ideas — the work there was not wasted — but
as a design reference, not a merge.

## The advisory-lock collision

`Dev` claims keys `7_300_004`, `7_300_005` and `7_300_006` for its
finished-goods, raw-gold and loose-material serials. The phase branches had
taken the same three for journal-entry numbers, tag numbers and the
opening-balance run.

Colliding keys do not corrupt anything — they just make unrelated operations
queue behind each other, invisibly and only under load, with nothing in either
file to explain why.

Resolved by moving **this** side out of the way. Every key now lives in
`backend/app/core/lock_keys.py`, `7_300_004..006` are reserved there for `Dev`,
and `assert_unique()` fails the suite if anything reclaims them.

## Independently found the same bug

Both lines fixed the serial-number generator, separately: `COUNT(*) + 1`
collides with a live serial as soon as any row is deleted. `Dev` uses
`MAX(serial)` lexicographically; the phase branches cast the numeric suffix
and take `MAX` of that. Same conclusion, and the comments give the same
reasoning.

Two people finding it independently is a good sign about the bug, and a
reminder that neither branch was being read by the other.

## If `Dev` is merged later

1. Take `inventory_subcategories` only after deciding whether it is a second
   axis under `items` or a duplicate of it.
2. Drop `Dev`'s `purchases` table, or rename it so it does not collide with
   the ledger-integrated purchasing.
3. Keep the lock keys as reserved above.
4. Run the e2e suite. It is the thing that will tell you whether the merge
   preserved the invariants — particularly that the trial balance still
   balances after every operation.
