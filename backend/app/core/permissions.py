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
        # Drawing a proposal costs real money per call, so it is its own
        # permission rather than riding on product:write — which counter staff
        # hold, because they upload photographs of finished pieces all day.
        "ai:image",
        "inventory:read",
        "stock_movement:read",
        "vendor:read",
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
        # Taking money and reconciling it is the accountant's core job.
        "payment:read", "payment:write", "payment:reverse",
        # The cash book is the accountant's ledger by another name: rent, wages,
        # bank charges and the till float all land in the books.
        "cash:read", "cash:write", "cash:flow",
        # Salesmen, brokers and the figures they are asked to hit.
        "seller:read", "seller:write",
        # Branch figures are money figures — sales by shop, stock by shop.
        # Opening or closing a branch is an owner decision, so writing stays
        # with admins.
        "branch:read",
        "transfer:read", "transfer:write",
        "order:read", "order:write",
        "notification:read", "notification:send",
        "approval:read", "approval:write",
    },
    "staff": {
        "customer:read", "customer:write", "customer:delete",
        "product:read", "product:write", "product:delete", "product_stone:write",
        "inventory:read", "inventory:write", "inventory:delete",
        "stock_movement:read", "stock_movement:write",
        "vendor:read", "vendor:write", "vendor:delete",
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
        # Counter staff record what leaves the till — a courier, tea, a taxi —
        # because an expense nobody could enter is an expense that never
        # reaches the books. Reading the cash *flow* is a money figure and
        # stays with the accountant, so the flow report checks "cash:flow".
        "cash:read", "cash:write",
        # The counter works alongside salesmen and needs to pick one on a bill.
        # Setting their targets is an owner decision.
        "seller:read",
        # Counter staff take money at the till and must be able to record it —
        # a payment that goes unrecorded because the salesperson lacked a
        # permission is worse than one recorded by the wrong person. Reversing
        # one is a correction to the books, so that stays with the accountant.
        "payment:read", "payment:write",
        # Staff need to know which shops exist in order to pick one, and they
        # are the people who physically pack and sign for a transfer. Opening
        # or closing a branch is not theirs.
        "branch:read",
        "transfer:read", "transfer:write",
        # Counter staff take the job in, chase it and hand it over. This is
        # their screen more than anyone's.
        "order:read", "order:write",
        # The counter is who tells a customer their piece is ready.
        "notification:read", "notification:send",
        # Letting a piece out on approval and chasing it back is
        # counter work, and the piece is the shop's until it sells.
        "approval:read", "approval:write",
    },
}


def role_has(role_name: str, perm: str) -> bool:
    granted = PERMISSIONS.get(role_name, set())
    return "*" in granted or perm in granted
