from datetime import datetime, timezone

from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.manufacturing import ManufacturingJob
from app.models.product import Product

# Stable bigint keys for pg_advisory_xact_lock — must be int8 range and deterministic.
_LOCK_KEYS = {
    "P": 7_300_001,
    "MJ": 7_300_002,
    "INV": 7_300_003,
}


async def _next_for_year(db: AsyncSession, model, column, prefix: str) -> str:
    """
    Generates `<prefix>-<YY>-<NNNNN>`. Serialised across concurrent transactions
    via a Postgres transaction-scoped advisory lock keyed by prefix, so two
    requests can't mint the same number.

    The next value comes from the highest suffix in use, not from a row count.
    Counting breaks as soon as anything is deleted: remove P-26-00003 from five
    products and the count is 4, so the next mint collides with the existing
    P-26-00005 and fails the unique constraint.
    """
    lock_key = _LOCK_KEYS.get(prefix)
    if lock_key is None:
        raise ValueError(f"No advisory-lock key registered for serial prefix '{prefix}'")
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=lock_key))

    year = datetime.now(timezone.utc).strftime("%y")
    pat = f"{prefix}-{year}-%"
    highest = (
        await db.execute(
            select(
                func.coalesce(
                    func.max(cast(func.substring(column, r"(\d+)$"), Integer)),
                    0,
                )
            )
            .select_from(model)
            .where(column.like(pat))
        )
    ).scalar_one()
    return f"{prefix}-{year}-{int(highest) + 1:05d}"


async def next_product_serial(db: AsyncSession) -> str:
    return await _next_for_year(db, Product, Product.serial_no, "P")


async def next_job_no(db: AsyncSession) -> str:
    return await _next_for_year(db, ManufacturingJob, ManufacturingJob.job_no, "MJ")


async def next_invoice_no(db: AsyncSession) -> str:
    return await _next_for_year(db, Invoice, Invoice.invoice_no, "INV")
