from fastapi import APIRouter

from app.api.v1 import (
    auth,
    customers,
    gold_rates,
    inventory,
    invoices,
    manufacturing,
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
