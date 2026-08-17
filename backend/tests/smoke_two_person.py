"""
Non-destructive smoke test for four-eyes approval on a metal write-off.

Lives here rather than in the e2e suite because the rule is switched by
configuration, and the e2e runs against a server the test cannot reconfigure.

It touches no database at all. The two guards under test are pure functions
over a `StockCount` — they read its status, who submitted it, and whether every
pot is weighed — so building the object in memory tests exactly what runs in
production without a transaction to roll back or a user row to invent.

The invariant: when `REQUIRE_TWO_PERSON_APPROVAL` is on, the person who
asserted what the scale said cannot also be the person who accepts the loss.
Both halves matter — a rule that blocks the wrong person and also blocks the
right one is not a control, it is an outage.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException

logging.disable(logging.INFO)

from app.core.config import settings  # noqa: E402
from app.models.metal import Metal  # noqa: E402
from app.models.stock_count import (  # noqa: E402
    StockCount,
    StockCountLine,
    StockCountStatus,
)
from app.services import reconciliation as svc  # noqa: E402

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"[PASS] {label}")
    else:
        fail += 1
        print(f"[FAIL] {label} {detail}")


def refused(fn, *args, **kwargs) -> int | None:
    """The status code `fn` refused with, or None if it allowed the call."""
    try:
        fn(*args, **kwargs)
    except HTTPException as exc:
        return exc.status_code
    return None


COUNTER = 101      # weighed the metal
APPROVER = 202     # signs off the loss


def sheet(*, weighed: bool = True) -> StockCount:
    """A sheet 2.6 g short, built in memory."""
    count = StockCount(
        count_no="SC-SMOKE-0001",
        branch_id=1,
        metal=Metal.gold,
        status=StockCountStatus.draft,
        counted_at=datetime.now(timezone.utc),
        created_by_user_id=COUNTER,
        reason="Month-end count",
    )
    line = StockCountLine(
        inventory_item_id=1,
        book_weight_g=Decimal("500"),
        counted_weight_g=Decimal("497.4") if weighed else None,
    )
    count.lines = [line]
    return count


def main() -> int:
    count = sheet()
    original = settings.require_two_person_approval
    try:
        # ---------- the rule is off (the default) ----------
        settings.require_two_person_approval = False
        count.reason = "Month-end count"
        check(
            "with the rule off, one person can post a draft",
            svc.assert_second_person(count, COUNTER) is None,
            "the default must stay usable for a single-admin shop",
        )

        # ---------- the rule is on ----------
        settings.require_two_person_approval = True
        check(
            "a draft cannot be posted at all — it has to be submitted first",
            refused(svc.assert_second_person, count, APPROVER) == 409,
            "without a submit step the approver has no queue to work from",
        )

        svc.submit_count(count, user_id=COUNTER)
        check(
            "submitting moves it out of draft and records who asserted the figures",
            count.status is StockCountStatus.submitted
            and count.submitted_by_user_id == COUNTER,
            f"status {count.status}, submitted_by {count.submitted_by_user_id}",
        )
        check(
            "submitting twice is refused",
            refused(svc.submit_count, count, user_id=COUNTER) == 409,
            "a second submit would silently reassign whose figures these are",
        )

        check(
            "the person who counted cannot accept the loss",
            refused(svc.assert_second_person, count, COUNTER) == 403,
            "this is the whole control",
        )
        check(
            "a colleague can",
            svc.assert_second_person(count, APPROVER) is None,
            "a rule that blocks everybody is an outage, not a control",
        )

        # The check follows whoever *submitted*, not whoever opened the
        # sheet — a count started in the morning and finished by the
        # evening shift is ordinary.
        count.submitted_by_user_id = APPROVER
        check(
            "it follows the submitter, not the creator",
            refused(svc.assert_second_person, count, APPROVER) == 403
            and svc.assert_second_person(count, COUNTER) is None,
            "the person whose word is being taken is the one who weighed it",
        )

        # A sheet with no reason is refused before anybody is asked to sign.
        count.reason = "   "
        check(
            "an unexplained variance is refused at submit, not at approval",
            refused(svc.assert_complete, count) == 400,
            "a control that fails at the last step teaches people to route around it",
        )
        # An unweighed pot is refused before anybody is asked to sign.
        check(
            "an unweighed pot is refused at submit, not at approval",
            refused(svc.assert_complete, sheet(weighed=False)) == 400,
            "a control that fails at the last step teaches people to route around it",
        )
    finally:
        settings.require_two_person_approval = original

    print(f"{ok} passed, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
