"""
What still needs setting up before the shop can work.

A new client opens this system to twenty-five screens and no idea which one
comes first. The answer is not a manual — it is a short, honest list of what is
missing, in the order it is needed, with a link to the screen that fixes each
one. Every item is a real query against their data, so the list empties itself
as they go and never congratulates them for something they have not done.

Ordering is dependency-driven, not alphabetical: a design cannot be minted
without an item, and no leg can post without a gold rate on record.
"""
from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select

from app.core import clock
from app.api.deps import CurrentUser, DbSession, require_perm
from app.models.branch import Branch
from app.models.currency import Currency
from app.models.customer import Customer
from app.models.department import Department
from app.models.design import Design
from app.models.gold_rate import GoldRate
from app.models.inventory import InventoryItem, InventoryType
from app.models.item import Item
from app.models.product import Product
from app.models.vendor import Vendor
from app.schemas.setup import SetupChecklist, SetupStep

router = APIRouter()
read = Depends(require_perm("master:read"))


async def _count(db: DbSession, model, *where) -> int:
    stmt = select(func.count(model.id))
    for clause in where:
        stmt = stmt.where(clause)
    return int((await db.execute(stmt)).scalar_one())


@router.get("/checklist", response_model=SetupChecklist, dependencies=[read])
async def checklist(db: DbSession, current: CurrentUser) -> SetupChecklist:
    """
    The shop's own state, as a list of next actions.

    Deliberately not stored. A stored checklist drifts from reality the moment
    someone deletes the only item, and then cheerfully reports the shop is
    ready when it cannot mint a design.
    """
    today = clock.today()

    items = await _count(db, Item, Item.is_active.is_(True))
    departments = await _count(db, Department, Department.is_active.is_(True))
    workers = await _count(db, Vendor, Vendor.is_active.is_(True))
    customers = await _count(db, Customer)
    branches = await _count(db, Branch, Branch.is_active.is_(True))
    gold_stock = await _count(
        db, InventoryItem, InventoryItem.type == InventoryType.raw_gold
    )
    designs = await _count(db, Design)
    products = await _count(db, Product)

    # A rate for today specifically. Yesterday's rate is not a rate: the
    # routing engine refuses to value a movement without one in force, so a
    # shop with a stale rate is a shop that cannot issue metal this morning.
    rate_today = int(
        (
            await db.execute(
                select(func.count(GoldRate.id)).where(
                    GoldRate.rate_date == today,
                    GoldRate.currency == Currency.PKR,
                )
            )
        ).scalar_one()
    )

    steps = [
        SetupStep(
            key="branch",
            title="Name your shop",
            detail=(
                "One branch already exists so nothing is homeless, but give it your shop's real "
                "name and code — it prints on labels and transfer notes."
            ),
            done=branches > 0,
            count=branches,
            to="/settings/branches",
            cta="Open branches",
            # Never blocking: the migration seeded one, so the shop can trade
            # from the first minute. This is a tidy-up, and is marked as such.
            optional=True,
        ),
        SetupStep(
            key="items",
            title="List the kinds of piece you make",
            detail=(
                "Taka, ring, set — each with a short abbreviation. The abbreviation becomes the "
                "prefix of every design number, so TK-00001 is a taka. Nothing can be minted "
                "until there is at least one."
            ),
            done=items > 0,
            count=items,
            to="/settings/items",
            cta="Add items",
        ),
        SetupStep(
            key="departments",
            title="List the stages a piece goes through",
            detail=(
                "Maker, stone fixer and lacker are set up already — whatever your floor actually "
                "runs. Each stage can carry its own wastage terms so you don't retype them on "
                "every job."
            ),
            done=departments > 0,
            count=departments,
            to="/settings/departments",
            cta="Add departments",
        ),
        SetupStep(
            key="gold_rate",
            title="Set today's gold rate",
            detail=(
                "Every movement of metal is valued at the rate in force. Without today's rate the "
                "system will refuse to issue gold rather than book a day's work at nothing — so "
                "this is the one thing to do each morning."
            ),
            done=rate_today > 0,
            count=rate_today,
            to="/gold-rates",
            cta="Set the rate",
        ),
        SetupStep(
            key="workers",
            title="Add your karigars",
            detail=(
                "Each with their department and their agreed wastage allowance. The allowance is "
                "frozen onto every job when the metal leaves, so a worker with none agreed is "
                "charged for every gram short."
            ),
            done=workers > 0,
            count=workers,
            to="/vendors",
            cta="Add workers",
        ),
        SetupStep(
            key="gold_stock",
            title="Put your metal on the books",
            detail=(
                "Record what is actually in the safe, by purity. Gold is issued out of these "
                "pots, so until one exists there is nothing to issue."
            ),
            done=gold_stock > 0,
            count=gold_stock,
            to="/inventory",
            cta="Open inventory",
        ),
        SetupStep(
            key="customers",
            title="Add a customer",
            detail=(
                "Needed before you can bill anyone or take an order. Their birthday and "
                "anniversary are worth filling in — the system will remind you."
            ),
            done=customers > 0,
            count=customers,
            to="/customers",
            cta="Add customers",
            optional=True,
        ),
        SetupStep(
            key="first_design",
            title="Mint your first design",
            detail=(
                "Give a piece its number the moment work starts on it. Everything the piece does "
                "afterwards — every department, every gram, every rupee of labour — is filed "
                "under that number."
            ),
            done=designs > 0,
            count=designs,
            to="/designs",
            cta="Open designs",
        ),
        SetupStep(
            key="first_product",
            title="Put a finished piece into stock",
            detail=(
                "When a design comes back from its last department, stocking it turns it into "
                "something sellable and locks in what it cost to make."
            ),
            done=products > 0,
            count=products,
            to="/designs",
            cta="Open designs",
            optional=True,
        ),
    ]

    required = [s for s in steps if not s.optional]
    return SetupChecklist(
        steps=steps,
        done_count=sum(1 for s in steps if s.done),
        total=len(steps),
        required_done=sum(1 for s in required if s.done),
        required_total=len(required),
        # The shop can actually work once the required steps are done. Said
        # plainly so the banner can disappear rather than nagging forever.
        ready=all(s.done for s in required),
        user_name=current.full_name,
    )
