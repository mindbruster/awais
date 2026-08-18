"""
The two ways a jeweller can be asked "what did we make on that?".

Both are legitimate and they answer different questions, which is why the shop
gets to choose rather than being handed one.

**Cost basis** values the metal at what the shop actually paid for it — the rate
locked onto the piece when it was stocked. It answers *"did we trade well?"* and
it is what an accountant means by gross profit. This is the default because it
is what almost every jeweller's books already do, and because it is the only one
of the two that reconciles to the ledger without further explanation.

**Replacement basis** values the metal at today's rate. It answers a different
and equally real question — *"can we restock what we just sold?"* — which in a
rising market is the one that decides whether the shop is actually growing or
quietly liquidating itself.

The gap between them is the holding gain, and it is not profit from trading. It
is already reported, separately and deliberately, by the metal revaluation. The
one thing a shop must not do is count it twice, which is why the report says so
on its face whenever replacement basis is selected.

Stones are at parcel cost under **both**. There is no market rate for a grade of
diamond the way there is for metal — a rate for "12 PTR commercial VS1" is a
negotiation, not a quotation — so a replacement value for stones would be a
number somebody invented.
"""
import enum


class ProfitBasis(str, enum.Enum):
    cost = "cost"
    replacement = "replacement"
