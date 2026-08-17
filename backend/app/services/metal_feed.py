"""
Live gold and silver rates, for looking at and nothing else.

The shop asked to see the market on a tab of its own, and the "of its own"
carries the whole design. Pricing — invoices, product costing, every journal
entry that values metal — reads the rate the shop *sets*, and must go on doing
so. A feed wired into pricing would reprice the counter mid-sale, and would do
it from a number nobody in the shop agreed to.

So nothing in this module is reachable from a posting path. It fetches, it
caches for a few minutes, and it hands back a figure with a timestamp and a
plain statement of what the figure is not.

**What it is not**, specifically: goldpricez quotes international spot
converted into the requested currency. The Pakistan market rate is set locally
and routinely differs — by the import premium, by the day's dollar, and by
whatever the bazaar is doing. Treating this as "the rate" would be wrong in a
way that looks right, so the response says so and the screen repeats it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx

from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

BASE_URL = "https://goldpricez.com/api/rates/currency/{currency}/measure/gram/metal/all"

# Long enough that opening the tab repeatedly costs one call, short enough that
# the number is still today's. The feed itself updates far less often than this.
CACHE_TTL = timedelta(minutes=5)

# The keys goldpricez returns for a per-gram quote. Gold is unprefixed and
# silver carries a prefix; both are pure metal, which is what makes them
# comparable to a 24k and a 999 rate respectively.
_GOLD_KEY = "gram_in_{currency}"
_SILVER_KEY = "silver_gram_in_{currency}"


@dataclass
class LiveRates:
    currency: str
    gold_per_gram: Decimal | None
    silver_per_gram: Decimal | None
    fetched_at: datetime
    # Set when the feed could not be reached or is not configured. The tab shows
    # this instead of a number: a stale or invented rate presented as live is
    # worse than an empty panel that explains itself.
    unavailable: str | None = None


_cache: tuple[datetime, LiveRates] | None = None


def _decimal(value) -> Decimal | None:
    """
    A quote, or nothing.

    The feed returns some fields as strings and some as floats, and an absent
    metal simply omits its key. Anything that will not parse is treated as
    absent rather than as zero — a rate of zero displayed as a rate is a lie,
    where a blank is merely a gap.
    """
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed > 0 else None


async def fetch(currency: str = "PKR", *, force: bool = False) -> LiveRates:
    """
    Today's spot, cached.

    Every failure mode returns a `LiveRates` carrying `unavailable` rather than
    raising. This is a display panel: the shop's day does not stop because a
    third party is down, and an endpoint that 500s would take the tab with it.
    """
    global _cache
    now = datetime.now(timezone.utc)
    if not force and _cache is not None:
        cached_at, rates = _cache
        if now - cached_at < CACHE_TTL and rates.currency == currency.upper():
            return rates

    if not settings.goldpricez_api_key:
        return LiveRates(
            currency=currency.upper(),
            gold_per_gram=None,
            silver_per_gram=None,
            fetched_at=now,
            unavailable=(
                "No goldpricez API key is configured, so live rates cannot be fetched. "
                "The rate you set under Gold rates is what prices everything either way."
            ),
        )

    url = BASE_URL.format(currency=currency.lower())
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                url, headers={"X-API-KEY": settings.goldpricez_api_key}
            )
    except httpx.HTTPError as exc:
        logger.warning("live metal rate fetch failed", extra={"error": str(exc)})
        return LiveRates(
            currency=currency.upper(),
            gold_per_gram=None,
            silver_per_gram=None,
            fetched_at=now,
            unavailable=f"The rate service could not be reached: {type(exc).__name__}.",
        )

    if response.status_code == 401:
        reason = "The goldpricez API key was refused."
    elif response.status_code == 429:
        reason = "The rate service is rate-limiting this key. Try again shortly."
    elif response.status_code >= 400:
        reason = f"The rate service returned {response.status_code}."
    else:
        reason = None

    if reason:
        logger.warning("live metal rate unavailable", extra={"status": response.status_code})
        return LiveRates(
            currency=currency.upper(),
            gold_per_gram=None,
            silver_per_gram=None,
            fetched_at=now,
            unavailable=reason,
        )

    try:
        body = response.json()
    except ValueError:
        return LiveRates(
            currency=currency.upper(),
            gold_per_gram=None,
            silver_per_gram=None,
            fetched_at=now,
            unavailable="The rate service returned something that was not JSON.",
        )
    if not isinstance(body, dict):
        body = {}

    key = currency.lower()
    rates = LiveRates(
        currency=currency.upper(),
        gold_per_gram=_decimal(body.get(_GOLD_KEY.format(currency=key))),
        silver_per_gram=_decimal(body.get(_SILVER_KEY.format(currency=key))),
        fetched_at=now,
    )
    if rates.gold_per_gram is None and rates.silver_per_gram is None:
        rates.unavailable = (
            "The rate service answered but carried no price for this currency."
        )
    _cache = (now, rates)
    return rates
