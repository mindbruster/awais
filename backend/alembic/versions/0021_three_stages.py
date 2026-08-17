"""Collapse the workshop to the three stages this shop actually runs.

The seed in 0009 shipped a nine-stage floor — RP, casting, cleaning, burning,
goldsmith, setting, polish, finish, rhodium — because that is what a large
manufacturer runs. This shop is not that shop. It has three people: the maker,
the stone fixer, and the lacker. Every extra department is a choice the counter
has to make on every issue, and each one is a chance to file a leg under a
stage nobody works at, which is how a worker's gold balance stops matching the
metal in his hand.

Departments stay data, not code. Nothing here hard-codes the three anywhere the
routing engine can see them; the shop can still add a stage from the settings
screen the day it hires a fourth man. This migration only changes what is in
the table.

Rows are not deleted out from under their history. Every job leg, design and
worker filed against a department that is going away is first pointed at Maker
— the stage all that work actually was — and only then are the empty
departments dropped. Setting and Lacker keep their own rows, so the per-100-
stones allowance and the per-piece lacquer rate the shop already agreed are
untouched.

The legacy `vendors.type` enum is realigned to follow the department, because
the two describe the same fact and the loss report reads the enum. Leaving a
polisher typed `polish` after his work moved to Maker would have the report
attributing making losses to a stage the shop no longer runs.

Revision ID: 0021_three_stages
Revises: 0020_approvals
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_three_stages"
down_revision: Union[str, None] = "0020_approvals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (code, name, sequence, consumes_stones) — the whole floor.
# Setting keeps the code `SET` rather than being replaced by a new row: its
# per-100-stones basis and agreed rate live on that row and are the shop's, not
# ours to re-guess.
STAGES = [
    ("MAKE", "Maker", 10, False),
    ("SET", "Stone Fixer", 20, True),
    ("LAC", "Lacker", 30, False),
]
KEEP = tuple(code for code, *_ in STAGES)
NAMES = tuple(name for _, name, *_ in STAGES)

# What 0009 seeded, for the downgrade.
SEEDED = [
    ("RP", "RP", 10, False),
    ("CLEAN", "Cleaning", 30, False),
    ("BURN", "Burning", 40, False),
    ("GOLD", "Goldsmith", 50, False),
    ("POL", "Polish", 70, False),
    ("FIN", "Finish", 80, False),
    ("RHOD", "Rhodium", 90, False),
]

# The department a worker belongs to, expressed in the old three-role enum the
# loss report still groups on. A lacker has no equivalent in that vocabulary —
# he is not a polisher — so he lands in `other` rather than being mislabelled.
LEGACY_TYPE = {"MAKE": "karigar", "SET": "stone_fixer", "LAC": "other"}


def upgrade() -> None:
    bind = op.get_bind()

    # A department already carrying one of the three names under a different
    # code would collide on `uq_departments_name` below. It is on its way out
    # anyway; move its name aside so the insert can land.
    bind.execute(
        sa.text(
            "UPDATE departments SET name = name || ' (retired)' "
            "WHERE name = ANY(:names) AND code <> ALL(:keep)"
        ),
        {"names": list(NAMES), "keep": list(KEEP)},
    )

    for code, name, sequence, stones in STAGES:
        # ON CONFLICT rather than a blind insert: this shop added Lacker by hand
        # months ago and that row holds its agreed 500-a-piece rate.
        bind.execute(
            sa.text(
                "INSERT INTO departments "
                "(name, code, sequence, consumes_stones, default_wastage_basis, "
                " is_active, created_at, updated_at) "
                "VALUES (:name, :code, :sequence, :stones, 'percent_of_issued', "
                " true, now(), now()) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "name": name, "sequence": sequence, "stones": stones},
        )
        # Identity only. The wastage basis, the per-100-stones figure and the
        # per-piece rate are terms the shop agreed with its workers; a schema
        # migration has no business overwriting them.
        bind.execute(
            sa.text(
                "UPDATE departments "
                "SET name = :name, sequence = :sequence, consumes_stones = :stones, "
                "    is_active = true, updated_at = now() "
                "WHERE code = :code"
            ),
            {"code": code, "name": name, "sequence": sequence, "stones": stones},
        )

    maker = bind.execute(
        sa.text("SELECT id FROM departments WHERE code = 'MAKE'")
    ).scalar_one()

    # Re-file the history before anything is dropped. Cleaning, burning, filing
    # and polishing are all work the maker does; that is the whole reason the
    # shop runs three stages and not nine.
    survivors = {"maker": maker, "keep": list(KEEP)}
    for table, column in (
        ("job_legs", "department_id"),
        ("designs", "current_department_id"),
        ("vendors", "department_id"),
    ):
        bind.execute(
            sa.text(
                f"UPDATE {table} SET {column} = :maker "
                f"WHERE {column} IS NOT NULL AND {column} NOT IN "
                "(SELECT id FROM departments WHERE code = ANY(:keep))"
            ),
            survivors,
        )

    bind.execute(
        sa.text("DELETE FROM departments WHERE code <> ALL(:keep)"), {"keep": list(KEEP)}
    )

    for code, legacy in LEGACY_TYPE.items():
        bind.execute(
            sa.text(
                # Cast explicitly: a bound parameter arrives as text, and
                # Postgres will not assign text to an enum column on its own.
                "UPDATE vendors SET type = CAST(:legacy AS vendor_type), updated_at = now() "
                "WHERE department_id = (SELECT id FROM departments WHERE code = :code)"
            ),
            {"code": code, "legacy": legacy},
        )


def downgrade() -> None:
    """
    Put the nine-stage floor back.

    The re-filing is not reversible: once a cleaning leg has been re-pointed at
    Maker, nothing records that it was ever a cleaning leg. The departments
    return empty, and the history stays where this migration put it.
    """
    bind = op.get_bind()
    for code, name, sequence, stones in SEEDED:
        bind.execute(
            sa.text(
                "INSERT INTO departments "
                "(name, code, sequence, consumes_stones, default_wastage_basis, "
                " is_active, created_at, updated_at) "
                "VALUES (:name, :code, :sequence, :stones, 'percent_of_issued', "
                " true, now(), now()) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "name": name, "sequence": sequence, "stones": stones},
        )
    bind.execute(
        sa.text(
            "UPDATE departments SET name = 'Casting', code = 'CAST', sequence = 20 "
            "WHERE code = 'MAKE'"
        )
    )
    bind.execute(
        sa.text("UPDATE departments SET name = 'Setting', sequence = 60 WHERE code = 'SET'")
    )
    bind.execute(
        sa.text("UPDATE departments SET sequence = 85 WHERE code = 'LAC'")
    )
