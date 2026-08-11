from fastapi import APIRouter

from app.api.v1 import (
    audit_log,
    auth,
    customers,
    designs,
    gold_rates,
    insights,
    inventory,
    invoices,
    ledger,
    manufacturing,
    masters,
    product_stones,
    products,
    reports,
    stock_movements,
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
api_router.include_router(manufacturing.router, prefix="/manufacturing", tags=["manufacturing"])
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

# The books, and the workshop floor that posts into them.
api_router.include_router(ledger.router, prefix="/ledger", tags=["ledger"])
api_router.include_router(designs.router, prefix="/designs", tags=["designs"])

# Analysis over the books. Degrades to plain statistics when no model provider
# is configured — nothing here is allowed to be load-bearing.
api_router.include_router(insights.router, prefix="/insights", tags=["insights"])
