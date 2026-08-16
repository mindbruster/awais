"""
Non-destructive smoke test for the karigar risk score.

The developer's database has one finished leg per worker, which is correctly
scored as "insufficient" — so the scoring itself would go untested against real
data. This builds enough synthetic legs inside a transaction to make each
component fire, checks it fires for the right reason, and rolls back.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

logging.disable(logging.INFO)

from app.api.v1.insights import BAND_HIGH, BAND_WATCH, RISK_MIN_LEGS, karigar_risk  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.department import Department  # noqa: E402
from app.models.design import Design, DesignStatus, JobLeg, LegStatus  # noqa: E402
from app.models.item import Item  # noqa: E402
from app.models.vendor import Vendor, VendorType  # noqa: E402
from app.services.routing import next_design_no  # noqa: E402

ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"[PASS] {label}")
    else:
        fail += 1
        print(f"[FAIL] {label} {detail}")


def reasons_of(row):
    return {r.code for r in row.reasons}


async def main():
    async with SessionLocal() as db:
        item = (await db.execute(select(Item).limit(1))).scalars().first()
        dept = (await db.execute(select(Department).limit(1))).scalars().first()
        if not (item and dept):
            print("Need an item and a department on file; skipping.")
            raise SystemExit(0)

        now = datetime.now(timezone.utc)

        async def worker(name: str) -> Vendor:
            v = Vendor(
                name=name,
                type=VendorType.karigar,
                department_id=dept.id,
                is_active=True,
            )
            db.add(v)
            await db.flush()
            return v

        design = Design(
            design_no=await next_design_no(db, item),
            item_id=item.id,
            status=DesignStatus.in_production,
        )
        db.add(design)
        await db.flush()

        def leg(v, *, issued, received, days_ago, held_days, excess, allowed=Decimal("0")):
            issued_at = now - timedelta(days=days_ago)
            return JobLeg(
                design_id=design.id,
                sequence=0,
                department_id=dept.id,
                worker_id=v.id,
                status=LegStatus.received,
                issued_at=issued_at,
                received_at=issued_at + timedelta(days=held_days),
                gold_issued_g=issued,
                gold_received_g=received,
                wastage_allowed_g=allowed,
                wastage_actual_g=issued - received,
                wastage_excess_g=excess,
            )

        # --- a clean worker: plenty of legs, losses inside the allowance -------
        clean = await worker("ZZ Smoke Clean")
        for i in range(6):
            db.add(leg(clean, issued=Decimal("100"), received=Decimal("99.8"),
                       days_ago=150 - i * 20, held_days=2,
                       excess=Decimal("0"), allowed=Decimal("0.5")))

        # --- a heavy loser: well past his allowance on every leg ---------------
        heavy = await worker("ZZ Smoke Heavy")
        for i in range(6):
            db.add(leg(heavy, issued=Decimal("100"), received=Decimal("95"),
                       days_ago=150 - i * 20, held_days=2,
                       excess=Decimal("4.5"), allowed=Decimal("0.5")))

        # --- a deteriorating worker: fine early, bad lately --------------------
        drift = await worker("ZZ Smoke Drift")
        for i in range(4):  # earlier half — 0.5% wastage
            db.add(leg(drift, issued=Decimal("100"), received=Decimal("99.5"),
                       days_ago=170 - i * 5, held_days=2,
                       excess=Decimal("0"), allowed=Decimal("1")))
        for i in range(4):  # recent half — 4% wastage
            db.add(leg(drift, issued=Decimal("100"), received=Decimal("96"),
                       days_ago=40 - i * 5, held_days=2,
                       excess=Decimal("3"), allowed=Decimal("1")))

        # --- a slow worker: sits on every job ----------------------------------
        slow = await worker("ZZ Smoke Slow")
        for i in range(6):
            db.add(leg(slow, issued=Decimal("100"), received=Decimal("99.8"),
                       days_ago=150 - i * 20, held_days=30,
                       excess=Decimal("0"), allowed=Decimal("0.5")))

        # --- a worker holding metal that never came back -----------------------
        holder = await worker("ZZ Smoke Holder")
        db.add(
            JobLeg(
                design_id=design.id,
                sequence=99,
                department_id=dept.id,
                worker_id=holder.id,
                status=LegStatus.issued,
                issued_at=now - timedelta(days=120),
                gold_issued_g=Decimal("250"),
                gold_received_g=Decimal("0"),
            )
        )

        # --- too few legs to judge ---------------------------------------------
        newbie = await worker("ZZ Smoke Newbie")
        db.add(leg(newbie, issued=Decimal("100"), received=Decimal("90"),
                   days_ago=10, held_days=1, excess=Decimal("9.5")))

        await db.flush()

        report = await karigar_risk(db, days=180)
        by_name = {r.worker_name: r for r in report.rows}

        for n in ("ZZ Smoke Clean", "ZZ Smoke Heavy", "ZZ Smoke Drift",
                  "ZZ Smoke Slow", "ZZ Smoke Holder", "ZZ Smoke Newbie"):
            if n not in by_name:
                check(f"{n} appears in the report", False, "missing")

        clean_r = by_name.get("ZZ Smoke Clean")
        heavy_r = by_name.get("ZZ Smoke Heavy")
        drift_r = by_name.get("ZZ Smoke Drift")
        slow_r = by_name.get("ZZ Smoke Slow")
        hold_r = by_name.get("ZZ Smoke Holder")
        new_r = by_name.get("ZZ Smoke Newbie")

        check("a clean worker scores nothing", clean_r and clean_r.score == 0,
              f"got {clean_r.score if clean_r else '—'}")
        check("a clean worker is banded low", clean_r and clean_r.band == "low",
              f"got {clean_r.band if clean_r else '—'}")

        check("heavy losses are flagged", heavy_r and "excess" in reasons_of(heavy_r),
              f"got {reasons_of(heavy_r) if heavy_r else '—'}")
        check("heavy losses score above the watch line",
              heavy_r and heavy_r.score >= BAND_WATCH, f"got {heavy_r.score if heavy_r else '—'}")

        check("a deteriorating rate is flagged", drift_r and "trend" in reasons_of(drift_r),
              f"got {reasons_of(drift_r) if drift_r else '—'}")
        check("the trend reason cites both halves",
              drift_r and any("%" in r.detail for r in drift_r.reasons if r.code == "trend"))

        check("sitting on jobs is flagged", slow_r and "slow" in reasons_of(slow_r),
              f"got {reasons_of(slow_r) if slow_r else '—'}")

        check("metal held too long is flagged", hold_r and "stale_open" in reasons_of(hold_r),
              f"got {reasons_of(hold_r) if hold_r else '—'}")
        check("a holder with no finished legs still appears",
              hold_r and hold_r.legs == 0 and hold_r.open_gold_g > 0)

        check("too few legs is not scored", new_r and new_r.band == "insufficient",
              f"got {new_r.band if new_r else '—'} score={new_r.score if new_r else '—'}")
        check("the minimum-legs rule is what excluded him",
              new_r and new_r.legs < RISK_MIN_LEGS)

        check("every reason carries points that add up",
              all(sum(x.points for x in r.reasons) == r.score
                  for r in report.rows if r.score < 100))
        check("scores are capped at 100", all(r.score <= 100 for r in report.rows))
        check("rows come back worst first",
              [r.score for r in report.rows] == sorted((r.score for r in report.rows), reverse=True))

        print("\n       scored rows:")
        for r in report.rows:
            if r.worker_name.startswith("ZZ Smoke"):
                print(f"         {r.worker_name:<18} score={r.score:>3} band={r.band:<12} "
                      f"reasons={sorted(reasons_of(r))}")

        await db.rollback()
        print("\n       rolled back — no changes committed")

    print(f"\n{ok} passed, {fail} failed")
    raise SystemExit(1 if fail else 0)


asyncio.run(main())
