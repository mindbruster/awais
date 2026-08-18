"""Cut the seeded roles back to the four this shop asked for.

0043 seeded nine roles because §11 of the specification listed nine. The shop
wants four: super admin, admin, accountant, staff. The other six go.

Deleting a role is not a safe operation in general — somebody may be signed in
on one — so this refuses rather than guesses. A role still carrying users is
left exactly where it is and named in the log, so whoever runs the upgrade can
move those people and drop it themselves. An empty role, which is what these
will be on any database that has only ever seeded them, is removed outright
along with its grants.

Nothing here touches admin, accountant or staff.

Revision ID: 0044_four_roles
Revises: 0043_rbac_modules
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0044_four_roles"
down_revision: Union[str, None] = "0043_rbac_modules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RETIRED = (
    "manager",
    "inventory_manager",
    "sales_manager",
    "salesman",
    "maker_manager",
    "viewer",
)


def upgrade() -> None:
    conn = op.get_bind()

    in_use = conn.execute(
        sa.text(
            """
            SELECT r.name, count(u.id) AS people
              FROM roles r JOIN users u ON u.role_id = r.id
             WHERE r.name = ANY(:names)
             GROUP BY r.name
            """
        ),
        {"names": list(RETIRED)},
    ).all()
    if in_use:
        # Loud on purpose. Reassigning somebody's role is a decision about a
        # colleague's access, and a migration is the wrong place to make it.
        detail = ", ".join(f"{name} ({people})" for name, people in in_use)
        print(
            f"  [0044] keeping roles that still have users: {detail}. "
            "Move these people to another role and delete the role yourself."
        )

    keep = {row[0] for row in in_use}
    doomed = [name for name in RETIRED if name not in keep]
    if not doomed:
        return

    conn.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE role_id IN "
            "(SELECT id FROM roles WHERE name = ANY(:names))"
        ),
        {"names": doomed},
    )
    conn.execute(
        sa.text("DELETE FROM roles WHERE name = ANY(:names)"),
        {"names": doomed},
    )


def downgrade() -> None:
    # Deliberately empty. Re-creating these would hand back roles holding no
    # users and no grants — the appearance of a restore without the substance.
    # A shop that wants them back builds them in the panel, which is the same
    # work and leaves a record of who decided it.
    pass
