# The workshop flow

What the shop actually does, from buying bullion to a finished piece in stock,
and the arithmetic behind each step. Every figure here is the client's own
worked example. Where a formula could be read two ways, the reading chosen is
stated along with the number the other reading would have produced — because
the difference is real metal.

This document is the specification. The e2e suite asserts these numbers; if a
figure here and a figure in the code disagree, the code is wrong.

---

## 0 · Units

| Thing | Unit | Never |
|---|---|---|
| Gold | grams | carats |
| Silver | grams | carats |
| Stones — purchase, stock, product, reports | carats | grams |
| Stones — the setter's weight reckoning only | grams | — |

**1 gram = 5 carats.** The conversion appears in exactly one place: working out
what physically went to the stone setter and what came back. Everywhere a human
reads a stone figure, it is in carats.

Pure content is **not** one formula:

```
gold    fine = weight × karat / 24          21k of 100 g = 87.500 g
silver  fine = weight × fineness / 1000     925 of 100 g = 92.500 g
```

Silver is quoted out of a thousand and gold out of twenty-four. Putting silver
through `/24` would call 925 silver "38.5k" and value it at four times what it
is. Where a document carries a measured **tunch %**, that governs and the karat
is display only; karat/24 is the fallback when no tunch was recorded.

---

## 1 · Buying

Three things are bought and three categories hold them:

- **raw gold** — always 24k / 999.9 pure
- **raw silver** — always 999 pure
- **raw stone** — diamonds and coloured stones, in carats

Silver has its own category rather than sharing the gold one. A stock figure
that can silently contain both metals cannot answer "how much gold do I have",
which is the only question the category exists to answer.

### Stone types and parcels

A stone **type** is a name the shop defines — "12 PTR commercial" — and it is
permanent. Buying more of that type **adds into the existing stock**: one
running carat figure, not a new entry per purchase.

Underneath that single figure, each purchase keeps its own rate, and issuing
draws from the **oldest parcel first**:

```
12 PTR commercial          stock 120.00 ct
  Jan parcel  50.00 ct @ Rs 8,000
  Mar parcel  70.00 ct @ Rs 9,200

a piece using 30 ct draws Jan first:
  30 × 8,000 = Rs 240,000
```

Averaging instead would have costed it at Rs 261,000 and let a parcel bought
dear hide inside the mean. The screen still shows one stock number; only the
costing looks underneath it.

### Rates

A **daily silver rate** is entered alongside the daily gold rate, at 999
reference. A silver movement on a day with no silver rate is refused, exactly
as a gold movement is today — posting at no value would let a day's work
balance perfectly while saying the shop moved nothing.

---

## 1a · The two wastage conventions are independent

The single most repeated instruction on this project, and the one thing most
worth getting wrong-proof: **the maker's allowance and the setter's allowance
are not the same rule with different numbers.** They differ in every way a rule
can differ, and neither converts into the other.

| | **Maker** — ratti | **Setter** — per 100 pieces |
|---|---|---|
| Measured against | what comes **back** | what went **out** |
| Quoted in | ratti out of 96 | grams per 100 stones |
| Denominated in | the **returned** karat | the **issued** karat |
| Reference known | only once the job is finished | at issue |
| An unused part is | **owed back to him** — an entitlement | **kept by the shop** — a cap |
| Moves with | the weight he returns | how many stones he sets |

The last two rows are where money is. A maker who takes less than his ratti is
owed the difference, so his excess is *signed*. A setter who loses less than
his allowance is owed nothing, so his floors at zero. Applying either rule's
sign convention to the other would hand metal away or pocket it.

And the reference weight makes them irreconcilable in principle: a percentage
of what was issued and a ratti of what was returned are not the same number and
cannot be converted into one another without already knowing the outcome. That
is why the basis is chosen when the deal is struck and travels frozen on the
leg.

Both worked examples below are asserted verbatim in the e2e suite, side by
side, under **"Maker vs setter — two conventions"**. If either figure ever
moves, that section fails.

## 2 · The maker

Pure metal goes out. 18k / 21k / 14k jewellery comes back.

### Wastage: ratti on the alloy, then convert

The allowance is worked out on the weight he **returns**, in the karat he
returns it, and is added to that weight *before* the conversion to pure:

```
Issued    100.0000 g pure 24k
Returned  107.5600 g of 21k, 6 ratti agreed

allowance = 107.5600 / 96 × 6      =   6.7225 g of 21k
credited  = 107.5600 + 6.7225      = 114.2825 g of 21k
fine      = 114.2825 × 21 / 24     =  99.9972 g pure
                                     ──────────────────
maker still owes                        0.0028 g pure
```

Ratti is quoted 1 to 24 against a base of 96, and the base travels on the leg
because it is a convention rather than a constant.

Treating the 6.7225 as *pure* grams instead would credit him 100.8375 g and
leave the shop owing him 0.8375 g on a job that in fact came out square. The
allowance is metal he keeps out of the piece he made, so it is in that piece's
karat.

### Terms

Wastage and a cash rate are **not** exclusive — a maker can have both on the
same job. Labour is **per piece** in current use; per-gram and flat exist as
selectable options for when the shop changes how it pays.

The piece count is agreed when the metal goes out, prefilled at receive, and
**the receiving figure is what pays him**: 12 agreed, 11 delivered, 11 × Rs 800.

### Purity of what comes back

