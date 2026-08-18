"""
Phase 8 — Role-based permission matrix.

Each role maps to a set of `<resource>:<action>` strings. The wildcard `"*"`
grants everything. Permissions are checked at the route level via the
`require_perm` dependency in `app.api.deps`.

If you add a new resource/action pair, declare it here AND in the route
that needs it; otherwise the role check will refuse the call.
"""
from __future__ import annotations

# Two permissions that used to be spelled `*`.
#
# The wildcard worked while permissions were a dict literal — `"*" in granted`
# — and stopped meaning anything the moment grants became rows, because a
# wildcard cannot be stored as one. Worse, it failed *closed*: admin quietly
# lost the ability to manage users, and the only symptom was a 403 on a screen
# that had always worked.
#
# They are real permissions now, which is also more honest. "Who may create a
# user" and "who may read the audit log" are exactly the questions a shop with
# a Manager role wants to answer for itself.
USER_MANAGE = "user:manage"
AUDIT_READ = "audit:read"

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


# Everything a role could be granted, flattened. This dict has a second job now
# that permissions live in the database: it is the **catalogue**. A screen
# offering permissions reads it, and a write is validated against it, so a typo
# cannot invent a permission that no endpoint will ever check and that therefore
# grants nothing while looking like it grants something.
# Every permission any endpoint actually asks for, filled in by `require_perm`
# as the routers are imported.
#
# The catalogue used to be derived from what the roles in `PERMISSIONS` happen
# to hold, and that was wrong in a way that failed silently: `master:delete` and
# `ledger:delete` are checked by real endpoints and were held by no role in the
# dict — admin reached them through `*`. Expanding `*` to "everything in the
# catalogue" therefore quietly dropped them, and the only symptom was a 403 on
# six delete buttons that had always worked.
#
# Registering at the point of the check makes the catalogue complete by
# construction: a permission cannot be guarded by an endpoint and missing from
# the list, because guarding it is what puts it on the list.
CHECKED: set[str] = set()


def register(perm: str) -> str:
    """Record a permission as one the application actually enforces."""
    if perm:
        CHECKED.add(perm)
    return perm


def all_permissions() -> set[str]:
    """
    Everything grantable: what the code checks, plus what the seeded roles hold.

    The union rather than either alone. `CHECKED` is only complete once the
    routers have been imported — a caller that has not imported them (the seed,
    a migration) would otherwise see an empty catalogue and grant nothing.
    """
    out: set[str] = {USER_MANAGE, AUDIT_READ} | set(CHECKED)
    for granted in PERMISSIONS.values():
        out |= {p for p in granted if p != "*"}
    return out


def default_permissions(role_name: str) -> set[str]:
    """What a seeded role starts with. Used once, at seed and migration time."""
    granted = PERMISSIONS.get(role_name, set())
    return all_permissions() if "*" in granted else set(granted)


def role_has(role_name: str, perm: str) -> bool:
    """
    The code-defined fallback, kept for the seeded roles only.

    Live checks go through `user_has` below, which reads what the role actually
    holds. This remains because the seed, the migration and a handful of tools
    need to know what a role *should* start with before any of it is in the
    database.
    """
    granted = PERMISSIONS.get(role_name, set())
    return "*" in granted or perm in granted


def user_has(user, perm: str) -> bool:
    """
    Does this user hold this permission, according to the database?

    Reads the grants on the role rather than a dict keyed by its name — which
    is the whole point of the change. Before this, a role the shop created
    itself held nothing at all: the dict had no entry for it, every check
    returned False, and no error anywhere said why.

    `superadmin` is the one name still hardcoded, and only to hold the two
    things that must not be grantable: editing roles and switching modules. A
    permission that could be granted to widen who may grant permissions is not
    a control, it is a formality.
    """
    role = getattr(user, "role", None)
    if role is None:
        return False
    if role.name == SUPERADMIN:
        return True
    return perm in role.permission_names


# The tier above admin. An admin who can widen their own permissions is not
# really constrained by them, so flags and role editing sit here instead.
SUPERADMIN = "superadmin"
