from fastapi import APIRouter, Depends

from app.api.deps import require_module
from app.api.v1 import (
    approvals,
    dashboard,
    audit_log,
    auth,
    branches,
    customers,
    designs,
    gold_rates,
    insights,
    inventory,
    invoices,
    ledger,
    cash,
    sales,
    masters,
    notifications,
    orders,
    payments,
    purchasing,
    product_stones,
    products,
    reports,
    setup,
    stock_movements,
    stocking,
    stones,
    users,
    vendors,
    admin,
    reconciliation,
    search,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(products.router, prefix="/products", tags=["products"], dependencies=[Depends(require_module("inventory"))])
api_router.include_router(product_stones.router, prefix="/products", tags=["products"], dependencies=[Depends(require_module("inventory"))])
api_router.include_router(customers.router, prefix="/customers", tags=["customers"], dependencies=[Depends(require_module("customers"))])
api_router.include_router(inventory.router, prefix="/inventory", tags=["inventory"], dependencies=[Depends(require_module("inventory"))])
api_router.include_router(stock_movements.router, prefix="/stock-movements", tags=["stock-movements"], dependencies=[Depends(require_module("inventory"))])
api_router.include_router(vendors.router, prefix="/vendors", tags=["vendors"], dependencies=[Depends(require_module("manufacturing"))])
api_router.include_router(invoices.router, prefix="/invoices", tags=["invoices"], dependencies=[Depends(require_module("sales"))])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"], dependencies=[Depends(require_module("reports"))])
api_router.include_router(gold_rates.router, prefix="/gold-rates", tags=["gold-rates"], dependencies=[Depends(require_module("rates"))])
api_router.include_router(stones.router, prefix="/stones", tags=["stones"], dependencies=[Depends(require_module("inventory"))])
api_router.include_router(audit_log.router, prefix="/audit-log", tags=["audit-log"])

# Reference data the shop configures once and then selects from everywhere.
api_router.include_router(masters.departments_router, prefix="/departments", tags=["masters"])
api_router.include_router(masters.items_router, prefix="/items", tags=["masters"])
api_router.include_router(
    masters.attribute_options_router, prefix="/attribute-options", tags=["masters"]
)
api_router.include_router(masters.countries_router, prefix="/countries", tags=["masters"])
api_router.include_router(masters.cities_router, prefix="/cities", tags=["masters"])
api_router.include_router(masters.banks_router, prefix="/banks", tags=["masters"])
api_router.include_router(masters.bank_accounts_router, prefix="/bank-accounts", tags=["masters"])

# What still needs configuring, computed from the shop's own data rather than
# stored — a stored checklist drifts from reality the moment something is deleted.
api_router.include_router(setup.router, prefix="/setup", tags=["setup"])

# Where the business trades from, and the goods moving between those places.
# Transfers are mounted separately so a transfer id can never be read as a
# branch id.
api_router.include_router(branches.router, prefix="/branches", tags=["branches"])
api_router.include_router(branches.transfers_router, prefix="/transfers", tags=["branches"], dependencies=[Depends(require_module("inventory"))])

# The books, and the workshop floor that posts into them.
api_router.include_router(ledger.router, prefix="/ledger", tags=["ledger"], dependencies=[Depends(require_module("finance"))])
api_router.include_router(designs.router, prefix="/designs", tags=["designs"], dependencies=[Depends(require_module("manufacturing"))])

# Work promised to a customer. A front door onto the routing engine above:
# an order mints a design and lets that machinery do the tracking.
api_router.include_router(orders.router, prefix="/orders", tags=["orders"], dependencies=[Depends(require_module("manufacturing"))])

# Pieces let out on approval. Not a sale — the goods are still the shop's,
# merely somewhere else — so nothing here posts to the ledger.
api_router.include_router(approvals.router, prefix="/approvals", tags=["approvals"], dependencies=[Depends(require_module("sales"))])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])

# Telling customers things. Nothing here fires on a schedule — every message
# is somebody at the counter deciding to send it.
api_router.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)

# Analysis over the books. Degrades to plain statistics when no model provider
# is configured — nothing here is allowed to be load-bearing.
api_router.include_router(insights.router, prefix="/insights", tags=["insights"], dependencies=[Depends(require_module("reports"))])

# The money side: settling bills, stocking finished pieces, and both buying
# channels. Each posts to the ledger, so none of them is a bolt-on.
api_router.include_router(payments.router, prefix="/payments", tags=["payments"], dependencies=[Depends(require_module("finance"))])
api_router.include_router(stocking.router, prefix="/stocking", tags=["stocking"], dependencies=[Depends(require_module("manufacturing"))])
api_router.include_router(cash.router, prefix="/cash", tags=["cash"], dependencies=[Depends(require_module("finance"))])
api_router.include_router(sales.router, prefix="/sales", tags=["sales"], dependencies=[Depends(require_module("sales"))])
api_router.include_router(purchasing.router, prefix="/purchasing", tags=["purchasing"], dependencies=[Depends(require_module("vendors"))])
api_router.include_router(
    reconciliation.router, prefix="/reconciliation", tags=["reconciliation"]
)
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
# Read-only, for the sidebar. Everyone signed in needs to know which sections
# exist; only a super admin may change them.
api_router.include_router(admin.public_router, prefix="/modules", tags=["admin"])
