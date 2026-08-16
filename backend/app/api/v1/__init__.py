from fastapi import APIRouter

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
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(products.router, prefix="/products", tags=["products"])
api_router.include_router(product_stones.router, prefix="/products", tags=["products"])
api_router.include_router(customers.router, prefix="/customers", tags=["customers"])
api_router.include_router(inventory.router, prefix="/inventory", tags=["inventory"])
api_router.include_router(stock_movements.router, prefix="/stock-movements", tags=["stock-movements"])
api_router.include_router(vendors.router, prefix="/vendors", tags=["vendors"])
api_router.include_router(invoices.router, prefix="/invoices", tags=["invoices"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(gold_rates.router, prefix="/gold-rates", tags=["gold-rates"])
api_router.include_router(stones.router, prefix="/stones", tags=["stones"])
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
api_router.include_router(branches.transfers_router, prefix="/transfers", tags=["branches"])

# The books, and the workshop floor that posts into them.
api_router.include_router(ledger.router, prefix="/ledger", tags=["ledger"])
api_router.include_router(designs.router, prefix="/designs", tags=["designs"])

# Work promised to a customer. A front door onto the routing engine above:
# an order mints a design and lets that machinery do the tracking.
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])

# Pieces let out on approval. Not a sale — the goods are still the shop's,
# merely somewhere else — so nothing here posts to the ledger.
api_router.include_router(approvals.router, prefix="/approvals", tags=["approvals"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])

# Telling customers things. Nothing here fires on a schedule — every message
# is somebody at the counter deciding to send it.
api_router.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)

# Analysis over the books. Degrades to plain statistics when no model provider
# is configured — nothing here is allowed to be load-bearing.
api_router.include_router(insights.router, prefix="/insights", tags=["insights"])

# The money side: settling bills, stocking finished pieces, and both buying
# channels. Each posts to the ledger, so none of them is a bolt-on.
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(stocking.router, prefix="/stocking", tags=["stocking"])
api_router.include_router(purchasing.router, prefix="/purchasing", tags=["purchasing"])
