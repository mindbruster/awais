"""
What day it is, in the shop's terms.

The system was of two minds about this. Routers asked Python for `date.today()`
— the server's local date — and services asked for `datetime.now(timezone.utc)
.date()`. On a developer's laptop in Karachi those two disagree for the first
five hours of every day; on a UTC container they agree with each other and both
disagree with the shop.

That is not cosmetic. `rate_in_force` treats a rate dated later than "today" as
a plan rather than a price, so between local midnight and 05:00 the rate the
shop had just keyed in was read as future-dated and ignored: the system either
priced the morning's metal at yesterday's rate or refused to issue it at all,
saying no rate was on record — while the rate sat on the screen in front of
them.

So there is one answer to "what day is it", it comes from here, and it is the
shop's day. `SHOP_TIMEZONE` sets it; the default is Pakistan, because that is
where the shop is.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings

DEFAULT_TIMEZONE = "Asia/Karachi"


@lru_cache(maxsize=4)
def shop_zone() -> ZoneInfo:
    """
    The shop's timezone, or UTC if the name is not one the system knows.

    Falling back rather than raising is deliberate: a typo in an environment
    variable must not stop the till from opening. UTC is wrong by a few hours;
    a crash at startup is wrong by a whole day of trading.
    """
    name = (getattr(settings, "shop_timezone", "") or DEFAULT_TIMEZONE).strip()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def now() -> datetime:
    """The current moment, as the shop's clock reads it."""
    return datetime.now(shop_zone())


def today() -> date:
    """The shop's current date. The one answer to 'what day is it'."""
    return now().date()


def shop_date(moment: datetime | None) -> date | None:
    """
    Which shop day a stored instant belongs to.

    `moment.date()` reads the date off whatever zone the value carries, which
    for a stored timestamp is UTC. A bill rung up at 02:00 in Karachi is dated
    the previous day by that reading — and then priced against the previous
    day's gold rate, which is the whole problem this module exists to stop.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(shop_zone()).date()


def day_start_utc(day: date) -> datetime:
    """
    The instant a shop day begins, in UTC.

    Timestamps are stored as UTC, so filtering "what sold today" against a UTC
    midnight counts the wrong five hours — a bill rung up at 02:00 local lands
    on yesterday, and the day's takings are wrong every morning until dawn.
    """
    return datetime.combine(day, time.min, tzinfo=shop_zone()).astimezone(timezone.utc)


def day_end_utc(day: date) -> datetime:
    """The instant a shop day ends, in UTC — exclusive of the next day."""
    return day_start_utc(day + timedelta(days=1))