The returned weight is converted at the purity it came back at — never at the
purity that went out. Crediting 107.560 g of 21k as though it were pure
overstates the return by about fourteen percent, and the shop believes a job
has settled while the metal is still short.

### When no gold is given

The maker works on his own metal and the shop owes him. The debt is the fine
content **plus his ratti**, so the reckoning reads identically whichever way
the job was funded — 99.9972 g pure on the figures above, against a due date
agreed at the time.

It settles in **metal or cash, whichever the shop chooses**, and partially.
A promise nobody wrote down is one nobody chases, so the due date is a first
class field and overdue metal promises are a report.

### Overrun

If his credit exceeds what he was issued, the balance flips and shows as gold
the shop owes him. This is normal — he added solder, alloy or findings — and it
posts without a block.

---

## 3 · Identity: lot, then pieces

```
day 1   gold out            →  LOT-0001   (100.000 g pure, ~12 pcs)
day 9   maker returns       →  LOT-0001 splits:
                                 TK-00001   9.100 g
                                 TK-00002   8.850 g
                                 …
                                 TK-00012   8.900 g
                                 ───────────────────
                                 total    107.560 g   must reconcile
day 14  to the setter       →  per piece, or the whole lot together
day 20  into stock          →  TK-00001 … TK-00012
```

The lot number exists from the moment metal leaves the safe, because a piece in
the maker's hands is precisely when the shop needs to find it. The per-piece
numbers are minted when the pieces physically exist, and each carries **one
number from there to the sale** — tag, setter, stock, invoice.

---

## 4 · The stone setter

He is given a finished piece and stones from stock. Stones may come from one
material or thirty.

### What is weighed, and what is worked out

The stones inside a finished piece cannot be put on a scale. So the carats set
are **stated at receive**, and everything else follows from them:

The plain case first — every stone set, nothing broken, nothing lost. This is
the client's own worked example and the numbers are asserted exactly:

```
OUT   100.0000 g of 21k product
      + 30.00 ct stones      (30.00 / 5 = 6.0000 g)
      = 106.0000 g handed over

BACK  piece gross            102.0000 g
      stones set in it        30.00 ct  = 6.0000 g

net metal  = 102.0000 − 6.0000   =  96.0000 g
short      = 106.0000 − 102.0000 =   4.0000 g
allowance  = 0.400 / 100 × 350   =   1.4000 g
                                    ──────────
receivable from the setter           2.6000 g
setting charge  350 × Rs 5        = Rs 1,750
```

Note the shortfall can be read two ways and they agree: 106 given less 102 back
is 4 g, and 100 g of metal issued less 96 g of metal returned is also 4 g. The
system computes the second — it nets the gross by the stones actually set —
because that is the only form that still works when some stones do not come
back.

Which is the second case:

```
BACK  piece gross            102.0000 g
      stones set in it        29.50 ct   ← stated
                            = 5.9000 g

unaccounted = 30.00 − 29.50  =  0.50 ct
   broken                       0.30 ct  → broken stock
   owed by the setter           0.20 ct  → his stone account

net gold   = 102.0000 − 5.9000  =  96.1000 g
gold short = 100.0000 − 96.1000 =   3.9000 g
allowance  = 0.400 / 100 × 350  =   1.4000 g
                                   ──────────
gold receivable from setter          2.5000 g of 21k
                                  =  2.1875 g fine
```

### The two editable entries

Agreed per leg and snapshotted, so renegotiating terms later cannot change how
a finished job is judged:

1. **waste per 100 stones**, in grams — 0.400
2. **setting charge per stone**, in rupees — 5, or 10

The **stone count is typed at receive** — 350 — and drives both:

```
waste  = 0.400 / 100 × 350  = 1.400 g
charge = 350 × Rs 5         = Rs 1,750
```

A weight per hundred pieces is used here rather than a percentage because a
setter's loss follows how many stones he handles, not how heavy the piece is.
A percentage would under-charge a light piece carrying many stones and
over-charge a heavy one carrying few.

### Missing stones

Carats that are neither set nor returned go one of two ways, decided at receive:

- **owed by the setter** — carats on his own stone account, valued at the
  **selling rate**, so losing a stone costs him the margin and not merely the
  cost. 0.20 ct at Rs 12,000 = Rs 2,400.
- **broken** — moved into the **broken / miscellaneous** stone category, held
  **at cost** and still sellable. Nothing is lost until it is disposed of.

### How his balances settle

His gold shortfall is held in **fine grams** (2.1875 g), his stone shortfall in
**carats**, his setting bill in **rupees** (Rs 1,750). Three balances; gold
clears in gold, stones in stones, cash in cash. They do not net against one
another.

---

## 5 · What the ledger needs

The journal is multi-commodity and balances on rupee value, not on quantity, so
each of these is a commodity plus a rate rather than a new kind of ledger:

| Commodity | Quantity in | Valued at |
|---|---|---|
| `PKR` | rupees | 1 |
| `USD` | dollars | the FX rate |
| `GOLD` | fine grams | PKR per fine gram, daily |
| `SILVER` | fine grams | PKR per fine gram of 999, daily |
| `STONE` | carats | the parcel rate, or the selling rate when charging a worker |

Accounts the flow above requires beyond those that exist: a silver counterpart
to *Gold in Hand* and *Gold with Workers*, and a *Stones with Workers* control
account so a setter's carat debt has somewhere to sit.
