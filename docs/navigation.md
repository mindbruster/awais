# Navigation

The map lives in `frontend/src/components/nav.ts`. `DashboardLayout` only draws
it, and `CommandPalette` searches it. Adding a screen means adding one entry
there and one route — nothing else knows the shape of the app.

## What was wrong

Thirty-eight destinations, **twenty-two of them in a single ungrouped column**
before the first heading appeared. The part of the list a new user met first was
the part with no structure at all, and the sidebar scrolled on any normal
laptop.

Worse than the length was the vocabulary. Six links said some version of *your
stuff is here* and nothing in the words told them apart:

| Was | Actually | Now |
|---|---|---|
| Stock | read-only summary of holdings | Inventory → **What we hold** |
| Inventory | melt pots, editable | Inventory → **Raw materials** |
| Stones | **a catalogue.** No quantity. | Settings → **Stone list** |
| Stone stock | the parcels, filed under Buying | Inventory → **Diamonds & stones** |
| Stock ledger | movement history | Inventory → **Stock movements** |
| Products / Gallery | the same pieces, twice | **Finished products** / **Product gallery** |

`Stones` was the worst of them: a list of grades with a default rate and no
quantity anywhere on it, sitting between two holdings screens, so it read as
stones the shop owned.

Two other defects: **Gold rates** and **Live rates** were indistinguishable by
name though one is the rate you price against and the other is untouchable spot;
and `/settings/departments` was routed but reachable from nowhere, having been
absorbed into the Workers page long before.

## The sections come from the spec

The section list and its order are **§22 of the UI/UX specification**, followed
rather than improved on. An application whose sidebar disagrees with its own
design document is one nobody can check against anything.

Four of §22's fourteen headings are folded in, on the authority of the spec's
own §15 — *do not put dozens of reports directly into the sidebar*. Each would
otherwise have been a heading holding exactly one link:

| §22 heading | Where it went | Why |
|---|---|---|
| Alerts | Dashboard | Every alert §22 lists is already there, where §3.3 puts it. |
| Targets | Sales | Beside the salesmen whose targets they are. |
| Product Gallery | Sales | A selling tool — you open it to show a customer a piece. |
| Audit Logs | Settings | Admin-only, as it already was. |

Result: **Dashboard · Inventory · Manufacturing · Sales · Customers · Vendors ·
Finance · Reports · Market rates · Settings**.

## The three rules

**A label says what the screen answers.** "Rates you set" and "Live gold &
silver" are longer than "Gold rates" and "Live rates" and tell you which one
bills a customer.

**Every entry carries the words a person would actually search.** `keywords` is
the vocabulary gap, not SEO. The shop says *karigar*, *bill*, *memo*, *udhaar*,
*chandi*, *bhao*, *tunch*; the system says workers, invoice, approval, credit,
silver, rate, fineness. The palette matches on these and never displays them, so
the shop's own words find the screen without the label having to be bilingual.

## Behaviour

Groups collapse; the one containing the current page opens itself. A group you
open or close by hand is remembered — until you navigate into it, which always
wins. A remembered preference that hides where you currently are is worse than
no memory at all, so a collapsed group holding the active page keeps a dot.

⌘K opens the palette and is advertised in the sidebar rather than left as
folklore. It searches **two things at once**, under separate headings:

- **Screens**, matched locally from `nav.ts`, instantly — navigating should
  never wait on a network round trip. Matching is a subsequence, so `stpr` finds
  *Stone parcels*, but ranked so an exact word beats a scattered one: typing
  `sto` lands on *Stone list*, not on *Cu**sto**mers*.
- **Records**, from `GET /search`, debounced at 180ms — an invoice number, a
  customer, a karigar, a job, a serial. Exact document numbers rank first, and
  the tail of a number works as well as the head, because people search
  `00025` as often as `INV-26-00025`.

Two headings rather than one blended list: a screen and a document are different
kinds of answer, and mixing them makes the reader check the right-hand column on
every row to find out which they are looking at.

**Search never returns what the caller could not open.** Each entity is gated on
the same permission its own endpoint uses, and disallowed types are skipped
rather than filtered afterwards. Today all three seeded roles hold read on every
searchable type, so the gate excludes nothing in practice — the e2e says so
plainly rather than asserting a restriction that would pass for the wrong
reason.

## Invariants worth keeping

Two hold this together and both are cheap to check:

- **Every nav entry has a route, and every concrete route has a nav entry.** A
  link that 404s and a screen nobody can reach are the same bug seen from two
  ends. Diff the `to:` values in `nav.ts` against the `path:` values in
  `routes/index.tsx`.
- **`sectionForPath` matches longest-first.** `/purchasing/stone-stock` lives
  under Stock while `/purchasing/stones` lives under Buy; first-prefix-wins would
  put one of them in the wrong group depending only on declaration order.
