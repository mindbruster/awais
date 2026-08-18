"""Roles that mean something, and modules that can be switched off.

Two features, one migration, because they answer the same question from two
sides: *what is this person allowed to reach.*

**Roles had no permissions in them.** The `roles` table stored a name and a
description; the permissions lived in a Python dict keyed by role *name*. A shop
could create a role called "Manager" through the API, and it would silently hold
zero permissions, with nothing to explain why — the dict had no entry for it and
`role_has` simply returned False for everything. Nine roles were asked for in
the specification and three existed, none of them changeable without a deploy.

Permissions now live in `role_permissions`, seeded from that same dict so no
existing role changes what it can do on the day this runs. The dict stays, and
keeps a second job: it is the **catalogue** of which permissions exist at all,
so a screen can offer them and a typo cannot invent one.

**`superadmin` is a new tier above admin.** The shop asked for it and the reason
is sound: an admin who can widen their own permissions is not really constrained
by them. Feature flags and role editing belong to somebody who is not also
running the counter. The existing `admin` role keeps everything else it had.

**Modules are rows, not code.** One per sidebar section, so a switch matches a
heading somebody already sees. `enabled` is the only mutable field; the key and
label are fixed, because a module whose key can be edited is a permission check
that can be renamed out of existence.

Revision ID: 0043_rbac_modules
Revises: 0042_two_person
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0043_rbac_modules"
down_revision: Union[str, None] = "0042_two_person"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors the sidebar. Ordered as the sidebar orders them so the settings screen
# reads in the same sequence as the thing it configures.
MODULES = [
    ("dashboard", "Dashboard", 10, False),
    ("inventory", "Inventory", 20, True),
    ("manufacturing", "Manufacturing", 30, True),
    ("sales", "Sales", 40, True),
    ("customers", "Customers", 50, True),
    ("vendors", "Vendors", 60, True),
    ("finance", "Finance", 70, True),
    ("reports", "Reports", 80, True),
    ("rates", "Market rates", 90, True),
    ("reconciliation", "Reconciliation", 95, True),
    ("settings", "Settings", 100, False),
]


def upgrade() -> None:
    op.create_table(
        "role_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "role_id",
            sa.Integer(),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Free text rather than an enum: the catalogue lives in code and grows
        # with every feature, and a database enum would need a migration for
        # each one. Values are validated against that catalogue on write.
        sa.Column("permission", sa.String(length=60), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_unique_constraint(
        "uq_role_permission", "role_permissions", ["role_id", "permission"]
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])

    # A role the shop set up itself can be renamed and deleted; the three the
    # system relies on cannot, or an upgrade would land on a database whose
    # roles no longer answer to the names the code seeds by.
    op.add_column(
        "roles",
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE roles SET is_system = TRUE WHERE name IN ('admin','accountant','staff')")

    op.create_table(
        "modules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        # Dashboard and Settings cannot be switched off. A shop that turned off
        # Settings could never turn anything back on, and one without a
        # dashboard has no way to see the alerts telling it what is wrong.
        sa.Column("can_disable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_modules_key", "modules", ["key"], unique=True)

    for key, label, order, can_disable in MODULES:
        op.execute(
            sa.text(
                """
                INSERT INTO modules (key, label, sort_order, enabled, can_disable)
                VALUES (:key, :label, :order, TRUE, :can_disable)
                ON CONFLICT (key) DO NOTHING
                """
            ).bindparams(key=key, label=label, order=order, can_disable=can_disable)
        )

    # Seed each existing role with exactly what the code dict granted it, so no
    # role changes what it can do on the day this runs. `admin` held "*", which
    # is expanded to the full catalogue: a wildcard cannot be stored as a row,
    # and leaving it implicit would mean admin silently losing every permission
    # added after this migration.
    conn = op.get_bind()
    from app.core.permissions import default_permissions  # noqa: E402

    for (role_id, role_name) in conn.execute(sa.text("SELECT id, name FROM roles")).all():
        for perm in sorted(default_permissions(role_name)):
            conn.execute(
                sa.text(
                    """
                    INSERT INTO role_permissions (role_id, permission, created_at, updated_at)
                    VALUES (:rid, :perm, NOW(), NOW())
                    ON CONFLICT (role_id, permission) DO NOTHING
                    """
                ).bindparams(rid=role_id, perm=perm)
            )

    # The new tier. Created here rather than left to the seed so an existing
    # installation gets it on upgrade, not only a fresh one.
    op.execute(
        """
        INSERT INTO roles (name, description, is_system, created_at, updated_at)
        VALUES ('superadmin',
                'Owns feature flags and role permissions. Cannot be edited from inside the app.',
                TRUE, NOW(), NOW())
        ON CONFLICT (name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_modules_key", table_name="modules")
    op.drop_table("modules")
    op.drop_index("ix_role_permissions_role_id", table_name="role_permissions")
    op.drop_constraint("uq_role_permission", "role_permissions", type_="unique")
    op.drop_table("role_permissions")
    op.drop_column("roles", "is_system")
    # The role stays if anybody is using it: deleting it would orphan a user
    # account and lock whoever holds it out of the system entirely.
    op.execute(
        """
        DELETE FROM roles
        WHERE name = 'superadmin'
          AND NOT EXISTS (SELECT 1 FROM users WHERE role_id = roles.id)
        """
    )
