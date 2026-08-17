"""Give the business more than one shop.

Stock, sales and staff all belonged nowhere in particular: `inventory_items`
carried a free-text `location`, and nothing else recorded which counter a piece
sat in or which till took the money. That is fine for one shop and unworkable
for two — "we have 400g of 22k" stops being an answer the moment there are two
places it could be.

Three tables become branch-scoped and non-nullable: inventory, products and
invoices. A row that cannot say where it is cannot be counted at either shop,
so the column is not allowed to be empty. Existing rows are backfilled onto a
single seeded branch — which is exactly what they were, the only shop — and the
NOT NULL is applied afterwards, so the migration is safe on a live database
with data in it.

Users get a nullable branch instead. An owner or accountant belongs to the
business rather than to one counter, and forcing them onto a branch would file
head-office work under whichever shop happened to be listed first.

Transfers are modelled as a send and a receive rather than one instantaneous
move, because metal in a van between two shops is real stock that is on neither
shelf, and that is precisely the moment it goes missing.

Revision ID: 0016_branches
Revises: 0015_stone_currency
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_branches"
down_revision: Union[str, None] = "0015_stone_currency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The three tables that must always be able to say which shop they belong to.
_SCOPED = ("inventory_items", "products", "invoices")


def upgrade() -> None:
    op.create_table(
        "branches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("phone", sa.String(30)),
        sa.Column("address", sa.Text()),
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("cities.id", ondelete="SET NULL")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_branches_code", "branches", ["code"], unique=True)
    op.create_index("ix_branches_name", "branches", ["name"], unique=True)
    op.create_index("ix_branches_is_active", "branches", ["is_active"])
    op.create_index("ix_branches_is_default", "branches", ["is_default"])
    op.create_index("ix_branches_city_id", "branches", ["city_id"])

    # At most one default. Enforced in the database rather than the service
    # layer because the backfill below and every later write both depend on
    # there being exactly one answer to "where does an unscoped row go".
    op.create_index(
        "uq_branches_single_default",
        "branches",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    # The shop that already existed. Seeded here rather than left to the app so
    # that the NOT NULL constraints below have something to point at on a
    # database that is already carrying stock.
    op.execute(
        """
        INSERT INTO branches (code, name, is_active, is_default, created_at, updated_at)
        VALUES ('MAIN', 'Main Shop', true, true, now(), now())
        """
    )

    for table in _SCOPED:
        op.add_column(table, sa.Column("branch_id", sa.Integer(), nullable=True))
        op.execute(
            f"UPDATE {table} SET branch_id = (SELECT id FROM branches WHERE is_default LIMIT 1)"
        )
        op.alter_column(table, "branch_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_branch_id", table, "branches", ["branch_id"], ["id"], ondelete="RESTRICT"
        )
        op.create_index(f"ix_{table}_branch_id", table, ["branch_id"])

    # Users are left unassigned rather than defaulted. Head office is a real
    # answer, and guessing one would be worse than none.
    op.add_column("users", sa.Column("branch_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_users_branch_id", "users", "branches", ["branch_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_users_branch_id", "users", ["branch_id"])

    # Created once, explicitly. The column below then references it with
    # create_type=False — passing a bare sa.Enum to a Column makes alembic
    # emit CREATE TYPE a second time inside the same transaction.
    sa.Enum("draft", "sent", "received", "cancelled", name="transfer_status").create(
        op.get_bind(), checkfirst=True
    )
    transfer_status = postgresql.ENUM(
        "draft", "sent", "received", "cancelled", name="transfer_status", create_type=False
    )

    op.create_table(
        "branch_transfers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transfer_no", sa.String(40), nullable=False),
        sa.Column(
            "from_branch_id",
            sa.Integer(),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "to_branch_id",
            sa.Integer(),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", transfer_status, nullable=False, server_default="draft"),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("sent_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("received_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_branch_transfers_transfer_no", "branch_transfers", ["transfer_no"], unique=True)
    op.create_index("ix_branch_transfers_from_branch_id", "branch_transfers", ["from_branch_id"])
    op.create_index("ix_branch_transfers_to_branch_id", "branch_transfers", ["to_branch_id"])
    op.create_index("ix_branch_transfers_status", "branch_transfers", ["status"])
    op.create_index("ix_branch_transfers_sent_by_id", "branch_transfers", ["sent_by_id"])
    op.create_index("ix_branch_transfers_received_by_id", "branch_transfers", ["received_by_id"])

    op.create_table(
        "branch_transfer_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "transfer_id",
            sa.Integer(),
            sa.ForeignKey("branch_transfers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT")),
        sa.Column(
            "inventory_item_id",
            sa.Integer(),
            sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
        ),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weight_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("weight_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("purity", sa.Integer()),
        sa.Column(
            "received_inventory_item_id",
            sa.Integer(),
            sa.ForeignKey("inventory_items.id", ondelete="SET NULL"),
        ),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # A line that names neither a piece nor a weight of stock cannot be
        # received, and one that names both cannot say what arrived.
        sa.CheckConstraint(
            "(product_id IS NOT NULL) <> (inventory_item_id IS NOT NULL)",
            name="ck_transfer_item_one_subject",
        ),
    )
    op.create_index("ix_branch_transfer_items_transfer_id", "branch_transfer_items", ["transfer_id"])
    op.create_index("ix_branch_transfer_items_product_id", "branch_transfer_items", ["product_id"])
    op.create_index(
        "ix_branch_transfer_items_inventory_item_id", "branch_transfer_items", ["inventory_item_id"]
    )


def downgrade() -> None:
    op.drop_table("branch_transfer_items")
    op.drop_table("branch_transfers")
    sa.Enum(name="transfer_status").drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_users_branch_id", table_name="users")
    op.drop_constraint("fk_users_branch_id", "users", type_="foreignkey")
    op.drop_column("users", "branch_id")

    for table in _SCOPED:
        op.drop_index(f"ix_{table}_branch_id", table_name=table)
        op.drop_constraint(f"fk_{table}_branch_id", table, type_="foreignkey")
        op.drop_column(table, "branch_id")

    op.drop_table("branches")
