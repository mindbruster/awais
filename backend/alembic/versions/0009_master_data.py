"""Master data foundation.

Adds the reference tables the shop configures once and then selects from
everywhere: departments, items (the source of design-number prefixes),
governed stone/diamond attribute options, countries and cities, and banks with
their accounts. Extends customers, workers and stones with the fields the
counter and workshop actually capture.

Seeds the nine departments and the standard diamond grades so a fresh install
is usable immediately; all of it is editable.

`vendors.department_id` is backfilled from the existing three-value `type`
enum. Both live side by side until the routing engine replaces the enum.

Revision ID: 0009_master_data
Revises: 0008_material_settlement
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_master_data"
down_revision: Union[str, None] = "0008_material_settlement"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (name, code, sequence, consumes_stones) — the flow demonstrated in the
# reference product. `sequence` is the default order, not a constraint.
DEPARTMENTS = [
    ("RP", "RP", 10, False),
    ("Casting", "CAST", 20, False),
    ("Cleaning", "CLEAN", 30, False),
    ("Burning", "BURN", 40, False),
    ("Goldsmith", "GOLD", 50, False),
    ("Setting", "SET", 60, True),
    ("Polish", "POL", 70, False),
    ("Finish", "FIN", 80, False),
    ("Rhodium", "RHOD", 90, False),
]

# (kind, value, sort_order)
ATTRIBUTE_OPTIONS = [
    *[("cut", v, i * 10) for i, v in enumerate(
        ["Round", "Princess", "Emerald", "Oval", "Marquise", "Pear", "Cushion", "Baguette"]
    )],
    *[("color", v, i * 10) for i, v in enumerate(
        ["D", "E", "F", "G", "H", "I", "J", "K", "L", "M"]
    )],
    *[("clarity", v, i * 10) for i, v in enumerate(
        ["FL", "IF", "VVS1", "VVS2", "VS1", "VS2", "SI1", "SI2", "I1", "I2", "I3"]
    )],
    *[("quality", v, i * 10) for i, v in enumerate(["Deluxe", "Commercial"])],
]


def upgrade() -> None:
    # --- departments ---
    departments = op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("code", sa.String(12), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consumes_stones", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_wastage_pct", sa.Numeric(6, 3), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_departments_name", "departments", ["name"])
    op.create_unique_constraint("uq_departments_code", "departments", ["code"])
    op.create_index("ix_departments_name", "departments", ["name"])
    op.create_index("ix_departments_sequence", "departments", ["sequence"])
    op.create_index("ix_departments_is_active", "departments", ["is_active"])
    op.bulk_insert(
        departments,
        [
            {"name": n, "code": c, "sequence": s, "consumes_stones": st, "is_active": True}
            for (n, c, s, st) in DEPARTMENTS
        ],
    )

    # --- items ---
    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("abbreviation", sa.String(8), nullable=False),
        sa.Column("category", sa.String(80), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_items_name", "items", ["name"])
    op.create_unique_constraint("uq_items_abbreviation", "items", ["abbreviation"])
    op.create_index("ix_items_name", "items", ["name"])
    op.create_index("ix_items_abbreviation", "items", ["abbreviation"])
    op.create_index("ix_items_category", "items", ["category"])
    op.create_index("ix_items_is_active", "items", ["is_active"])

    # --- attribute options ---
    # Create the type once, explicitly, then reference it with create_type=False
    # so create_table doesn't try to emit CREATE TYPE a second time.
    attribute_kind = postgresql.ENUM(
        "cut", "color", "clarity", "quality", name="attribute_kind", create_type=False
    )
    attribute_kind.create(op.get_bind(), checkfirst=True)
    attribute_options = op.create_table(
        "attribute_options",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", attribute_kind, nullable=False),
        sa.Column("value", sa.String(60), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint(
        "uq_attribute_options_kind_value", "attribute_options", ["kind", "value"]
    )
    op.create_index("ix_attribute_options_kind", "attribute_options", ["kind"])
    op.create_index("ix_attribute_options_is_active", "attribute_options", ["is_active"])
    op.bulk_insert(
        attribute_options,
        [
            {"kind": k, "value": v, "sort_order": o, "is_active": True}
            for (k, v, o) in ATTRIBUTE_OPTIONS
        ],
    )

    # --- countries / cities ---
    op.create_table(
        "countries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("iso_code", sa.String(2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_countries_name", "countries", ["name"])
    op.create_index("ix_countries_name", "countries", ["name"])
    op.create_index("ix_countries_is_active", "countries", ["is_active"])

    op.create_table(
        "cities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("country_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["country_id"], ["countries.id"], ondelete="RESTRICT"),
    )
    op.create_unique_constraint("uq_cities_country_name", "cities", ["country_id", "name"])
    op.create_index("ix_cities_name", "cities", ["name"])
    op.create_index("ix_cities_country_id", "cities", ["country_id"])
    op.create_index("ix_cities_is_active", "cities", ["is_active"])

    # --- banks / bank accounts ---
    op.create_table(
        "banks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("deduction_rate", sa.Numeric(6, 3), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_banks_name", "banks", ["name"])
    op.create_index("ix_banks_name", "banks", ["name"])
    op.create_index("ix_banks_is_active", "banks", ["is_active"])

    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bank_id", sa.Integer(), nullable=False),
        sa.Column("account_no", sa.String(50), nullable=False),
        sa.Column("title", sa.String(150), nullable=True),
        sa.Column(
            # The currency type was created back in 0005; reference it, don't
            # redeclare it.
            "currency",
            postgresql.ENUM("PKR", "USD", name="currency", create_type=False),
            nullable=False,
            server_default="PKR",
        ),
        sa.Column("opening_balance", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["bank_id"], ["banks.id"], ondelete="RESTRICT"),
    )
    op.create_unique_constraint(
        "uq_bank_accounts_bank_account_no", "bank_accounts", ["bank_id", "account_no"]
    )
    op.create_index("ix_bank_accounts_bank_id", "bank_accounts", ["bank_id"])
    op.create_index("ix_bank_accounts_account_no", "bank_accounts", ["account_no"])
    op.create_index("ix_bank_accounts_currency", "bank_accounts", ["currency"])
    op.create_index("ix_bank_accounts_is_active", "bank_accounts", ["is_active"])

    # --- customers: counter fields ---
    op.add_column("customers", sa.Column("phone2", sa.String(30), nullable=True))
    op.add_column("customers", sa.Column("cnic", sa.String(20), nullable=True))
    op.add_column("customers", sa.Column("reference", sa.String(150), nullable=True))
    op.add_column("customers", sa.Column("date_of_birth", sa.Date(), nullable=True))
    op.add_column("customers", sa.Column("anniversary", sa.Date(), nullable=True))
    op.add_column("customers", sa.Column("city_id", sa.Integer(), nullable=True))
    op.add_column("customers", sa.Column("country_id", sa.Integer(), nullable=True))
    op.add_column(
        "customers",
        sa.Column("opening_balance", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.create_index("ix_customers_cnic", "customers", ["cnic"])
    op.create_index("ix_customers_city_id", "customers", ["city_id"])
    op.create_index("ix_customers_country_id", "customers", ["country_id"])
    op.create_foreign_key(
        "fk_customers_city", "customers", "cities", ["city_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_customers_country", "customers", "countries", ["country_id"], ["id"], ondelete="SET NULL"
    )

    # --- vendors (workers): department link + terms + opening balances ---
    op.add_column("vendors", sa.Column("department_id", sa.Integer(), nullable=True))
    op.add_column("vendors", sa.Column("cnic", sa.String(20), nullable=True))
    op.add_column("vendors", sa.Column("default_wastage_pct", sa.Numeric(6, 3), nullable=True))
    op.add_column(
        "vendors",
        sa.Column("opening_cash_balance", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "vendors",
        sa.Column("opening_gold_g", sa.Numeric(14, 4), nullable=False, server_default="0"),
    )
    op.add_column(
        "vendors", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.create_index("ix_vendors_department_id", "vendors", ["department_id"])
    op.create_index("ix_vendors_cnic", "vendors", ["cnic"])
    op.create_index("ix_vendors_is_active", "vendors", ["is_active"])
    op.create_foreign_key(
        "fk_vendors_department",
        "vendors",
        "departments",
        ["department_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    # Map the legacy three-role enum onto the seeded departments so existing
    # workers land in the right place. 'other' is left unmapped deliberately —
    # there is no correct guess, and the shop should assign it explicitly.
    op.execute(
        """
        UPDATE vendors v
        SET department_id = d.id
        FROM departments d
        WHERE (v.type = 'karigar'     AND d.code = 'GOLD')
           OR (v.type = 'stone_fixer' AND d.code = 'SET')
           OR (v.type = 'polish'      AND d.code = 'POL')
        """
    )

    # --- stones: category, abbreviation, quality ---
    stone_category = postgresql.ENUM(
        "stone", "diamond", name="stone_category", create_type=False
    )
    stone_category.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "stones",
        sa.Column("category", stone_category, nullable=False, server_default="stone"),
    )
    op.add_column("stones", sa.Column("abbreviation", sa.String(8), nullable=True))
    op.add_column("stones", sa.Column("quality", sa.String(60), nullable=True))
    op.create_index("ix_stones_category", "stones", ["category"])
    op.create_index("ix_stones_abbreviation", "stones", ["abbreviation"])
    op.create_index("ix_stones_quality", "stones", ["quality"])
    # Existing rows already record diamonds via `kind`; carry that across so the
    # new category column is correct from the start rather than all 'stone'.
    op.execute("UPDATE stones SET category = 'diamond' WHERE kind = 'diamond'")


def downgrade() -> None:
    op.drop_index("ix_stones_quality", table_name="stones")
    op.drop_index("ix_stones_abbreviation", table_name="stones")
    op.drop_index("ix_stones_category", table_name="stones")
    op.drop_column("stones", "quality")
    op.drop_column("stones", "abbreviation")
    op.drop_column("stones", "category")
    sa.Enum(name="stone_category").drop(op.get_bind(), checkfirst=True)

    op.drop_constraint("fk_vendors_department", "vendors", type_="foreignkey")
    op.drop_index("ix_vendors_is_active", table_name="vendors")
    op.drop_index("ix_vendors_cnic", table_name="vendors")
    op.drop_index("ix_vendors_department_id", table_name="vendors")
    for col in (
        "is_active",
        "opening_gold_g",
        "opening_cash_balance",
        "default_wastage_pct",
        "cnic",
        "department_id",
    ):
        op.drop_column("vendors", col)

    op.drop_constraint("fk_customers_country", "customers", type_="foreignkey")
    op.drop_constraint("fk_customers_city", "customers", type_="foreignkey")
    op.drop_index("ix_customers_country_id", table_name="customers")
    op.drop_index("ix_customers_city_id", table_name="customers")
    op.drop_index("ix_customers_cnic", table_name="customers")
    for col in (
        "opening_balance",
        "country_id",
        "city_id",
        "anniversary",
        "date_of_birth",
        "reference",
        "cnic",
        "phone2",
    ):
        op.drop_column("customers", col)

    op.drop_table("bank_accounts")
    op.drop_table("banks")
    op.drop_table("cities")
    op.drop_table("countries")
    op.drop_table("attribute_options")
    sa.Enum(name="attribute_kind").drop(op.get_bind(), checkfirst=True)
    op.drop_table("items")
    op.drop_table("departments")
