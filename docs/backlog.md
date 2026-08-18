# Backlog

Everything asked for and not yet built, checked against what the system already
does so nothing gets built twice. Marked:

- **new** — nothing exists
- **partial** — the data or the endpoint exists, the screen or the shape does not
- **exists** — already built; listed only so it is not requested again by mistake

Where a requirement could be read two ways, the reading is stated and the
question is left open rather than guessed at. Open questions are collected at
the bottom; none of them block the items that don't depend on them.

---

## 1 · Invoices — two kinds

The shop writes two different bills and the system has one layout.

### 1.1 Finished product invoice — **done**

Columns, in order:

| # | Column |
|---|---|
| 1 | Sr |
| 2 | Product code |
| 3 | Product name |
| 4 | Gold weight |
| 5 | Discount |
| 6 | Diamond CT |
| 7 | Diamond price |
| 8 | Amount |
| 9 | Image |

The image column is the notable one: a printed bill that shows the article is
what lets a customer check the box against the paper. `invoice_items` already
carries `product_image_url` and the e2e suite asserts it reaches the client, so
the field exists and the layout does not.

### 1.2 Loose materials invoice — **done**

Selling stones on their own — no gold, so no gold column and no wastage.

| # | Column |
|---|---|
| 1 | Sr |
| 2 | Product code |
| 3 | Product name |
| 4 | Diamond CT |
| 5 | Diamond price |
| 6 | Discount |
| 7 | Amount |

Note the discount moves: on a finished piece it sits against the gold, here it
sits against the stone price. That is not a cosmetic reordering — it says the
two bills discount different things.

> **Open question 1.** The brief listed both layouts under heading "1" and left
> heading "2" empty. The second table has no gold column at all, which is what
> a loose-stone sale looks like, so it is recorded here as the type-2 layout.
> Confirm before this is built.

---

## 2 · Money in and out

| Item | State | Notes |
|---|---|---|
| Expenses | **done** | `cash_entries` + `cash_categories`, `POST /cash/entries`. Every row posts a balanced journal entry, so cash and bank balances stay derived from the ledger. Categories map to a ledger head, falling back to 5300 / 4400. |
| Manual bank / cash entry for receipts and expenses | **done** | `method` is cash or bank; a bank entry must name its account and a cash one must not. Receipts that are not customer settlements post to the new **4400 Other Income**. |
| Daily cash report / money flow | **done** | `GET /cash/flow`, defaulting to today. Reads the **journal**, not the cash-entry table, so bills settled, suppliers paid, wages and the till float appear side by side. Opening + net = closing is asserted. |
| Reports for every cash flow | **done** | Same endpoint with `date_from` / `date_to`, grouped by ledger head. |
| Business overview | **partial** | `/dashboard` and `/ledger/position` exist. "Complete" needs scoping — see open question 2. |

Still to build on the cash book: a **screen** for it (all of the above is API-only),
and a CSV export to match every other report.

---

## 3 · Customers

| Item | State | Notes |
|---|---|---|
| Customer ledger / statements | **exists** | `/ledger/party-statement` and the Statements screen. Worth reviewing against what is wanted rather than rebuilding. |
| Customers ranked top spend → low | **exists** | `/reports/customers`, and the Customers tab under Reports. |
| Profit margin per customer | **exists** | Same report — revenue, cost, margin and margin % per customer. |
| Customer sales targets — by date range, monthly, annually | **exists** | `SalesTarget` with `scope=customer`; actuals read from invoices, never stored. |

---

## 4 · Vendors

| Item | State | Notes |
|---|---|---|
| Vendor details | **exists** | `vendors` master, and the Vendors screen. |
| Vendor bills and due dates | **exists** | `due_date` on bullion and stone bills; `/purchasing/bills` ages them. See 4b. |
| Add new vendor | **exists** | |
| Every cash flow with a vendor | **exists** | Bills, payments and the running balance, all on `/purchasing/bills`. |

---

## 4j · The two printed bills, and images that never break — **done**

**The loose-materials layout.** The backend has had two invoice kinds for a
while — a loose bill refuses gold weight and wastage — but the *printed* page
had one layout for both, with a Gold Weight column on a bill that has no gold
on it. Now:

| Finished piece | Loose material |
|---|---|
| Sr · Product Details · **Gold Weight** · Discount · Diamond CT · Diamond Price · Image | Sr · Product Details · Diamond CT · Diamond Price · **Discount** · Amount |

