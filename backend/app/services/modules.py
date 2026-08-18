"""
Which modules this shop uses, and what stands in the way of switching one off.

Two rules, and the second is the one that matters.

**A module that is off is off on the server.** Hiding a link changes nothing: a
POST still reaches the endpoint, and a shop that believes Manufacturing is
switched off while jobs can still be created has a control that exists only in
the sidebar. Every router that belongs to a module carries the guard.

**A module holding live work cannot be switched off at all.** The shop chose
this over hiding it, and the reason is that hiding is the more dangerous
option: turning off Manufacturing while 1,272 fine grams sit with karigars
would make the screen that receives them unreachable, stranding real metal in a
state nothing can move it out of. So the switch is refused, and it names what
has to be settled first.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import SystemAccount
from app.models.approval import Approval, ApprovalStatus
from app.models.design import JobLeg, LegStatus
from app.models.invoice import Invoice, InvoiceStatus
from app.models.journal import Commodity
from app.models.module import Module
from app.services import ledger

_ZERO = Decimal("0")


@dataclass
class Blocker:
    """One reason a module cannot be switched off, in the shop's own words."""

    what: str
    where: str | None = None


@dataclass
class ModuleState:
    module: Module
    blockers: list[Blocker] = field(default_factory=list)

    @property
    def can_switch_off(self) -> bool:
        return self.module.can_disable and not self.blockers


async def enabled_keys(db: AsyncSession) -> set[str]:
    """The modules currently switched on, as a set for cheap membership tests."""
    return {
        k
        for (k,) in (
            await db.execute(select(Module.key).where(Module.enabled.is_(True)))
        ).all()
    }


async def get_module(db: AsyncSession, key: str) -> Module | None:
    return (
        await db.execute(select(Module).where(Module.key == key))
    ).scalar_one_or_none()


async def blockers_for(db: AsyncSession, key: str) -> list[Blocker]:
    """
    What is still live inside this module.

    Deliberately specific. "Cannot disable: module in use" tells somebody
    nothing they can act on; "3 jobs still out with workers, 1,272.180 fine g
    outside" tells them exactly what to go and settle.

    Only obligations count — things the shop owes or is owed, or material that
    is somewhere it cannot be recovered from with the module off. Historic
    records are not blockers: a thousand settled invoices do not stop Sales
    being switched off, because nothing about them is waiting on anybody.
    """
    out: list[Blocker] = []

    if key == "manufacturing":
        open_legs = (
            await db.execute(
                select(func.count(JobLeg.id)).where(JobLeg.status == LegStatus.issued)
            )
        ).scalar_one()
        if open_legs:
            out.append(Blocker(f"{open_legs} job(s) still out with workers", "/designs"))
        for label, account, commodity in (
            ("gold", SystemAccount.GOLD_WITH_WORKERS, Commodity.GOLD),
            ("silver", SystemAccount.SILVER_WITH_WORKERS, Commodity.SILVER),
        ):
            held = await ledger.balance(
                db, account_code=account.value, commodity=commodity
            )
            if held != 0:
                out.append(
                    Blocker(f"{held} fine g of {label} is outside the building",
                            "/material-outside")
                )

    if key == "sales":
        unpaid = (
            await db.execute(
                select(func.count(Invoice.id)).where(
                    Invoice.status == InvoiceStatus.issued
                )
            )
        ).scalar_one()
        if unpaid:
            out.append(Blocker(f"{unpaid} invoice(s) not yet settled", "/invoices"))
        # Both states count: a memo with one piece back is still a memo with
        # pieces out, and collapsing the two would let stock be hidden while it
        # is sitting in a customer's house.
        memos = (
            await db.execute(
                select(func.count(Approval.id)).where(
                    Approval.status.in_(
                        (ApprovalStatus.out, ApprovalStatus.partly_returned)
                    )
                )
            )
        ).scalar_one()
        if memos:
            out.append(Blocker(f"{memos} memo(s) still out on approval", "/approvals"))

    if key == "vendors":
        owed = await ledger.balance_pkr(db, account_code=SystemAccount.SUPPLIERS.value)
        if owed != 0:
            out.append(Blocker(f"Rs {abs(owed):,.0f} still owed to dealers",
                               "/purchasing/bills"))

    if key == "customers":
        due = await ledger.balance_pkr(db, account_code=SystemAccount.CUSTOMERS.value)
        if due != 0:
            out.append(Blocker(f"Rs {abs(due):,.0f} still owed by customers", "/customers"))

    if key == "finance":
        owed = await ledger.balance_pkr(
            db, account_code=SystemAccount.WORKERS_PAYABLE.value
        )
        if owed != 0:
            out.append(Blocker(f"Rs {abs(owed):,.0f} owed to workers for labour",
                               "/material-outside"))

    if key == "inventory":
        for label, account, commodity in (
            ("gold", SystemAccount.GOLD_IN_HAND, Commodity.GOLD),
            ("silver", SystemAccount.SILVER_IN_HAND, Commodity.SILVER),
        ):
            held = await ledger.balance(
                db, account_code=account.value, commodity=commodity
            )
            if held != 0:
                out.append(
                    Blocker(f"{held} fine g of {label} is still in stock", "/stock")
                )

    return out


async def state_of(db: AsyncSession, module: Module) -> ModuleState:
    """A module with the reasons it cannot be switched off, if any."""
    # Only computed for modules that are currently on: what stands in the way of
    # switching something off is not a question about something already off.
    blockers = await blockers_for(db, module.key) if module.enabled else []
    return ModuleState(module=module, blockers=blockers)


async def assert_enabled(db: AsyncSession, key: str) -> None:
    """Refuse a request into a module this shop has switched off."""
    module = await get_module(db, key)
    if module is not None and not module.enabled:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"{module.label} is switched off for this shop. A super admin can turn it "
            "back on under Settings → Modules.",
        )
