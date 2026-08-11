"""Multi-commodity ledger + department routing engine.

Two subsystems the shop cannot be run correctly without.

The ledger treats gold as a commodity the business banks in, not merely as
stock. Workers, customers and the shop each carry running balances in metal
*and* cash that settle independently, so "how much gold does Zahid owe me" is
a balance rather than a guess. Entries balance on a PKR valuation rather than
per-commodity, which is what lets a rupee invoice be settled partly in old gold.

The routing engine replaces the fixed three-stage job row. Designs are minted
at the first department from the item abbreviation and carry the piece through
however many departments the shop runs, with issue/receive legs, itemised
stone lines and explicit wastage settlement.

The seeded chart of accounts includes the heads the posting service resolves
by code; those are flagged is_system and refuse deletion.

Revision ID: 0010_ledger_and_routing
Revises: 0009_master_data
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_ledger_and_routing"
down_revision: Union[str, None] = "0009_master_data"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (code, name, type, parent_code, is_system, is_postable)
CHART = [
    ("1000", "Assets", "asset", None, False, False),
    ("1100", "Current Assets", "asset", "1000", False, False),
    ("1110", "Cash in Hand", "asset", "1100", True, True),
    ("1120", "Bank", "asset", "1100", True, True),
    ("1130", "Gold in Hand", "asset", "1100", True, True),
    ("1140", "Stone Inventory", "asset", "1100", True, True),
    ("1150", "Finished Goods", "asset", "1100", True, True),
    ("1160", "Gold with Workers", "asset", "1100", True, True),
    ("1200", "Receivables", "asset", "1000", False, False),
    ("1210", "Customers", "asset", "1200", True, True),
    ("2000", "Liabilities", "liability", None, False, False),
    ("2100", "Payables", "liability", "2000", False, False),
    ("2110", "Suppliers", "liability", "2100", True, True),
    ("2120", "Workers Payable", "liability", "2100", True, True),
    ("3000", "Equity", "equity", None, False, False),
    ("3100", "Capital", "equity", "3000", True, True),
    ("3200", "Opening Balance Equity", "equity", "3000", True, True),
    ("4000", "Income", "income", None, False, False),
    ("4100", "Sales", "income", "4000", True, True),
    ("4200", "Wastage Recovered", "income", "4000", True, True),
    ("5000", "Expenses", "expense", None, False, False),
    ("5100", "Labour Cost", "expense", "5000", True, True),
    ("5200", "Wastage Expense", "expense", "5000", True, True),
    ("5300", "Other Expenses", "expense", "5000", True, True),
]


def upgrade() -> None:
    ts = dict(
        created_at=sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        updated_at=sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # ---------------- chart of accounts ----------------
    account_type = postgresql.ENUM(
        "asset", "liability", "equity", "income", "expense",
        name="account_type", create_type=False,
    )
    account_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("type", account_type, nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_postable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        ts["created_at"], ts["updated_at"],
        sa.ForeignKeyConstraint(["parent_id"], ["accounts.id"], ondelete="RESTRICT"),
    )
    op.create_unique_constraint("uq_accounts_code", "accounts", ["code"])
    op.create_index("ix_accounts_code", "accounts", ["code"])
    op.create_index("ix_accounts_name", "accounts", ["name"])
    op.create_index("ix_accounts_type", "accounts", ["type"])
    op.create_index("ix_accounts_parent_id", "accounts", ["parent_id"])
    op.create_index("ix_accounts_is_system", "accounts", ["is_system"])
    op.create_index("ix_accounts_is_active", "accounts", ["is_active"])

    # Insert parents before children so parent_id can be resolved by code.
    conn = op.get_bind()
    for code, name, type_, parent_code, is_system, is_postable in CHART:
        conn.execute(
            sa.text(
                """
                INSERT INTO accounts (code, name, type, parent_id, is_system, is_postable, is_active)
                VALUES (
                    :code, :name, CAST(:type AS account_type),
                    (SELECT id FROM accounts WHERE code = :parent_code),
                    :is_system, :is_postable, TRUE
                )
                """
            ).bindparams(
                code=code, name=name, type=type_, parent_code=parent_code,
                is_system=is_system, is_postable=is_postable,
            )
        )

    # ---------------- journal ----------------
    commodity = postgresql.ENUM("PKR", "USD", "GOLD", name="commodity", create_type=False)
    commodity.create(op.get_bind(), checkfirst=True)
    party_type = postgresql.ENUM(
        "customer", "worker", "supplier", name="party_type", create_type=False
    )
    party_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_no", sa.String(50), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(50), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("reverses_entry_id", sa.Integer(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        ts["created_at"], ts["updated_at"],
        sa.ForeignKeyConstraint(["reverses_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_unique_constraint("uq_journal_entries_entry_no", "journal_entries", ["entry_no"])
    op.create_index("ix_journal_entries_entry_no", "journal_entries", ["entry_no"])
    op.create_index("ix_journal_entries_entry_date", "journal_entries", ["entry_date"])
    op.create_index("ix_journal_entries_source", "journal_entries", ["source_type", "source_id"])
    op.create_index(
        "ix_journal_entries_reverses", "journal_entries", ["reverses_entry_id"]
    )

    op.create_table(
        "journal_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("commodity", commodity, nullable=False, server_default="PKR"),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("rate", sa.Numeric(18, 4), nullable=False, server_default="1"),
        sa.Column("value_pkr", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("native_weight_g", sa.Numeric(14, 4), nullable=True),
        sa.Column("native_purity", sa.Integer(), nullable=True),
        sa.Column("party_type", party_type, nullable=True),
        sa.Column("party_id", sa.Integer(), nullable=True),
        sa.Column("memo", sa.Text(), nullable=True),
        ts["created_at"], ts["updated_at"],
        sa.ForeignKeyConstraint(["entry_id"], ["journal_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_journal_lines_entry_id", "journal_lines", ["entry_id"])
    op.create_index("ix_journal_lines_account_id", "journal_lines", ["account_id"])
    op.create_index("ix_journal_lines_commodity", "journal_lines", ["commodity"])
    # The statement query: one party's lines on one control account, in date
    # order. Without this every customer ledger is a full scan of the journal.
    op.create_index(
        "ix_journal_lines_party", "journal_lines", ["party_type", "party_id", "account_id"]
    )

    # ---------------- routing engine ----------------
    design_status = postgresql.ENUM(
        "in_production", "stocked", "sold", "cancelled",
        name="design_status", create_type=False,
    )
    design_status.create(op.get_bind(), checkfirst=True)
    leg_status = postgresql.ENUM(
        "issued", "received", "cancelled", name="leg_status", create_type=False
    )
    leg_status.create(op.get_bind(), checkfirst=True)
    labour_basis = postgresql.ENUM(
        "per_gram", "per_piece", "flat", name="labour_basis", create_type=False
    )
    labour_basis.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "designs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("design_no", sa.String(40), nullable=False),
        sa.Column("tag_no", sa.String(40), nullable=True),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("current_department_id", sa.Integer(), nullable=True),
        sa.Column("status", design_status, nullable=False, server_default="in_production"),
        sa.Column("image_url", sa.String(500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        ts["created_at"], ts["updated_at"],
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["current_department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
    )
    op.create_unique_constraint("uq_designs_design_no", "designs", ["design_no"])
    op.create_unique_constraint("uq_designs_tag_no", "designs", ["tag_no"])
    op.create_index("ix_designs_design_no", "designs", ["design_no"])
    op.create_index("ix_designs_tag_no", "designs", ["tag_no"])
    op.create_index("ix_designs_item_id", "designs", ["item_id"])
    op.create_index("ix_designs_customer_id", "designs", ["customer_id"])
    op.create_index("ix_designs_current_department_id", "designs", ["current_department_id"])
    op.create_index("ix_designs_status", "designs", ["status"])
    op.create_index("ix_designs_product_id", "designs", ["product_id"])

    op.create_table(
        "job_legs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("design_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Integer(), nullable=True),
        sa.Column("status", leg_status, nullable=False, server_default="issued"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gold_issued_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("gold_issued_purity", sa.Integer(), nullable=True),
        sa.Column("stones_issued_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("gold_source_inventory_id", sa.Integer(), nullable=True),
        sa.Column("stone_source_inventory_id", sa.Integer(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gold_received_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("stones_used_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("stones_returned_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("wastage_allowed_pct", sa.Numeric(6, 3), nullable=True),
        sa.Column("wastage_allowed_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("wastage_actual_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("wastage_excess_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("labour_basis", labour_basis, nullable=False, server_default="per_gram"),
        sa.Column("labour_rate", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("labour_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        ts["created_at"], ts["updated_at"],
        sa.ForeignKeyConstraint(["design_id"], ["designs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["worker_id"], ["vendors.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["gold_source_inventory_id"], ["inventory_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stone_source_inventory_id"], ["inventory_items.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_job_legs_design_id", "job_legs", ["design_id"])
    op.create_index("ix_job_legs_sequence", "job_legs", ["sequence"])
    op.create_index("ix_job_legs_department_id", "job_legs", ["department_id"])
    op.create_index("ix_job_legs_worker_id", "job_legs", ["worker_id"])
    op.create_index("ix_job_legs_status", "job_legs", ["status"])

    op.create_table(
        "leg_stones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("leg_id", sa.Integer(), nullable=False),
        sa.Column("stone_id", sa.Integer(), nullable=False),
        sa.Column("quantity_issued", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weight_issued_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("quantity_returned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weight_returned_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("rate_per_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        ts["created_at"], ts["updated_at"],
        sa.ForeignKeyConstraint(["leg_id"], ["job_legs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stone_id"], ["stones.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_leg_stones_leg_id", "leg_stones", ["leg_id"])
    op.create_index("ix_leg_stones_stone_id", "leg_stones", ["stone_id"])


def downgrade() -> None:
    op.drop_table("leg_stones")
    op.drop_table("job_legs")
    op.drop_table("designs")
    for name in ("labour_basis", "leg_status", "design_status"):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)

    op.drop_table("journal_lines")
    op.drop_table("journal_entries")
    for name in ("party_type", "commodity"):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)

    op.drop_table("accounts")
    sa.Enum(name="account_type").drop(op.get_bind(), checkfirst=True)