The discount **moves**, and that is the point of two layouts rather than one
with blanks: on a piece it is ratti argued against the metal, on a parcel it is
money off the stone price. The column order says which conversation the bill
was. No photograph on a parcel either — there is no piece to show, and an empty
frame prints as a form half filled in.

**Images.** A real bug, found while auditing: the invoice detail screen rendered
`product_image_url` **raw**, without `staticUrl()`. A bare `/static/...`
resolves against the *frontend* origin, which serves the SPA shell for any
unknown path — so the browser was handed `text/html` where it expected a PNG,
and every product photo on every bill was broken. Confirmed by content type
before fixing.

All eleven image sites now go through one `<Img>` component that falls back
instead of showing the browser's torn-page glyph. Two failures are kept
distinct: *no src* is a piece never photographed and ordinary; *a src that
404s* is a file that was expected and is gone, so it carries a title on hover.
`onError` fires once and does not retry — a missing file does not become present
because the page asked twice.

`tools/check_images.py` (`npm run check:images`) walks every record carrying an
image and checks the file behind it, reporting missing files **and** orphans on
disk. Local storage only, and it says so rather than implying it covered S3.

---

## 4i · The owner's second maker example — **pinned**

Given after the fact and matching the implementation exactly:

```
100 g pure gold given to the maker
102 g of 18k received back
102 / 96 * 10      = 10.625 g allowance at 10 ratti
102 + 10.625       = 112.625 g adjusted
112.625 / 24 * 18  =  84.469 g pure equivalent
100 - 84.469       =  15.531 g the maker owes the shop
```

The system computes **15.5312** by the other route — issued fine, less received
fine, less the allowance in fine — which is the same identity rearranged.
Asserting the *answer* rather than the route is what makes that safe: if either
derivation drifts, the test fails.

---

## 4h · Profit, two ways — **done**

Guide §41 named two profit setups and said the formulas were *"TBD and must be
finalized with the business"*. They never were. Rather than leave the last item
open indefinitely, the **common jeweller's convention** is implemented, both
methods are selectable, and **every judgement the report makes is printed on the
report** — so a figure built on a rule the owner did not choose is visible
rather than authoritative-looking.

| Basis | Metal valued at | Answers |
|---|---|---|
| `cost` *(default)* | the rate locked when the piece was stocked | *Did we trade well?* |
| `replacement` | today's rate | *Can we restock what we sold?* |

On the current data the two differ by **Rs 44,227** — and that gap is the
holding gain, not trading profit.

Three rules:

- **Only the gold stream can move between bases.** Stones and making are
  identical under both, and the e2e asserts it: a difference appearing anywhere
  else means the basis leaked.
- **Stones are at parcel cost under both.** There is no market rate for a grade
  of diamond the way there is for metal — a price for "12 PTR commercial VS1" is
  a negotiation, not a quotation — so a replacement value would be invented.
- **The replacement basis warns against double counting.** The gap between the
  two *is* the holding gain, and the metal revaluation already reports it. A
  shop reading replacement here and adding the revaluation counts the same money
  twice, so the report says so on its face.

An unknown basis is a 422 rather than a silent fallback: reporting one method
under another's name is worse than refusing.

**Still not settled.** This is a convention, not the shop's own rule. The screen
says so in as many words and invites correction. When the owner writes the two
formulas down, they replace these and get pinned like the maker's 15.531 g.

---

## 4g · Two-person approval on a write-off — **done** (0042)

`stock_counts` already recorded the creator and the poster separately, so a shop
could *see* whether two people were involved. Nothing required it, and nothing
gave the second person a queue — the approver had no way to know a sheet was
waiting.

| Item | State | Notes |
|---|---|---|
| `submitted` state | **exists** | Draft = still weighing. Submitted = a decision is wanted. |
| `submitted_by` / `submitted_at` | **exists** | Who asserted the figures. |
| The rule | **exists** | `REQUIRE_TWO_PERSON_APPROVAL`, **off by default**. |
| Explained in the UI | **exists** | Button greyed with the reason, not a 403 at the last click. |
| Approver's queue | **exists** | "Review & approve" on the overview, plus a dashboard alert. |

Four decisions:

- **Off by default, and that is deliberate rather than lax.** A shop with one
  admin would otherwise be unable to post a count at all. A control that makes
  the feature unusable pushes the reconciliation back onto paper, which is
  strictly worse than not having the control.
