"""
Phase 8 — Role-based permission matrix.

Each role maps to a set of `<resource>:<action>` strings. The wildcard `"*"`
grants everything. Permissions are checked at the route level via the
`require_perm` dependency in `app.api.deps`.

If you add a new resource/action pair, declare it here AND in the route
that needs it; otherwise the role check will refuse the call.
"""
from __future__ import annotations

PERMISSIONS: dict[str, set[str]] = {
    "admin": {"*"},
    "accountant": {
        "customer:read", "customer:write", "customer:delete",
        "product:read", "product_stone:write",
        "inventory:read",
        "stock_movement:read",
        "vendor:read",
        "manufacturing:read",
        "invoice:read", "invoice:write", "invoice:delete",
        "invoice:issue", "invoice:mark_paid", "invoice:void",
        "report:stock", "report:sales", "report:loss", "report:profit",
        "gold_rate:read", "gold_rate:write",
        "stone:read",
        # Reference data: accountants maintain the financial masters (banks,
        # accounts) and need to read the rest to reconcile.
        "master:read", "master:write",
        # The books are the accountant's job — they may define accounts and
        # post entries. Deleting accounts stays with admins.
        "ledger:read", "ledger:write", "ledger:post",
        "design:read",
    },
    "staff": {
        "customer:read", "customer:write", "customer:delete",
        "product:read", "product:write", "product:delete", "product_stone:write",
        "inventory:read", "inventory:write", "inventory:delete",
        "stock_movement:read", "stock_movement:write",
        "vendor:read", "vendor:write", "vendor:delete",
        "manufacturing:read", "manufacturing:write",
        "invoice:read",
        # Staff sees stock + loss but NOT sales / profit (money-sensitive)
        "report:stock", "report:loss",
        "gold_rate:read",
        "stone:read", "stone:write", "stone:delete",
        # Staff select from reference data all day but must not redefine the
        # shop's departments, items or bank accounts. Read only; deleting a
        # master is admin-only because it silently reshapes historic reports.
        "master:read",
        # Staff run the workshop floor: they mint designs and record issue and
        # receive all day. They cannot see the books those postings land in —
        # worker gold liabilities and cash balances are owner information.
        "design:read", "design:write",
    },
}


def role_has(role_name: str, perm: str) -> bool:
    granted = PERMISSIONS.get(role_name, set())
    return "*" in granted or perm in granted
