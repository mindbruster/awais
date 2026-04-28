"""phase 3-6: stock movements, vendors, manufacturing, invoices

Revision ID: 0002_phase3_to_6
Revises: 0001_initial
Create Date: 2026-04-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase3_to_6"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "type",
            sa.Enum(
                "purchase_in",
                "manufacturing_out",
                "manufacturing_in",
                "sale_out",
                "sale_return_in",
                "approval_out",
                "approval_return_in",
                "adjustment",
                name="stock_movement_type",
            ),
            nullable=False,
        ),
        sa.Column("inventory_item_id", sa.Integer(), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("weight_g_delta", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("weight_ct_delta", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("reference_type", sa.String(length=50), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_stock_movements_type", "stock_movements", ["type"])
    op.create_index("ix_stock_movements_inventory_item_id", "stock_movements", ["inventory_item_id"])
    op.create_index("ix_stock_movements_reference_type", "stock_movements", ["reference_type"])
    op.create_index("ix_stock_movements_reference_id", "stock_movements", ["reference_id"])

    op.create_table(
        "vendors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column(
            "type",
            sa.Enum("karigar", "stone_fixer", "polish", "other", name="vendor_type"),
            nullable=False,
        ),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_vendors_name", "vendors", ["name"])
    op.create_index("ix_vendors_type", "vendors", ["type"])

    op.create_table(
        "manufacturing_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_no", sa.String(length=50), nullable=False),
        sa.Column(
            "stage",
            sa.Enum(
                "draft",
                "karigar_assigned",
                "karigar_received",
                "stone_fixer_assigned",
                "stone_fixer_received",
                "polish_assigned",
                "polish_received",
                "completed",
                "cancelled",
                name="manufacturing_stage",
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("karigar_id", sa.Integer(), nullable=True),
        sa.Column("gold_assigned_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("gold_assigned_purity", sa.Integer(), nullable=True),
        sa.Column("gold_assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("jewelry_received_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("karigar_loss_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("stone_fixer_id", sa.Integer(), nullable=True),
        sa.Column("stones_assigned_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("stones_used_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("stones_returned_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("polish_vendor_id", sa.Integer(), nullable=True),
        sa.Column("weight_before_polish_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("weight_after_polish_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("polish_loss_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("job_no"),
        sa.ForeignKeyConstraint(["karigar_id"], ["vendors.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stone_fixer_id"], ["vendors.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["polish_vendor_id"], ["vendors.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_manufacturing_jobs_job_no", "manufacturing_jobs", ["job_no"])
    op.create_index("ix_manufacturing_jobs_stage", "manufacturing_jobs", ["stage"])

    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_no", sa.String(length=50), nullable=False),
        sa.Column(
            "sale_type",
            sa.Enum("normal", "on_approval", name="sale_type"),
            nullable=False,
            server_default="normal",
        ),
        sa.Column(
            "status",
            sa.Enum("draft", "issued", "paid", "returned", "void", name="invoice_status"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("gold_rate_per_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("discount_weight_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("invoice_no"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_invoices_invoice_no", "invoices", ["invoice_no"])
    op.create_index("ix_invoices_sale_type", "invoices", ["sale_type"])
    op.create_index("ix_invoices_status", "invoices", ["status"])
    op.create_index("ix_invoices_customer_id", "invoices", ["customer_id"])

    op.create_table(
        "invoice_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("gold_weight_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("gold_purity", sa.Integer(), nullable=True),
        sa.Column("gold_rate_per_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("gold_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("stone_weight_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("stone_rate_per_ct", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("stone_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("labor_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("line_total", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_invoice_items_invoice_id", "invoice_items", ["invoice_id"])
    op.create_index("ix_invoice_items_product_id", "invoice_items", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_invoice_items_product_id", table_name="invoice_items")
    op.drop_index("ix_invoice_items_invoice_id", table_name="invoice_items")
    op.drop_table("invoice_items")

    op.drop_index("ix_invoices_customer_id", table_name="invoices")
    op.drop_index("ix_invoices_status", table_name="invoices")
    op.drop_index("ix_invoices_sale_type", table_name="invoices")
    op.drop_index("ix_invoices_invoice_no", table_name="invoices")
    op.drop_table("invoices")
    sa.Enum(name="invoice_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="sale_type").drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_manufacturing_jobs_stage", table_name="manufacturing_jobs")
    op.drop_index("ix_manufacturing_jobs_job_no", table_name="manufacturing_jobs")
    op.drop_table("manufacturing_jobs")
    sa.Enum(name="manufacturing_stage").drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_vendors_type", table_name="vendors")
    op.drop_index("ix_vendors_name", table_name="vendors")
    op.drop_table("vendors")
    sa.Enum(name="vendor_type").drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_stock_movements_reference_id", table_name="stock_movements")
    op.drop_index("ix_stock_movements_reference_type", table_name="stock_movements")
    op.drop_index("ix_stock_movements_inventory_item_id", table_name="stock_movements")
    op.drop_index("ix_stock_movements_type", table_name="stock_movements")
    op.drop_table("stock_movements")
    sa.Enum(name="stock_movement_type").drop(op.get_bind(), checkfirst=True)