- **The check follows the *submitter*, not the creator.** A sheet opened in the
  morning and finished by the evening shift is ordinary; the person whose word
  is being taken is the one who weighed it.
- **Submitting is its own act.** Without it there is no difference between a
  sheet half-filled and one ready to sign, and the approver would have to open
  every draft to find out.
- **Completeness is checked at submit, not at approval.** A control that fails
  at the last step teaches people to route around it.

Tested in `tests/smoke_two_person.py` — no database, because the guards are pure
functions over a `StockCount`. Nine assertions, covering the rule **off** as
well as on: a rule that blocks the wrong person and also blocks the right one is
an outage, not a control.

---

## 4f · Audit before/after — **done** (0041)

`audit_log` recorded who, what, when and a free-form blob. Whether a line
carried the *old* value depended on what each call site happened to put in that
blob, and most put nothing — so it could say Abdul edited a gold rate and not
what it had been. That is a notification, not an audit trail.

| Item | State | Notes |
|---|---|---|
| `before` / `after` columns | **exists** | JSONB, only the fields that moved. |
| `reason` column | **exists** | Its own column so it can be filtered on. |
| The eight shared masters | **exists** | Items, branches, banks, departments, stone grades, countries, cities, suppliers — **none of which logged anything at all** before this. |
| Gold and silver rate changes | **exists** | Create and delete, both previously unaudited. |
| Product edits and deletes | **exists** | Weight, purity, cost, price. |
| On screen | **exists** | `old → new` per field, with the reason beneath. |

Four decisions:

- **Only the changed fields are stored.** A full snapshot of both sides buries
  the one number that moved in forty that did not, and on a wide table makes the
  log larger than the data it describes.
- **Both sides carry identical keys**, so a reader can put them side by side
  without checking each field exists on both.
- **An edit that changed nothing writes no row.** "Somebody opened this and
  altered nothing" only makes the real edits harder to find.
- **A delete keeps the whole row**, because afterwards there is nothing left to
  compare against — the one case where a full snapshot is the point.

Decimals are stored as strings. This log is read to settle arguments about
weights and money, and `2.6` coming back as `2.5999999999999996` would undermine
the whole point of keeping it.

`details` stays alongside. Plenty of actions are not field changes — how many
lots were on a bill, which entry a reversal produced — and forcing those into a
diff shape would lose them.

---

## 4e · Schema-drift check — **done**

The bug that cost a day: `job_legs` grew nine columns in the model — `metal`,
the wastage trio, the ratti fields — and **no migration was ever written**.
Nothing failed at import, nothing failed at startup, the suite was green, and
every `POST /designs` returned a 500. The entire workshop was unreachable while
the software looked like it worked.

`tools/check_schema_drift.py` compares `Base.metadata` against the database
`alembic upgrade head` actually builds, using alembic's own autogenerate
comparison.

| | |
|---|---|
| Run it | `npm run check:schema` (`--strict` for the noise) |
| In CI | straight after `alembic upgrade head`, before anything else runs |
| Exit | 0 agree · 1 drift · 2 could not connect |

**Catches:** a table or column the models declare and the migrations never
create; a type or nullability the two disagree about; and anything alembic
reports that this script does not recognise — an unclassified difference is
treated as drift rather than swallowed.

**Ignores:** indexes, constraints and defaults. On this schema that is 88
differences with nothing wrong — a column marked `unique=True, index=True`
becomes a unique constraint *plus* an index in Postgres, and autogenerate wants
to swap them on every run. Partial indexes written as raw SQL are invisible to
the models and read the same way. A check that cries wolf 88 times is one people
learn to skip.

**Proven, not assumed.** Adding a column to a model with no migration was
verified to fail the check, naming `job_legs.<column>` — the same shape as the
original bug — and to exit 1.

---

## 4d · Universal search and the product timeline — **done**

Two of the three gaps left after the reconciliation centre. Neither needed a
migration: both are derived from what the documents already say.

**Universal search** — `GET /search`. The palette could find *screens*; it could
not find `INV-26-00025`, "Sarafa", or a serial. Eight types now: invoices,
products, jobs, orders, customers, karigars, suppliers, sellers. Exact document
numbers rank first, the tail of a number works as well as the head, and each
type is gated on the same permission its own endpoint uses — disallowed types
are skipped rather than filtered, so a restricted role gets no row at all.

*Worth knowing:* all three seeded roles hold read on every searchable type, so
the gate currently excludes nothing. The e2e says so rather than asserting a
restriction that would pass for the wrong reason.

