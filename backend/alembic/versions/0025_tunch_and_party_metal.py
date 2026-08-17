"""Tunch as a decimal, and a metal account per trade party.

Two changes that together turn a retail counter system into one a wholesaler
can keep his books in.

**Tunch.** Purity was a karat integer in ten tables, and `fine_grams()`
computed it as `karat / 24`. That is fine for a shop selling 22k to walk-in
customers, where 22 is a category. It is not fine between jewellers, who trade
on an assayed fineness quoted to a decimal — 91.6, 91.7, 99.5 — and weigh to
three places precisely because they intend to argue about it. On a five-kilo
lot, 91.6 against 92.0 is twenty fine grams.

So every purity column gains a `tunch_pct` beside it, and `fine_grams()`
prefers it. Crucially, **nothing is backfilled.** 22/24 is 0.91666..., and any
decimal written in its place is a rounding of that — a backfill would silently
move the fine weight of every row already on the books. Left NULL, historic
rows take the karat fallback and compute to the same last decimal they always
did. Precision arrives for new documents without restating old ones.

**Party metal.** Account 1215, holding a running fine-gram balance per trade
party. One account that swings both ways rather than a receivable and a
payable, because the same jeweller settles a bill in bullion on Tuesday and
drops off 500g for job work on Thursday, and splitting that across two accounts
would mean reclassifying it constantly.

**Making income.** Account 4300. `5100 Labour Cost` is what the karigar is
paid; there was no account for what the shop charges, so making fell into
`4100 Sales` alongside the metal. For a wholesaler that hides the entire
business — making and wastage are the margin, and the metal largely passes
through at cost.

Reversible in full. `downgrade()` drops the columns, removes the two accounts
(refusing if anything has posted to them), and leaves the enum value in place,
which is the one thing Postgres will not take back.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_tunch_and_party_metal"
down_revision: Union[str, None] = "0024_gold_purchases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, new column). Every one sits beside an existing karat integer and is
# nullable with no default, so adding it rewrites no rows and locks nothing for
# any meaningful time.
TUNCH_COLUMNS = [
    ("products", "gold_tunch_pct"),
    ("invoice_items", "gold_tunch_pct"),
    ("inventory_items", "tunch_pct"),
    ("job_legs", "gold_issued_tunch_pct"),
    ("journal_lines", "native_tunch_pct"),
    ("payments", "gold_tunch_pct"),
    ("old_gold_purchases", "tunch_pct"),
    ("gold_purchase_items", "tunch_pct"),
    ("customer_orders", "intake_tunch_pct"),
    ("branch_transfer_items", "tunch_pct"),
]

# (code, name, type, parent_code). Both are system accounts: the posting
# services resolve them by code, so they refuse deletion and code changes.
NEW_ACCOUNTS = [
    ("1215", "Party Metal Account", "asset", "1200"),
    ("4300", "Making & Labour Income", "income", "4000"),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table, column in TUNCH_COLUMNS:
        # The transfer-items and gold-purchase tables arrived in later
        # migrations than some installs have run, and the retired
        # manufacturing tables may be gone entirely. Skipping a table that is
        # not there beats failing the whole migration on a schema that is
        # merely older than expected.
        if table not in existing_tables:
            continue
        if column not in {c["name"] for c in inspector.get_columns(table)}:
            op.add_column(table, sa.Column(column, sa.Numeric(6, 3), nullable=True))

        # A tunch is a percentage of pure. Zero is not a reading — it is an
        # empty field somebody typed a nought into — and it would silently
        # value a whole lot at nothing, so the floor is exclusive.
        #
        # Guarded on the existing constraint names rather than assumed absent:
        # if this migration half-ran and is being re-applied, the column check
        # above already skipped, and an unguarded create would fail on the
        # duplicate name and strand the schema between two states.
        name = f"ck_{table}_{column}_range"
        if name not in {c["name"] for c in inspector.get_check_constraints(table)}:
            op.create_check_constraint(
                name,
                table,
                f"{column} IS NULL OR ({column} > 0 AND {column} <= 100)",
            )

    for code, name, type_, parent_code in NEW_ACCOUNTS:
        op.execute(
            sa.text(
                """
                INSERT INTO accounts
                    (code, name, type, parent_id, is_system, is_postable, is_active)
                VALUES (
                    :code, :name, CAST(:type AS account_type),
                    (SELECT id FROM accounts WHERE code = :parent_code),
                    TRUE, TRUE, TRUE
                )
                ON CONFLICT (code) DO NOTHING
                """
            ).bindparams(code=code, name=name, type=type_, parent_code=parent_code)
        )

    # Postgres will not add an enum value inside a transaction that later uses
    # it, and Alembic runs migrations in one. Nothing here posts a salesman
    # line, so the value is merely declared for the route work to come.
    op.execute("ALTER TYPE party_type ADD VALUE IF NOT EXISTS 'salesman'")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # Refuse to remove an account that has been posted to. Dropping it would
    # either orphan the lines or cascade them away, and a ledger that quietly
    # loses postings on a downgrade is worse than a downgrade that stops.
    for code, _, _, _ in NEW_ACCOUNTS:
        posted = bind.execute(
            sa.text(
                """
                SELECT COUNT(*) FROM journal_lines l
                JOIN accounts a ON a.id = l.account_id
                WHERE a.code = :code
                """
            ).bindparams(code=code)
        ).scalar_one()
        if posted:
            raise RuntimeError(
                f"Account {code} has {posted} journal line(s) posted to it. "
                "Reverse those entries before downgrading."
            )

    for code, _, _, _ in NEW_ACCOUNTS:
        op.execute(sa.text("DELETE FROM accounts WHERE code = :code").bindparams(code=code))

    for table, column in TUNCH_COLUMNS:
        if table not in existing_tables:
            continue
        op.drop_constraint(f"ck_{table}_{column}_range", table, type_="check")
        op.drop_column(table, column)

    # 'salesman' stays on party_type. Postgres cannot drop an enum value, and
    # recreating the type would mean rewriting every journal line to do it.
    # An unused value is harmless; the alternative is not.
