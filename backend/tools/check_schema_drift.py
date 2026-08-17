"""
Does the database the migrations build actually match the models?

This exists because of a specific bug that cost a day. `job_legs` grew nine
columns in `app/models/design.py` — `metal`, the wastage trio, the ratti
fields — and no migration was ever written for them. Nothing failed at import,
nothing failed at startup, and the test suite was green. Every `POST /designs`
returned a 500 and the entire workshop was unreachable, which is a much worse
outcome than a crash on boot, because it looked like working software.

That class of bug is invisible to every other check in this repository. Unit
tests do not touch the schema, the e2e suite only exercises paths somebody
remembered to write a test for, and `alembic upgrade head` succeeds happily
against migrations that are missing half the model.

**What this catches:** a column or table the models declare that the migrations
never create, and a type or nullability the two disagree about. Those are the
ones that produce a runtime error or silent corruption.

**What it deliberately ignores:** indexes, constraints and server defaults.
Alembic's autogenerate is noisy about all three, and on this schema it reports
88 of them with nothing wrong: a column declared `unique=True, index=True`
becomes a unique *constraint* plus an index in Postgres, and autogenerate wants
to drop one and recreate the other on every single run. Partial indexes written
as raw SQL in a migration — `uq_approval_items_product_out`,
`uq_branches_single_default` — are invisible to the models and show up the same
way. A check that cries wolf 88 times is a check people learn to skip.
`--strict` lists them for when somebody wants to look.

Run: `python -m tools.check_schema_drift`   (or `npm run check:schema`)

Exits 0 when the two agree, 1 when they do not.
"""
from __future__ import annotations

import argparse
import asyncio
import warnings

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import Base
from app.core.config import settings
from app import models  # noqa: F401  — registers every model on Base.metadata

# `designs` and `products` reference each other — a job knows the piece it
# became, and a piece knows the job that made it — so SQLAlchemy cannot put the
# tables in dependency order and warns that it will skip the foreign keys
# between them. That is fine here and worth being explicit about rather than
# silently swallowing: this check compares **tables, columns and types**, and
# foreign keys are in the ignored set anyway. A cycle would matter to
# `create_all`, which this repository never calls; migrations build the schema.
warnings.filterwarnings("ignore", message=".*unresolvable cycles.*")

# Alembic's own bookkeeping. It is in the database and will never be in the
# models, so it is not drift.
IGNORED_TABLES = {"alembic_version"}

# Diffs that mean the application will break, or already is.
#
# `add_*` is the dangerous direction and the reason this file exists: the model
# says a column exists, the database has never heard of it, and every query
# touching it fails at runtime.
BREAKING = {
    "add_table",
    "add_column",
    "modify_type",
    "modify_nullable",
    # The other direction: the database carries something the models dropped.
    # Less likely to crash, but it means a migration was written and the model
    # change was not — or a column is being maintained by nobody.
    "remove_table",
    "remove_column",
}

# Real differences that are usually cosmetic and always noisy. Reported under
# --strict only.
NOISY = {
    "add_index", "remove_index",
    "add_constraint", "remove_constraint",
    "add_fk", "remove_fk",
    "modify_default", "modify_comment",
    "add_table_comment", "remove_table_comment",
}


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    if type_ == "table" and name in IGNORED_TABLES:
        return False
    return True


def _describe(diff) -> tuple[str, str]:
    """(kind, one line a human can act on) for one autogenerate diff."""
    # Alembic hands back either a tuple or a list of tuples for column-level
    # modifications; the list form is only ever one logical change.
    if isinstance(diff, list):
        diff = diff[0]
    kind = diff[0]

    if kind in ("add_table", "remove_table"):
        table = diff[1]
        where = "models but not in the database" if kind == "add_table" else "the database but not in the models"
        return kind, f"table {table.name!r} is in {where}"

    if kind in ("add_column", "remove_column"):
        _, _schema, table, column = diff
        where = "models but not in the database" if kind == "add_column" else "the database but not in the models"
        return kind, f"{table}.{column.name} ({column.type}) is in {where}"

    if kind == "modify_nullable":
        _, _schema, table, column, _opts, old, new = diff
        return kind, f"{table}.{column} nullable: database says {old}, models say {new}"

    if kind == "modify_type":
        _, _schema, table, column, _opts, old, new = diff
        return kind, f"{table}.{column} type: database has {old}, models say {new}"

    if kind == "modify_default":
        _, _schema, table, column, _opts, old, new = diff
        return kind, f"{table}.{column} default: database {old!r}, models {new!r}"

    # Indexes and constraints carry an object rather than a name tuple.
    obj = diff[1] if len(diff) > 1 else None
    label = getattr(obj, "name", None) or repr(obj)
    return kind, f"{kind}: {label}"


async def _diffs() -> list:
    engine = create_async_engine(settings.database_url, poolclass=None)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(
                lambda sync_conn: compare_metadata(
                    MigrationContext.configure(
                        sync_conn,
                        opts={
                            "include_object": _include_object,
                            # Enums are compared by name; without this every
                            # native Postgres enum reads as a type change on
                            # every run.
                            "compare_type": True,
                        },
                    ),
                    Base.metadata,
                )
            )
    finally:
        await engine.dispose()


async def main(strict: bool) -> int:
    try:
        raw = await _diffs()
    except Exception as exc:  # noqa: BLE001 — the reason matters more than the type
        print(f"Could not compare the schema: {exc}")
        print("Is the database up and migrated? `npm run db:up && npm run migrate`")
        return 2

    breaking: list[str] = []
    noisy: list[str] = []
    for diff in raw:
        kind, line = _describe(diff)
        if kind in BREAKING:
            breaking.append(line)
        elif kind in NOISY:
            noisy.append(line)
        else:
            # Something autogenerate produced that this script has not seen
            # before. Treated as breaking rather than swallowed: an unknown
            # difference is exactly what this check exists to surface.
            breaking.append(f"{line}  (unclassified — treated as drift)")

    if breaking:
        print(f"Schema drift: {len(breaking)} difference(s) between the models and the migrations.\n")
        for line in breaking:
            print(f"  • {line}")
        print(
            "\nEvery one of these means the models and `alembic upgrade head` disagree.\n"
            "A column the models declare and the database lacks does not fail at\n"
            "startup — it fails on the first request that touches it, which is how\n"
            "an entire module can be unreachable while the tests stay green.\n\n"
            "Write the migration: `python -m alembic revision -m \"...\"`."
        )

    if noisy:
        if strict:
            print(f"\nAlso {len(noisy)} index/constraint/default difference(s):\n")
            for line in noisy:
                print(f"  • {line}")
        else:
            print(
                f"\n({len(noisy)} index/constraint/default difference(s) not shown — "
                "these are usually autogenerate noise. Use --strict to see them.)"
            )

    if breaking:
        return 1
    if not noisy:
        print("Schema matches the models. Nothing to migrate.")
    else:
        print("No breaking drift. The models and the migrations agree on tables, columns and types.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also list index, constraint and default differences.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.strict)))