**Product timeline** — `GET /products/{id}/timeline`, drawn under the piece on
its own page, as §19 of the UI spec asks. Job opened → issued to each worker →
received with the wastage settled → stocked → transferred → out on memo → sold,
with the bill and the margin at the end.

Assembled from the documents, never stored. A stored timeline is a second
version of history and drifts from the first the moment anything is reversed.
Undated events sort **last**: a leg still out with a worker has no return date,
and sorting a missing timestamp as the epoch would put it before the metal was
bought. Margin is null until the piece sells — a margin on unsold stock is a
guess dressed as a figure.

---

## 4c · Reconciliation — **done** (0040)

The one thing a precious-metals system must do and this one could not: compare
what the books say with what is on the scale. Stock only ever moved through
documents — the right rule, and exactly why a discrepancy had nowhere to go.

| Item | State | Notes |
|---|---|---|
| Overview of what can be checked | **exists** | `GET /reconciliation`. |
| Gold and silver counts | **exists** | Sheet per metal per branch, `SC-` series. |
| Variance in both units | **exists** | As-weighed **and** fine, converted at the pot's purity. |
| Posting an adjustment | **exists** | Movement + journal entry, one transaction, to **5500**. |
| Reason required | **exists** | A 400 without one. |
| Stones / cash / bank | **listed, not countable** | With a sentence saying why. |

Five rules worth keeping:

- **A count never overwrites a balance.** There is no endpoint that sets a stock
  figure. The sheet is the source document, like a purchase.
- **Book figures freeze when the sheet opens.** A count taken over an hour while
  the counter is still selling would otherwise show a variance made partly of
  real sales.
- **The books move by the fine figure, not the scale reading.** 2.6 g short on a
  22k pot is 2.3833 fine grams; booking 2.6 would leave the trial balance out by
  the alloy.
- **Counting and accepting the loss are different permissions.** Opening a sheet
  needs `inventory:write`; posting needs `report:profit` and a password.
- **An unweighed pot is not an empty one.** Posting is refused while any line is
  blank, because treating it as zero would write the whole pot off.

`5500 Stock Variance` swings both ways. A credit balance is worth a hard look:
finding *more* metal than the books show means something arrived unrecorded.

---

## 4b · Vendor bills, due dates and paying them — **done** (0039)

Two halves of one hole. A purchase on credit posted to `2110 Suppliers` and sat
there: nothing said when it was due, and **nothing in the system could pay it** —
`Payment` is customer-only, so a payable could only be cleared by a hand-written
journal. Guide §36 and the vendor half of §44 had nothing behind them.

| Item | State | Notes |
|---|---|---|
| Due date on a bill | **exists** | Bullion and stone bills. Nullable — see below. |
| Upcoming / due today / overdue | **exists** | `GET /purchasing/bills`, plus `undated`. |
| Paid / partially paid | **exists** | Derived, oldest-first. |
| Paying a supplier | **exists** | `VP-` series, posts 2110 ↔ cash/bank, reversible. |
| Dashboard alerts | **exists** | Overdue and due-today, beside the maker metal alert. |
| Screen | **exists** | `/purchasing/bills`, with a preview of what a payment will clear. |

Three decisions worth keeping:

- **`due_date` is nullable and stays nullable.** Plenty of bills are settled at
  the counter and never had a date. Forcing one invents a deadline nobody
  agreed to, so an undated bill reports as `undated` rather than as due.
- **No allocation table.** Which bills a payment settles is derived at read
  time, oldest first — the shop's own khata rule. The cost is real and is
  printed on the screen: *money paid for this week's bill shows as clearing the
  oldest one still open.* What it buys is that a bill's status cannot drift from
  the ledger, because nothing about it is stored.
- **A cash-paid bullion bill is not a debt** and never appears. It never touched
  2110.

---

## 4a · Buying silver — **done** (0038)

Everything downstream of a silver purchase already existed — `raw_silver` stock,
`1135 Silver in Hand`, silver on a job leg, a silver rate, silver on the stock
page and in the revaluation. Silver could be issued to a karigar, come back as
925, be valued and reported. It simply could not be **bought**: `gold_purchases`
had no metal column, so the only way silver ever entered the books was an
opening balance or a hand-written journal.

| Item | State | Notes |
|---|---|---|
| Silver dealer bill | **exists** | Same document as a gold bill; `metal` on the header. |
| Its own series | **exists** | `SB-26-00001`. Not `SP`, which is stone purchases. |
| Its own control account | **exists** | Debits 1135, commodity `SILVER`. |
| Fineness not karat | **exists** | 999 → 99.9 tunch. A karat on a silver lot is a 422. |
| A pot per fineness | **exists** | 999 and sterling never blend into one figure. |
| Screen | **exists** | `/purchasing/silver`, sharing the gold page's code. |

Metal sits on the **bill**, not the lot: one document must not straddle 1130 and
1135, and the field deciding where five kilos land is not one to leave settable
row by row. `purity` on a lot is now nullable for the same reason — karat cannot
describe silver, and a placeholder 24 would read as pure gold on every screen
that printed it.

---

## 5 · Salesmen and brokers — **done**

| Item | State | Notes |
|---|---|---|
| Profile | **exists** | Name, kind, phone, CNIC, commission %, notes. |
| Bills assigned | **exists** | `Sold by` on the invoice form; the list and detail show the name. |
| Sales / performance | **exists** | `/sales/:id` — revenue, margin, average, largest, volumes. |
| Collections | **exists** | Collected against outstanding, held apart from sales. |
| Customer relationships | **exists** | Who they sell to, ranked, with margin each. |
| Targets | **exists** | Their targets travel with the page, calendar beside them. |
| Commission | **exists** | Estimated at their rate — labelled an estimate; nothing posts it. |

**The defect this closed:** `Invoice.seller_id` and the seller-scoped target
both existed, and no screen ever set the field — so *every seller target read 0%
forever* and the whole feature was decorative. The e2e now asserts the round
trip: a bill names a seller, and that seller's page **and** target both move.

---

## 5a · Salesmen and brokers — original scope

Nothing exists beyond `PartyType.salesman`, which was declared for exactly this
and has never been written to.

- Salesman records, and brokers alongside them
- Targets per salesman
- Bills assigned to a salesman
- Reports and performance data per salesman

The party type is already reserved with a note explaining why a salesman is not
a kind of worker: a karigar is given metal to transform and owes it back as
pieces; a salesman is given finished pieces and owes them back as goods or
money. Same firm assets, obligations that settle in different units.

---

## 6 · Company targets — **done**

Company sales target, alongside the per-customer and per-salesman targets
above. All three want the same shape — a figure, a period, and actuals read
from the same place — so they should be one mechanism, not three.

---

## 7 · Profit, two ways — **done** — see 4h

Two separate profit setups, kept apart rather than blended:

1. **Gold** — margin on metal
2. **Raw materials** — margin on diamonds and stones

Related, and the harder half: **gold capital and costing that moves with the
rate.** Metal held at cost is not what metal is worth this morning, and a shop
whose capital is mostly gold cannot read its own position from a cost figure.
The ledger already snapshots a rate onto every metal line, which is what makes
this answerable at all.

> **Open question 3.** Is the revaluation to be *reported* only, or *posted* —
> does a rate movement create a journal entry, or is it a reporting overlay on
> historic cost? These give different balance sheets and the choice is the
> shop's, not the system's.

---

## 8 · Live metal rates — **done**

Fetch gold and silver rates live, shown in **their own tab** — deliberately not
wired into pricing, which continues to use the rate the shop sets. A live feed
that silently prices invoices would reprice the counter mid-sale.

`gold_rates` now carries `metal` and `fineness_pct`, so a fetched rate has
somewhere to land for both metals.

> **Open question 4.** Which source, and in what currency and purity does it
> quote? A feed quoting USD per troy ounce needs two conversions before it
> means anything on this floor, and both are places to be wrong.

---

## 9 · Product photography for marketing — **done**

A tab of product pictures, its own screen:

- Grid of images, keyed by product id
- Clicking one opens that product's detail
- Each shows **how much gold and how much diamond** went into the piece

The material figures already exist: `products.material_cost`, the product stone
breakdown, and the design trace that shows every gram and carat the piece
consumed. This is a presentation of data the system already holds.

---

## Open questions

1. **Invoice type 2** — is the second column layout the loose-materials bill?
   (See 1.2.)
2. **"Business overview complete"** — what is missing from the dashboard as it
   stands? Easier to answer against the screen than in the abstract.
3. **Gold revaluation** — reported, or posted to the ledger? (See 7.)
4. **Live rate source** — which feed, quoted in what unit? (See 8.)
5. **Targets** — are company, customer and salesman targets in money, in
   weight, or both? A gold business often sets them in grams.
